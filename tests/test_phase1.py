"""
Phase 1 全功能测试脚本

测试内容：
1. 基础数据结构（Message, Usage, ToolUseContext, QueryParams）
2. TranscriptWriter（JSONL 持久化 + UUID 去重 + 恢复）
3. QueryEngine（submitMessage 7 阶段）
4. SessionManager（会话 CRUD + 消息路由）
5. 多轮对话 + parentUuid 链完整性
6. 实际 LLM 调用（需要 API Key）

运行方式：
    conda activate BA_py311
    python tests/test_phase1.py
"""

import sys
import os
import asyncio
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models.types import (
    Message, Usage, ToolUseContext, QueryParams, ToolDefinition,
    StreamChunk, ChunkType, MessageConverter, new_uuid,
)
from src.models.config import load_config, get_config, reset_config
from src.models.client import LLMClient
from src.engine.transcript import TranscriptWriter
from src.engine.query import queryloop
from src.engine.queryengine import QueryEngine
from src.daemon.session_manager import SessionManager


# ============================================================
# 测试工具
# ============================================================

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} — {detail}")


def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ============================================================
# 1. 基础数据结构
# ============================================================


async def test_datastructures():
    section("1. 基础数据结构")

    # Usage
    u1 = Usage(input_tokens=100, output_tokens=50)
    u2 = Usage(input_tokens=200, output_tokens=80)
    u1 += u2
    check("Usage.__iadd__", u1.input_tokens == 300 and u1.output_tokens == 130)

    # ToolUseContext
    ctx = ToolUseContext(agent_id="test", cwd=".")
    check("ToolUseContext 创建", ctx.agent_id == "test" and ctx.total_usage.input_tokens == 0)

    # Message 基本字段
    m = Message(uuid=new_uuid(), role="user", content="hello", timestamp=time.time())
    check("Message.uuid 非空", len(m.uuid) == 36)
    check("Message.type 默认值", m.type == "message")
    check("Message.parentUuid 默认 None", m.parentUuid is None)
    check("Message.usage 默认 None", m.usage is None)

    # Message 链表
    m1 = Message(uuid="u1", role="user", content="q", timestamp=1.0)
    m2 = Message(uuid="a1", parentUuid="u1", role="assistant", content="a", timestamp=2.0)
    check("Message parentUuid 链", m2.parentUuid == m1.uuid)

    # Message compact_boundary
    boundary = Message(uuid="b1", parentUuid=None, role="assistant", content="[compact]", type="compact_boundary")
    check("compact_boundary parentUuid=None", boundary.parentUuid is None)
    check("compact_boundary type", boundary.type == "compact_boundary")

    # QueryParams
    params = QueryParams(
        messages=[m1], system_prompt="test", tools=[],
        tool_use_context=ctx, model_config=None,
    )
    check("QueryParams 创建", params.max_tool_rounds == 20)

    # MessageConverter
    cvt = MessageConverter()
    litellm_msgs = cvt.to_provider([m1], provider="deepseek")
    check("Converter.to_provider", len(litellm_msgs) == 1 and litellm_msgs[0]["role"] == "user")

    raw = {"role": "assistant", "content": "hi", "tool_calls": None}
    internal = cvt.from_provider(raw, provider="deepseek")
    check("Converter.from_provider", internal.role == "assistant" and internal.content == "hi")


# ============================================================
# 2. TranscriptWriter
# ============================================================


