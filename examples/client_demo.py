"""
client.py 使用演示

架构说明：
  get_config()（全局配置，只读）  →  LLMClient（绑定别名，参数预计算）  →  litellm API
                                          ↓
                                  MessageConverter（无状态，provider 由调用方指定）

使用方式：
    python examples/client_demo.py                   # 流式（默认 reasoning 模型）
    python examples/client_demo.py --mode sync       # 非流式
    python examples/client_demo.py --model flash     # 使用 flash 模型
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models import (
    AppConfig,
    LLMClient,
    Message,
    ChunkType,
    ToolDefinition,
    load_config,
)


def print_config(config: AppConfig):
    """打印配置信息"""
    print("\n配置加载完成：")
    for alias, mc in config.models.items():
        key_display = "***" if mc.api_key else "None"
        print(f"  {alias}: {mc.litellm_model} (provider={mc.provider}, max_tokens={mc.max_tokens}, api_key={key_display})")
    print(f"  default_model: {config.default_model}")


async def demo_streaming(client: LLMClient):
    """流式输出演示"""
    cvt = client.converter
    p = client.provider

    print(f"\n{'='*60}")
    print(f"流式调用 | model={client.model_alias} | provider={p}")
    print(f"{'='*60}\n")

    messages = [Message(role="user", content="用三句话介绍你自己。")]
    litellm_msgs = cvt.to_provider(messages, provider=p)

    print("Assistant: ", end="", flush=True)
    async for chunk in client.chat_stream(litellm_msgs):
        if chunk.type == ChunkType.TEXT:
            print(chunk.data, end="", flush=True)
        elif chunk.type == ChunkType.TOOL_USE:
            print(f"\n[工具调用] {chunk.data['name']}({json.dumps(chunk.data['input'], ensure_ascii=False)})")
        elif chunk.type == ChunkType.DONE:
            pass
    print("\n")


async def demo_non_streaming(client: LLMClient):
    """非流式输出演示"""
    cvt = client.converter
    p = client.provider

    print(f"\n{'='*60}")
    print(f"非流式调用 | model={client.model_alias} | provider={p}")
    print(f"{'='*60}\n")

    messages = [Message(role="user", content="用三句话介绍你自己。")]
    litellm_msgs = cvt.to_provider(messages, provider=p)

    raw_response = await client.chat(litellm_msgs)
    assistant_msg = cvt.from_provider(raw_response, provider=p)
    print(f"Assistant: {assistant_msg.content}\n")


async def demo_tool_calling(client: LLMClient):
    """工具调用演示（流式）"""
    cvt = client.converter
    p = client.provider

    print(f"\n{'='*60}")
    print(f"工具调用（流式）| model={client.model_alias} | provider={p}")
    print(f"{'='*60}\n")

    weather_tool = ToolDefinition(
        name="get_weather",
        description="获取指定城市的天气信息",
        input_schema={
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名称"},
            },
            "required": ["city"],
        },
    )

    messages = [Message(role="user", content="北京今天天气怎么样？")]
    litellm_msgs = cvt.to_provider(messages, provider=p)
    litellm_tools = cvt.to_provider_tools([weather_tool], provider=p)

    print("Assistant: ", end="", flush=True)
    async for chunk in client.chat_stream(litellm_msgs, tools=litellm_tools):
        if chunk.type == ChunkType.TEXT:
            print(chunk.data, end="", flush=True)
        elif chunk.type == ChunkType.TOOL_USE:
            print(f"\n[工具调用] {chunk.data['name']}({json.dumps(chunk.data['input'], ensure_ascii=False)})")
        elif chunk.type == ChunkType.DONE:
            pass
    print("\n")


async def demo_tool_result_flow(client: LLMClient):
    """
    完整的工具调用流程演示：
    用户提问 → LLM 调用工具 → 注入工具结果 → LLM 生成最终回答

    这就是 QueryLoop 的基本模式。
    """
    cvt = client.converter
    p = client.provider

    print(f"\n{'='*60}")
    print(f"完整工具调用流程 | model={client.model_alias} | provider={p}")
    print(f"{'='*60}\n")

    weather_tool = ToolDefinition(
        name="get_weather",
        description="获取指定城市的天气信息",
        input_schema={
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名称"},
            },
            "required": ["city"],
        },
    )

    # 第一轮：用户提问，LLM 调用工具
    messages = [Message(role="user", content="北京今天天气怎么样？")]
    litellm_msgs = cvt.to_provider(messages, provider=p)
    litellm_tools = cvt.to_provider_tools([weather_tool], provider=p)

    print(">>> 第一轮：用户提问，LLM 决定调用工具")
    tool_use_blocks = []
    thinking_content = None
    async for chunk in client.chat_stream(litellm_msgs, tools=litellm_tools):
        if chunk.type == ChunkType.TEXT:
            pass
        elif chunk.type == ChunkType.THINKING:
            thinking_content = chunk.data
            print(f"    [思考过程] {chunk.data[:100]}...")
        elif chunk.type == ChunkType.TOOL_USE:
            tool_use_blocks.append(chunk.data)
            print(f"    LLM 调用工具: {chunk.data['name']}({json.dumps(chunk.data['input'], ensure_ascii=False)})")

    if not tool_use_blocks:
        print("    LLM 未调用工具，直接返回文本。")
        return

    # 第二轮：注入工具结果，LLM 生成最终回答
    print("\n>>> 第二轮：注入工具结果，LLM 生成最终回答")

    assistant_msg = cvt.from_stream_chunks(
        {0: {
            "id": tool_use_blocks[0]["id"],
            "name": tool_use_blocks[0]["name"],
            "arguments": json.dumps(tool_use_blocks[0]["input"]),
        }},
        thinking=thinking_content,
    )
    messages.append(assistant_msg)

    tool_result_msg = cvt.make_tool_result_message(
        tool_use_id=tool_use_blocks[0]["id"],
        content='{"city": "北京", "weather": "晴", "temp": "25°C"}',
    )
    messages.append(tool_result_msg)

    litellm_msgs = cvt.to_provider(messages, provider=p)
    print("    Assistant: ", end="", flush=True)
    async for chunk in client.chat_stream(litellm_msgs):
        if chunk.type == ChunkType.TEXT:
            print(chunk.data, end="", flush=True)
    print("\n")


async def main():
    mode = "stream"
    model_alias = None
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--mode" and i < len(sys.argv) - 1:
            mode = sys.argv[i + 1]
        elif arg == "--model" and i < len(sys.argv) - 1:
            model_alias = sys.argv[i + 1]

    config = load_config()
    print_config(config)

    alias = model_alias or config.default_model
    client = LLMClient(alias)

    if mode == "stream":
        await demo_streaming(client)
    else:
        await demo_non_streaming(client)

    await demo_tool_calling(client)
    await demo_tool_result_flow(client)


if __name__ == "__main__":
    asyncio.run(main())
