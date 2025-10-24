#!/usr/bin/env python3
"""
orchestrator.py - AI 驱动 AI 最小可行版本 (MVP)

架构简单：
1. 启动两个 CLI 进程（Codex + Claude Code）
2. 都运行在伪终端（PTY）中以维持会话
3. 用户与 Codex 交互
4. Codex 可以向 Claude Code 发送命令
5. Claude Code 的输出被 Codex 看到（通过重定向）

为未来扩展 Gemini/其他 AI 留好架构余地
"""

import os
import sys
import signal
import pty
import time
import select
import fcntl
import struct
from pathlib import Path
from typing import Dict, Optional
import logging

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
    
    def __init__(self, name: str, cli_command: str, log_file: Optional[str] = None):
        """
        Args:
            name: Agent 名称（用于标识）
            cli_command: 启动命令（如 'codex' 或 'claude'）
            log_file: 可选的日志文件
        """
        self.name = name
        self.cli_command = cli_command
        self.log_file = log_file
        
        self.pid: Optional[int] = None
        self.fd: Optional[int] = None  # PTY master fd
        self.slave_fd: Optional[int] = None  # PTY slave fd
        self.process_running = False
        
        self.logger = logging.getLogger(f'agent.{name}')
    
    def start(self) -> bool:
        """启动 CLI 进程在 PTY 中"""
        try:
            # 创建伪终端对
            self.pid, self.fd = pty.openpty()
            
            if self.pid == 0:
                # 子进程：连接到 PTY slave 并运行 CLI
                os.setsid()  # 新会话
                
                # 打开 PTY slave
                self.slave_fd = os.open('/dev/tty', os.O_RDWR)
                if self.slave_fd < 0:
                    # 备用方案
                    self.slave_fd = os.open(os.ttyname(0), os.O_RDWR)
                
                # 重定向 stdin/stdout/stderr 到 PTY
                os.dup2(self.slave_fd, 0)  # stdin
                os.dup2(self.slave_fd, 1)  # stdout
                os.dup2(self.slave_fd, 2)  # stderr
                
                # 设置 PTY 为控制终端
                os.tcsetpgrp(self.slave_fd, os.getpid())
                
                # 执行 CLI 命令
                try:
                    os.execvp(self.cli_command, [self.cli_command])
                except FileNotFoundError:
                    print(f"Error: Command '{self.cli_command}' not found", file=sys.stderr)
                    sys.exit(1)
            
            else:
                # 父进程：管理 PTY
                self.process_running = True
                
                # 设置非阻塞模式
                fcntl.fcntl(self.fd, fcntl.F_SETFL, os.O_NONBLOCK)
                
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
            
            self.logger.debug(f"Sent to {self.name}: {command[:50]}")
            return True
        
        except Exception as e:
            self.logger.error(f"Error sending command to {self.name}: {e}")
            return False
    
    def read_output(self, timeout: float = 0.1) -> str:
        """从 Agent 读取输出"""
        if not self.process_running or self.fd is None:
            return ""
        
        output = ""
        start_time = time.time()
        
        try:
            while time.time() - start_time < timeout:
                # 使用 select 等待数据
                ready, _, _ = select.select([self.fd], [], [], 0.01)
                
                if ready:
                    try:
                        chunk = os.read(self.fd, 4096)
                        if chunk:
                            output += chunk.decode('utf-8', errors='replace')
                        else:
                            # EOF
                            self.process_running = False
                            break
                    except OSError:
                        break
        
        except Exception as e:
            self.logger.debug(f"Error reading from {self.name}: {e}")
        
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
            if self.fd is not None:
                try:
                    os.close(self.fd)
                except:
                    pass
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
        """注册新 Agent"""
        if name in self.agents:
            self.logger.warning(f"Agent {name} already registered")
            return False
        
        agent = CLIAgent(name=name, cli_command=cli_command)
        self.agents[name] = agent
        
        self.logger.info(f"Registered agent: {name} (command: {cli_command})")
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
            time.sleep(1)
        
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
    """与 Codex 的交互式会话"""
    
    def __init__(self, orchestrator: Orchestrator):
        self.orchestrator = orchestrator
        self.codex = orchestrator.get_agent("codex")
        self.claude = orchestrator.get_agent("claude-code")
        self.logger = logging.getLogger('session')
        
        if not self.codex:
            raise RuntimeError("Codex agent not found")
        if not self.claude:
            raise RuntimeError("Claude Code agent not found")
    
    def show_help(self):
        """显示帮助信息"""
        help_text = """
╔════════════════════════════════════════════════════════════╗
║           AI Orchestrator - Interactive Session            ║
║              (Codex driving Claude Code)                   ║
╚════════════════════════════════════════════════════════════╝

Commands:
  /help             Show this help message
  /status           Show agent status
  /claude_output    Show Claude Code's latest output
  /clear            Clear screen
  /exit             Exit the session

Normal input is sent to Codex.
Codex can command Claude Code using standard CLI commands.

Examples:
  > write a Python function to calculate factorial
  > ask claude to optimize the code
  > run tests
  > /status
"""
        print(help_text)
    
    def run(self):
        """运行交互式会话"""
        print("\n" + "="*60)
        print("🤖 AI Orchestrator - Codex + Claude Code")
        print("="*60)
        print("Type '/help' for commands")
        print("="*60 + "\n")
        
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
                    else:
                        # 发送给 Codex
                        self._send_to_codex(user_input)
                
                except KeyboardInterrupt:
                    print("\n\nUse '/exit' to quit")
                except EOFError:
                    break
        
        finally:
            print("\n✅ Session ended")
    
    def _handle_command(self, cmd: str):
        """处理特殊命令"""
        cmd = cmd.lower()
        
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
        """向 Codex 发送命令"""
        # 发送命令给 Codex
        if not self.codex.send_command(command):
            print("❌ Failed to send command to Codex")
            return
        
        # 等待 Codex 响应
        time.sleep(0.5)
        
        # 读取 Codex 的输出
        output = self.codex.read_output(timeout=3.0)
        
        if output:
            # 显示 Codex 的输出（除了 echo 的输入）
            lines = output.strip().split('\n')
            for line in lines:
                if line.strip() and not line.strip().startswith(command):
                    print(line)
    
    def _show_claude_output(self):
        """显示 Claude Code 的最新输出"""
        output = self.claude.read_output(timeout=1.0)
        
        if output.strip():
            print("\n--- Claude Code Output ---")
            print(output)
            print("--- End Output ---\n")
        else:
            print("(No recent output from Claude Code)")


def main():
    """主函数"""
    # 创建主控器
    orchestrator = Orchestrator()
    
    # 注册 Agent
    orchestrator.register_agent("codex", "codex")
    orchestrator.register_agent("claude-code", "claude")
    
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
    
    finally:
        orchestrator.shutdown()


if __name__ == "__main__":
    main()