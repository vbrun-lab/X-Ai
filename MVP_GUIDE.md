# 🤖 AI Orchestrator - MVP 版本

极简实现：只有 Codex + Claude Code，你直接与 Codex 交互

---

## 📋 5分钟快速开始

### 1️⃣ 确保必要工具已安装

```bash
# 检查 Codex
which codex

# 检查 Claude Code
which claude

# 如果未安装，执行：
npm install -g @openai/codex
npm install -g @anthropic-ai/claude-code
```

### 2️⃣ 启动系统

```bash
# 方法 1：使用启动脚本
bash start_minimal.sh

# 方法 2：直接运行（增强版，推荐）
python3 orchestrator_enhanced.py

# 方法 3：基础版本
python3 orchestrator_enhanced.py simple
```

### 3️⃣ 开始交互

```
🤖 AI Orchestrator - MVP Version
   Codex + Claude Code
════════════════════════════════════════════════════════

codex> write a python function to calculate factorial
[Codex 思考并执行...]

codex> /status
[查看当前状态]

codex> > claude optimize this code
[向 Claude Code 发送命令]

codex> /help
[查看帮助]

codex> /exit
[退出]
```

---

## 🏗️ 架构（超简单）

```
你
 ↓
终端输入
 ↓
Orchestrator
 ├─ Codex（会话活跃的进程）
 └─ Claude Code（会话活跃的进程）

工作流：
1. 你向 Codex 发送任务
   → orchestrator 写入 Codex 的 stdin

2. Codex 处理并可能需要 Claude Code
   → 如果你输入 "> claude ...", orchestrator 转发给 Claude
   → Claude 的输出返回给 Codex

3. 结果展示给你
```

---

## 💬 使用示例

### 示例 1：简单任务

```
codex> write a function to find prime numbers

[Codex 执行任务...]
[输出结果]
```

### 示例 2：多步协作

```
codex> write a python REST API

[Codex 处理...]

codex> > claude optimize the code for performance

[Codex 转发给 Claude]
[Claude 优化代码]
[结果返回]

codex> > claude add error handling

[继续对话...]
```

### 示例 3：检查状态

```
codex> /status

========================================
Agent Status:
========================================
  codex           🟢 Running
  claude-code     🟢 Running
========================================
```

---

## 🎮 命令参考

### 直接输入（发送给 Codex）

```
codex> [任何命令]
```
→ 直接发送给 Codex 处理

### 特殊命令

| 命令 | 功能 |
|------|------|
| `/help` | 显示帮助信息 |
| `/status` | 显示所有 Agent 状态 |
| `/claude_output` | 查看 Claude Code 最新输出 |
| `/clear` | 清屏 |
| `/exit` | 退出程序 |

### 向 Claude Code 发送命令

```
codex> > claude [命令]
```
例：
```
codex> > claude write a test suite
codex> > claude optimize the function
codex> > claude add documentation
```

---

## 📊 实际工作流示例

### 完整案例：构建一个计算器

```
你的命令                          系统动作
─────────────────────────────────────────────────

codex> write a calculator         
  ↓                               
Codex 会话:                       
  收到: "write a calculator"      
  Codex 思考: 需要创建代码        
  执行任务                        
  返回结果                        
  ↑                               
显示给你
  

codex> > claude make it a class    
  ↓                               
Codex 识别: "> claude" 前缀       
Codex 转发给 Claude:              
  命令: "make it a class"         
Claude 会话:                      
  收到命令                        
  修改代码                        
  返回结果                        
  ↑                               
转发回 Codex                       
显示给你
  

codex> > claude add unit tests    
  ↓                               
[重复上面的流程]
```

---

## 🔧 技术细节（可选阅读）

### 为什么使用 subprocess 而不是 tmux？

```
✅ 优点：
   - 不依赖 tmux（跨平台兼容）
   - 直接的进程管理（更可靠）
   - 简单的 I/O 重定向
   - 易于为未来扩展

❌ tmux 的问题：
   - 依赖特定工具
   - 屏幕捕获不可靠
   - 维护复杂
```

### 会话持久化原理

```
CLI 进程在后台持续运行：
┌─────────────────────────────┐
│ Codex 进程                  │
├─────────────────────────────┤
│ stdin  → 接收你的命令        │
│ stdout → 输出结果            │
│ stderr → 输出错误            │
│                             │
│ 状态保留在内存中：           │
│ - 变量 ✓                    │
│ - 上下文 ✓                  │
│ - 历史记录 ✓                │
└─────────────────────────────┘

每条命令：
1. 写入 stdin
2. 读取 stdout
3. 继续（不重启进程）
```

### 消息流向

