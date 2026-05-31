"""测试 LiteLLM/DeepSeek 对消息顺序的要求"""

import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models import Message, MessageConverter, LLMClient, load_config


async def test_consecutive_user():
    """测试：连续两条 user 消息"""
    config = load_config()
    client = LLMClient("flash", config)
    converter = MessageConverter()

    msgs = [
        Message(role="user", content="你好"),
        Message(role="user", content="今天天气怎么样？"),
    ]
    litellm_msgs = converter.to_litellm(msgs)
    print(f"测试: 连续 user 消息")
    print(f"  messages: {litellm_msgs}")
    try:
        result = await client.chat(litellm_msgs)
        print(f"  结果: 成功 - {result.get('content', '')[:50]}")
    except Exception as e:
        print(f"  结果: 失败 - {type(e).__name__}: {str(e)[:100]}")


async def test_consecutive_assistant():
    """测试：连续两条 assistant 消息"""
    config = load_config()
    client = LLMClient("flash", config)
    converter = MessageConverter()

    msgs = [
        Message(role="user", content="你好"),
        Message(role="assistant", content="你好！有什么可以帮助你的？"),
        Message(role="assistant", content="我随时准备为你服务。"),
    ]
    litellm_msgs = converter.to_litellm(msgs)
    print(f"\n测试: 连续 assistant 消息")
    print(f"  messages: {litellm_msgs}")
    try:
        result = await client.chat(litellm_msgs)
        print(f"  结果: 成功 - {result.get('content', '')[:50]}")
    except Exception as e:
        print(f"  结果: 失败 - {type(e).__name__}: {str(e)[:100]}")


async def test_tool_then_user():
    """测试：tool 消息后紧跟 user 消息（而不是 assistant）"""
    config = load_config()
    client = LLMClient("flash", config)
    converter = MessageConverter()

    msgs = [
        Message(role="user", content="北京天气？"),
        Message(role="assistant", content=[
            {"type": "tool_use", "id": "call_1", "name": "get_weather", "input": {"city": "北京"}}
        ]),
        Message(role="tool", content='{"temp":"25C"}', tool_call_id="call_1"),
        Message(role="user", content="谢谢"),
    ]
    litellm_msgs = converter.to_litellm(msgs)
    print(f"\n测试: tool 后跟 user")
    print(f"  messages: {litellm_msgs}")
    try:
        result = await client.chat(litellm_msgs)
        print(f"  结果: 成功 - {result.get('content', '')[:50]}")
    except Exception as e:
        print(f"  结果: 失败 - {type(e).__name__}: {str(e)[:100]}")


async def test_normal_alternating():
    """测试：正常的 user-assistant 交替"""
    config = load_config()
    client = LLMClient("flash", config)
    converter = MessageConverter()

    msgs = [
        Message(role="user", content="你好"),
        Message(role="assistant", content="你好！"),
        Message(role="user", content="今天天气？"),
    ]
    litellm_msgs = converter.to_litellm(msgs)
    print(f"\n测试: 正常交替")
    print(f"  messages: {litellm_msgs}")
    try:
        result = await client.chat(litellm_msgs)
        print(f"  结果: 成功 - {result.get('content', '')[:50]}")
    except Exception as e:
        print(f"  结果: 失败 - {type(e).__name__}: {str(e)[:100]}")


async def main():
    await test_consecutive_user()
    await test_consecutive_assistant()
    await test_tool_then_user()
    await test_normal_alternating()


if __name__ == "__main__":
    asyncio.run(main())
