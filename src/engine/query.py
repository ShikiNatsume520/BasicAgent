"""
query — 无状态 LLM 调用 async generator

提供两种模式：
- chat(): 简易对话（queryloop 的简化版，保留压缩管线和记忆占位，去掉循环和工具调用）
- queryloop(): ReAct 循环（支持工具调用，适用于 Agent 场景）

两种模式都不负责状态持久化，由 QueryEngine 处理。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import AsyncGenerator

from src.models.types import (
    Message,
    ChunkType,
    QueryParams,
    new_uuid,
)


# ============================================================
# queryloop 内部状态
# ============================================================


@dataclass
class State:
    """queryloop 每次迭代的局部状态，不与外部共享"""
    messages: list[Message]
    max_output_tokens_recovery_count: int = 0


# ============================================================
# 占位函数（Phase 2/3 实现）
# ============================================================


def _apply_compression_pipeline(messages: list[Message]) -> list[Message]:
    """占位：Phase 3 实现压缩管线（snip → microcompact → autocompact）"""
    return messages


async def _execute_tool(tool_use: dict, context) -> str:
    """占位：Phase 2 实现工具执行"""
    return json.dumps({"error": f"Tool '{tool_use.get('name')}' not implemented yet"})


# ============================================================
# 核心循环
# ============================================================


async def queryloop(params: QueryParams) -> AsyncGenerator[Message, None]:
    """
    无状态 ReAct 循环。

    输入：QueryParams（上下文快照）
    输出：yield 每一轮新产生的消息（assistant / tool_result）
    """
    # 延迟导入，避免循环依赖
    from src.models.client import LLMClient

    llm_client = LLMClient(params.model_config.alias)
    converter = llm_client.converter
    provider = llm_client.provider

    state = State(messages=list(params.messages))

    while True:
        # ── 步骤 1：压缩管线（占位，直接透传）──
        messages_for_query = _apply_compression_pipeline(state.messages)

        # ── 步骤 2：调用 LLM API（流式）──
        provider_msgs = converter.to_provider(messages_for_query, provider)
        provider_tools = None
        if params.tools:
            provider_tools = converter.to_provider_tools(params.tools, provider)

        assistant_text = ""
        tool_calls_buffer: dict[int, dict] = {}
        thinking = ""
        stop_reason = "end_turn"

        async for chunk in llm_client.chat_stream(provider_msgs, provider_tools):
            if chunk.type == ChunkType.TEXT:
                assistant_text += chunk.data
            elif chunk.type == ChunkType.TOOL_USE:
                tool_calls_buffer[len(tool_calls_buffer)] = chunk.data
                stop_reason = "tool_use"
            elif chunk.type == ChunkType.THINKING:
                thinking = chunk.data
            # DONE chunk 不做处理，循环自然结束

        # ── 步骤 3：构建 assistant_message ──
        if stop_reason == "tool_use":
            content = [{"type": "tool_use", **tc} for tc in tool_calls_buffer.values()]
        else:
            content = assistant_text

        assistant_message = Message(
            uuid=new_uuid(),
            parentUuid=state.messages[-1].uuid if state.messages else None,
            role="assistant",
            content=content,
            thinking=thinking or None,
            timestamp=time.time(),
        )
        state.messages.append(assistant_message)
        yield assistant_message

        # ── 步骤 4：判断 stop_reason ──
        if stop_reason == "end_turn":
            return

        elif stop_reason == "tool_use":
            # 执行每个工具调用
            for tc in tool_calls_buffer.values():
                tool_result_content = await _execute_tool(tc, params.tool_use_context)
                tool_result_msg = Message(
                    uuid=new_uuid(),
                    parentUuid=assistant_message.uuid,
                    role="tool",
                    content=tool_result_content,
                    tool_call_id=tc["id"],
                    timestamp=time.time(),
                )
                state.messages.append(tool_result_msg)
                yield tool_result_msg
            # continue → 下一轮迭代（重新调用 API）
            continue

        elif stop_reason == "max_tokens":
            if state.max_output_tokens_recovery_count < 3:
                state.max_output_tokens_recovery_count += 1
                recovery_msg = Message(
                    uuid=new_uuid(),
                    parentUuid=state.messages[-1].uuid,
                    role="user",
                    content="[请继续]",
                    timestamp=time.time(),
                )
                state.messages.append(recovery_msg)
                yield recovery_msg
                continue
            else:
                return

        else:
            return


# ============================================================
# 简易对话（queryloop 的简化版）
# ============================================================


async def chat_stream(params: QueryParams) -> AsyncGenerator[str | Message, None]:
    """
    简易对话（流式版）— queryloop 的简化版。

    保留：压缩管线、记忆占位
    去掉：循环、工具调用、max_tokens 恢复

    输入：QueryParams（上下文快照）
    输出：逐 token yield 文本，最后 yield 完整 Message

    适用于实时对话游戏等需要逐 token 输出的场景。
    """
    from src.models.client import LLMClient

    llm_client = LLMClient(params.model_config.alias)
    converter = llm_client.converter
    provider = llm_client.provider

    # ── 步骤 1：压缩管线（与 queryloop 相同）──
    messages_for_query = _apply_compression_pipeline(params.messages)

    # ── 步骤 2：记忆注入（占位，Phase 4 实现）──
    # messages_for_query = await _inject_memory(messages_for_query, params.system_prompt)

    # ── 步骤 3：构建 provider 格式消息 ──
    full_messages = [Message(role="system", content=params.system_prompt)] + messages_for_query
    provider_msgs = converter.to_provider(full_messages, provider)

    # ── 步骤 4：流式调用，逐 token yield ──
    assistant_text = ""
    thinking = ""

    async for chunk in llm_client.chat_stream(provider_msgs):
        if chunk.type == ChunkType.TEXT:
            assistant_text += chunk.data
            yield chunk.data  # 逐 token 输出
        elif chunk.type == ChunkType.THINKING:
            thinking = chunk.data

    # ── 步骤 5：构建完整 Message ──
    assistant_message = Message(
        uuid=new_uuid(),
        parentUuid=messages_for_query[-1].uuid if messages_for_query else None,
        role="assistant",
        content=assistant_text,
        thinking=thinking or None,
        timestamp=time.time(),
    )
    yield assistant_message


async def chat(params: QueryParams) -> AsyncGenerator[Message, None]:
    """
    简易对话（Message 版）— chat_stream 的包装。

    与 chat_stream 相同的逻辑，但只 yield 最终完整 Message（不逐 token 输出）。
    适用于不需要实时显示的场景。

    输入：QueryParams（上下文快照）
    输出：yield 一条 assistant Message
    """
    async for chunk in chat_stream(params):
        if isinstance(chunk, Message):
            yield chunk
