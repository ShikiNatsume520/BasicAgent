"""验证 provider 感知的 MessageConverter（无状态版本）"""

import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models import Message, MessageConverter, LLMClient, load_config

# 1. 测试 LLMClient 自动绑定 provider
client = LLMClient("reasoning")
print(f"client.provider: {client.provider}")

cvt = client.converter
p = client.provider

# 2. 测试 to_provider（传入 provider）
msgs = [
    Message(role="user", content="hello"),
    Message(role="assistant", content=[
        {"type": "tool_use", "id": "call_1", "name": "get_weather", "input": {"city": "北京"}}
    ], thinking="用户问天气"),
    Message(role="tool", content='{"temp":"25C"}', tool_call_id="call_1"),
]
result = cvt.to_provider(msgs, provider=p)
print(f"\nto_provider (provider={p}):")
print(json.dumps(result, ensure_ascii=False, indent=2))

# 3. 测试 from_provider
raw = {
    "role": "assistant",
    "reasoning_content": "让我想想",
    "content": None,
    "tool_calls": [{
        "id": "call_abc",
        "type": "function",
        "function": {"name": "get_weather", "arguments": '{"city":"北京"}'}
    }]
}
msg = cvt.from_provider(raw, provider=p)
print(f"\nfrom_provider: thinking={msg.thinking}, content={msg.content}")

# 4. 不支持的 provider 应抛出异常
try:
    cvt.to_provider(msgs, provider="unsupported")
    print("\nERROR: 应该抛出异常")
except ValueError as e:
    print(f"\n未知 provider 正确抛出异常: {e}")

# 5. 无状态验证：同一个 converter 可用于不同 provider
result_openai = cvt.to_provider(msgs, provider="openai")
result_deepseek = cvt.to_provider(msgs, provider="deepseek")
assert result_openai == result_deepseek, "openai 和 deepseek 应使用相同路径"
print("\n无状态验证通过: 同一 converter 可用于不同 provider")

print("\nAll checks passed!")