async def test_transcript():
    section("2. TranscriptWriter")

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test.jsonl"
        writer = TranscriptWriter(path)

        # 写入
        msgs = [
            Message(uuid="t1", role="user", content="hello", timestamp=1.0),
            Message(uuid="t2", parentUuid="t1", role="assistant", content="hi", timestamp=2.0),
            Message(uuid="t3", parentUuid="t2", role="user", content="bye", timestamp=3.0),
        ]
        await writer.record(msgs)
        await asyncio.sleep(0.2)  # 等待批量刷新

        check("JSONL 文件已创建", path.exists())

        # 恢复
        writer2 = TranscriptWriter(path)
        loaded = await writer2.load()
        check("恢复消息数量", len(loaded) == 3)
        check("恢复消息内容", loaded[0].content == "hello" and loaded[2].content == "bye")
        check("恢复 parentUuid", loaded[1].parentUuid == "t1")
        check("message_set 去重集合", writer2.message_set == {"t1", "t2", "t3"})

        # 去重
        await writer2.record([Message(uuid="t1", role="user", content="dup", timestamp=4.0)])
        await asyncio.sleep(0.2)
        writer3 = TranscriptWriter(path)
        loaded2 = await writer3.load()
        check("UUID 去重", len(loaded2) == 3)  # 不应增加

        # Pydantic 序列化往返
        original = Message(uuid="s1", role="assistant", content=[{"type": "text", "text": "ok"}],
                           thinking="reasoning...", timestamp=5.0)
        json_str = original.model_dump_json()
        restored = Message.model_validate_json(json_str)
        check("Pydantic 序列化往返", restored.uuid == "s1" and restored.thinking == "reasoning...")


# ============================================================
# 3. 配置系统
# ============================================================


async def test_config():
    section("3. 配置系统")

    reset_config()
    config = load_config()

    check("配置加载成功", config is not None)
    check("reasoning 模型存在", "reasoning" in config.models)
    check("flash 模型存在", "flash" in config.models)

    rc = config.models.get("reasoning")
    if rc:
        check("reasoning provider", rc.provider == "deepseek")
        check("reasoning litellm_model", "deepseek" in rc.litellm_model)
        check("reasoning api_key 存在", rc.api_key is not None and len(rc.api_key) > 0)
    else:
        check("reasoning 配置", False, "reasoning model not found")

    # CompressionConfig
    check("压缩配置存在", config.compression.snip_window_tokens == 100000)


# ============================================================
# 4. LLMClient（实际 API 调用）
# ============================================================


async def test_llm_client():
    section("4. LLMClient（实际 API 调用）")

    reset_config()
    try:
        client = LLMClient("reasoning")
    except Exception as e:
        check("LLMClient 初始化", False, str(e))
        return

    check("LLMClient 初始化", True)
    check("provider 标识", client.provider == "deepseek")

    # 非流式调用
    cvt = client.converter
    msgs = cvt.to_provider([Message(role="user", content="回复OK两个字母")], provider=client.provider)
    try:
        raw = await client.chat(msgs, max_tokens=50)
        check("非流式调用", raw.get("content") is not None, f"content={raw.get('content')}")
    except Exception as e:
        check("非流式调用", False, str(e))
        return

    # 流式调用
    text = ""
    thinking = ""
    try:
        async for chunk in client.chat_stream(msgs, max_tokens=100):
            if chunk.type == ChunkType.TEXT:
                text += chunk.data
            elif chunk.type == ChunkType.THINKING:
                thinking += chunk.data
        check("流式调用", len(text) > 0 or len(thinking) > 0,
              f"text='{text[:50]}' thinking='{thinking[:50]}'")
    except Exception as e:
        check("流式调用", False, str(e))


# ============================================================
# 5. queryloop（Mock + 实际调用）
# ============================================================


async def test_queryloop_mock():
    section("5a. queryloop（Mock 测试）")
    from unittest.mock import MagicMock, patch

    user_msg = Message(uuid=new_uuid(), role="user", content="hello", timestamp=1.0)
    mock_config = MagicMock()
    mock_config.alias = "test"

    params = QueryParams(
        messages=[user_msg], system_prompt="test", tools=[],
        tool_use_context=ToolUseContext(agent_id="test", cwd="."),
        model_config=mock_config,
    )

    mock_client = MagicMock()
    mock_client.provider = "deepseek"
    mock_converter = MagicMock()
    mock_converter.to_provider.return_value = [{"role": "user", "content": "hello"}]
    mock_converter.to_provider_tools.return_value = None
    mock_client.converter = mock_converter

    async def mock_stream(*args, **kwargs):
        yield StreamChunk(type=ChunkType.TEXT, data="Mock response")
        yield StreamChunk(type=ChunkType.DONE, data="")

    mock_client.chat_stream = mock_stream

    with patch("src.models.client.LLMClient", return_value=mock_client):
        messages = []
        async for msg in queryloop(params):
            messages.append(msg)

    check("Mock: yield 1 条消息", len(messages) == 1)
    check("Mock: role=assistant", messages[0].role == "assistant")
    check("Mock: content 正确", messages[0].content == "Mock response")
    check("Mock: parentUuid 链接", messages[0].parentUuid == user_msg.uuid)
    check("Mock: uuid 非空", len(messages[0].uuid) > 0)


