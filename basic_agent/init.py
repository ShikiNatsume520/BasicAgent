# -*- coding: utf-8 -*-
"""
BasicAgent 初始化脚本

职责：
- 自动补全缺失的配置文件（供 config.py 内部调用）
- 通过 `python -m basic_agent.init` 手动初始化配置

所有文件生成在当前工作目录下：
    config/
        BA_Agent.json           # 模型别名配置
        compression.json        # 压缩策略配置
        prompts/
            compact.txt         # 压缩提示词模板
        provider/
            deepseek-v4-flash.json
            deepseek-v4-pro.json
            gpt-4.json
            gpt-4o-mini.json
            gpt-4o.json
            ollama-llama3.json
    .env                        # API Keys 配置
"""

from __future__ import annotations

import json
import os
from pathlib import Path


# ============================================================
# 默认配置模板
# ============================================================

DEFAULT_BA_AGENT = {
    "reasoning": "deepseek-v4-pro",
    "flash": "deepseek-v4-flash"
}

DEFAULT_COMPRESSION = {
    "snip": {
        "window_tokens": 100000
    },
    "microcompact": {
        "max_tool_result_tokens": 5000
    },
    "memory": {
        "timeout_minutes": 30,
        "autocompact_threshold": 0.8,
        "compact_prompt_path": "config/prompts/compact.txt"
    },
    "tier3": {
        "mode": "auto",
        "threshold": 0.8
    }
}

DEFAULT_COMPACT_PROMPT = """你是一个对话历史压缩助手。请将以下对话压缩成简洁的摘要。

## 压缩要求
1. 保持角色语气和性格特征
2. 保留重要事实和约定
3. 记录情感状态变化
4. 保持时间线清晰
5. 忽略闲聊和重复内容

## 对话历史
{conversation_history}

## 压缩后的摘要"""

PROVIDER_CONFIGS = {
    "deepseek-v4-flash": {
        "litellm_model": "deepseek/deepseek-v4-flash",
        "api_base": None,
        "max_tokens": 1000000,
        "api_key_env": "DEEPSEEK_API_KEY"
    },
    "deepseek-v4-pro": {
        "litellm_model": "deepseek/deepseek-v4-pro",
        "api_base": None,
        "max_tokens": 1000000,
        "api_key_env": "DEEPSEEK_API_KEY"
    },
    "gpt-4": {
        "litellm_model": "openai/gpt-4",
        "api_base": None,
        "max_tokens": 128000,
        "api_key_env": "OPENAI_API_KEY"
    },
    "gpt-4o-mini": {
        "litellm_model": "openai/gpt-4o-mini",
        "api_base": None,
        "max_tokens": 128000,
        "api_key_env": "OPENAI_API_KEY"
    },
    "gpt-4o": {
        "litellm_model": "openai/gpt-4o",
        "api_base": None,
        "max_tokens": 128000,
        "api_key_env": "OPENAI_API_KEY"
    },
    "ollama-llama3": {
        "litellm_model": "ollama/llama3",
        "api_base": "http://localhost:11434",
        "max_tokens": 128000,
        "api_key_env": None
    }
}

ENV_CONTENT = """# BasicAgent 环境变量配置
# 请根据你使用的模型提供商，填写相应的 API Key

# DeepSeek API Key (用于 deepseek-v4-flash, deepseek-v4-pro)
DEEPSEEK_API_KEY=

# OpenAI API Key (用于 gpt-4, gpt-4o-mini, gpt-4o)
OPENAI_API_KEY=

# Anthropic API Key (用于 claude-3-opus, claude-3-sonnet)
ANTHROPIC_API_KEY=

# Google API Key (用于 gemini-pro, gemini-ultra)
GOOGLE_API_KEY=

# Ollama 本地模型不需要 API Key
# 确保 Ollama 服务已启动: ollama serve
"""


# ============================================================
# 内部函数（供 config.py 调用）
# ============================================================


def ensure_config(config_dir: Path | None = None, env_path: Path | None = None) -> None:
    """
    确保配置文件完整，缺失的文件自动创建。

    由 config.py 在加载配置时自动调用，也可以在外部手动调用。

    Args:
        config_dir: 配置目录，默认当前工作目录下的 config/
        env_path: .env 文件路径，默认当前工作目录下的 .env
    """
    if config_dir is None:
        config_dir = Path.cwd() / "config"
    if env_path is None:
        env_path = Path.cwd() / ".env"

    _ensure_dirs(config_dir)
    _ensure_file(config_dir / "BA_Agent.json", json.dumps(DEFAULT_BA_AGENT, indent=2, ensure_ascii=False))
    _ensure_file(config_dir / "compression.json", json.dumps(DEFAULT_COMPRESSION, indent=2, ensure_ascii=False))
    _ensure_file(config_dir / "prompts" / "compact.txt", DEFAULT_COMPACT_PROMPT)
    _ensure_file(env_path, ENV_CONTENT)


