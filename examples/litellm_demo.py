"""
LiteLLM Provider 切换演示

演示内容：
1. 如何用 litellm_model string 前缀自动路由到不同 provider
2. 如何通过 api_base 指定自定义端点（Ollama、中转站）
3. 流式输出的处理方式
4. 工具调用（function calling）在流式模式下的缓冲拼接

使用方式：
    # 对 Ollama（需要本地运行 ollama serve）
    python examples/litellm_demo.py ollama

    # 对 OpenAI（需要设置 OPENAI_API_KEY 环境变量）
    python examples/litellm_demo.py openai

    # 对 OpenAI 中转站
    python examples/litellm_demo.py openai --base-url https://your-proxy/v1
"""

import asyncio
import json
import sys
import os
from pathlib import Path

# 加载 .env
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import litellm


# ============================================================
# 配置：根据 provider 选择不同的 model string 和 api_base
# ============================================================

PROVIDERS = {
    "ollama": {
        "model": "ollama_chat/llama3",
        "api_base": "http://localhost:11434",
        "api_key": None,
    },
    "openai": {
        "model": "openai/gpt-4o-mini",
        "api_base": None,  # 使用默认 OpenAI 端点
        "api_key": os.getenv("OPENAI_API_KEY"),
    },
}


# ============================================================
# 示例 1：纯文本流式对话
# ============================================================

async def demo_streaming(provider_name: str, base_url: str | None = None):
    """流式文本输出 — 最基础的用法"""
    config = PROVIDERS[provider_name].copy()
    if base_url:
        config["api_base"] = base_url

    print(f"\n{'='*60}")
    print(f"示例1: 流式对话 | provider={provider_name} | model={config['model']}")
    print(f"{'='*60}\n")

    messages = [
        {"role": "user", "content": "用三句话介绍你自己。"}
    ]

    kwargs = {
        "model": config["model"],
        "messages": messages,
        "stream": True,
    }
    if config["api_base"]:
        kwargs["api_base"] = config["api_base"]
    if config["api_key"]:
        kwargs["api_key"] = config["api_key"]

    response = await litellm.acompletion(**kwargs)

    print("Assistant: ", end="", flush=True)
    async for chunk in response:
        delta = chunk.choices[0].delta
        content = delta.content
        if content:
            print(content, end="", flush=True)
    print("\n")


# ============================================================
# 示例 2：流式工具调用（带缓冲拼接）
# ============================================================

# 定义一个简单的工具
WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "获取指定城市的天气信息",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "城市名称，如 '北京'、'上海'"
                }
            },
            "required": ["city"]
        }
    }
}


async def demo_tool_calling(provider_name: str, base_url: str | None = None):
    """
    流式工具调用 — 核心难点演示

    LiteLLM 将所有 provider 的工具调用归一化为 OpenAI 格式：
    - chunk.choices[0].delta.tool_calls 是一个列表
    - 每个 tool_call 有 index、id、function.name、function.arguments
    - arguments 是分 chunk 到达的，需要按 index 缓冲拼接
    - 当 arguments 拼接完成后，尝试 json.loads 解析，成功则说明工具调用完成
    """
    config = PROVIDERS[provider_name].copy()
    if base_url:
        config["api_base"] = base_url

    print(f"\n{'='*60}")
    print(f"示例2: 流式工具调用 | provider={provider_name} | model={config['model']}")
    print(f"{'='*60}\n")

    messages = [
        {"role": "user", "content": "北京和上海今天天气怎么样？"}
    ]

    kwargs = {
        "model": config["model"],
        "messages": messages,
        "tools": [WEATHER_TOOL],
        "stream": True,
    }
    if config["api_base"]:
        kwargs["api_base"] = config["api_base"]
    if config["api_key"]:
        kwargs["api_key"] = config["api_key"]

    response = await litellm.acompletion(**kwargs)

    # 缓冲区：按 tool_call index 分别存储
    tool_calls_buffer: dict[int, dict] = {}
    text_parts: list[str] = []

    async for chunk in response:
        delta = chunk.choices[0].delta

        # 收集文本部分
        if delta.content:
            text_parts.append(delta.content)
            print(delta.content, end="", flush=True)

        # 收集工具调用部分
        if delta.tool_calls:
            for tc in delta.tool_calls:
                idx = tc.index
                if idx not in tool_calls_buffer:
                    tool_calls_buffer[idx] = {
                        "id": tc.id or "",
                        "name": "",
                        "arguments": "",
                    }
                if tc.id:
                    tool_calls_buffer[idx]["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        tool_calls_buffer[idx]["name"] = tc.function.name
                    if tc.function.arguments:
                        tool_calls_buffer[idx]["arguments"] += tc.function.arguments

    # 输出结果
    print("\n")
    if text_parts:
        print(f"[文本响应] {''.join(text_parts)}")

    if tool_calls_buffer:
        print(f"\n[检测到 {len(tool_calls_buffer)} 个工具调用]")
        for idx, tc in tool_calls_buffer.items():
            print(f"  工具调用 #{idx}:")
            print(f"    id: {tc['id']}")
            print(f"    name: {tc['name']}")
            try:
                args = json.loads(tc['arguments'])
                print(f"    arguments: {json.dumps(args, ensure_ascii=False, indent=4)}")
            except json.JSONDecodeError:
                print(f"    arguments (raw): {tc['arguments']}")
                print(f"    ⚠️ JSON 解析失败，arguments 可能不完整")

    print()


# ============================================================
# 示例 3：展示 LiteLLM 的 model string 路由机制
# ============================================================

async def demo_routing():
    """
    展示 LiteLLM 如何通过 model string 前缀路由到不同 provider

    格式：{provider}/{model_name}

    常用前缀：
    - openai/         → OpenAI API
    - ollama_chat/    → Ollama /api/chat 端点
    - ollama/         → Ollama /api/generate 端点
    - anthropic/      → Anthropic Claude
    - gemini/         → Google Gemini
    - openai/{model}  + api_base → 任意 OpenAI 兼容端点（中转站）
    """
    print(f"\n{'='*60}")
    print("示例3: LiteLLM 路由机制说明")
    print(f"{'='*60}")
    print("""
LiteLLM 通过 model string 的前缀自动选择 provider：

  model string              →  路由目标
  ─────────────────────────────────────────
  openai/gpt-4o-mini        →  OpenAI 官方 API
  ollama_chat/llama3         →  本地 Ollama (推荐)
  ollama/llama3              →  本地 Ollama (旧端点)
  anthropic/claude-3-haiku   →  Anthropic Claude
  gemini/gemini-2.0-flash    →  Google Gemini

对于中转站 / 自部署服务，使用 openai/ 前缀 + api_base 参数：

  model="openai/your-model"
  api_base="https://your-proxy.com/v1"

这会通过 OpenAI 兼容协议访问你的自定义端点。
""")


# ============================================================
# 主入口
# ============================================================

async def main():
    if len(sys.argv) < 2:
        print("用法: python litellm_demo.py <provider> [--base-url URL]")
        print("  provider: ollama | openai")
        print("  --base-url: 自定义 API 端点（可选）")
        sys.exit(1)

    provider = sys.argv[1]
    base_url = None
    if "--base-url" in sys.argv:
        idx = sys.argv.index("--base-url")
        base_url = sys.argv[idx + 1]

    if provider not in PROVIDERS:
        print(f"未知 provider: {provider}，可选: {list(PROVIDERS.keys())}")
        sys.exit(1)

    await demo_routing()
    await demo_streaming(provider, base_url)
    await demo_tool_calling(provider, base_url)


if __name__ == "__main__":
    asyncio.run(main())
