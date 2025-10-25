#!/usr/bin/env python3
"""
orchestrator_enhanced.py - 增强版最小可行版本

改进：
1. Claude-1 可以通过 > 符号向 Claude-2 发送命令
   例如: > claude write a python function
2. Claude-2 的输出自动返回给 Claude-1
3. 支持多轮对话和协作
4. 为未来添加更多 AI 预留架构
"""

import os
import sys
import signal
import pty
import time
import select
import fcntl
import subprocess
from pathlib import Path
from typing import Dict, Optional, Tuple, List, Any
import logging
import threading

# 导入配置和对话历史模块
try:
    from config_loader import ConfigLoader, get_config
    from conversation_history import ConversationHistory, SessionManager
    CONFIG_AVAILABLE = True
except ImportError as e:
    logging.warning(f"配置模块未找到，使用默认设置: {e}")
    CONFIG_AVAILABLE = False
    ConfigLoader = None
    ConversationHistory = None
    SessionManager = None

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('orchestrator.log')
    ]
)
logger = logging.getLogger('orchestrator')


class CLIAgent:
    """管理单个 CLI 的进程和 PTY"""

    def __init__(self, name: str, cli_command: str, config: Optional[Dict[str, Any]] = None):
        """
        Args:
            name: Agent 名称（如 'codex', 'claude-code'）
            cli_command: 启动命令（如 'codex' 或 'claude'）
            config: Agent 配置字典（可选）
        """
        self.name = name
        self.cli_command = cli_command
        self.config = config or {}

        self.pid: Optional[int] = None
        self.fd: Optional[int] = None  # PTY master fd
        self.process_running = False
        self.pty_closed = False  # 跟踪 PTY 是否已关闭

        self.logger = logging.getLogger(f'agent.{name}')
        self.output_buffer = ""  # 缓存输出
        self.buffer_lock = threading.Lock()  # 保护 output_buffer 的线程锁

        # 心跳机制（用于保持 codex 活跃）
        self.heartbeat_thread: Optional[threading.Thread] = None
        self.heartbeat_running = False
    
    def start(self) -> bool:
        """启动 CLI 进程在 PTY 中"""
        try:
            # 首先检查命令是否存在
            import shutil
            import struct
            import termios

            if not shutil.which(self.cli_command):
                self.logger.error(f"❌ Command '{self.cli_command}' not found in PATH")
                self.logger.info(f"   Skipping {self.name} agent")
                return False

            # 使用 PTY fork 创建真正的伪终端
            self.pid, self.fd = pty.fork()

            if self.pid == 0:
                # 子进程：执行 CLI 命令
                # 设置环境变量以提供更好的终端支持
                os.environ['TERM'] = 'xterm-256color'
                os.environ['COLORTERM'] = 'truecolor'

                try:
                    os.execvp(self.cli_command, [self.cli_command])
                except Exception as e:
                    sys.stderr.write(f"Failed to exec {self.cli_command}: {e}\n")
                    sys.exit(1)

            # 父进程：配置 PTY
            # 设置终端尺寸（避免显示问题）
            try:
                winsize = struct.pack('HHHH', 24, 80, 0, 0)  # 24 行，80 列
                fcntl.ioctl(self.fd, termios.TIOCSWINSZ, winsize)
            except Exception as e:
                self.logger.debug(f"Could not set terminal size: {e}")

            # 设置非阻塞模式
            fcntl.fcntl(self.fd, fcntl.F_SETFL, os.O_NONBLOCK)

            # 保存 stdout_fd 以便后续读取
            self.stdout_fd = self.fd

            # 等待一下让进程初始化（延长到15秒）
            time.sleep(15.0)

            # 尝试读取初始输出（可能包含欢迎信息和错误）
            initial_output = ""
            max_read_attempts = 30  # 增加尝试次数以读取完整的欢迎信息
            for attempt in range(max_read_attempts):
                try:
                    chunk = os.read(self.fd, 4096)
                    if chunk:
                        initial_output += chunk.decode('utf-8', errors='replace')
                        self.output_buffer += chunk.decode('utf-8', errors='replace')
                except OSError as e:
                    if e.errno == 5:  # EIO - PTY 已关闭
                        self.logger.debug(f"{self.name}: PTY closed during startup")
                        break
                    elif e.errno in (11, 35):  # EAGAIN/EWOULDBLOCK
                        # 没有更多数据，但继续尝试一会儿
                        pass
                time.sleep(0.1)

            # 再等待一下，确保进程稳定
            time.sleep(2.0)

            # 检查进程是否立即退出
            try:
                pid_result, status = os.waitpid(self.pid, os.WNOHANG)
                if pid_result != 0:
                    # 进程已退出
                    exit_code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else -1
                    self.logger.error(f"❌ {self.name} exited immediately with code {exit_code}")

                    # 显示可能的错误信息
                    if initial_output:
                        self.logger.error(f"   Output: {initial_output[:500]}")

                    return False
            except OSError:
                pass  # 进程仍在运行

            # 如果没有实质性的初始输出，可能需要发送一个输入来激活进程
            # 检查是否有有意义的内容（过滤掉 ANSI 转义序列后）
            import re
            clean_output = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', initial_output)
            meaningful_content = clean_output.strip()

            # 如果没有实质内容，或者看起来只是 ANSI 序列，发送换行来激活
            should_send_newline = (
                not initial_output or
                len(meaningful_content) < 10 or
                # 对于 codex，总是尝试发送换行（它可能需要交互）
                self.cli_command == 'codex'
            )

            if should_send_newline:
                self.logger.debug(f"{self.name}: Sending initial newline to activate CLI")
                try:
                    # 发送一个换行符
                    os.write(self.fd, b'\n')
                    time.sleep(0.3)

                    # 尝试读取响应
                    try:
                        response = os.read(self.fd, 4096)
                        if response:
                            decoded = response.decode('utf-8', errors='replace')
                            initial_output += decoded
                            self.output_buffer += decoded
                            self.logger.debug(f"{self.name}: Got response after newline: {len(decoded)} bytes")
                    except OSError as e:
                        if e.errno == 5:  # EIO
                            self.logger.error(f"❌ {self.name}: PTY closed after sending newline")
                            # 再次检查进程状态
                            pid_result, status = os.waitpid(self.pid, os.WNOHANG)
                            if pid_result != 0:
                                exit_code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else -1
                                self.logger.error(f"   Process exited with code {exit_code}")
                            return False
                except OSError as e:
                    self.logger.debug(f"{self.name}: Could not send initial newline: {e}")

                # 对于 codex，发送一个初始命令来保持它活跃
                if self.cli_command == 'codex':
                    self.logger.debug(f"{self.name}: Sending initial command to keep it active")
                    time.sleep(0.5)  # 稍等片刻
                    try:
                        # 发送 /status 命令
                        os.write(self.fd, b'/status\n')
                        time.sleep(0.5)

                        # 读取响应
                        try:
                            status_response = os.read(self.fd, 8192)
                            if status_response:
                                decoded = status_response.decode('utf-8', errors='replace')
                                initial_output += decoded
                                self.output_buffer += decoded
                                self.logger.debug(f"{self.name}: Got status response: {len(decoded)} bytes")
                        except OSError as e:
                            if e.errno not in (5, 11, 35):  # 忽略 EIO, EAGAIN
                                self.logger.debug(f"{self.name}: Error reading status response: {e}")
                    except OSError as e:
                        self.logger.debug(f"{self.name}: Could not send status command: {e}")

            self.process_running = True
            self.logger.info(f"✅ Started {self.name} (PID: {self.pid})")

            # 如果有初始输出，记录一下（但过滤 ANSI 转义序列以便阅读）
            if initial_output:
                # clean_output 已经在上面定义了
                self.logger.debug(f"{self.name} initial output: {meaningful_content[:200]}")
            else:
                self.logger.warning(f"{self.name}: No initial output received (may be normal)")

            # 对于 codex，启动心跳线程保持它活跃
            if self.cli_command == 'codex':
                self._start_heartbeat()

            return True

        except FileNotFoundError:
            self.logger.error(f"❌ Command '{self.cli_command}' not found")
            return False
        except Exception as e:
            self.logger.error(f"❌ Failed to start {self.name}: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
            return False
    
    def send_command(self, command: str) -> bool:
        """向 Agent 发送命令"""
        if self.fd is None:
            self.logger.warning(f"Cannot send command: {self.name} not initialized")
            return False

        # 检查进程是否还在运行
        if not self.is_running():
            self.logger.warning(f"Cannot send command: {self.name} not running")
            return False

        try:
            # 发送命令 + Enter
            cmd_bytes = command.encode('utf-8')
            if cmd_bytes:
                os.write(self.fd, cmd_bytes)

            # Claude / Gemini 等 CLI 需要先发送 C-j (LF) 再发送 C-m (CR) 才会触发执行
            requires_crlf = self.cli_command in {'claude', 'gemini'}

            if requires_crlf:
                os.write(self.fd, b'\n')  # C-j
                time.sleep(0.05)         # 短暂等待，模拟连续按键
                os.write(self.fd, b'\r') # C-m
            else:
                os.write(self.fd, b'\n')

            self.logger.debug(f"→ {self.name}: {command[:60]}")
            return True

        except Exception as e:
            self.logger.error(f"Error sending command to {self.name}: {e}")
            return False
    
    def read_output(self, timeout: float = 0.2) -> str:
        """从 Agent 读取输出"""
        if not self.stdout_fd:
            return ""

        # 首先从 output_buffer 获取已有内容（可能是心跳线程读取的）
        with self.buffer_lock:
            output = self.output_buffer
            self.output_buffer = ""  # 清空 buffer

        # 如果 PTY 已关闭，只返回 buffer 中剩余的内容
        if self.pty_closed:
            return output

        # 检查进程是否还在运行
        if not self.is_running():
            return output

        # 然后尝试从文件描述符读取新内容
        start_time = time.time()

        try:
            while time.time() - start_time < timeout:
                # 使用 select 等待数据可读
                ready, _, _ = select.select([self.stdout_fd], [], [], 0.05)

                if ready:
                    try:
                        chunk = os.read(self.stdout_fd, 4096)
                        if chunk:
                            decoded = chunk.decode('utf-8', errors='replace')
                            output += decoded
                        # 不要在这里设置 process_running = False
                        # 空 chunk 不一定意味着进程退出
                    except OSError as e:
                        # EAGAIN/EWOULDBLOCK 是正常的非阻塞错误
                        if e.errno in (11, 35):  # EAGAIN, EWOULDBLOCK
                            continue
                        # EIO (errno 5) 通常意味着 PTY slave 已关闭（进程退出）
                        # 但也可能是暂时的，所以需要验证进程状态
                        elif e.errno == 5:
                            # 只有在进程真的退出时才报告
                            if not self.is_running():
                                if not self.pty_closed:
                                    self.logger.debug(f"{self.name}: PTY closed (process exited)")
                                    self.pty_closed = True
                                    self.process_running = False
                            break
                        else:
                            self.logger.debug(f"Error reading from {self.name}: {e}")
                        break

        except Exception as e:
            self.logger.debug(f"Error reading from {self.name}: {e}")

        # 过滤 ANSI 和 OSC 转义序列以便更清晰地阅读
        if output:
            import re
            # 移除大多数 CSI 序列（含扩展模式）
            output = re.sub(r'\x1b\[[0-9;?]*[ -/]*[@-~]', '', output)
            # 移除 OSC 序列（超链接、标题等），支持 BEL 或 ST 结尾
            output = re.sub(r'\x1b\][^\x07\x1b]*(\x07|\x1b\\)', '', output)
            # 移除单字符转义序列（G0/G1 选择等）
            output = re.sub(r'\x1b[()][0-9A-Za-z]', '', output)
            # 移除其他孤立的 ESC 控制
            output = output.replace('\x1b=', '').replace('\x1b>', '')
            # 统一回车符
            output = output.replace('\r\n', '\n').replace('\r', '\n')

        return output
    
    def is_running(self) -> bool:
        """检查进程是否还在运行"""
        if self.pid is None:
            return False

        try:
            # 使用 os.kill 的信号 0 来测试进程是否存在
            os.kill(self.pid, 0)
            return True
        except (ProcessLookupError, OSError):
            self.process_running = False
            return False

    def _start_heartbeat(self):
        """启动心跳线程保持 codex 活跃"""
        def heartbeat():
            self.logger.debug(f"{self.name}: Starting heartbeat thread")
            last_heartbeat_time = time.time()

            while self.heartbeat_running and self.is_running():
                current_time = time.time()

                # 每 10 秒发送一次心跳
                if current_time - last_heartbeat_time >= 10:
                    try:
                        if self.fd and not self.pty_closed:
                            # 发送一个空换行作为心跳
                            os.write(self.fd, b'\n')
                            self.logger.debug(f"{self.name}: Heartbeat sent")

                            # 尝试读取任何响应（清理缓冲区）
                            try:
                                response = os.read(self.fd, 4096)
                                if response:
                                    with self.buffer_lock:
                                        self.output_buffer += response.decode('utf-8', errors='replace')
                            except OSError:
                                pass  # 忽略读取错误

                            last_heartbeat_time = current_time
                    except OSError as e:
                        self.logger.debug(f"{self.name}: Heartbeat failed: {e}")
                        if e.errno == 5:  # EIO - PTY closed
                            break

                time.sleep(1)  # 每秒检查一次

            self.logger.debug(f"{self.name}: Heartbeat thread stopped")

        self.heartbeat_running = True
        self.heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
        self.heartbeat_thread.start()
        self.logger.info(f"{self.name}: Heartbeat enabled (10s interval)")

    def _stop_heartbeat(self):
        """停止心跳线程"""
        if self.heartbeat_running:
            self.heartbeat_running = False
            if self.heartbeat_thread:
                self.heartbeat_thread.join(timeout=2)
            self.logger.debug(f"{self.name}: Heartbeat stopped")

    def terminate(self):
        """优雅地终止 Agent"""
        if self.pid is None:
            return

        # 停止心跳线程
        self._stop_heartbeat()

        try:
            # 首先尝试 SIGTERM
            os.kill(self.pid, signal.SIGTERM)
            
            # 等待 2 秒
            for _ in range(20):
                if not self.is_running():
                    break
                time.sleep(0.1)
            
            # 如果还在运行，使用 SIGKILL
            if self.is_running():
                os.kill(self.pid, signal.SIGKILL)
            
            self.logger.info(f"✅ Terminated {self.name}")
        
        except Exception as e:
            self.logger.debug(f"Error terminating {self.name}: {e}")
        
        finally:
            self.process_running = False


class Orchestrator:
    """主控器：管理 Claude-1 和 Claude-2 的交互"""
    
    def __init__(self):
        self.agents: Dict[str, CLIAgent] = {}
        self.running = False
        self.logger = logging.getLogger('orchestrator')
        
        # 设置信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """处理中断信号"""
        self.logger.info("Received interrupt signal, shutting down...")
        self.shutdown()
        sys.exit(0)
    
    def register_agent(self, name: str, cli_command: str, config: Optional[Dict[str, Any]] = None) -> bool:
        """
        注册新 Agent（为未来扩展留好接口）

        Args:
            name: Agent 名称
            cli_command: CLI 命令
            config: Agent 配置字典（可选）
        """
        if name in self.agents:
            self.logger.warning(f"Agent {name} already registered")
            return False

        agent = CLIAgent(name=name, cli_command=cli_command, config=config)
        self.agents[name] = agent

        self.logger.info(f"Registered agent: {name}")
        return True
    
    def start_all(self) -> bool:
        """启动所有 Agent"""
        self.logger.info("Starting all agents...")

        success_count = 0
        failed_agents = []

        for name, agent in self.agents.items():
            if agent.start():
                success_count += 1
                # 等待 Agent 启动
                time.sleep(0.5)
            else:
                self.logger.warning(f"⚠️  Failed to start {name}")
                failed_agents.append(name)

        if success_count == 0:
            self.logger.error("❌ No agents could be started")
            self.shutdown()
            return False

        self.running = True

        if failed_agents:
            self.logger.warning(f"⚠️  Some agents failed to start: {', '.join(failed_agents)}")
            self.logger.info(f"✅ {success_count}/{len(self.agents)} agents started successfully")
        else:
            self.logger.info("✅ All agents started successfully")

        return True
    
    def get_agent(self, name: str) -> Optional[CLIAgent]:
        """获取 Agent"""
        return self.agents.get(name)
    
    def shutdown(self):
        """关闭所有 Agent"""
        self.logger.info("Shutting down all agents...")
        
        for name, agent in self.agents.items():
            agent.terminate()
        
        self.running = False
        self.logger.info("✅ All agents shut down")
    
    def show_status(self):
        """显示所有 Agent 的状态"""
        print("\n" + "="*50)
        print("Agent Status:")
        print("="*50)
        
        for name, agent in self.agents.items():
            status = "🟢 Running" if agent.is_running() else "🔴 Stopped"
            print(f"  {name:15} {status}")
        
        print("="*50 + "\n")


class InteractiveSession:
    """与 Claude-1 的交互式会话，支持 Claude-1 驱动 Claude-2"""

    def __init__(self, orchestrator: Orchestrator, enable_history: bool = True):
        self.orchestrator = orchestrator
        self.claude1 = orchestrator.get_agent("claude-1")
        self.claude2 = orchestrator.get_agent("claude-2")
        self.logger = logging.getLogger('session')

        # 检查至少有一个 agent 可用
        if not self.claude1 and not self.claude2:
            raise RuntimeError("No agents available")

        # 检查 codex 是否真的在运行
        if self.claude1 and not self.claude1.is_running():
            self.logger.warning("⚠️  Claude-1 agent not running, will use Claude-2 only")
            self.claude1 = None

        if not self.claude2 or not self.claude2.is_running():
            if not self.claude1 or not self.claude1.is_running():
                raise RuntimeError("No running agents available")

        # 监听线程
        self.monitor_thread = None
        self.monitoring = True

        # 对话历史
        self.history_enabled = enable_history and CONFIG_AVAILABLE and ConversationHistory
        if self.history_enabled:
            self.history = ConversationHistory(max_entries=1000)
            self.session_manager = SessionManager()
            self.logger.info("✅ 对话历史已启用")
        else:
            self.history = None
            self.session_manager = None
            if enable_history and not CONFIG_AVAILABLE:
                self.logger.warning("⚠️  对话历史模块不可用")

        # AI 自动编排
        self.auto_orchestration = True  # 默认启用自动编排
        self.max_orchestration_loops = 10  # 最大循环次数，防止死循环
    
    def show_help(self):
        """显示帮助信息"""
        help_text = """
╔════════════════════════════════════════════════════════════╗
║     AI Orchestrator - Claude-1 Driving Claude-2           ║
╚════════════════════════════════════════════════════════════╝

INTERACTIVE MODE:
  直接输入任务 → 由 Claude-1 处理
  例: write a Python function to calculate factorial

SPECIAL COMMANDS (在 Claude-1 中执行):
  > claude [command]   向 Claude-2 发送命令
  例: > claude optimize the previous code

  /status              显示 Agent 状态
  /claude_output       查看 Claude-2 的最新输出
  /clear               清屏
  /help                显示此帮助
  /exit                退出

CONVERSATION HISTORY COMMANDS (对话历史):
  /history [n]         显示最近 n 条对话（默认 10 条）
  /history search <keyword>  搜索包含关键词的对话
  /save [name]         保存当前会话
  /load <name>         加载历史会话
  /sessions            列出所有已保存的会话
  /export <filename>   导出对话历史为 Markdown
  /stats               显示对话统计信息

AI AUTO-ORCHESTRATION (AI自动编排):
  直接输入复杂任务，Claude-1 会自动调用 Claude-2 协作
  Claude-1 使用 @claude-2: <任务> 来调用 Claude-2
  任务完成时会输出 [COMPLETE] 标记
  /auto on|off         开启或关闭自动编排模式

WORKFLOW EXAMPLE:
  codex> write a python function
  [Claude-1 思考...并可能调用 Claude-2]
  
  codex> > claude make it more efficient
  [Claude-1 向 Claude-2 发送: make it more efficient]
  [Claude-2 执行，输出返回给 Claude-1]
  
  codex> > claude add error handling
  [继续对话...]

NOTES:
  - 所有输出自动记录到 orchestrator.log
  - Claude-1 和 Claude-2 都在后台运行
  - 架构支持未来添加更多 AI (Gemini etc.)
"""
        print(help_text)

    def _parse_agent_call(self, output: str) -> Optional[Tuple[str, str]]:
        """
        解析 AI 输出，检测是否调用其他 Agent

        Returns:
            (agent_name, task) 或 None
        """
        import re

        # 匹配 @agent-name: task
        pattern = r'@(claude-\d+|codex|gemini):\s*(.+?)(?=\n@|\n\[|$)'
        match = re.search(pattern, output, re.DOTALL)

        if match:
            agent_name = match.group(1)
            task = match.group(2).strip()
            return (agent_name, task)

        return None

    def _is_complete(self, output: str) -> bool:
        """检测任务是否完成"""
        return '[COMPLETE]' in output or '[DONE]' in output

    def _extract_final_result(self, output: str) -> str:
        """提取最终结果"""
        if '[COMPLETE]' in output:
            parts = output.split('[COMPLETE]', 1)
            if len(parts) > 1:
                return parts[1].strip()
        elif '[DONE]' in output:
            parts = output.split('[DONE]', 1)
            if len(parts) > 1:
                return parts[1].strip()
        return output

    def _send_to_claude1_with_orchestration(self, command: str):
        """
        向 Claude-1 发送命令，支持自动编排
        Claude-1 可以通过 @claude-2 自动调用 Claude-2
        """
        if not self.claude1 or not self.claude1.is_running():
            print("❌ Claude-1 is not available")
            return

        # 记录用户消息
        if self.history_enabled:
            self.history.add_user_message(command)

        # 构建初始提示（包含系统指令）
        if self.auto_orchestration:
            system_instruction = """
[SYSTEM] 你是一个 AI 编排器。你可以调用 Claude-2 协助完成任务：
- 使用 @claude-2: <任务> 来调用
- 完成后输出 [COMPLETE] 标记

"""
            initial_command = system_instruction + command
        else:
            initial_command = command

        print(f"→ Sending to Claude-1: {command}")
        print("🔄 自动编排模式已启用\n")

        # 开始编排循环
        loop_count = 0
        current_agent = self.claude1
        current_command = initial_command

        while loop_count < self.max_orchestration_loops:
            loop_count += 1
            self.logger.debug(f"Orchestration loop {loop_count}")

            # 发送命令
            if not current_agent.send_command(current_command):
                print("❌ Failed to send command")
                break

            # 等待响应
            time.sleep(2.0)

            # 读取输出
            output = ""
            deadline = time.time() + 45.0
            idle_checks = 0
            max_idle_checks = 3

            while time.time() < deadline and idle_checks < max_idle_checks:
                chunk = current_agent.read_output(timeout=3.0)
                if chunk:
                    output += chunk
                    idle_checks = 0
                    time.sleep(0.5)
                else:
                    idle_checks += 1
                    time.sleep(2.0 if not output.strip() else 1.0)

            if not output.strip():
                print("⚠️  No response")
                break

            # 清理输出
            normalized = output.replace('\r\n', '\n').replace('\r', '\n')
            lines = normalized.split('\n')
            cleaned_lines = self._clean_output_lines(current_command, lines, current_agent.name)
            cleaned_output = '\n'.join(cleaned_lines) if cleaned_lines else output

            # 记录响应
            if self.history_enabled:
                self.history.add_agent_message(current_agent.name, cleaned_output)

            # 显示输出
            print(f"\n{'='*60}")
            print(f"📤 {current_agent.name} 响应:")
            print(f"{'='*60}")
            for line in cleaned_lines[:50]:  # 限制显示行数
                print(line)
            if len(cleaned_lines) > 50:
                print(f"... (还有 {len(cleaned_lines) - 50} 行)")
            print(f"{'='*60}\n")

            # 检测是否完成
            if self._is_complete(cleaned_output):
                final_result = self._extract_final_result(cleaned_output)
                print("\n✅ 任务完成！\n")
                print(f"{'='*60}")
                print("🎯 最终结果:")
                print(f"{'='*60}")
                print(final_result)
                print(f"{'='*60}\n")
                break

            # 检测是否调用其他 Agent
            agent_call = self._parse_agent_call(cleaned_output)
            if agent_call:
                target_agent_name, task = agent_call
                print(f"\n🔵 检测到调用: {target_agent_name}")
                print(f"   任务: {task[:100]}{'...' if len(task) > 100 else ''}\n")

                # 路由到目标 Agent
                if target_agent_name == 'claude-2' and self.claude2:
                    target_agent = self.claude2

                    # 记录调用
                    if self.history_enabled:
                        self.history.add_system_message(f"Claude-1 调用 Claude-2: {task[:100]}")

                    # 发送给 Claude-2
                    if not target_agent.send_command(task):
                        print("❌ Failed to call Claude-2")
                        break

                    # 等待 Claude-2 响应
                    time.sleep(2.0)
                    claude2_output = ""
                    deadline2 = time.time() + 45.0
                    idle_checks2 = 0

                    while time.time() < deadline2 and idle_checks2 < 3:
                        chunk2 = target_agent.read_output(timeout=3.0)
                        if chunk2:
                            claude2_output += chunk2
                            idle_checks2 = 0
                            time.sleep(0.5)
                        else:
                            idle_checks2 += 1
                            time.sleep(1.0)

                    # 清理 Claude-2 输出
                    normalized2 = claude2_output.replace('\r\n', '\n').replace('\r', '\n')
                    lines2 = normalized2.split('\n')
                    cleaned_lines2 = self._clean_output_lines(task, lines2, 'claude-2')
                    cleaned_output2 = '\n'.join(cleaned_lines2) if cleaned_lines2 else claude2_output

                    # 记录 Claude-2 响应
                    if self.history_enabled:
                        self.history.add_agent_message('claude-2', cleaned_output2)

                    # 显示 Claude-2 输出
                    print(f"\n{'='*60}")
                    print(f"📥 Claude-2 响应:")
                    print(f"{'='*60}")
                    for line in cleaned_lines2[:30]:
                        print(line)
                    if len(cleaned_lines2) > 30:
                        print(f"... (还有 {len(cleaned_lines2) - 30} 行)")
                    print(f"{'='*60}\n")

                    # 把 Claude-2 的响应发回给 Claude-1
                    print("🔄 将响应返回给 Claude-1...\n")
                    current_agent = self.claude1
                    current_command = f"Claude-2 的响应：\n\n{cleaned_output2}\n\n请继续处理。"

                else:
                    print(f"⚠️  Agent {target_agent_name} not available")
                    break
            else:
                # 没有检测到调用，也没有完成标记
                print("\n⚠️  Claude-1 没有标记任务完成，也没有调用其他 Agent")
                print("   可能需要手动继续...\n")
                break

        if loop_count >= self.max_orchestration_loops:
            print(f"\n⚠️  达到最大循环次数 ({self.max_orchestration_loops})，停止编排")

    def _start_monitoring(self):
        """启动后台监听线程（监控输出和进程状态）"""
        # 跟踪已知的进程状态
        claude1_was_running = self.claude1 and self.claude1.is_running()
        claude2_was_running = self.claude2 and self.claude2.is_running()

        def monitor():
            nonlocal claude1_was_running, claude2_was_running

            while self.monitoring and self.orchestrator.running:
                # 检查 Claude-1 状态变化
                if self.claude1 and self.claude1.pid:
                    claude1_running_now = self.claude1.is_running()
                    if claude1_was_running and not claude1_running_now:
                        # 尝试获取退出状态
                        try:
                            pid_result, status = os.waitpid(self.claude1.pid, os.WNOHANG)
                            if pid_result != 0:
                                if os.WIFEXITED(status):
                                    exit_code = os.WEXITSTATUS(status)
                                    self.logger.warning(f"⚠️  Claude-1 exited with code {exit_code}")
                                    print(f"\n⚠️  Warning: Claude-1 exited with code {exit_code}\n")
                                elif os.WIFSIGNALED(status):
                                    signal_num = os.WTERMSIG(status)
                                    self.logger.warning(f"⚠️  Claude-1 killed by signal {signal_num}")
                                    print(f"\n⚠️  Warning: Claude-1 killed by signal {signal_num}\n")
                                else:
                                    self.logger.warning("⚠️  Claude-1 exited unexpectedly")
                                    print("\n⚠️  Warning: Claude-1 exited unexpectedly\n")
                            else:
                                self.logger.warning("⚠️  Claude-1 stopped running")
                                print("\n⚠️  Warning: Claude-1 stopped running\n")
                        except (OSError, ChildProcessError):
                            self.logger.warning("⚠️  Claude-1 stopped running")
                            print("\n⚠️  Warning: Claude-1 stopped running\n")

                        print("claude1> ", end='', flush=True)  # 重新显示提示符
                    claude1_was_running = claude1_running_now

                    # 只在进程运行时读取输出
                    if claude1_running_now:
                        try:
                            output = self.claude1.read_output(timeout=0.1)
                            if output and "[BACKGROUND]" in output:
                                self.logger.info(f"Claude-1 background: {output[:100]}")
                        except Exception as e:
                            self.logger.debug(f"Error in monitor reading codex: {e}")

                # 检查 Claude-2 状态变化
                if self.claude2 and self.claude2.pid:
                    claude2_running_now = self.claude2.is_running()
                    if claude2_was_running and not claude2_running_now:
                        # 尝试获取退出状态
                        try:
                            pid_result, status = os.waitpid(self.claude2.pid, os.WNOHANG)
                            if pid_result != 0:
                                if os.WIFEXITED(status):
                                    exit_code = os.WEXITSTATUS(status)
                                    self.logger.warning(f"⚠️  Claude-2 exited with code {exit_code}")
                                    print(f"\n⚠️  Warning: Claude-2 exited with code {exit_code}\n")
                                elif os.WIFSIGNALED(status):
                                    signal_num = os.WTERMSIG(status)
                                    self.logger.warning(f"⚠️  Claude-2 killed by signal {signal_num}")
                                    print(f"\n⚠️  Warning: Claude-2 killed by signal {signal_num}\n")
                                else:
                                    self.logger.warning("⚠️  Claude-2 exited unexpectedly")
                                    print("\n⚠️  Warning: Claude-2 exited unexpectedly\n")
                            else:
                                self.logger.warning("⚠️  Claude-2 stopped running")
                                print("\n⚠️  Warning: Claude-2 stopped running\n")
                        except (OSError, ChildProcessError):
                            self.logger.warning("⚠️  Claude-2 stopped running")
                            print("\n⚠️  Warning: Claude-2 stopped running\n")

                        print("claude2> ", end='', flush=True)  # 重新显示提示符
                    claude2_was_running = claude2_running_now

                time.sleep(10.0)  # 监控间隔（10秒足够检测进程退出）

        self.monitor_thread = threading.Thread(target=monitor, daemon=True)
        self.monitor_thread.start()
    
    def run(self):
        """运行交互式会话"""
        print("\n" + "="*60)
        print("🤖 AI Orchestrator - MVP Version")

        # 显示可用的 agents
        available_agents = []
        if self.claude1 and self.claude1.is_running():
            available_agents.append("Claude-1")
        if self.claude2 and self.claude2.is_running():
            available_agents.append("Claude-2")

        print(f"   Available: {', '.join(available_agents)}")
        print("="*60)
        print("Type '/help' for commands")
        print("="*60 + "\n")

        # 如果只有 Claude-2 可用，显示提示
        if not self.claude1 and self.claude2:
            print("ℹ️  Note: Claude-1 is not available, using Claude-2 only")
            print("   You can interact directly with Claude-2\n")

        self._start_monitoring()

        # 选择提示符
        prompt = "claude2> " if (not self.claude1 and self.claude2) else "claude1> "

        try:
            while True:
                try:
                    user_input = input(prompt).strip()

                    if not user_input:
                        continue

                    # 处理特殊命令
                    if user_input.startswith('/'):
                        self._handle_command(user_input)

                    # 向 Claude-2 发送命令（使用 > 前缀或直接输入）
                    elif user_input.startswith('>') or (not self.claude1 and self.claude2):
                        command = user_input[1:].strip() if user_input.startswith('>') else user_input
                        self._send_to_claude2(command)

                    # 正常输入发送给 Claude-1（使用自动编排模式）
                    elif self.claude1:
                        if self.auto_orchestration:
                            self._send_to_claude1_with_orchestration(user_input)
                        else:
                            self._send_to_claude1(user_input)
                    else:
                        print("⚠️  No agent available to handle this command")

                except KeyboardInterrupt:
                    print("\n\nUse '/exit' to quit")
                except EOFError:
                    break

        finally:
            self.monitoring = False
            print("\n✅ Session ended")
    
    def _handle_command(self, cmd: str):
        """处理特殊命令"""
        cmd_lower = cmd.lower().strip()
        parts = cmd.strip().split(maxsplit=1)
        cmd_name = parts[0].lower()

        if cmd_name == '/help':
            self.show_help()

        elif cmd_name == '/status':
            self.orchestrator.show_status()

        elif cmd_name == '/claude_output':
            self._show_claude_output()

        elif cmd_name == '/clear':
            os.system('clear' if os.name == 'posix' else 'cls')

        elif cmd_name == '/exit':
            print("Exiting...")
            sys.exit(0)

        # 对话历史命令
        elif cmd_name == '/history':
            self._handle_history_command(parts[1] if len(parts) > 1 else '')

        elif cmd_name == '/save':
            self._handle_save_command(parts[1] if len(parts) > 1 else None)

        elif cmd_name == '/load':
            if len(parts) < 2:
                print("❌ 用法: /load <session_name>")
            else:
                self._handle_load_command(parts[1])

        elif cmd_name == '/sessions':
            self._handle_sessions_command()

        elif cmd_name == '/export':
            if len(parts) < 2:
                print("❌ 用法: /export <filename>")
            else:
                self._handle_export_command(parts[1])

        elif cmd_name == '/stats':
            self._handle_stats_command()

        # 自动编排命令
        elif cmd_name == '/auto':
            if len(parts) < 2:
                status = "启用" if self.auto_orchestration else "禁用"
                print(f"自动编排模式: {status}")
                print("用法: /auto on|off")
            else:
                mode = parts[1].lower()
                if mode == 'on':
                    self.auto_orchestration = True
                    print("✅ 自动编排模式已启用")
                    print("   Claude-1 现在可以自动调用 Claude-2")
                elif mode == 'off':
                    self.auto_orchestration = False
                    print("❌ 自动编排模式已禁用")
                    print("   需要手动使用 > claude-2 调用")
                else:
                    print("❌ 无效参数，使用: /auto on 或 /auto off")

        else:
            print(f"Unknown command: {cmd_name}")
            print("Type '/help' for available commands")
    
    def _clean_output_lines(self, command: str, lines: List[str], agent_label: str) -> List[str]:
        """过滤掉 CLI UI 噪声，只保留有效内容"""
        cleaned: List[str] = []
        seen: set = set()

        # 常见噪声关键词（大小写不敏感匹配）
        noise_keywords = [
            "? for shortcuts",
            "thinking on",
            "approaching weekly limit",
            "ctrl-g to edit prompt in vi",
            "ctrl+o to show thinking",
            "billowing…",
            "marinating…",
            "thinking…",
            "∙ billowing",
            "∙ marinating",
            "thought for",
            "esc to interrupt",
            "tab to toggle",
            "weekly limit",
            "token",
            "bonjour claude",  # placeholder, keep optional
        ]

        for raw_line in lines:
            if not raw_line:
                continue

            # 统一空白字符并剥离前后空格
            normalized = raw_line.replace('\xa0', ' ').strip()
            if not normalized:
                continue

            lower_line = normalized.lower()

            # 跳过命令回显和提示符
            if normalized == command:
                continue
            if normalized in {'>', f'{agent_label}>'}:
                continue
            if normalized.startswith(f'{agent_label}>'):
                tail = normalized[len(agent_label) + 1 :].strip()
                if not tail or tail == command:
                    continue
                normalized = tail
                lower_line = normalized.lower()

            if normalized.startswith('>'):
                # 处理 > command 或者 >  command 变体
                remaining = normalized[1:].strip()
                if remaining == command or not remaining:
                    continue

            # 跳过由装饰字符组成的分割线
            if all(ch in {'─', '─', ' ', '-', '·', '—'} for ch in normalized):
                continue

            # 跳过噪声关键字
            if any(keyword in lower_line for keyword in noise_keywords):
                continue

            # 避免重复行
            if normalized in seen:
                continue

            seen.add(normalized)
            cleaned.append(normalized)

        return cleaned

    def _send_to_claude1(self, command: str):
        """向 Claude-1 发送命令并显示响应"""
        if not self.claude1 or not self.claude1.is_running():
            print("❌ Claude-1 is not available")
            return

        # 记录用户消息到历史
        if self.history_enabled:
            self.history.add_user_message(command)

        print(f"→ Sending to Claude-1: {command}")

        if not self.claude1.send_command(command):
            print("❌ Failed to send command to Claude-1")
            return

        # 等待 Claude-1 处理（AI 模型需要更长时间生成响应）
        time.sleep(2.0)

        # 读取 Claude-1 的输出
        output = ""
        deadline = time.time() + 45.0  # 最多等待约 45 秒
        idle_checks = 0
        max_idle_checks = 3  # 允许多次空读，以适应慢速流式响应
        attempt = 0

        while time.time() < deadline and idle_checks < max_idle_checks:
            attempt += 1
            chunk = self.claude1.read_output(timeout=3.0)

            if chunk:
                self.logger.debug(f"Received chunk {attempt}: {len(chunk)} bytes")
                output += chunk
                idle_checks = 0  # 有新内容，重置空读计数
                time.sleep(0.5)
            else:
                idle_checks += 1
                # 初次读取不到内容，等待更久；后续空读采用较短等待
                sleep_time = 2.0 if not output.strip() else 1.0
                self.logger.debug(
                    f"No new content on attempt {attempt} "
                    f"(idle {idle_checks}/{max_idle_checks})"
                )
                time.sleep(sleep_time)

        self.logger.debug(
            f"Total output received: {len(output)} bytes; "
            f"idle_checks={idle_checks}"
        )

        if output.strip():
            normalized = output.replace('\r\n', '\n').replace('\r', '\n')
            lines = normalized.split('\n')
            cleaned_lines = self._clean_output_lines(command, lines, 'claude1')

            if cleaned_lines:
                response_text = '\n'.join(cleaned_lines)

                # 记录 Agent 响应到历史
                if self.history_enabled:
                    self.history.add_agent_message('claude-1', response_text)

                for line in cleaned_lines:
                    print(line)
            else:
                print("⚠️  Claude-1 produced output that could not be parsed.")
        else:
            print("⚠️  No response from Claude-1 (timeout or rate limit)")
    
    def _send_to_claude2(self, command: str):
        """从 Claude-1 向 Claude-2 发送命令"""
        if not self.claude2 or not self.claude2.is_running():
            print("❌ Claude-2 is not available")
            return

        # 记录用户消息到历史（发送给 Claude-2）
        if self.history_enabled:
            self.history.add_user_message(f"> claude {command}")

        print(f"\n🔵 Claude-2 ← Sending: {command}")

        if not self.claude2.send_command(command):
            print("❌ Failed to send command to Claude-2")
            return

        # 等待 Claude-2 处理（AI 模型需要更长时间生成响应）
        time.sleep(2.0)

        # 读取 Claude-2 的输出
        output = ""
        deadline = time.time() + 45.0  # 最多等待约 45 秒
        idle_checks = 0
        max_idle_checks = 3
        attempt = 0

        while time.time() < deadline and idle_checks < max_idle_checks:
            attempt += 1
            chunk = self.claude2.read_output(timeout=3.0)

            if chunk:
                self.logger.debug(f"Received Claude chunk {attempt}: {len(chunk)} bytes")
                output += chunk
                idle_checks = 0
                time.sleep(0.5)
            else:
                idle_checks += 1
                sleep_time = 2.0 if not output.strip() else 1.0
                self.logger.debug(
                    f"No more Claude content on attempt {attempt} "
                    f"(idle {idle_checks}/{max_idle_checks})"
                )
                time.sleep(sleep_time)

        self.logger.debug(
            f"Total Claude output received: {len(output)} bytes; "
            f"idle_checks={idle_checks}"
        )

        if output.strip():
            normalized = output.replace('\r\n', '\n').replace('\r', '\n')
            lines = normalized.split('\n')
            filtered = self._clean_output_lines(command, lines, 'claude2')

            if filtered:
                response_text = '\n'.join(filtered[-20:])

                # 记录 Claude-2 响应到历史
                if self.history_enabled:
                    self.history.add_agent_message('claude-2', response_text)

                print("\n🔵 Claude-2 Output:")
                print("-" * 50)
                for line in filtered[-20:]:
                    print(line)
                print("-" * 50)
            else:
                print("⚠️  Claude-2 produced output that could not be parsed.")
        else:
            print("⚠️  No response from Claude-2 (timeout or rate limit)")

        if self.claude1:
            print("\n继续 Claude-1 会话...\n")
        else:
            print()
    
    def _show_claude_output(self):
        """显示 Claude-2 的最新输出"""
        if not self.claude2 or not self.claude2.is_running():
            print("❌ Claude-2 is not available")
            return

        output = self.claude2.read_output(timeout=0.5)

        if output.strip():
            print("\n--- Claude-2 Output ---")
            print(output)
            print("--- End Output ---\n")
        else:
            print("(No recent output from Claude-2)")

    def _handle_history_command(self, args: str):
        """处理 /history 命令"""
        if not self.history_enabled:
            print("❌ 对话历史功能未启用")
            return

        args = args.strip()

        # /history search <keyword>
        if args.startswith('search '):
            keyword = args[7:].strip()
            if not keyword:
                print("❌ 请提供搜索关键词")
                return

            results = self.history.search(keyword, limit=20)
            if not results:
                print(f"未找到包含 '{keyword}' 的对话")
                return

            print(f"\n搜索结果 ('{keyword}'):")
            print("=" * 60)
            for msg in results:
                timestamp = msg.format_timestamp('%H:%M:%S')
                role_icon = {'user': '👤', 'agent': '🤖', 'system': 'ℹ️'}.get(msg.role, '•')
                agent_info = f" [{msg.agent_name}]" if msg.agent_name else ""
                print(f"{role_icon} [{timestamp}]{agent_info} {msg.content[:80]}")
            print("=" * 60 + "\n")

        # /history [n]
        else:
            try:
                count = int(args) if args else 10
                count = max(1, min(count, 100))  # 限制在 1-100 之间
            except ValueError:
                print("❌ 无效的数字")
                return

            messages = self.history.get_recent_messages(count)
            if not messages:
                print("暂无对话历史")
                return

            print(f"\n最近 {len(messages)} 条对话:")
            print("=" * 60)
            for msg in messages:
                timestamp = msg.format_timestamp('%H:%M:%S')
                role_icon = {'user': '👤', 'agent': '🤖', 'system': 'ℹ️'}.get(msg.role, '•')
                agent_info = f" [{msg.agent_name}]" if msg.agent_name else ""
                print(f"{role_icon} [{timestamp}]{agent_info}")
                print(f"  {msg.content[:200]}")
                if len(msg.content) > 200:
                    print(f"  ... (共 {len(msg.content)} 字符)")
                print()
            print("=" * 60 + "\n")

    def _handle_save_command(self, name: Optional[str]):
        """处理 /save 命令"""
        if not self.history_enabled:
            print("❌ 对话历史功能未启用")
            return

        if not name:
            name = f"session_{int(time.time())}"

        try:
            file_path = self.session_manager.save_session(self.history, name)
            print(f"✅ 会话已保存: {file_path}")
        except Exception as e:
            print(f"❌ 保存会话失败: {e}")

    def _handle_load_command(self, name: str):
        """处理 /load 命令"""
        if not self.history_enabled:
            print("❌ 对话历史功能未启用")
            return

        try:
            loaded_history = self.session_manager.load_session(name)
            if loaded_history:
                self.history = loaded_history
                stats = self.history.get_stats()
                print(f"✅ 已加载会话: {name}")
                print(f"   消息数: {stats['messages_in_memory']}")
                print(f"   会话 ID: {stats['session_id']}")
            else:
                print(f"❌ 无法加载会话: {name}")
        except Exception as e:
            print(f"❌ 加载会话失败: {e}")

    def _handle_sessions_command(self):
        """处理 /sessions 命令"""
        if not self.history_enabled:
            print("❌ 对话历史功能未启用")
            return

        try:
            sessions = self.session_manager.list_sessions()
            if not sessions:
                print("暂无已保存的会话")
                return

            print(f"\n已保存的会话 ({len(sessions)} 个):")
            print("=" * 80)
            for session in sessions:
                from datetime import datetime
                start_time = datetime.fromtimestamp(session['start_time']).strftime('%Y-%m-%d %H:%M:%S')
                modified_time = datetime.fromtimestamp(session['modified_time']).strftime('%Y-%m-%d %H:%M:%S')
                size_kb = session['file_size'] / 1024

                print(f"📁 {session['filename']}")
                print(f"   会话 ID: {session['session_id']}")
                print(f"   开始时间: {start_time}")
                print(f"   修改时间: {modified_time}")
                print(f"   消息数: {session['message_count']}")
                print(f"   文件大小: {size_kb:.1f} KB")
                print()
            print("=" * 80 + "\n")
        except Exception as e:
            print(f"❌ 列出会话失败: {e}")

    def _handle_export_command(self, filename: str):
        """处理 /export 命令"""
        if not self.history_enabled:
            print("❌ 对话历史功能未启用")
            return

        if not filename.endswith('.md'):
            filename += '.md'

        try:
            if self.history.export_to_markdown(filename):
                print(f"✅ 对话历史已导出: {filename}")
            else:
                print(f"❌ 导出失败")
        except Exception as e:
            print(f"❌ 导出失败: {e}")

    def _handle_stats_command(self):
        """处理 /stats 命令"""
        if not self.history_enabled:
            print("❌ 对话历史功能未启用")
            return

        stats = self.history.get_stats()
        duration_minutes = stats['session_duration'] / 60

        print("\n📊 对话统计:")
        print("=" * 50)
        print(f"  会话 ID: {stats['session_id']}")
        print(f"  会话时长: {duration_minutes:.1f} 分钟")
        print(f"  总消息数: {stats['total_messages']}")
        print(f"  - 用户消息: {stats['user_messages']}")
        print(f"  - Agent 消息: {stats['agent_messages']}")
        print(f"  - 系统消息: {stats['system_messages']}")
        print(f"  内存中消息: {stats['messages_in_memory']}")
        print("=" * 50 + "\n")


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(
        description="AI Orchestrator - Claude-1 driving Claude-2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 orchestrator_enhanced.py
  python3 orchestrator_enhanced.py --debug   # Enable debug logging
  python3 orchestrator_enhanced.py --config custom_config.yaml

Notes:
  - Make sure codex and claude CLIs are installed
  - All interactions are logged to orchestrator.log
  - Architecture is extensible for future AI additions
  - Configuration file support: config.yaml
  - Conversation history automatically saved
        """
    )

    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging for detailed output'
    )

    parser.add_argument(
        '--config',
        type=str,
        default='config.yaml',
        help='Path to configuration file (default: config.yaml)'
    )

    parser.add_argument(
        '--no-history',
        action='store_true',
        help='Disable conversation history'
    )

    args = parser.parse_args()

    # 加载配置文件
    config = None
    if CONFIG_AVAILABLE:
        config = ConfigLoader(args.config)
        if config.load():
            logger.info(f"✅ 配置文件加载成功: {args.config}")

            # 从配置更新日志级别
            log_level = config.get('orchestrator.logging.level', 'INFO')
            if args.debug:
                log_level = 'DEBUG'

            for handler in logging.root.handlers[:]:
                logging.root.removeHandler(handler)

            logging.basicConfig(
                level=getattr(logging, log_level),
                format=config.get('orchestrator.logging.format', '[%(asctime)s] %(name)s: %(message)s'),
                handlers=[
                    logging.StreamHandler(),
                    logging.FileHandler(config.get('orchestrator.logging.file', 'orchestrator.log'))
                ]
            )
        else:
            logger.warning("⚠️  配置文件加载失败，使用默认设置")
    else:
        logger.warning("⚠️  配置模块不可用，使用默认设置")

        # 如果启用 debug，更新日志级别
        if args.debug:
            for handler in logging.root.handlers[:]:
                logging.root.removeHandler(handler)

            logging.basicConfig(
                level=logging.DEBUG,
                format='[%(asctime)s] %(name)s: %(message)s',
                handlers=[
                    logging.StreamHandler(),
                    logging.FileHandler('orchestrator.log')
                ]
            )

    if args.debug:
        logger.info("🔍 Debug mode enabled")

    # 创建主控器
    orchestrator = Orchestrator()

    # 注册 Agent
    if config and CONFIG_AVAILABLE:
        # 从配置文件注册 agents
        enabled_agents = config.get_enabled_agents()
        logger.info(f"从配置文件加载 {len(enabled_agents)} 个 Agent")

        for agent_config in enabled_agents:
            agent_name = agent_config.get('name')
            agent_command = agent_config.get('command')

            logger.info(f"注册 Agent: {agent_name} ({agent_command})")
            orchestrator.register_agent(agent_name, agent_command, agent_config)
    else:
        # 使用默认配置（两个 Claude 实例）
        logger.info("使用默认 Agent 配置")
        orchestrator.register_agent("claude-1", "claude")
        orchestrator.register_agent("claude-2", "claude")

    logger.info("Starting AI Orchestrator (MVP)")

    # 启动所有 Agent
    if not orchestrator.start_all():
        logger.error("Failed to start agents")
        sys.exit(1)

    # 运行交互式会话
    try:
        enable_history = not args.no_history
        session = InteractiveSession(orchestrator, enable_history=enable_history)
        session.run()

    except RuntimeError as e:
        logger.error(f"Session error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)

    finally:
        orchestrator.shutdown()


if __name__ == "__main__":
    main()
