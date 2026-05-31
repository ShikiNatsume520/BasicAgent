"""
压缩管线实现

职责：
- snip: 裁剪消息快照（compact_boundary 之前 + 超时旧消息）
- microcompact: 占位函数（v1.1 不实现）
- autocompact: 自动压缩会话历史

设计原则：
- 所有操作都在消息快照上进行，不修改原始 mutable_messages
- compact_boundary 消息会返回给 QueryEngine 并持久化
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from src.models.types import Message, new_uuid
from src.models.config import MemoryConfig


def snip(messages: list[Message], config: MemoryConfig) -> list[Message]:
    """
    裁剪消息快照

    逻辑：
    1. 找到最近的 compact_boundary 消息
    2. 裁剪该消息之前的所有消息（boundary 本身保留）
    3. 基于 timeout_minutes 裁剪 boundary 后面的超时旧消息

    Args:
        messages: 消息快照（不会被修改）
        config: 记忆配置

    Returns:
        裁剪后的消息列表
    """
    if not messages:
        return []

    # 步骤 1: 找到最近的 compact_boundary 消息的索引
    boundary_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].type == "compact_boundary":
            boundary_idx = i
            break

    # 步骤 2: 裁剪 boundary 之前的消息
    if boundary_idx >= 0:
        # 保留 boundary 及其之后的消息
        trimmed = list(messages[boundary_idx:])
    else:
        # 没有 boundary，保留所有消息
        trimmed = list(messages)

    # 步骤 3: 基于 timeout 裁剪 boundary 后面的超时旧消息
    if config.timeout_minutes > 0 and len(trimmed) > 1:
        timeout_seconds = config.timeout_minutes * 60
        current_time = time.time()
        cutoff_time = current_time - timeout_seconds

        # 分离 boundary 和普通消息
        boundary_messages = [msg for msg in trimmed if msg.type == "compact_boundary"]
        normal_messages = [msg for msg in trimmed if msg.type != "compact_boundary"]

        # 过滤超时的普通消息
        valid_normal_messages = [msg for msg in normal_messages if msg.timestamp >= cutoff_time]

        # 如果所有普通消息都超时了，保留最后一条
        if not valid_normal_messages and normal_messages:
            valid_normal_messages = [normal_messages[-1]]

        # 重新组合：boundary + 有效的普通消息
        trimmed = boundary_messages + valid_normal_messages

    return trimmed


def microcompact(messages: list[Message], config: MemoryConfig) -> list[Message]:
    """
    微压缩（占位函数）

    v1.1 不实现，直接返回原消息。
    后续版本将实现：
    - 压缩单条过长的工具结果
    - 截断过长的代码块

    Args:
        messages: 消息快照
        config: 记忆配置

    Returns:
        原消息列表
    """
    return messages


async def autocompact(
    messages: list[Message],
    system_prompt: str,
    config: MemoryConfig,
    llm_client,
) -> tuple[list[Message], Optional[Message]]:
    """
    自动压缩会话历史

    逻辑：
    1. 计算当前 token 数（system_prompt + messages）
    2. 如果超过阈值（max_tokens * autocompact_threshold）：
       - 先执行 snip 裁剪
       - 加载压缩提示词
       - 将 snip 后的消息 + 压缩指令发送给 LLM
       - 将返回的摘要封装成 compact_boundary 消息
    3. 返回处理后的消息列表和 compact_boundary 消息（如果有）

    Args:
        messages: 消息快照（不会被修改）
        system_prompt: 系统提示词
        config: 记忆配置
        llm_client: LLM 客户端实例

    Returns:
        tuple: (处理后的消息列表, compact_boundary 消息或 None)
    """
    # 步骤 1: 估算当前 token 数
    # 简单估算：1 个中文字符 ≈ 2 tokens，1 个英文单词 ≈ 1 token
    total_chars = len(system_prompt)
    for msg in messages:
        if isinstance(msg.content, str):
            total_chars += len(msg.content)
        elif isinstance(msg.content, list):
            for block in msg.content:
                if isinstance(block, dict) and "text" in block:
                    total_chars += len(block["text"])

    # 粗略估算 token 数
    estimated_tokens = total_chars * 1.5

    # 获取模型的 max_tokens（通过 llm_client）
    max_tokens = getattr(llm_client, 'max_tokens', 1000000)
    threshold = max_tokens * config.autocompact_threshold

    # 步骤 2: 检查是否需要压缩
    if estimated_tokens < threshold:
        return messages, None

    # 步骤 3: 执行 snip 裁剪
    trimmed_messages = snip(messages, config)

    # 如果 snip 后消息为空，直接返回
    if not trimmed_messages:
        return messages, None

    # 步骤 4: 加载压缩提示词
    compact_prompt = _load_compact_prompt(config.compact_prompt_path)
    if not compact_prompt:
        return trimmed_messages, None

    # 步骤 5: 构建对话历史文本
    conversation_text = _format_conversation(trimmed_messages)
    full_prompt = compact_prompt.replace("{conversation_history}", conversation_text)

    # 步骤 6: 调用 LLM 生成摘要
    try:
        summary = await _call_llm_for_summary(llm_client, full_prompt)
    except Exception as e:
        # 压缩失败，返回 snip 后的消息
        return trimmed_messages, None

    # 步骤 7: 创建 compact_boundary 消息
    compact_boundary = Message(
        uuid=new_uuid(),
        role="assistant",
        content=summary,
        type="compact_boundary",
        timestamp=time.time(),
    )

    # 返回：boundary + 最近的消息
    # 保留最近的几条消息以保持对话连贯性
    recent_messages = trimmed_messages[-5:] if len(trimmed_messages) > 5 else trimmed_messages
    result_messages = [compact_boundary] + recent_messages

    return result_messages, compact_boundary


def _load_compact_prompt(prompt_path: str) -> Optional[str]:
    """加载压缩提示词文件"""
    try:
        path = Path(prompt_path)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def _format_conversation(messages: list[Message]) -> str:
    """将消息列表格式化为对话文本"""
    lines = []
    for msg in messages:
        # 跳过 compact_boundary 消息
        if msg.type == "compact_boundary":
            continue

        role = msg.role
        if isinstance(msg.content, str):
            content = msg.content
        elif isinstance(msg.content, list):
            # 提取文本内容
            text_parts = []
            for block in msg.content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        text_parts.append(f"[工具调用: {block.get('name', 'unknown')}]")
            content = " ".join(text_parts) if text_parts else "[无内容]"
        else:
            content = str(msg.content)

        # 格式化角色名称
        if role == "user":
            role_name = "用户"
        elif role == "assistant":
            role_name = "助手"
        elif role == "system":
            role_name = "系统"
        else:
            role_name = role

        lines.append(f"{role_name}: {content}")

    return "\n".join(lines)


async def _call_llm_for_summary(llm_client, prompt: str) -> str:
    """调用 LLM 生成摘要"""
    from src.models.types import Message as MsgType, ChunkType

    # 构建消息
    messages = [{"role": "user", "content": prompt}]

    # 调用 LLM
    summary = ""
    async for chunk in llm_client.chat_stream(messages):
        if chunk.type == ChunkType.TEXT:
            summary += chunk.data

    return summary.strip()