def ensure_provider_config(provider_name: str, config_dir: Path) -> Path:
    """
    确保指定 provider 的配置完整，缺失则自动创建。

    由 config.py 在加载 provider 配置时自动调用。

    Args:
        provider_name: provider 名称（如 deepseek-v4-pro）
        config_dir: 配置目录

    Returns:
        创建的 provider 配置文件路径
    """
    _ensure_dirs(config_dir)
    provider_dir = config_dir / "provider"
    provider_dir.mkdir(parents=True, exist_ok=True)

    provider_path = provider_dir / f"{provider_name}.json"
    if not provider_path.exists():
        provider_config = PROVIDER_CONFIGS.get(provider_name)
        if provider_config:
            with open(provider_path, "w", encoding="utf-8") as f:
                json.dump(provider_config, f, indent=2, ensure_ascii=False)

    return provider_path


def _ensure_dirs(config_dir: Path) -> None:
    """确保配置目录结构完整"""
    for d in [config_dir, config_dir / "prompts", config_dir / "provider"]:
        d.mkdir(parents=True, exist_ok=True)


def _ensure_file(file_path: Path, content: str) -> None:
    """确保文件存在，缺失则创建"""
    if not file_path.exists():
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)


# ============================================================
# CLI 入口（手动初始化）
# ============================================================


def init_config(force: bool = False) -> None:
    """
    生成配置文件到当前工作目录。

    Args:
        force: 如果为 True，覆盖已存在的文件
    """
    cwd = Path.cwd()
    config_dir = cwd / "config"
    env_path = cwd / ".env"

    print(f"BasicAgent 初始化")
    print(f"=" * 60)
    print(f"工作目录: {cwd}")
    print()

    _ensure_dirs(config_dir)
    print(f"[OK] 创建目录: config")
    print(f"[OK] 创建目录: config/prompts")
    print(f"[OK] 创建目录: config/provider")

    # 生成配置文件
    files = {
        config_dir / "BA_Agent.json": json.dumps(DEFAULT_BA_AGENT, indent=2, ensure_ascii=False),
        config_dir / "compression.json": json.dumps(DEFAULT_COMPRESSION, indent=2, ensure_ascii=False),
    }

    for file_path, content in files.items():
        if file_path.exists() and not force:
            print(f"[SKIP] 文件已存在: {file_path.relative_to(cwd)}")
        else:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"[OK] 生成配置: {file_path.relative_to(cwd)}")

    # 生成压缩提示词
    compact_path = config_dir / "prompts" / "compact.txt"
    if compact_path.exists() and not force:
        print(f"[SKIP] 文件已存在: {compact_path.relative_to(cwd)}")
    else:
        with open(compact_path, "w", encoding="utf-8") as f:
            f.write(DEFAULT_COMPACT_PROMPT)
        print(f"[OK] 生成提示词: {compact_path.relative_to(cwd)}")

    # 生成 provider 配置
    for provider_name, provider_config in PROVIDER_CONFIGS.items():
        provider_path = config_dir / "provider" / f"{provider_name}.json"
        if provider_path.exists() and not force:
            print(f"[SKIP] 文件已存在: {provider_path.relative_to(cwd)}")
        else:
            with open(provider_path, "w", encoding="utf-8") as f:
                json.dump(provider_config, f, indent=2, ensure_ascii=False)
            print(f"[OK] 生成配置: {provider_path.relative_to(cwd)}")

    # 生成 .env 文件
    if env_path.exists() and not force:
        print(f"[SKIP] 文件已存在: {env_path.relative_to(cwd)}")
    else:
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(ENV_CONTENT)
        print(f"[OK] 生成配置: {env_path.relative_to(cwd)}")

    print()
    print("=" * 60)
    print("初始化完成！")
    print()
    print("下一步：")
    print("1. 编辑 .env 文件，添加你的 API Key")
    print("   例如: DEEPSEEK_API_KEY=sk-xxxxxxxxxxxx")
    print()
    print("2. 如果需要修改模型配置，编辑 config/BA_Agent.json")
    print()
    print("3. 开始使用 BasicAgent：")
    print("   from basic_agent.daemon.session_manager import SessionManager")
    print("=" * 60)


# ============================================================
# 命令行入口
# ============================================================

if __name__ == "__main__":
    import sys

    force = "--force" in sys.argv or "-f" in sys.argv
    ensure_config()
    if force:
        init_config(force=True)