# 手动调用测试指南 - Claude-1 → Gemini (Claude-2)

## ✅ 配置已修正

现在系统配置：
- **claude-1**: 使用 `claude` CLI
- **claude-2**: 使用 `gemini` CLI

## 🧪 正确的测试步骤

### 测试1：基础通信测试

```bash
# 1. 启动系统（安装 PyYAML 以启用配置）
pip3 install pyyaml
bash start_minimal.sh --debug

# 2. 关闭自动编排模式
claude1> /auto off
# 应该看到：❌ 自动编排模式已禁用

# 3. 测试发送给 Gemini (claude-2)
claude1> > 你好，我是 Claude-1，请介绍一下你自己
        ↑↑↑ 注意：必须有 > 符号！

# 期望看到：
# 🔵 Claude-2 ← Sending: 你好，我是 Claude-1，请介绍一下你自己
# [Gemini 的响应...]
```

### ❌ 常见错误

**错误1：忘记 `>` 符号**
```bash
# ❌ 这会发给 Claude-1，不是 Gemini
claude1> 你好

# ✅ 正确写法（注意 > 后面有空格）
claude1> > 你好
```

**错误2：`>` 符号位置错误**
```bash
# ❌ 错误
claude1 > > 你好

# ✅ 正确
claude1> > 你好
```

### 测试2：验证 Gemini 接收和响应

```bash
# 发送一个简单任务给 Gemini
claude1> > 写一个 Python 函数计算 1+1

# 观察要点：
# 1. 是否显示 "🔵 Claude-2 ← Sending: ..."
# 2. Gemini 是否开始响应
# 3. 是否收到完整的输出
# 4. 是否显示 "🔵 Claude-2 Output:"
```

### 测试3：多轮对话测试

```bash
# 第一轮
claude1> > 写一个 Python 列表

# 等待 Gemini 响应...

# 第二轮（测试上下文）
claude1> > 给刚才的列表添加 5 个元素

# 观察 Gemini 是否记得上一轮的内容
```

### 测试4：切换回 Claude-1

```bash
# 不使用 > 前缀，命令发给 Claude-1
claude1> 请总结一下刚才 Gemini 说了什么

# 这会发给 Claude-1
# 测试 Claude-1 是否记得之前的对话
```

## 📊 预期输出示例

### 成功的输出应该是：

```
claude1> /auto off
❌ 自动编排模式已禁用
   需要手动使用 > claude-2 调用

claude1> > 你好

🔵 Claude-2 ← Sending: 你好

[2025-10-25 22:35:01] agent.claude-2: → claude-2: 你好
[2025-10-25 22:35:05] session: Received Claude chunk 1: 1234 bytes
...

==================================================
📥 Claude-2 响应:
==================================================
你好！我是 Gemini，...
[Gemini 的完整响应]
==================================================

继续 Claude-1 会话...

claude1>
```

## 🔍 调试检查清单

如果测试失败，检查：

### 1. 配置文件是否正确加载
```bash
# 查看日志开头
grep "配置文件加载成功" orchestrator.log
# 或
grep "yaml" orchestrator.log
```

### 2. Gemini 是否正常启动
```bash
# 查看启动日志
grep "claude-2" orchestrator.log | grep "Started"
# 应该看到类似：✅ Started claude-2 (PID: xxxxx)
```

### 3. Gemini CLI 是否可用
```bash
# 在另一个终端测试
which gemini
gemini --version
```

### 4. 查看详细的发送日志
```bash
# 查看是否发送了命令
tail -f orchestrator.log | grep "claude-2"
```

## 🐛 故障排查

### 问题1：看到 "No module named 'yaml'"

**解决方案：**
```bash
pip3 install pyyaml
# 重启系统
bash start_minimal.sh --debug
```

### 问题2：Gemini 没有响应

**可能原因：**
1. Gemini CLI 未正确安装
2. Gemini 需要登录或配置

**检查方法：**
```bash
# 测试 Gemini 单独运行
gemini
# 如果需要登录，先完成登录
```

### 问题3：输出乱码或不完整

**可能原因：**
1. 等待时间不够
2. 输出过滤器过于激进

**解决方案：**
```bash
# 查看原始日志
tail -100 orchestrator.log
```

## ✅ 成功标志

如果看到以下内容，说明通信成功：

1. ✅ `🔵 Claude-2 ← Sending: ...`
2. ✅ `[agent.claude-2: → claude-2: ...]` 在日志中
3. ✅ `📥 Claude-2 响应:`
4. ✅ Gemini 的实际响应内容
5. ✅ `继续 Claude-1 会话...`

## 📝 记录测试结果

请记录以下信息：

```
测试时间: ___________
配置加载: 成功/失败
Gemini 启动: 成功/失败 (PID: _____)
命令发送: 成功/失败
接收响应: 成功/失败
响应长度: _____ 字节
响应时间: _____ 秒
```

## 🎯 下一步

如果手动调用测试成功：
1. ✅ 说明基础通信正常
2. ✅ 可以进行自动编排测试
3. ✅ 需要改进 Claude-1 的系统提示

如果手动调用测试失败：
1. ❌ 需要调试 Gemini CLI
2. ❌ 检查配置文件
3. ❌ 查看详细日志

---

**请按照这个指南重新测试，并告诉我结果！** 🚀
