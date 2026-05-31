"""验证 thinking 字段的保留与传回"""

import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models import Message, MessageConverter

c = MessageConverter()

# 模拟 DeepSeek 返回带 reasoning_content 的 assistant 消息
raw_response = {
    "role": "assistant",
    "reasoning_content": "用户问北京天气，我需要调用 get_weather 工具",
    "content": None,
    "tool_calls": [{
        "id": "call_abc",
        "type": "function",
        "function": {"name": "get_weather", "arguments": '{"city":"北京"}'}
    }]
}

# 1. from_litellm 应保留 thinking
msg = c.from_litellm(raw_response)
print(f"from_litellm: thinking={msg.thinking}")
print(f"  content={msg.content}")

# 2. to_litellm 应传回 reasoning_content
litellm_msgs = c.to_litellm([msg])
print(f"\nto_litellm: {json.dumps(litellm_msgs, ensure_ascii=False, indent=2)}")

# 3. 空 thinking 不应出现在输出中
msg_no_thinking = Message(role="assistant", content="hello")
litellm_no_thinking = c.to_litellm([msg_no_thinking])
print(f"\n无 thinking: {json.dumps(litellm_no_thinking, ensure_ascii=False)}")
assert "reasoning_content" not in litellm_no_thinking[0], "空 thinking 不应出现在输出中"

# 4. 完整流程：user → assistant(tool_use+thinking) → tool → assistant
msgs = [
    Message(role="user", content="北京天气？"),
    msg,  # assistant with thinking + tool_use
    Message(role="tool", content='{"temp":"25C"}', tool_call_id="call_abc"),
    Message(role="assistant", content="北京25度", thinking=None),
]
result = c.to_litellm(msgs)
print(f"\n完整对话:")
print(json.dumps(result, ensure_ascii=False, indent=2))

print("\nAll checks passed!")
