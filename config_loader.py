#!/usr/bin/env python3
"""
config_loader.py - 配置文件加载和管理模块

功能：
1. 加载 YAML 配置文件
2. 提供配置访问接口
3. 配置验证
4. 默认配置回退
"""

import os
import yaml
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger('config')


class ConfigLoader:
    """配置加载器"""

    DEFAULT_CONFIG = {
        'version': '1.0.2',
        'agents': [
            {
                'name': 'claude-1',
                'command': 'claude',
                'enabled': True,
                'startup': {
                    'timeout': 20,
                    'wait_after_start': 2.0,
                    'initial_read_attempts': 30
                },
                'response': {
                    'timeout': 45,
                    'read_timeout': 3.0,
                    'max_idle_checks': 3,
                    'idle_wait': 2.0
                },
                'heartbeat': {
                    'enabled': False,
                    'interval': 10
                }
            },
            {
                'name': 'claude-2',
                'command': 'claude',
                'enabled': True,
                'startup': {
                    'timeout': 20,
                    'wait_after_start': 2.0,
                    'initial_read_attempts': 30
                },
                'response': {
                    'timeout': 45,
                    'read_timeout': 3.0,
                    'max_idle_checks': 3,
                    'idle_wait': 2.0
                },
                'heartbeat': {
                    'enabled': False,
                    'interval': 10
                }
            }
        ],
        'orchestrator': {
            'logging': {
                'level': 'INFO',
                'file': 'orchestrator.log',
                'format': '[%(asctime)s] %(name)s: %(message)s'
            },
            'monitoring': {
                'enabled': True,
                'interval': 10,
                'check_process_status': True
            }
        },
        'conversation': {
            'history': {
                'enabled': True,
                'max_entries': 1000,
                'save_to_file': True,
                'file_path': 'conversations/history.json'
            },
            'session': {
                'auto_save': True,
                'save_interval': 60,
                'session_dir': 'conversations/sessions'
            },
            'context': {
                'max_context_messages': 20,
                'include_timestamps': True,
                'include_agent_info': True
            }
        },
        'output': {
            'filtering': {
                'remove_ansi': True,
                'remove_noise': True,
                'noise_keywords': [
                    "? for shortcuts",
                    "thinking on",
                    "approaching weekly limit"
                ]
            },
            'display': {
                'max_lines': 100,
                'show_timestamps': False,
                'show_agent_name': True,
                'color_output': True
            }
        },
        'interface': {
            'prompt': {
                'claude1': 'claude1> ',
                'claude2': 'claude2> ',
                'default': '> '
            },
            'commands': {
                'prefix': '/'
            }
        }
    }

    def __init__(self, config_path: str = 'config.yaml'):
        """
        初始化配置加载器

        Args:
            config_path: 配置文件路径
        """
        self.config_path = config_path
        self.config: Dict[str, Any] = {}
        self._loaded = False

    def load(self, fallback_to_default: bool = True) -> bool:
        """
        加载配置文件

        Args:
            fallback_to_default: 如果加载失败，是否回退到默认配置

        Returns:
            是否成功加载
        """
        try:
            if not os.path.exists(self.config_path):
                logger.warning(f"配置文件不存在: {self.config_path}")
                if fallback_to_default:
                    logger.info("使用默认配置")
                    self.config = self.DEFAULT_CONFIG.copy()
                    self._loaded = True
                    return True
                return False

            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f)

            if not self.config:
                logger.error("配置文件为空")
                if fallback_to_default:
                    self.config = self.DEFAULT_CONFIG.copy()
                    self._loaded = True
                    return True
                return False

            # 验证配置
            if not self._validate():
                logger.warning("配置验证失败，使用默认值填充")
                self._merge_with_defaults()

            self._loaded = True
            logger.info(f"成功加载配置: {self.config_path}")
            return True

        except yaml.YAMLError as e:
            logger.error(f"YAML 解析错误: {e}")
            if fallback_to_default:
                logger.info("使用默认配置")
                self.config = self.DEFAULT_CONFIG.copy()
                self._loaded = True
                return True
            return False

        except Exception as e:
            logger.error(f"加载配置失败: {e}")
            if fallback_to_default:
                self.config = self.DEFAULT_CONFIG.copy()
                self._loaded = True
                return True
            return False

    def _validate(self) -> bool:
        """验证配置的完整性"""
        required_keys = ['agents', 'orchestrator', 'conversation']

        for key in required_keys:
            if key not in self.config:
                logger.warning(f"缺少必需的配置项: {key}")
                return False

        # 验证 agents 配置
        if not isinstance(self.config['agents'], list):
            logger.error("agents 配置必须是列表")
            return False

        if len(self.config['agents']) == 0:
            logger.warning("没有配置任何 agent")
            return False

        return True

    def _merge_with_defaults(self):
        """合并默认配置（缺失的部分使用默认值）"""
        def merge_dict(base: dict, override: dict) -> dict:
            """递归合并字典"""
            result = base.copy()
            for key, value in override.items():
                if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                    result[key] = merge_dict(result[key], value)
                else:
                    result[key] = value
            return result

        self.config = merge_dict(self.DEFAULT_CONFIG, self.config)

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        获取配置值（支持点号路径）

        Args:
            key_path: 配置路径，如 'agents.0.name' 或 'orchestrator.logging.level'
            default: 默认值

        Returns:
            配置值

        Examples:
            >>> config.get('orchestrator.logging.level')
            'INFO'
            >>> config.get('agents.0.name')
            'claude-1'
        """
        if not self._loaded:
            logger.warning("配置尚未加载，使用默认配置")
            self.load()

        keys = key_path.split('.')
        value = self.config

        try:
            for key in keys:
                if key.isdigit():
                    # 数组索引
                    value = value[int(key)]
                else:
                    value = value[key]
            return value
        except (KeyError, IndexError, TypeError):
            logger.debug(f"配置项不存在: {key_path}，使用默认值: {default}")
            return default

    def get_agent_config(self, agent_name: str) -> Optional[Dict[str, Any]]:
        """
        获取指定 agent 的配置

        Args:
            agent_name: Agent 名称

        Returns:
            Agent 配置字典，如果不存在返回 None
        """
        agents = self.get('agents', [])
        for agent in agents:
            if agent.get('name') == agent_name:
                return agent
        return None

    def get_enabled_agents(self) -> List[Dict[str, Any]]:
        """
        获取所有启用的 agent 配置

        Returns:
            启用的 agent 配置列表
        """
        agents = self.get('agents', [])
        return [agent for agent in agents if agent.get('enabled', True)]

    def get_all_agents(self) -> List[Dict[str, Any]]:
        """
        获取所有 agent 配置（包括禁用的）

        Returns:
            所有 agent 配置列表
        """
        return self.get('agents', [])

    def is_loaded(self) -> bool:
        """检查配置是否已加载"""
        return self._loaded

    def reload(self) -> bool:
        """重新加载配置文件"""
        self._loaded = False
        return self.load()

    def save_default_config(self, path: str = 'config.yaml') -> bool:
        """
        保存默认配置到文件

        Args:
            path: 保存路径

        Returns:
            是否成功保存
        """
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(path) or '.', exist_ok=True)

            with open(path, 'w', encoding='utf-8') as f:
                yaml.dump(
                    self.DEFAULT_CONFIG,
                    f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False
                )

            logger.info(f"默认配置已保存到: {path}")
            return True

        except Exception as e:
            logger.error(f"保存默认配置失败: {e}")
            return False


# 全局配置实例
_global_config: Optional[ConfigLoader] = None


def get_config(config_path: str = 'config.yaml', reload: bool = False) -> ConfigLoader:
    """
    获取全局配置实例（单例模式）

    Args:
        config_path: 配置文件路径
        reload: 是否重新加载

    Returns:
        ConfigLoader 实例
    """
    global _global_config

    if _global_config is None or reload:
        _global_config = ConfigLoader(config_path)
        _global_config.load()

    return _global_config


if __name__ == '__main__':
    # 测试代码
    logging.basicConfig(level=logging.DEBUG)

    print("测试配置加载器")
    print("=" * 50)

    # 测试加载
    config = ConfigLoader('config.yaml')
    if config.load():
        print("✅ 配置加载成功")
    else:
        print("❌ 配置加载失败")

    # 测试获取配置
    print("\n配置测试:")
    print(f"  版本: {config.get('version')}")
    print(f"  日志级别: {config.get('orchestrator.logging.level')}")
    print(f"  第一个 agent: {config.get('agents.0.name')}")

    # 测试获取启用的 agents
    enabled_agents = config.get_enabled_agents()
    print(f"\n启用的 Agents ({len(enabled_agents)}):")
    for agent in enabled_agents:
        print(f"  - {agent['name']} ({agent['command']})")

    # 测试获取特定 agent 配置
    claude1_config = config.get_agent_config('claude-1')
    if claude1_config:
        print(f"\nClaude-1 配置:")
        print(f"  启动超时: {claude1_config['startup']['timeout']}s")
        print(f"  响应超时: {claude1_config['response']['timeout']}s")
        print(f"  心跳启用: {claude1_config['heartbeat']['enabled']}")

    print("\n" + "=" * 50)
    print("测试完成")
