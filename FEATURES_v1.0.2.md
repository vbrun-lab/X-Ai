# X-Ai v1.0.2 新功能指南

## 🎉 主要新功能

### 1. 配置文件支持

系统现在支持通过 YAML 配置文件自定义所有参数。

#### 使用方法

```bash
# 使用默认配置文件 (config.yaml)
python3 orchestrator_enhanced.py

# 使用自定义配置文件
python3 orchestrator_enhanced.py --config my_config.yaml
```

#### 配置文件结构

```yaml
# config.yaml
agents:
  - name: "claude-1"
    command: "claude"
    enabled: true
    startup:
      timeout: 20          # 启动超时（秒）
      wait_after_start: 2.0
      initial_read_attempts: 30
    response:
      timeout: 45          # 响应超时（秒）
      read_timeout: 3.0
      max_idle_checks: 3
      idle_wait: 2.0

conversation:
  history:
    enabled: true
    max_entries: 1000      # 内存中保留的最大消息数
    save_to_file: true
    file_path: "conversations/history.json"
```

### 2. 对话历史管理

所有对话自动记录，支持完整的会话管理。

#### 新增命令

```bash
# 查看历史
/history              # 显示最近10条对话
/history 20           # 显示最近20条对话
/history search "关键词"  # 搜索包含关键词的对话

# 会话管理
/save my_session      # 保存当前会话
/load my_session      # 加载历史会话
/sessions             # 列出所有已保存的会话

# 导出和统计
/export report.md     # 导出对话历史为Markdown
/stats                # 显示对话统计信息
```

#### 使用场景

**场景1：保存重要会话**
```bash
claude1> 你好，帮我写一个复杂的算法
[多轮对话...]
claude1> /save algorithm_discussion
✅ 会话已保存: conversations/sessions/algorithm_discussion.json
```

**场景2：恢复历史会话**
```bash
claude1> /load algorithm_discussion
✅ 已加载会话: algorithm_discussion
   消息数: 15
   会话 ID: session_1761398932_2266
```

**场景3：搜索历史对话**
```bash
claude1> /history search "python function"
搜索结果 ('python function'):
==================================================
👤 [20:15:30] 写一个 python function 来处理数据
🤖 [20:15:35] [claude-1] 好的，我来写一个函数...
==================================================
```

**场景4：导出完整对话**
```bash
claude1> /export today_discussion.md
✅ 对话历史已导出: today_discussion.md
```

### 3. 多轮对话上下文

系统现在自动维护完整的对话上下文，支持：

- ✅ 自动记录所有用户输入
- ✅ 自动记录所有 Agent 响应
- ✅ 保留时间戳和 Agent 信息
- ✅ 支持上下文搜索和回溯

#### 示例工作流

```bash
# 第一轮
claude1> 创建一个用户管理API
[Claude-1 生成代码...]

# 第二轮（基于上一轮的上下文）
claude1> > claude 检查这个API的安全性
[Claude-2 分析并给出建议...]

# 第三轮（继续基于完整上下文）
claude1> 根据建议改进代码
[Claude-1 实现改进...]

# 随时查看历史
claude1> /history
# 可以看到完整的三轮对话
```

### 4. 会话统计

实时统计对话数据：

```bash
claude1> /stats

📊 对话统计:
==================================================
  会话 ID: session_1761398932_2266
  会话时长: 15.3 分钟
  总消息数: 24
  - 用户消息: 12
  - Agent 消息: 12
  - 系统消息: 0
  内存中消息: 24
==================================================
```

## 🚀 快速开始

### 安装和配置

```bash
# 1. 安装依赖
pip3 install -r requirements.txt

# 2. 检查配置文件（可选，系统会使用默认配置）
cat config.yaml

# 3. 创建对话历史目录（自动创建）
mkdir -p conversations/sessions

# 4. 启动系统
bash start_minimal.sh --debug
# 或
python3 orchestrator_enhanced.py
```

### 第一次使用

```bash
# 启动后
claude1> 你好
[Claude-1 响应...]

# 查看帮助
claude1> /help

# 开始对话
claude1> 写一个Python函数来计算斐波那契数列
[Claude-1 生成代码...]

# 让Claude-2参与
claude1> > claude 优化这个函数的性能
[Claude-2 分析并优化...]

# 保存这个有价值的讨论
claude1> /save fibonacci_optimization

# 查看统计
claude1> /stats
```

## 📚 高级使用

### 自定义配置

创建自己的配置文件：

```bash
# 复制默认配置
cp config.yaml my_config.yaml

# 编辑配置
vim my_config.yaml

# 使用自定义配置启动
python3 orchestrator_enhanced.py --config my_config.yaml
```

### 禁用对话历史

如果不需要对话历史功能：

```bash
python3 orchestrator_enhanced.py --no-history
```

### 多Agent配置

在 `config.yaml` 中添加更多 Agent：

```yaml
agents:
  - name: "claude-1"
    command: "claude"
    enabled: true

  - name: "claude-2"
    command: "claude"
    enabled: true

  - name: "gemini-1"
    command: "gemini"
    enabled: false  # 暂时禁用
```

## 🔍 故障排查

### 问题：对话历史未启用

**原因**: 缺少 PyYAML 依赖或配置文件错误

**解决方案**:
```bash
pip3 install pyyaml
python3 orchestrator_enhanced.py
```

### 问题：无法保存会话

**原因**: 会话目录不存在

**解决方案**:
```bash
mkdir -p conversations/sessions
```

### 问题：配置文件加载失败

**原因**: YAML 语法错误

**解决方案**:
```bash
# 验证配置文件
python3 config_loader.py

# 使用默认配置
python3 orchestrator_enhanced.py  # 会自动回退到默认配置
```

## 📖 更多信息

- 完整文档: [README.md](README.md)
- MVP 指南: [MVP_GUIDE.md](MVP_GUIDE.md)
- 项目主页: https://github.com/vbrun-lab/X-Ai

## 🎯 下一步

现在你可以：

1. ✅ 开始使用配置文件自定义系统行为
2. ✅ 利用对话历史管理复杂的多轮对话
3. ✅ 保存重要的会话以便日后参考
4. ✅ 搜索历史对话快速找到信息
5. ✅ 导出对话为文档分享或存档

祝你使用愉快！🚀