async def test_queryloop_real():
    section("5b. queryloop（实际 LLM 调用）")

    reset_config()
    config = get_config()
    mc = config.models.get(config.default_model)
    if not mc:
        check("模型配置", False, "no default model")
        return

    user_msg = Message(uuid=new_uuid(), role="user", content="回复OK两个字母，不要多说", timestamp=1.0)
    params = QueryParams(
        messages=[user_msg], system_prompt="你是一个助手。",
        tools=[], tool_use_context=ToolUseContext(agent_id="test", cwd="."),
        model_config=mc,
    )

    messages = []
    try:
        async for msg in queryloop(params):
            messages.append(msg)
    except Exception as e:
        check("queryloop 执行", False, str(e))
        return

    check("queryloop: yield 至少 1 条", len(messages) >= 1)
    check("queryloop: 最后一条是 assistant", messages[-1].role == "assistant")

    if messages:
        content = messages[-1].content if isinstance(messages[-1].content, str) else str(messages[-1].content)
        thinking = messages[-1].thinking or ""
        check("queryloop: 有输出（文本或思考）", len(content) > 0 or len(thinking) > 0,
              f"content='{content[:50]}' thinking='{thinking[:50]}'")
        check("queryloop: parentUuid 链接", messages[-1].parentUuid == user_msg.uuid)


# ============================================================
# 6. QueryEngine（submitMessage）
# ============================================================


async def test_queryengine_mock():
    section("6a. QueryEngine（Mock 测试）")
    from unittest.mock import patch, MagicMock

    engine = QueryEngine(session_id="test-engine", model_alias="reasoning")

    async def mock_queryloop(params):
        yield Message(
            uuid=new_uuid(),
            parentUuid=params.messages[-1].uuid if params.messages else None,
            role="assistant", content="Engine response", timestamp=time.time(),
        )

    mock_config = MagicMock()
    mock_config.alias = "reasoning"

    with patch("src.engine.queryengine.queryloop", side_effect=mock_queryloop), \
         patch.object(engine, "_get_model_config", return_value=mock_config):

        messages = []
        async for msg in engine.submitMessage("test input"):
            messages.append(msg)

    check("Engine: yield 3 条消息", len(messages) == 3,
          f"got {len(messages)}")
    check("Engine: [0] user", messages[0].role == "user" and messages[0].content == "test input")
    check("Engine: [1] assistant", messages[1].role == "assistant" and messages[1].content == "Engine response")
    check("Engine: [2] result", messages[2].type == "result" and messages[2].content == "[done]")

    # parentUuid 链
    check("Engine: parentUuid 链 [1]→[0]", messages[1].parentUuid == messages[0].uuid)
    check("Engine: parentUuid 链 [2]→[1]", messages[2].parentUuid == messages[1].uuid)

    # mutable_messages
    check("Engine: mutable_messages 包含 2 条", len(engine.mutable_messages) == 2)


