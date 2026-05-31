"""QueryEngine 集成测试 — 验证 submitMessage 7 阶段流程"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.models.types import (
    Message, Usage, ToolUseContext, QueryParams,
    StreamChunk, ChunkType, new_uuid,
)
from src.models.config import ModelConfig


# ============================================================
# 辅助函数
# ============================================================


def _make_model_config() -> ModelConfig:
    return ModelConfig(
        alias="test",
        litellm_model="deepseek/deepseek-v4-pro",
        provider="deepseek",
        api_base=None,
        max_tokens=100000,
        api_key="sk-test",
    )


# ============================================================
# 测试
# ============================================================


@pytest.mark.asyncio
async def test_engine_submit_message():
    """submitMessage 应 yield user_msg + assistant_msg + result_msg"""
    from src.engine.queryengine import QueryEngine

    engine = QueryEngine(session_id="test-session", model_alias="reasoning")

    # Mock queryloop 直接 yield 一条 assistant 消息
    async def mock_queryloop(params):
        yield Message(
            uuid=new_uuid(),
            parentUuid=params.messages[-1].uuid if params.messages else None,
            role="assistant",
            content="Hello!",
            timestamp=1.0,
        )

    # Mock _get_model_config
    mock_config = _make_model_config()

    with patch("src.engine.queryengine.queryloop", side_effect=mock_queryloop), \
         patch.object(engine, "_get_model_config", return_value=mock_config):

        messages = []
        async for msg in engine.submitMessage("hi"):
            messages.append(msg)

    # 应该有 3 条消息：user + assistant + result
    assert len(messages) == 3
    assert messages[0].role == "user"
    assert messages[0].content == "hi"
    assert messages[1].role == "assistant"
    assert messages[1].content == "Hello!"
    assert messages[2].role == "assistant"
    assert messages[2].type == "result"
    assert messages[2].content == "[done]"

    # 验证 parentUuid 链
    assert messages[0].parentUuid is None  # 第一条消息
    assert messages[1].parentUuid == messages[0].uuid
    assert messages[2].parentUuid == messages[1].uuid


@pytest.mark.asyncio
async def test_engine_mutable_messages_updated():
    """submitMessage 结束后 mutable_messages 应包含所有消息"""
    from src.engine.queryengine import QueryEngine

    engine = QueryEngine(session_id="test-session-2", model_alias="reasoning")

    async def mock_queryloop(params):
        yield Message(
            uuid=new_uuid(),
            parentUuid=params.messages[-1].uuid if params.messages else None,
            role="assistant",
            content="Response",
            timestamp=1.0,
        )

    mock_config = _make_model_config()

    with patch("src.engine.queryengine.queryloop", side_effect=mock_queryloop), \
         patch.object(engine, "_get_model_config", return_value=mock_config):

        async for msg in engine.submitMessage("test"):
            pass  # 消费所有消息

    # mutable_messages 应包含 user + assistant（不包含 result）
    assert len(engine.mutable_messages) == 2
    assert engine.mutable_messages[0].role == "user"
    assert engine.mutable_messages[1].role == "assistant"


@pytest.mark.asyncio
async def test_engine_multi_turn():
    """多轮对话：mutable_messages 应持续累积"""
    from src.engine.queryengine import QueryEngine

    engine = QueryEngine(session_id="test-multi", model_alias="reasoning")

    turn_count = 0

    async def mock_queryloop(params):
        nonlocal turn_count
        turn_count += 1
        yield Message(
            uuid=new_uuid(),
            parentUuid=params.messages[-1].uuid if params.messages else None,
            role="assistant",
            content=f"Response {turn_count}",
            timestamp=float(turn_count),
        )

    mock_config = _make_model_config()

    with patch("src.engine.queryengine.queryloop", side_effect=mock_queryloop), \
         patch.object(engine, "_get_model_config", return_value=mock_config):

        # 第 1 轮
        async for msg in engine.submitMessage("msg1"):
            pass

        # 第 2 轮
        async for msg in engine.submitMessage("msg2"):
            pass

    # 2 轮对话：user1 + assistant1 + user2 + assistant2 = 4 条
    assert len(engine.mutable_messages) == 4
    assert engine.mutable_messages[0].content == "msg1"
    assert engine.mutable_messages[1].content == "Response 1"
    assert engine.mutable_messages[2].content == "msg2"
    assert engine.mutable_messages[3].content == "Response 2"

    # parentUuid 链完整
    assert engine.mutable_messages[1].parentUuid == engine.mutable_messages[0].uuid
    assert engine.mutable_messages[2].parentUuid == engine.mutable_messages[1].uuid
    assert engine.mutable_messages[3].parentUuid == engine.mutable_messages[2].uuid


@pytest.mark.asyncio
async def test_transcript_write_and_load():
    """TranscriptWriter 写入后应能正确恢复"""
    import tempfile
    from src.engine.transcript import TranscriptWriter

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test.jsonl"
        writer = TranscriptWriter(path)

        # 写入消息
        msgs = [
            Message(uuid="u1", role="user", content="hello", timestamp=1.0),
            Message(uuid="a1", parentUuid="u1", role="assistant", content="hi", timestamp=2.0),
        ]
        await writer.record(msgs)

        # 等待批量刷新完成
        await asyncio.sleep(0.2)

        # 新建 writer 加载
        writer2 = TranscriptWriter(path)
        loaded = await writer2.load()

        assert len(loaded) == 2
        assert loaded[0].uuid == "u1"
        assert loaded[0].role == "user"
        assert loaded[1].uuid == "a1"
        assert loaded[1].parentUuid == "u1"


@pytest.mark.asyncio
async def test_transcript_dedup():
    """TranscriptWriter 应跳过重复 UUID"""
    import tempfile
    from src.engine.transcript import TranscriptWriter

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "dedup.jsonl"
        writer = TranscriptWriter(path)

        msg = Message(uuid="dup1", role="user", content="test", timestamp=1.0)

        # 写入两次
        await writer.record([msg])
        await asyncio.sleep(0.2)
        await writer.record([msg])
        await asyncio.sleep(0.2)

        # 加载
        writer2 = TranscriptWriter(path)
        loaded = await writer2.load()

        # 应该只有 1 条
        assert len(loaded) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
