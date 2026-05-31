"""
Daemon 使用示例

演示两种对话模式：
1. chat() — 逐 token 流式输出（推荐用于实时游戏）
2. send() — Agent 模式（支持工具调用）
"""

import asyncio
from src.daemon import SessionManager
from src.models.types import Message


async def demo_chat():
    """简易对话模式 — 逐 token 输出，延迟最低"""
    print("=" * 50)
    print("  模式 1: chat() — 逐 token 流式")
    print("=" * 50)

    manager = SessionManager()
    session_id = await manager.create_session(
        model_alias="reasoning",
        system_prompt="你是一个游戏商人，回复简短。",
    )

    # 逐 token 输出
    print("\n玩家: 你卖什么？\n商人: ", end="", flush=True)
    async for chunk in manager.chat(session_id, "你卖什么？"):
        if isinstance(chunk, str):
            print(chunk, end="", flush=True)
        elif chunk.type == "result":
            print("\n")

    # 多轮
    print("玩家: 多少钱？\n商人: ", end="", flush=True)
    async for chunk in manager.chat(session_id, "多少钱？"):
        if isinstance(chunk, str):
            print(chunk, end="", flush=True)
        elif chunk.type == "result":
            print("\n")

    await manager.delete(session_id)


async def demo_send():
    """Agent 模式 — 支持工具调用（工具在 Phase 2 实现）"""
    print("=" * 50)
    print("  模式 2: send() — Agent 模式")
    print("=" * 50)

    manager = SessionManager()
    session_id = await manager.create_session(
        model_alias="reasoning",
        system_prompt="你是一个助手。",
    )

    print("\n用户: 你好\n")
    async for msg in manager.send(session_id, "你好"):
        if msg.role == "assistant" and isinstance(msg.content, str) and msg.type == "message":
            print(f"  Assistant: {msg.content}")
        elif msg.type == "result":
            print(f"  [完成]")

    await manager.delete(session_id)


async def main():
    await demo_chat()
    print()
    await demo_send()


if __name__ == "__main__":
    asyncio.run(main())
