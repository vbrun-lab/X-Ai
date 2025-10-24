#!/usr/bin/env python3
"""
orchestrator_enhanced.py - 增强版最小可行版本

改进：
1. Codex 可以通过 > 符号向 Claude Code 发送命令
   例如: > claude write a python function
2. Claude Code 的输出自动返回给 Codex
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
from typing import Dict, Optional, Tuple
import logging
import threading

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
    
    def __init__(self, name: str, cli_command: str):
        """
        Args:
            name: Agent 名称（如 'codex', 'claude-code'）
            cli_command: 启动命令（如 'codex' 或 'claude'）
        """
        self.name = name
        self.cli_command = cli_command
        
        self.pid: Optional[int] = None
        self.fd: Optional[int] = None  # PTY master fd
        self.process_running = False
        
        self.logger = logging.getLogger(f'agent.{name}')
        self.output_buffer = ""  # 缓存输出
    
    def start(self) -> bool:
        """启动 CLI 进程在 PTY 中"""
        try:
            # 启动子进程
            process = subprocess.Popen(
                [self.cli_command],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
                preexec_fn=os.setsid,  # 新进程组
                universal_newlines=False
            )
            
            self.pid = process.pid
            self.fd = process.stdin.fileno() if process.stdin else None
            self.stdout_fd = process.stdout.fileno() if process.stdout else None
            
            # 设置非阻塞模式
            if self.stdout_fd:
                fcntl.fcntl(self.stdout_fd, fcntl.F_SETFL, os.O_NONBLOCK)
            
            self.process_running = True
            self.logger.info(f"✅ Started {self.name} (PID: {self.pid})")
            
            return True
        
        except Exception as e:
            self.logger.error(f"❌ Failed to start {self.name}: {e}")
            return False
    
    def send_command(self, command: str) -> bool:
        """向 Agent 发送命令"""
        if not self.process_running or self.fd is None:
            self.logger.warning(f"Cannot send command: {self.name} not running")
            return False
        
        try:
            # 发送命令 + Enter
            cmd_bytes = (command + '\n').encode('utf-8')
            os.write(self.fd, cmd_bytes)
            
            self.logger.debug(f"→ {self.name}: {command[:60]}")
            return True
        
        except Exception as e:
            self.logger.error(f"Error sending command to {self.name}: {e}")
            return False
    
    def read_output(self, timeout: float = 0.2) -> str:
        """从 Agent 读取输出"""
        if not self.process_running or not self.stdout_fd:
            return ""
        
        output = ""
        start_time = time.time()
        
        try:
            while time.time() - start_time < timeout:
                # 使用 select 等待数据可读
                ready, _, _ = select.select([self.stdout_fd], [], [], 0.05)
                
                if ready:
                    try:
                        chunk = os.read(self.stdout_fd, 4096)
                        if chunk:
                            output += chunk.decode('utf-8', errors='replace')
                        else:
                            # EOF - 进程已结束
                            self.process_running = False
                            break
                    except OSError as e:
                        if e.errno != 11:  # EAGAIN
                            self.process_running = False
                        break
        
        except Exception as e:
            self.logger.debug(f"Error reading from {self.name}: {e}")
        
        # 更新缓冲区
        if output:
            self.output_buffer += output
        
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
    
    def terminate(self):
        """优雅地终止 Agent"""
        if self.pid is None:
            return
        
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
    """主控器：管理 Codex 和 Claude Code 的交互"""
    
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
    
    def register_agent(self, name: str, cli_command: str) -> bool:
        """注册新 Agent（为未来扩展留好接口）"""
        if name in self.agents:
            self.logger.warning(f"Agent {name} already registered")
            return False
        
        agent = CLIAgent(name=name, cli_command=cli_command)
        self.agents[name] = agent
        
        self.logger.info(f"Registered agent: {name}")
        return True
    
    def start_all(self) -> bool:
        """启动所有 Agent"""
        self.logger.info("Starting all agents...")
        
        for name, agent in self.agents.items():
            if not agent.start():
                self.logger.error(f"Failed to start {name}")
                self.shutdown()
                return False
            
            # 等待 Agent 启动
            time.sleep(0.5)
        
        self.running = True
        self.logger.info("✅ All agents started")
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
    """与 Codex 的交互式会话，支持 Codex 驱动 Claude Code"""
    
    def __init__(self, orchestrator: Orchestrator):
        self.orchestrator = orchestrator
        self.codex = orchestrator.get_agent("codex")
        self.claude = orchestrator.get_agent("claude-code")
        self.logger = logging.getLogger('session')
        
        if not self.codex:
            raise RuntimeError("Codex agent not found")
        if not self.claude:
            raise RuntimeError("Claude Code agent not found")
        
        # 监听线程
        self.monitor_thread = None
        self.monitoring = True
    
    def show_help(self):
        """显示帮助信息"""
        help_text = """
╔════════════════════════════════════════════════════════════╗
║     AI Orchestrator - Codex Driving Claude Code           ║
╚════════════════════════════════════════════════════════════╝

INTERACTIVE MODE:
  直接输入任务 → 由 Codex 处理
  例: write a Python function to calculate factorial

SPECIAL COMMANDS (在 Codex 中执行):
  > claude [command]   向 Claude Code 发送命令
  例: > claude optimize the previous code
  
  /status              显示 Agent 状态
  /claude_output       查看 Claude Code 的最新输出
  /clear               清屏
  /help                显示此帮助
  /exit                退出

