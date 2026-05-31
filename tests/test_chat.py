"""
chat / chat_stream 测试脚本

测试内容：
1. chat_stream() — 逐 token 流式输出 + 最终 Message
2. chat() — 只 yield 最终 Message
3. QueryEngine.chatMessage() — 会话级逐 token 输出
4. SessionManager.chat() — 通过管理器使用
5. 多轮对话 + parentUuid 链完整性
6. 与 queryloop 对比

运行方式：
    conda activate BA_py311
    python tests/test_chat.py
"""

import sys
import asyncio
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models.types import Message, QueryParams, ToolUseContext, new_uuid
from src.models.config import get_config, reset_config
from src.engine.query import chat, chat_stream
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


def _make_params(messages: list[Message], system_prompt: str = "你是一个助手。") -> QueryParams:
    reset_config()
    config = get_config()
    mc = config.models.get(config.default_model)
    return QueryParams(
        messages=messages,
        system_prompt=system_prompt,
        tools=[],
        tool_use_context=ToolUseContext(agent_id="test", cwd="."),
        model_config=mc,
    )


# ============================================================
# 1. chat_stream() — 逐 token 流式
# ============================================================


async def test_chat_stream():
    section("1. chat_stream() — 逐 token 流式输出")

    messages = [Message(uuid=new_uuid(), role="user", content="说'你好世界'", timestamp=1.0)]
    params = _make_params(messages)

    tokens = []
    final_msg = None
    t0 = time.time()

    async for chunk in chat_stream(params):
        if isinstance(chunk, str):
            tokens.append(chunk)
            print(f"    token: '{chunk}'", flush=True)
        elif isinstance(chunk, Message):
            final_msg = chunk

    elapsed = time.time() - t0

    check("收到 token", len(tokens) > 0, f"got {len(tokens)} tokens")
    check("token 非空", all(len(t) > 0 for t in tokens))
    check("收到完整消息", final_msg is not None)
    if final_msg:
        check("role=assistant", final_msg.role == "assistant")
        check("content 匹达", final_msg.content == "".join(tokens),
              f"content='{final_msg.content}' joined='{ ''.join(tokens)}'")
        check("parentUuid 链接", final_msg.parentUuid == messages[0].uuid)
        check("uuid 非空", len(final_msg.uuid) > 0)

    full_text = "".join(tokens)
    print(f"    完整回复: '{full_text}'")
    print(f"    耗时: {elapsed:.2f}s, {len(tokens)} tokens")


# ============================================================
# 2. chat() — 只 yield Message
# ============================================================


async def test_chat_message():
    section("2. chat() — 只 yield 最终 Message")

    messages = [Message(uuid=new_uuid(), role="user", content="回复OK", timestamp=1.0)]
    params = _make_params(messages)

    msgs = []
    t0 = time.time()

    async for msg in chat(params):
        msgs.append(msg)

    elapsed = time.time() - t0

    check("yield 1 条消息", len(msgs) == 1, f"got {len(msgs)}")
    if msgs:
        check("role=assistant", msgs[0].role == "assistant")
        check("content 有内容", len(msgs[0].content) > 0, f"'{msgs[0].content[:50]}'")
        check("parentUuid 链接", msgs[0].parentUuid == messages[0].uuid)

    print(f"    回复: '{msgs[0].content[:100]}'")
    print(f"    耗时: {elapsed:.2f}s")


# ============================================================
# 3. QueryEngine.chatMessage() — 会话级
# ============================================================


async def test_engine_chatMessage():
    section("3. QueryEngine.chatMessage() — 逐 token + 状态管理")

    engine = QueryEngine(
        session_id="test-chat",
        model_alias="reasoning",
        system_prompt="你是一个游戏NPC。回复简短。",
    )

    tokens = []
    result_msgs = []
    t0 = time.time()

    async for chunk in engine.chatMessage("你是谁？"):
        if isinstance(chunk, str):
            tokens.append(chunk)
        elif isinstance(chunk, Message):
            result_msgs.append(chunk)

    elapsed = time.time() - t0

    check("收到 token", len(tokens) > 0)
    check("收到 result 消息", len(result_msgs) == 1)
    if result_msgs:
        check("result type", result_msgs[0].type == "result")

    check("mutable_messages 包含 2 条", len(engine.mutable_messages) == 2)
    if len(engine.mutable_messages) >= 2:
        check("[0] user", engine.mutable_messages[0].role == "user")
        check("[1] assistant", engine.mutable_messages[1].role == "assistant")
        check("parentUuid 链", engine.mutable_messages[1].parentUuid == engine.mutable_messages[0].uuid)
        check("assistant content 匹配", engine.mutable_messages[1].content == "".join(tokens))

    print(f"    回复: '{ ''.join(tokens)[:100]}'")
    print(f"    耗时: {elapsed:.2f}s")


