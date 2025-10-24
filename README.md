# X-Ai - AI Orchestrator

> 一个强大的AI协同编排系统，让多个AI CLI工具无缝协作

[![Version](https://img.shields.io/badge/version-1.0.1-blue.svg)](https://github.com/vbrun-lab/X-Ai/releases)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8+-yellow.svg)](https://www.python.org/)

## 特性

- **多AI协作** - 支持Codex、Claude Code等多个AI CLI工具协同工作
- **智能编排** - 通过简单的 `>` 符号在不同AI之间转发命令
- **会话保持** - 所有AI进程常驻内存，保持上下文连续性
- **实时通信** - 基于PTY的双向通信，无延迟无丢包
- **易于扩展** - 模块化设计，轻松添加新的AI工具
- **完整日志** - 详细的日志记录，便于调试和监控

## 快速开始

### 前置要求

- Python 3.8+
- Node.js 16+ (用于安装AI CLI工具)
- 已安装的AI CLI工具（如 `codex`、`claude`）

### 安装AI CLI工具

```bash
# 安装Codex CLI
npm install -g @openai/codex

# 安装Claude Code CLI
npm install -g @anthropic-ai/claude-code

# 验证安装
which codex
which claude
```

### 启动系统

```bash
# 方法1: 使用启动脚本（推荐）
bash start_minimal.sh

# 方法2: 直接运行Python脚本
python3 orchestrator_enhanced.py

# 方法3: 简化版本
python3 orchestrator_enhanced.py simple
```

### 基本使用

启动后，你将看到交互式命令行界面：

```
🤖 AI Orchestrator - v1.0.1
   Codex + Claude Code
════════════════════════════════════════════════════════

codex> write a python function to calculate factorial
[Codex 处理并生成代码...]

codex> > claude optimize this code
🔵 Claude Code ← Sending: optimize this code
[Claude Code 分析并优化代码...]

codex> /status
📊 System Status:
   - Codex: Active
   - Claude Code: Active

codex> /help
Available commands:
  /status  - 查看所有AI状态
  /help    - 显示帮助信息
  /exit    - 退出系统
  > <ai> <command> - 向指定AI发送命令

codex> /exit
👋 Shutting down...
```

## 工作原理

### 架构图

```
┌─────────────────────────────────────────────┐
│              User Input                      │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│         Orchestrator (Python)                │
│  ┌──────────────────────────────────────┐   │
│  │     CLIAgent Manager                  │   │
│  │  - Process Management                 │   │
│  │  - PTY Communication                  │   │
│  │  - Command Routing                    │   │
│  └──────────────────────────────────────┘   │
└──────┬──────────────────────┬───────────────┘
       │                      │
       ▼                      ▼
┌─────────────┐      ┌──────────────┐
│   Codex     │      │ Claude Code  │
│   Process   │◄────►│   Process    │
└─────────────┘      └──────────────┘
```

### 核心组件

1. **CLIAgent** - 管理单个AI CLI进程
   - PTY (伪终端) 通信
   - 异步I/O处理
   - 输出缓冲和监控

2. **Orchestrator** - 主编排器
   - Agent注册和管理
   - 进程生命周期控制
   - 命令路由和转发

3. **InteractiveSession** - 交互式会话
   - 用户输入处理
   - 命令解析和执行
   - 输出格式化显示

## 高级功能

### 多轮对话

```bash
codex> create a REST API for user management
[Codex 生成API代码...]

codex> > claude review the security of this API
[Claude 分析安全性...]

codex> > claude suggest improvements
[Claude 提供改进建议...]

codex> implement the suggestions
[Codex 实现改进...]
```

### 添加新的AI工具

编辑 `orchestrator_enhanced.py`，在 `main()` 函数中添加：

```python
def main():
    orchestrator = Orchestrator()

    # 现有的Agent
    orchestrator.register_agent("codex", "codex")
    orchestrator.register_agent("claude-code", "claude")

    # 添加新的AI工具
    orchestrator.register_agent("gemini", "gemini")

    orchestrator.start_all()
    # ...
```

然后在交互式会话中使用：

```bash
codex> > gemini analyze this algorithm
```

## 文档

- [MVP 快速指南](MVP_GUIDE.md) - 5分钟快速上手
- [MVP vs 完整版对比](README_MVP_vs_FULL.md) - 版本选择指南
- [故障排查](MVP_GUIDE.md#故障排查) - 常见问题解决

## 版本历史

### v1.0.1 (2025-10-25)
- 改进Claude输出处理逻辑
- 扩展所有超时参数以更好处理AI响应
- 优化监控线程性能
- 移除冗余的调试日志
- 添加.gitignore规则

### v1.0.0 (2025-10-24)
- 初始MVP版本发布
- 支持Codex和Claude Code协作
- PTY通信实现
- 基础命令路由功能

## 系统要求

- **操作系统**: Linux, macOS, WSL2
- **Python**: 3.8 或更高版本
- **内存**: 建议 4GB+
- **存储**: 100MB+

## 开发路线图

- [ ] 添加Web UI仪表板
- [ ] 支持更多AI工具（Gemini, GPT-4等）
- [ ] 实现MCP (Model Context Protocol)集成
- [ ] 添加配置文件支持
- [ ] 实现命令历史和会话恢复
- [ ] 性能优化和并发处理

## 贡献

欢迎贡献代码、报告问题或提出建议！

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启Pull Request

## 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

## 致谢

- [Anthropic Claude](https://www.anthropic.com/) - 提供强大的AI能力
- [OpenAI Codex](https://openai.com/blog/openai-codex) - 代码生成和理解
- 所有贡献者和使用者

## 联系方式

- 项目主页: [https://github.com/vbrun-lab/X-Ai](https://github.com/vbrun-lab/X-Ai)
- 问题反馈: [GitHub Issues](https://github.com/vbrun-lab/X-Ai/issues)

---

**Made with ❤️ by vbrun-lab**
