#!/usr/bin/env python3
"""
conversation_history.py - 对话历史记录和会话管理模块

功能：
1. 记录所有对话历史（用户输入和 Agent 输出）
2. 支持多轮对话上下文保持
3. 会话保存和加载
4. 对话搜索和导出
"""

import os
import json
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from collections import deque

logger = logging.getLogger('conversation')


@dataclass
class Message:
    """对话消息"""
    timestamp: float  # Unix 时间戳
    role: str  # 'user', 'agent', 'system'
    agent_name: Optional[str]  # Agent 名称（如果是 agent 消息）
    content: str  # 消息内容
    metadata: Dict[str, Any]  # 额外元数据

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'Message':
        """从字典创建"""
        return Message(**data)

    def format_timestamp(self, format_str: str = '%Y-%m-%d %H:%M:%S') -> str:
        """格式化时间戳"""
        return datetime.fromtimestamp(self.timestamp).strftime(format_str)


class ConversationHistory:
    """对话历史管理器"""

    def __init__(self, max_entries: int = 1000, enable_persistence: bool = True):
        """
        初始化对话历史管理器

        Args:
            max_entries: 内存中保留的最大消息数
            enable_persistence: 是否启用持久化存储
        """
        self.max_entries = max_entries
        self.enable_persistence = enable_persistence

        # 使用 deque 作为固定大小的环形缓冲区
        self.messages: deque = deque(maxlen=max_entries)

        # 会话信息
        self.session_id: str = self._generate_session_id()
        self.session_start_time: float = time.time()
        self.session_metadata: Dict[str, Any] = {}

        # 统计信息
        self.stats = {
            'total_messages': 0,
            'user_messages': 0,
            'agent_messages': 0,
            'system_messages': 0
        }

    def _generate_session_id(self) -> str:
        """生成会话 ID"""
        return f"session_{int(time.time())}_{os.getpid()}"

    def add_message(
        self,
        role: str,
        content: str,
        agent_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Message:
        """
        添加消息到历史记录

        Args:
            role: 消息角色 ('user', 'agent', 'system')
            content: 消息内容
            agent_name: Agent 名称（如果是 agent 消息）
            metadata: 额外元数据

        Returns:
            创建的 Message 对象
        """
        message = Message(
            timestamp=time.time(),
            role=role,
            agent_name=agent_name,
            content=content,
            metadata=metadata or {}
        )

        self.messages.append(message)

        # 更新统计
        self.stats['total_messages'] += 1
        if role == 'user':
            self.stats['user_messages'] += 1
        elif role == 'agent':
            self.stats['agent_messages'] += 1
        elif role == 'system':
            self.stats['system_messages'] += 1

        logger.debug(f"添加消息: {role} - {content[:50]}...")

        return message

    def add_user_message(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> Message:
        """添加用户消息"""
        return self.add_message('user', content, metadata=metadata)

    def add_agent_message(
        self,
        agent_name: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Message:
        """添加 Agent 消息"""
        return self.add_message('agent', content, agent_name=agent_name, metadata=metadata)

    def add_system_message(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> Message:
        """添加系统消息"""
        return self.add_message('system', content, metadata=metadata)

    def get_messages(
        self,
        limit: Optional[int] = None,
        role: Optional[str] = None,
        agent_name: Optional[str] = None
    ) -> List[Message]:
        """
        获取消息列表

        Args:
            limit: 返回的最大消息数（从最新开始）
            role: 过滤角色
            agent_name: 过滤 Agent 名称

        Returns:
            消息列表
        """
        messages = list(self.messages)

        # 过滤
        if role:
            messages = [m for m in messages if m.role == role]
        if agent_name:
            messages = [m for m in messages if m.agent_name == agent_name]

        # 限制数量（取最新的）
        if limit and limit > 0:
            messages = messages[-limit:]

        return messages

    def get_recent_messages(self, count: int = 10) -> List[Message]:
        """获取最近的 N 条消息"""
        return self.get_messages(limit=count)

    def get_context(self, max_messages: int = 20) -> List[Dict[str, Any]]:
        """
        获取上下文（用于 Agent 间共享）

        Args:
            max_messages: 最大消息数

        Returns:
            消息字典列表
        """
        messages = self.get_recent_messages(max_messages)
        return [m.to_dict() for m in messages]

    def search(self, keyword: str, limit: int = 50) -> List[Message]:
        """
        搜索包含关键词的消息

        Args:
            keyword: 搜索关键词
            limit: 最大返回数量

        Returns:
            匹配的消息列表
        """
        keyword_lower = keyword.lower()
        results = [
            m for m in self.messages
            if keyword_lower in m.content.lower()
        ]

        # 返回最新的匹配结果
        return results[-limit:] if limit > 0 else results

    def clear(self):
        """清空历史记录"""
        self.messages.clear()
        self.stats = {
            'total_messages': 0,
            'user_messages': 0,
            'agent_messages': 0,
            'system_messages': 0
        }
        logger.info("历史记录已清空")

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        duration = time.time() - self.session_start_time
        return {
            **self.stats,
            'session_id': self.session_id,
            'session_duration': duration,
            'messages_in_memory': len(self.messages)
        }

    def save_to_file(self, file_path: str) -> bool:
        """
        保存历史记录到文件

        Args:
            file_path: 保存路径

        Returns:
            是否成功保存
        """
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(file_path) or '.', exist_ok=True)

            data = {
                'session_id': self.session_id,
                'session_start_time': self.session_start_time,
                'session_metadata': self.session_metadata,
                'stats': self.stats,
                'messages': [m.to_dict() for m in self.messages]
            }

            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            logger.info(f"历史记录已保存到: {file_path}")
            return True

        except Exception as e:
            logger.error(f"保存历史记录失败: {e}")
            return False

    def load_from_file(self, file_path: str) -> bool:
        """
        从文件加载历史记录

        Args:
            file_path: 文件路径

        Returns:
            是否成功加载
        """
        try:
            if not os.path.exists(file_path):
                logger.error(f"文件不存在: {file_path}")
                return False

            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            self.session_id = data.get('session_id', self.session_id)
            self.session_start_time = data.get('session_start_time', self.session_start_time)
            self.session_metadata = data.get('session_metadata', {})
            self.stats = data.get('stats', self.stats)

            # 加载消息
            self.messages.clear()
            for msg_data in data.get('messages', []):
                message = Message.from_dict(msg_data)
                self.messages.append(message)

            logger.info(f"已加载 {len(self.messages)} 条消息从: {file_path}")
            return True

        except Exception as e:
            logger.error(f"加载历史记录失败: {e}")
            return False

    def export_to_markdown(self, file_path: str, title: str = "对话历史") -> bool:
        """
        导出为 Markdown 格式

        Args:
            file_path: 保存路径
            title: 文档标题

        Returns:
            是否成功导出
        """
        try:
            os.makedirs(os.path.dirname(file_path) or '.', exist_ok=True)

            with open(file_path, 'w', encoding='utf-8') as f:
                # 标题和元信息
                f.write(f"# {title}\n\n")
                f.write(f"**会话 ID**: {self.session_id}\n\n")
                f.write(f"**开始时间**: {datetime.fromtimestamp(self.session_start_time)}\n\n")
                f.write(f"**消息数量**: {len(self.messages)}\n\n")
                f.write("---\n\n")

                # 消息内容
                for msg in self.messages:
                    timestamp_str = msg.format_timestamp()

                    if msg.role == 'user':
                        f.write(f"## 👤 用户 ({timestamp_str})\n\n")
                        f.write(f"{msg.content}\n\n")
                    elif msg.role == 'agent':
                        f.write(f"## 🤖 {msg.agent_name or 'Agent'} ({timestamp_str})\n\n")
                        f.write(f"{msg.content}\n\n")
                    elif msg.role == 'system':
                        f.write(f"## ℹ️ 系统 ({timestamp_str})\n\n")
                        f.write(f"{msg.content}\n\n")

                    f.write("---\n\n")

                # 统计信息
                f.write("## 📊 统计信息\n\n")
                stats = self.get_stats()
                for key, value in stats.items():
                    f.write(f"- **{key}**: {value}\n")

            logger.info(f"已导出为 Markdown: {file_path}")
            return True

        except Exception as e:
            logger.error(f"导出 Markdown 失败: {e}")
            return False


class SessionManager:
    """会话管理器"""

    def __init__(self, session_dir: str = "conversations/sessions"):
        """
        初始化会话管理器

        Args:
            session_dir: 会话保存目录
        """
        self.session_dir = session_dir
        os.makedirs(session_dir, exist_ok=True)

    def save_session(self, history: ConversationHistory, name: Optional[str] = None) -> str:
        """
        保存会话

        Args:
            history: 对话历史对象
            name: 会话名称（可选，默认使用 session_id）

        Returns:
            保存的文件路径
        """
        if name:
            filename = f"{name}.json"
        else:
            filename = f"{history.session_id}.json"

        file_path = os.path.join(self.session_dir, filename)
        history.save_to_file(file_path)

        return file_path

    def load_session(self, name: str) -> Optional[ConversationHistory]:
        """
        加载会话

        Args:
            name: 会话名称或 session_id

        Returns:
            ConversationHistory 对象，如果失败返回 None
        """
        # 尝试直接匹配
        file_path = os.path.join(self.session_dir, f"{name}.json")

        if not os.path.exists(file_path):
            # 尝试查找包含该名称的文件
            for filename in os.listdir(self.session_dir):
                if name in filename and filename.endswith('.json'):
                    file_path = os.path.join(self.session_dir, filename)
                    break
            else:
                logger.error(f"找不到会话: {name}")
                return None

        history = ConversationHistory()
        if history.load_from_file(file_path):
            return history
        return None

    def list_sessions(self) -> List[Dict[str, Any]]:
        """
        列出所有会话

        Returns:
            会话信息列表
        """
        sessions = []

        try:
            for filename in os.listdir(self.session_dir):
                if not filename.endswith('.json'):
                    continue

                file_path = os.path.join(self.session_dir, filename)
                stat = os.stat(file_path)

                # 尝试读取会话基本信息
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        sessions.append({
                            'filename': filename,
                            'session_id': data.get('session_id', 'unknown'),
                            'start_time': data.get('session_start_time', 0),
                            'message_count': len(data.get('messages', [])),
                            'file_size': stat.st_size,
                            'modified_time': stat.st_mtime
                        })
                except Exception as e:
                    logger.debug(f"读取会话信息失败 {filename}: {e}")
                    continue

            # 按修改时间排序（最新的在前）
            sessions.sort(key=lambda x: x['modified_time'], reverse=True)

        except Exception as e:
            logger.error(f"列出会话失败: {e}")

        return sessions

    def delete_session(self, name: str) -> bool:
        """
        删除会话

        Args:
            name: 会话名称

        Returns:
            是否成功删除
        """
        file_path = os.path.join(self.session_dir, f"{name}.json")

        if not os.path.exists(file_path):
            logger.error(f"会话不存在: {name}")
            return False

        try:
            os.remove(file_path)
            logger.info(f"已删除会话: {name}")
            return True
        except Exception as e:
            logger.error(f"删除会话失败: {e}")
            return False


if __name__ == '__main__':
    # 测试代码
    logging.basicConfig(level=logging.DEBUG)

    print("测试对话历史管理器")
    print("=" * 50)

    # 创建历史记录
    history = ConversationHistory(max_entries=100)

    # 添加消息
    history.add_user_message("你好")
    history.add_agent_message("claude-1", "你好！我是 Claude，很高兴见到你。")
    history.add_user_message("写一个 Python 函数")
    history.add_agent_message("claude-1", "好的，我来写一个函数：\n```python\ndef hello():\n    print('Hello!')\n```")

    # 获取消息
    print("\n最近的消息:")
    for msg in history.get_recent_messages(5):
        print(f"  [{msg.format_timestamp()}] {msg.role}: {msg.content[:50]}")

    # 统计信息
    print("\n统计信息:")
    stats = history.get_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")

    # 保存到文件
    print("\n保存历史记录...")
    history.save_to_file('test_history.json')

    # 导出为 Markdown
    print("导出为 Markdown...")
    history.export_to_markdown('test_history.md')

    # 会话管理
    print("\n测试会话管理器...")
    session_mgr = SessionManager('test_sessions')
    session_mgr.save_session(history, 'test_session')

    print("\n可用会话:")
    for session in session_mgr.list_sessions():
        print(f"  - {session['filename']}: {session['message_count']} 条消息")

    print("\n" + "=" * 50)
    print("测试完成")