WORKFLOW EXAMPLE:
  codex> write a python function
  [Codex 思考...并可能调用 Claude Code]
  
  codex> > claude make it more efficient
  [Codex 向 Claude Code 发送: make it more efficient]
  [Claude Code 执行，输出返回给 Codex]
  
  codex> > claude add error handling
  [继续对话...]

NOTES:
  - 所有输出自动记录到 orchestrator.log
  - Codex 和 Claude Code 都在后台运行
  - 架构支持未来添加更多 AI (Gemini etc.)
"""
        print(help_text)
    
    def _start_monitoring(self):
        """启动后台监听线程（监控输出）"""
        def monitor():
            while self.monitoring and self.orchestrator.running:
                # 定期读取 Codex 的输出（用于日志）
                output = self.codex.read_output(timeout=0.1)
                if output and "[BACKGROUND]" in output:
                    self.logger.info(f"Codex background: {output[:100]}")
                
                time.sleep(0.5)
        
        self.monitor_thread = threading.Thread(target=monitor, daemon=True)
        self.monitor_thread.start()
    
    def run(self):
        """运行交互式会话"""
        print("\n" + "="*60)
        print("🤖 AI Orchestrator - MVP Version")
        print("   Codex + Claude Code")
        print("="*60)
        print("Type '/help' for commands")
        print("="*60 + "\n")
        
        self._start_monitoring()
        
        try:
            while True:
                try:
                    # 显示 Codex 提示符
                    user_input = input("codex> ").strip()
                    
                    if not user_input:
                        continue
                    
                    # 处理特殊命令
                    if user_input.startswith('/'):
                        self._handle_command(user_input)
                    
                    # 向 Claude Code 发送命令（使用 > 前缀）
                    elif user_input.startswith('>'):
                        self._send_to_claude(user_input[1:].strip())
                    
                    # 正常输入发送给 Codex
                    else:
                        self._send_to_codex(user_input)
                
                except KeyboardInterrupt:
                    print("\n\nUse '/exit' to quit")
                except EOFError:
                    break
        
        finally:
            self.monitoring = False
            print("\n✅ Session ended")
    
    def _handle_command(self, cmd: str):
        """处理特殊命令"""
        cmd = cmd.lower().strip()
        
        if cmd == '/help':
            self.show_help()
        
        elif cmd == '/status':
            self.orchestrator.show_status()
        
        elif cmd == '/claude_output':
            self._show_claude_output()
        
        elif cmd == '/clear':
            os.system('clear' if os.name == 'posix' else 'cls')
        
        elif cmd == '/exit':
            print("Exiting...")
            sys.exit(0)
        
        else:
            print(f"Unknown command: {cmd}")
    
    def _send_to_codex(self, command: str):
        """向 Codex 发送命令并显示响应"""
        print(f"→ Sending to Codex: {command}")
        
        if not self.codex.send_command(command):
            print("❌ Failed to send command to Codex")
            return
        
        # 等待 Codex 处理
        time.sleep(0.3)
        
        # 读取 Codex 的输出
        output = ""
        for _ in range(10):  # 最多等待 1 秒
            chunk = self.codex.read_output(timeout=0.1)
            if chunk:
                output += chunk
            time.sleep(0.1)
        
        if output.strip():
            # 过滤回显和提示符
            lines = output.strip().split('\n')
            for line in lines:
                line = line.strip()
                if line and not line.startswith('codex>'):
                    print(line)
    
    def _send_to_claude(self, command: str):
        """从 Codex 向 Claude Code 发送命令"""
        print(f"\n🔵 Claude Code ← Sending: {command}")
        
        if not self.claude.send_command(command):
            print("❌ Failed to send command to Claude Code")
            return
        
        # 等待 Claude Code 处理
        time.sleep(0.5)
        
        # 读取 Claude Code 的输出
        output = ""
        for _ in range(20):  # 最多等待 2 秒
            chunk = self.claude.read_output(timeout=0.1)
            if chunk:
                output += chunk
            time.sleep(0.1)
        
        if output.strip():
            print("\n🔵 Claude Code Output:")
            print("-" * 50)
            # 只显示关键行
            lines = output.strip().split('\n')
            for line in lines[-20:]:  # 显示最后 20 行
                if line.strip():
                    print(line)
            print("-" * 50)
        else:
            print("(No output from Claude Code)")
        
        print("\n继续 Codex 会话...\n")
    
    def _show_claude_output(self):
        """显示 Claude Code 的最新输出"""
        output = self.claude.read_output(timeout=0.5)
        
        if output.strip():
            print("\n--- Claude Code Output ---")
            print(output)
            print("--- End Output ---\n")
        else:
            print("(No recent output from Claude Code)")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="AI Orchestrator - Codex driving Claude Code",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 orchestrator_enhanced.py
  
Notes:
  - Make sure codex and claude CLIs are installed
  - All interactions are logged to orchestrator.log
  - Architecture is extensible for future AI additions
        """
    )
    
    args = parser.parse_args()
    
    # 创建主控器
    orchestrator = Orchestrator()
    
    # 注册 Agent（为未来添加更多 AI 预留接口）
    orchestrator.register_agent("codex", "codex")
    orchestrator.register_agent("claude-code", "claude")
    
    logger.info("Starting AI Orchestrator (MVP)")
    
    # 启动所有 Agent
    if not orchestrator.start_all():
        logger.error("Failed to start agents")
        sys.exit(1)
    
    # 运行交互式会话
    try:
        session = InteractiveSession(orchestrator)
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