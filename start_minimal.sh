#!/bin/bash
# start_minimal.sh - 启动最小可行版本

set -e

# 颜色输出
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}═════════════════════════════════════════${NC}"
echo -e "${BLUE}  AI Orchestrator - MVP版本启动${NC}"
echo -e "${BLUE}═════════════════════════════════════════${NC}\n"

# 检查依赖
echo -e "${YELLOW}检查依赖...${NC}"

if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗ Python 3 未安装${NC}"
    exit 1
fi

if ! command -v codex &> /dev/null; then
    echo -e "${RED}✗ Codex CLI 未安装${NC}"
    echo "  安装: npm install -g @openai/codex"
    exit 1
fi

if ! command -v claude &> /dev/null; then
    echo -e "${RED}✗ Claude Code CLI 未安装${NC}"
    echo "  安装: npm install -g @anthropic-ai/claude-code"
    exit 1
fi

echo -e "${GREEN}✓ 所有依赖已安装${NC}\n"

# 启动程序
echo -e "${YELLOW}启动 Orchestrator...${NC}\n"

# 选择版本
if [ "$1" == "simple" ]; then
    echo -e "${GREEN}使用基础版本 (minimal_orchestrator.py)${NC}\n"
    python3 minimal_orchestrator.py
else
    echo -e "${GREEN}使用增强版本 (orchestrator_enhanced.py)${NC}"
    echo -e "  支持: > claude [command] 语法\n"
    python3 orchestrator_enhanced.py
fi