```
你的输入
   ↓
Python 读取 (input())
   ↓
判断：是否以 > 开头？
   ├─ 是 → 转发给 Claude Code
   └─ 否 → 发送给 Codex
   ↓
写入目标进程的 stdin (os.write)
   ↓
目标进程处理
   ↓
读取 stdout (os.read)
   ↓
显示给你
```

---

## 🛠️ 故障排查

### Q: 启动时说 "Command 'codex' not found"

```bash
# 检查 npm 全局包
npm list -g @openai/codex

# 如果未安装
npm install -g @openai/codex

# 检查 PATH
echo $PATH | grep npm
```

### Q: Claude Code 没有响应

```bash
# 重新启动脚本
pkill -f orchestrator_enhanced.py
python3 orchestrator_enhanced.py

# 或查看日志
tail -f orchestrator.log
```

### Q: 看不到输出

```
常见原因：
1. 进程还在处理（等等看）
2. CLI 的输出格式特殊
3. 日志级别太高

解决方案：
- 查看日志文件: tail -f orchestrator.log
- 使用 /status 检查进程状态
- 使用 /claude_output 查看原始输出
```

### Q: 如何退出

```
codex> /exit

或按 Ctrl+C 两次
```

---

## 📝 日志和调试

### 查看完整日志

```bash
tail -f orchestrator.log
```

日志包含：
- ✅ Agent 启动/关闭
- → 发送给 Agent 的命令
- ← 从 Agent 接收的输出
- ❌ 错误信息

### 调试模式（可选修改）

在 `orchestrator_enhanced.py` 中：

```python
# 第一行改为：
logging.basicConfig(
    level=logging.DEBUG,  # 改为 DEBUG
    ...
)
```

然后重启，会看到更详细的日志。

---

## 🚀 为未来扩展做准备

当前架构已为添加新 AI 做了准备：

```python
# 要添加 Gemini，只需：
orchestrator.register_agent("gemini", "gemini")

# 然后在会话中使用：
codex> > gemini review this code
```

架构关键点：
1. ✅ `CLIAgent` 类是通用的（支持任何 CLI）
2. ✅ `Orchestrator` 可管理任意数量的 Agent
3. ✅ `InteractiveSession` 支持动态命令转发

---

## 📊 系统资源占用

```
Codex 进程:    ~30-50 MB
Claude 进程:   ~30-50 MB
Python 脚本:   ~10-20 MB
─────────────────────────
总计:          ~70-120 MB
CPU:           <5% (空闲时)
```

---

## ✅ 验收清单

你的系统应该能做到：

- [ ] 启动脚本成功运行
- [ ] 看到 `🤖 AI Orchestrator` 欢迎信息
- [ ] `codex>` 提示符出现
- [ ] 在 Codex 中输入任务
- [ ] 使用 `> claude [command]` 向 Claude 发送命令
- [ ] 查看 `/status` 显示两个 Agent 都在运行
- [ ] 查看 `orchestrator.log` 有完整的交互记录
- [ ] `/exit` 可以正常退出

---

## 🎓 Next Steps

### 熟悉当前版本（第一天）
1. 启动系统
2. 尝试简单任务
3. 试用 `> claude` 语法
4. 查看日志理解流程

### 探索更多功能（第二天）
1. 试试复杂的多步任务
2. 检查 Claude 的输出
3. 修改代码调整行为

### 准备添加新 AI（第三天）
1. 理解代码结构
2. 计划添加新 Agent
3. 实现 Gemini 集成（或其他）

---

## 📚 文件说明

| 文件 | 大小 | 说明 |
|------|------|------|
| `orchestrator_enhanced.py` | ~6KB | 增强版（推荐） |
| `minimal_orchestrator.py` | ~5KB | 基础版 |
| `start_minimal.sh` | <1KB | 启动脚本 |
| `orchestrator.log` | 动态 | 运行日志 |

---

## 🎉 完成！

你现在已有一个**工作的 AI 驱动 AI 系统**！

**启动命令：**
```bash
python3 orchestrator_enhanced.py
```

**或：**
```bash
bash start_minimal.sh
```

---

## 💡 使用技巧

### 技巧 1：保存会话

```bash
# 将日志导出为文本
cp orchestrator.log session_$(date +%s).txt

# 或查看特定时间的日志
tail -n 100 orchestrator.log
```

### 技巧 2：快速重启

```bash
# 如果 Claude 卡住了
Ctrl+C  # 停止

# 重启脚本
python3 orchestrator_enhanced.py
```

### 技巧 3：合并输出

```bash
# 如果想看 Claude 的完整输出
/claude_output
```

### 技巧 4：查看所有可用命令

```bash
/help
```

---

**祝你使用愉快！🚀**