async def test_queryengine_real():
    section("6b. QueryEngine（实际 LLM 调用）")

    engine = QueryEngine(session_id="test-real", model_alias="reasoning",
                         system_prompt="你是一个助手。回复简短。")

    messages = []
    try:
        async for msg in engine.submitMessage("回复OK两个字母"):
            messages.append(msg)
    except Exception as e:
        check("Engine 实际调用", False, str(e))
        return

    check("Engine 实际: yield 至少 2 条", len(messages) >= 2,
          f"got {len(messages)}")

    user_msgs = [m for m in messages if m.role == "user"]
    asst_msgs = [m for m in messages if m.role == "assistant" and m.type == "message"]
    result_msgs = [m for m in messages if m.type == "result"]

    check("Engine 实际: 有 user 消息", len(user_msgs) == 1)
    check("Engine 实际: 有 assistant 消息", len(asst_msgs) >= 1)
    check("Engine 实际: 有 result 消息", len(result_msgs) == 1)

    if asst_msgs:
        content = asst_msgs[-1].content if isinstance(asst_msgs[-1].content, str) else str(asst_msgs[-1].content)
        thinking = asst_msgs[-1].thinking or ""
        check("Engine 实际: assistant 有输出", len(content) > 0 or len(thinking) > 0,
              f"content='{content[:50]}' thinking='{thinking[:50]}'")

    # mutable_messages
    check("Engine 实际: mutable_messages 已更新", len(engine.mutable_messages) >= 2)


# ============================================================
# 7. SessionManager（会话 CRUD + 多轮对话）
# ============================================================


async def test_session_manager():
    section("7. SessionManager（会话管理）")

    manager = SessionManager()

    # 创建会话
    sid = await manager.create_session(model_alias="reasoning", system_prompt="简短回复。")
    check("创建会话", sid is not None and len(sid) == 36)

    # 列出会话
    sessions = await manager.list_sessions()
    check("列出会话", sid in sessions)

    # 发送消息
    messages = []
    async for msg in manager.send(sid, "回复OK"):
        messages.append(msg)
    check("发送消息: 收到响应", len(messages) >= 2)

    # 多轮对话
    messages2 = []
    async for msg in manager.send(sid, "1+1=?"):
        messages2.append(msg)
    check("多轮对话: 收到响应", len(messages2) >= 2)

    # 验证会话内消息累积
    engine = manager.sessions[sid]
    check("消息累积: mutable_messages", len(engine.mutable_messages) >= 4,
          f"got {len(engine.mutable_messages)}")

    # parentUuid 链完整性
    msgs = engine.mutable_messages
    chain_ok = True
    for i in range(1, len(msgs)):
        if msgs[i].parentUuid != msgs[i-1].uuid:
            chain_ok = False
            break
    check("parentUuid 链完整性", chain_ok)

    # 删除会话
    await manager.delete(sid)
    sessions_after = await manager.list_sessions()
    check("删除会话", sid not in sessions_after)


# ============================================================
# 8. Transcript 持久化 + resume
# ============================================================


async def test_resume():
    section("8. Transcript 持久化 + resume")

    manager = SessionManager()
    sid = await manager.create_session(model_alias="reasoning")

    # 发送消息
    async for msg in manager.send(sid, "记住数字42"):
        pass

    # 等待 transcript 写入
    await asyncio.sleep(0.3)

    # 验证 JSONL 文件存在
    transcript_path = Path(f"data/sessions/{sid}.jsonl")
    check("JSONL 文件已创建", transcript_path.exists())

    # 创建新 SessionManager，模拟进程重启
    manager2 = SessionManager()
    sid2 = await manager2.create_session(model_alias="reasoning")

    # 手动设置 session_id 为原来的（模拟 resume）
    engine2 = manager2.sessions[sid2]
    engine2.session_id = sid
    engine2.transcript = TranscriptWriter(transcript_path)

    # resume
    await engine2.resume()
    check("resume: 恢复消息", len(engine2.mutable_messages) > 0,
          f"got {len(engine2.mutable_messages)} messages")

    if engine2.mutable_messages:
        check("resume: 第一条是 user", engine2.mutable_messages[0].role == "user")


# ============================================================
# 主入口
# ============================================================


async def main():
    print("\n" + "=" * 60)
    print("  BasicAgent Phase 1 全功能测试")
    print("=" * 60)

    await test_datastructures()
    await test_transcript()
    await test_config()
    await test_llm_client()
    await test_queryloop_mock()
    await test_queryloop_real()
    await test_queryengine_mock()
    await test_queryengine_real()
    await test_session_manager()
    await test_resume()

    print(f"\n{'='*60}")
    print(f"  结果: {passed} passed, {failed} failed, {passed+failed} total")
    print(f"{'='*60}")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