# ============================================================
# 4. SessionManager.chat()
# ============================================================


async def test_session_manager_chat():
    section("4. SessionManager.chat() — 通过管理器")

    manager = SessionManager()
    sid = await manager.create_session(
        model_alias="reasoning",
        system_prompt="你是一个游戏商人。回复简短。",
    )

    tokens = []
    result_msg = None

    async for chunk in manager.chat(sid, "你卖什么？"):
        if isinstance(chunk, str):
            tokens.append(chunk)
        elif isinstance(chunk, Message):
            result_msg = chunk

    check("收到 token", len(tokens) > 0)
    check("收到 result", result_msg is not None and result_msg.type == "result")

    print(f"    回复: '{ ''.join(tokens)[:100]}'")

    await manager.delete(sid)


# ============================================================
# 5. 多轮对话
# ============================================================


async def test_multi_turn():
    section("5. 多轮对话 — parentUuid 链完整性")

    manager = SessionManager()
    sid = await manager.create_session(
        model_alias="reasoning",
        system_prompt="你是一个助手。回复简短。",
    )

    # 第 1 轮
    t1 = []
    async for chunk in manager.chat(sid, "记住数字42"):
        if isinstance(chunk, str):
            t1.append(chunk)

    # 第 2 轮
    t2 = []
    async for chunk in manager.chat(sid, "我让你记住的数字是多少？"):
        if isinstance(chunk, str):
            t2.append(chunk)

    engine = manager.sessions[sid]
    msgs = engine.mutable_messages

    check("两轮后有 4 条消息", len(msgs) == 4, f"got {len(msgs)}")

    if len(msgs) >= 4:
        check("[0] user", msgs[0].role == "user" and msgs[0].content == "记住数字42")
        check("[1] assistant", msgs[1].role == "assistant")
        check("[2] user", msgs[2].role == "user")
        check("[3] assistant", msgs[3].role == "assistant")

        chain_ok = (
            msgs[1].parentUuid == msgs[0].uuid
            and msgs[2].parentUuid == msgs[1].uuid
            and msgs[3].parentUuid == msgs[2].uuid
        )
        check("parentUuid 链完整", chain_ok)

    print(f"    第2轮回复: '{ ''.join(t2)[:100]}'")

    await manager.delete(sid)


# ============================================================
# 6. 与 queryloop 对比
# ============================================================


async def test_compare_speed():
    section("6. 速度对比: chat vs queryloop")

    reset_config()
    config = get_config()
    mc = config.models.get(config.default_model)

    messages = [Message(uuid=new_uuid(), role="user", content="用一句话介绍你自己", timestamp=1.0)]

    # chat（简易模式）
    params = _make_params(messages)
    t0 = time.time()
    chat_msgs = []
    async for msg in chat(params):
        chat_msgs.append(msg)
    chat_time = time.time() - t0

    # queryloop（完整模式）
    from src.engine.query import queryloop
    t0 = time.time()
    loop_msgs = []
    async for msg in queryloop(params):
        loop_msgs.append(msg)
    loop_time = time.time() - t0

    print(f"    chat:      {chat_time:.2f}s, {len(chat_msgs)} messages")
    print(f"    queryloop: {loop_time:.2f}s, {len(loop_msgs)} messages")

    check("两者都产生输出", len(chat_msgs) > 0 and len(loop_msgs) > 0)


# ============================================================
# 主入口
# ============================================================


async def main():
    print("\n" + "=" * 60)
    print("  chat / chat_stream 功能测试")
    print("=" * 60)

    await test_chat_stream()
    await test_chat_message()
    await test_engine_chatMessage()
    await test_session_manager_chat()
    await test_multi_turn()
    await test_compare_speed()

    print(f"\n{'='*60}")
    print(f"  结果: {passed} passed, {failed} failed, {passed+failed} total")
    print(f"{'='*60}")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
