"""基础验证：导入 + 配置加载 + 转换器"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models import (
    Message, ToolDefinition, StreamChunk, ChunkType,
    MessageConverter, load_config, LLMClient,
)

# 1. 配置加载
config = load_config()
print("Config loaded:")
for alias, mc in config.models.items():
    print(f"  {alias}: {mc.litellm_model} (api_key={'***' if mc.api_key else 'None'})")

# 2. LLMClient 初始化
client = LLMClient("reasoning", config)
print(f"\nLLMClient._base_kwargs: {client._base_kwargs}")

# 3. 消息转换
converter = MessageConverter()
msgs = [Message(role="user", content="hello")]
litellm_msgs = converter.to_litellm(msgs)
print(f"\nto_litellm: {litellm_msgs}")

# 4. 反向转换
raw = {"role": "assistant", "content": "hi there", "tool_calls": None}
msg = converter.from_litellm(raw)
print(f"from_litellm: role={msg.role}, content={msg.content}")

# 5. 工具调用反向转换
raw_tc = {
    "role": "assistant",
    "content": None,
    "tool_calls": [
        {
            "id": "call_123",
            "type": "function",
            "function": {
                "name": "get_weather",
                "arguments": '{"city":"北京"}'
            }
        }
    ]
}
msg_tc = converter.from_litellm(raw_tc)
print(f"from_litellm (tool_call): role={msg_tc.role}, content={msg_tc.content}")

print("\nAll checks passed!")
