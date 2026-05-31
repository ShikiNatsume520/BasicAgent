"""queryloop 单元测试 — 验证 ReAct 循环逻辑"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.models.types import (
    Message, Usage, ToolUseContext, QueryParams, ToolDefinition,
    StreamChunk, ChunkType, new_uuid,
)
from src.models.config import ModelConfig


# ============================================================
# 辅助函数
# ============================================================


def _make_model_config() -> ModelConfig:
    """创建测试用 ModelConfig"""
    return ModelConfig(
        alias="test",
        litellm_model="deepseek/deepseek-v4-pro",
        provider="deepseek",
        api_base=None,
        max_tokens=100000,
        api_key="sk-test",
    )


def _make_params(messages: list[Message], tools: list[ToolDefinition] = None) -> QueryParams:
    """创建测试用 QueryParams"""
    return QueryParams(
        messages=messages,
        system_prompt="You are a test assistant.",
        tools=tools or [],
        tool_use_context=ToolUseContext(agent_id="test", cwd="."),
        model_config=_make_model_config(),
    )


def _text_stream_chunks(text: str) -> list[StreamChunk]:
    """生成纯文本流式 chunks"""
    return [
        StreamChunk(type=ChunkType.TEXT, data=text),
        StreamChunk(type=ChunkType.DONE, data=""),
    ]


def _tool_use_stream_chunks(tool_id: str, tool_name: str, tool_input: dict) -> list[StreamChunk]:
    """生成工具调用流式 chunks"""
    return [
        StreamChunk(type=ChunkType.TOOL_USE, data={"id": tool_id, "name": tool_name, "input": tool_input}),
        StreamChunk(type=ChunkType.DONE, data=""),
    ]


# ============================================================
# 测试
# ============================================================


@pytest.mark.asyncio
async def test_queryloop_text_response():
    """纯文本响应：queryloop 应 yield 一条 assistant 消息后结束"""
    from src.engine.query import queryloop

    user_msg = Message(uuid=new_uuid(), role="user", content="hello", timestamp=1.0)
    params = _make_params([user_msg])

    # Mock LLMClient
    mock_client = MagicMock()
    mock_client.provider = "deepseek"
    mock_client.converter = MagicMock()
    mock_client.converter.to_provider.return_value = [{"role": "user", "content": "hello"}]
    mock_client.converter.to_provider_tools.return_value = None

    async def mock_stream(*args, **kwargs):
        for chunk in _text_stream_chunks("Hi there!"):
            yield chunk

    mock_client.chat_stream = mock_stream

    with patch("src.models.client.LLMClient", return_value=mock_client):
        messages = []
        async for msg in queryloop(params):
            messages.append(msg)

    # 应该只有 1 条 assistant 消息
    assert len(messages) == 1
    assert messages[0].role == "assistant"
    assert messages[0].content == "Hi there!"
    assert messages[0].uuid  # uuid 不为空
    assert messages[0].parentUuid == user_msg.uuid
    assert messages[0].type == "message"


@pytest.mark.asyncio
async def test_queryloop_tool_use():
    """工具调用：queryloop 应 yield assistant + tool_result 后继续，最终结束"""
    from src.engine.query import queryloop

    user_msg = Message(uuid=new_uuid(), role="user", content="get weather", timestamp=1.0)
    params = _make_params([user_msg])

    call_count = 0

    mock_client = MagicMock()
    mock_client.provider = "deepseek"
    mock_client.converter = MagicMock()
    mock_client.converter.to_provider.return_value = [{"role": "user", "content": "get weather"}]
    mock_client.converter.to_provider_tools.return_value = None

    async def mock_stream(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # 第一轮：返回工具调用
            for chunk in _tool_use_stream_chunks("call_123", "get_weather", {"city": "北京"}):
                yield chunk
        else:
            # 第二轮：返回纯文本（工具结果已在上下文中）
            for chunk in _text_stream_chunks("北京今天晴天"):
                yield chunk

    mock_client.chat_stream = mock_stream

    with patch("src.models.client.LLMClient", return_value=mock_client):
        messages = []
        async for msg in queryloop(params):
            messages.append(msg)

    # 应该有 3 条消息：assistant(tool_use) + tool_result + assistant(text)
    assert len(messages) == 3

    # 第 1 条：assistant 工具调用
    assert messages[0].role == "assistant"
    assert isinstance(messages[0].content, list)
    assert messages[0].content[0]["type"] == "tool_use"
    assert messages[0].content[0]["name"] == "get_weather"

    # 第 2 条：tool_result（占位返回）
    assert messages[1].role == "tool"
    assert messages[1].tool_call_id == "call_123"
    assert "not implemented" in messages[1].content

    # 第 3 条：assistant 文本
    assert messages[2].role == "assistant"
    assert messages[2].content == "北京今天晴天"

    # 验证 parentUuid 链
    assert messages[0].parentUuid == user_msg.uuid
    assert messages[1].parentUuid == messages[0].uuid
    assert messages[2].parentUuid == messages[1].uuid


@pytest.mark.asyncio
async def test_queryloop_multiple_tool_uses():
    """同一轮多个工具调用：应依次执行"""
    from src.engine.query import queryloop

    user_msg = Message(uuid=new_uuid(), role="user", content="do two things", timestamp=1.0)
    params = _make_params([user_msg])

    call_count = 0

    mock_client = MagicMock()
    mock_client.provider = "deepseek"
    mock_client.converter = MagicMock()
    mock_client.converter.to_provider.return_value = [{"role": "user", "content": "do two things"}]
    mock_client.converter.to_provider_tools.return_value = None

    async def mock_stream(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            yield StreamChunk(type=ChunkType.TOOL_USE, data={"id": "call_a", "name": "tool_a", "input": {}})
            yield StreamChunk(type=ChunkType.TOOL_USE, data={"id": "call_b", "name": "tool_b", "input": {}})
            yield StreamChunk(type=ChunkType.DONE, data="")
        else:
            for chunk in _text_stream_chunks("done"):
                yield chunk

    mock_client.chat_stream = mock_stream

    with patch("src.models.client.LLMClient", return_value=mock_client):
        messages = []
        async for msg in queryloop(params):
            messages.append(msg)

    # assistant(2 tool_uses) + tool_result_a + tool_result_b + assistant(text) = 4
    assert len(messages) == 4
    assert messages[0].role == "assistant"
    assert len(messages[0].content) == 2
    assert messages[1].role == "tool" and messages[1].tool_call_id == "call_a"
    assert messages[2].role == "tool" and messages[2].tool_call_id == "call_b"
    assert messages[3].role == "assistant" and messages[3].content == "done"


@pytest.mark.asyncio
async def test_queryloop_empty_history():
    """空历史：queryloop 仍应正常工作"""
    from src.engine.query import queryloop

    params = _make_params([])

    mock_client = MagicMock()
    mock_client.provider = "deepseek"
    mock_client.converter = MagicMock()
    mock_client.converter.to_provider.return_value = []
    mock_client.converter.to_provider_tools.return_value = None

    async def mock_stream(*args, **kwargs):
        for chunk in _text_stream_chunks("Hello!"):
            yield chunk

    mock_client.chat_stream = mock_stream

    with patch("src.models.client.LLMClient", return_value=mock_client):
        messages = []
        async for msg in queryloop(params):
            messages.append(msg)

    assert len(messages) == 1
    assert messages[0].role == "assistant"
    assert messages[0].parentUuid is None  # 无历史，parentUuid 为 None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
