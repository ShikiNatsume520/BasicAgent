"""验证 MessageConverter 的 to_litellm 转换是否正确"""

import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models import Message, MessageConverter

c = MessageConverter()

# 1. Assistant 工具调用 → OpenAI tool_calls 格式
msg_tool_use = Message(role="assistant", content=[
    {"type": "tool_use", "id": "call_abc", "name": "get_weather", "input": {"city": "北京"}}
])
result = c.to_litellm([msg_tool_use])
print("=== tool_use → tool_calls ===")
print(json.dumps(result, ensure_ascii=False, indent=2))

# 2. 工具结果
msg_tool_result = c.make_tool_result_message("call_abc", '{"temp":"25C"}')
result2 = c.to_litellm([msg_tool_result])
print("\n=== tool_result ===")
print(json.dumps(result2, ensure_ascii=False, indent=2))

# 3. 完整对话流程
msgs = [
    Message(role="user", content="北京天气？"),
    msg_tool_use,
    msg_tool_result,
    Message(role="assistant", content="北京25度"),
]
result3 = c.to_litellm(msgs)
print("\n=== 完整对话 ===")
print(json.dumps(result3, ensure_ascii=False, indent=2))
