# -*- coding: utf-8 -*-
"""
配置加载与管理

职责：
- 优先使用工作目录下的 config/ 配置
- 当配置缺失时自动调用 init.ensure_config() 生成
- 产出不可变的 AppConfig，全局可读
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


# ============================================================
# 配置数据结构（不可变）
# ============================================================


@dataclass(frozen=True)
class ModelConfig:
    """单个模型的完整配置，初始化后不可变"""
    alias: str               # 别名: reasoning / flash / multi
    litellm_model: str       # LiteLLM model string, e.g. "deepseek/deepseek-v4-pro[1m]"
    provider: str            # 供应商标识: deepseek / openai / anthropic / gemini / ollama ...
    api_base: str | None     # 自定义端点，None 表示用默认
    max_tokens: int          # context window 大小
    api_key: str | None      # API Key


@dataclass(frozen=True)
class MemoryConfig:
    """记忆系统配置"""
    timeout_minutes: int = 30  # 低价值旧消息超时时间（分钟）
    autocompact_threshold: float = 0.8  # 触发自动压缩的 token 占比阈值
    compact_prompt_path: str = "config/prompts/compact.txt"  # 压缩指令提示词路径


@dataclass(frozen=True)
class CompressionConfig:
    """压缩策略配置"""
    snip_window_tokens: int = 100000
    microcompact_max_tool_result_tokens: int = 5000
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    tier3_mode: str = "auto"
    tier3_threshold: float = 0.8


@dataclass(frozen=True)
class AppConfig:
    """全局配置，初始化后不可变"""
    models: dict[str, ModelConfig]
    default_model: str = "reasoning"
    compression: CompressionConfig = field(default_factory=CompressionConfig)
    config_dir: str = ""  # 实际使用的配置目录


# ============================================================
# 配置目录查找
# ============================================================

_PROJECT_ROOT = Path(__file__).parent.parent.parent


def _resolve_config_dir() -> Path:
    """
    确定配置目录，优先级：
    1. 当前工作目录下的 config/
    2. 自动在 cwd 下初始化 config/
    """
    cwd_config = Path.cwd() / "config"

    # 如果工作目录下已有 config，直接使用
    if cwd_config.exists() and (cwd_config / "BA_Agent.json").exists():
        return cwd_config

    # 如果工作目录下 config 不存在或不完整，自动创建
    from basic_agent.init import ensure_config
    ensure_config()
    return cwd_config


def _resolve_env_path() -> Path:
    """
    确定 .env 文件路径，优先级：
    1. 当前工作目录下的 .env
    2. 自动创建 .env 模板
    """
    cwd_env = Path.cwd() / ".env"
    if cwd_env.exists():
        return cwd_env

    # 自动创建 .env 模板
    from basic_agent.init import ensure_config
    ensure_config()
    return cwd_env


# ============================================================
# 配置加载
# ============================================================


def load_config() -> AppConfig:
    """
    加载完整配置链：
    1. 自动识别/创建配置目录
    2. 读取 .env（API Keys）
    3. 读取 BA_Agent.json（模型别名映射）
    4. 对每个别名，读取对应的 provider/*.json
    5. 读取 compression.json（可选）
    6. 组装成不可变的 AppConfig
    """
    # 1. 确定配置目录（自动补全缺失文件）
    config_dir = _resolve_config_dir()

    # 2. 加载 .env
    env_path = _resolve_env_path()
    if env_path.exists():
        load_dotenv(env_path)

    # 3. 读取 BA_Agent.json
    ba_path = config_dir / "BA_Agent.json"
    with open(ba_path, "r", encoding="utf-8") as f:
        ba_config = json.load(f)

    # 4. 对每个别名加载 provider 配置
    models: dict[str, ModelConfig] = {}
    for alias, provider_name in ba_config.items():
        if provider_name is None:
            continue

        provider_path = config_dir / "provider" / f"{provider_name}.json"
        if not provider_path.exists():
            # 自动补全缺失的 provider 配置
            from basic_agent.init import ensure_provider_config
            ensure_provider_config(provider_name, config_dir)
            # 重新读取
            with open(provider_path, "r", encoding="utf-8") as f:
                provider_config = json.load(f)
        else:
            with open(provider_path, "r", encoding="utf-8") as f:
                provider_config = json.load(f)

        # 从 .env 读取 API Key
        api_key = None
        api_key_env = provider_config.get("api_key_env")
        if api_key_env:
            api_key = os.getenv(api_key_env)

        # 从 litellm_model 提取 provider 标识
        litellm_model = provider_config["litellm_model"]
        provider = litellm_model.split("/")[0] if "/" in litellm_model else "openai"

        models[alias] = ModelConfig(
            alias=alias,
            litellm_model=litellm_model,
            provider=provider,
            api_base=provider_config.get("api_base"),
            max_tokens=provider_config.get("max_tokens", 128000),
            api_key=api_key,
        )

    # 5. 读取 compression.json（可选）
    compression = CompressionConfig()
    comp_path = config_dir / "compression.json"
    if comp_path.exists():
        with open(comp_path, "r", encoding="utf-8") as f:
            comp = json.load(f)

        memory_config = MemoryConfig()
        mem = comp.get("memory", {})
        if mem:
            memory_config = MemoryConfig(
                timeout_minutes=mem.get("timeout_minutes", 30),
                autocompact_threshold=mem.get("autocompact_threshold", 0.8),
                compact_prompt_path=mem.get("compact_prompt_path", "config/prompts/compact.txt"),
            )

        compression = CompressionConfig(
            snip_window_tokens=comp.get("snip", {}).get("window_tokens", 100000),
            microcompact_max_tool_result_tokens=comp.get("microcompact", {}).get("max_tool_result_tokens", 5000),
            memory=memory_config,
            tier3_mode=comp.get("tier3", {}).get("mode", "auto"),
            tier3_threshold=comp.get("tier3", {}).get("threshold", 0.8),
        )

    return AppConfig(
        models=models,
        compression=compression,
        config_dir=str(config_dir),
    )


# ============================================================
# 全局共享配置（惰性加载，只读）
# ============================================================

_shared_config: AppConfig | None = None


def get_config() -> AppConfig:
    """获取全局共享配置，首次调用时加载，后续直接返回"""
    global _shared_config
    if _shared_config is None:
        _shared_config = load_config()
    return _shared_config


def reset_config() -> None:
    """重置全局配置（用于测试或热重载）"""
    global _shared_config
    _shared_config = None