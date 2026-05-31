# 消息格式对照说明

## 1. LiteLLM (OpenAI) 格式

LiteLLM 统一使用 OpenAI 的消息格式。以下是各种消息类型的精确 JSON 结构。

### 1.1 系统消息

```json
{"role": "system", "content": "你是一个助手"}
```

### 1.2 用户消息（纯文本）

```json
{"role": "user", "content": "北京天气怎么样？"}
```

### 1.3 Assistant 消息（纯文本）

```json
{"role": "assistant", "content": "北京今天晴天，25°C"}
```

### 1.4 Assistant 消息（发起工具调用）

**关键：tool_calls 是 assistant 消息的顶层字段，不是 content 的一部分。**

```json
{
  "role": "assistant",
  "content": null,
  "tool_calls": [
    {
      "id": "call_abc123",
      "type": "function",
      "function": {
        "name": "get_weather",
        "arguments": "{\"city\":\"北京\"}"
      }
    }
  ]
}
```

- `content` 可以是 `null` 或一段文本（LLM 先说话再调工具时）
- `tool_calls` 是数组，支持一次返回多个工具调用
- `arguments` 是 JSON 字符串（不是对象）
- `type` 固定为 `"function"`

### 1.5 工具结果消息

**关键：role 是 "tool"，不是 "user"。tool_call_id 必须对应上面的 id。**

```json
{
  "role": "tool",
  "tool_call_id": "call_abc123",
  "content": "{\"city\":\"北京\",\"weather\":\"晴\",\"temp\":\"25°C\"}"
}
```

- 每个 tool_call 对应一条独立的 tool 消息（不是合并在一条里）
- `content` 是字符串（通常是 JSON 字符串化的结果）

### 1.6 完整的工具调用对话示例

```json
[
  {"role": "user", "content": "北京天气怎么样？"},

  {"role": "assistant", "content": null, "tool_calls": [
    {"id": "call_abc", "type": "function", "function": {"name": "get_weather", "arguments": "{\"city\":\"北京\"}"}}
  ]},

  {"role": "tool", "tool_call_id": "call_abc", "content": "{\"weather\":\"晴\",\"temp\":\"25C\"}"},

  {"role": "assistant", "content": "北京今天天气晴朗，气温25°C。"}
]
```

---

## 2. 我们的内部格式

### 2.1 Message 数据模型

```python
class Message(BaseModel):
    uuid: str                          # 唯一标识符, 用于去重
    role: str                          # "system" | "user" | "assistant" | "tool"
    content: str | list[dict]          # 纯文本 或 ContentBlock 列表
    tool_call_id: str | None = None    # 仅 role="tool" 时使用
```

### 2.2 ContentBlock 类型

```python
# 纯文本
{"type": "text", "text": "..."}

# 工具调用（仅 assistant 消息）
{"type": "tool_use", "id": "call_xxx", "name": "get_weather", "input": {"city": "北京"}}

# 工具结果（不用，见下文说明）
{"type": "tool_result", "tool_use_id": "call_xxx", "content": "..."}
```

### 2.3 各角色的消息示例

```python
# 系统消息
Message(role="system", content="你是一个助手")

# 用户消息
Message(role="user", content="北京天气怎么样？")

# Assistant 纯文本
Message(role="assistant", content="今天晴天")

# Assistant 工具调用（tool_use 放在 content 列表中）
Message(role="assistant", content=[
    {"type": "tool_use", "id": "call_abc", "name": "get_weather", "input": {"city": "北京"}}
])

# 工具结果
Message(role="tool", content='{"weather":"晴"}', tool_call_id="call_abc")
```

---

## 3. 转换对照表

### 3.1 内部 → LiteLLM（to_litellm）

| 内部格式 | LiteLLM 格式 |
|---------|-------------|
| `Message(role="system", content="...")` | `{"role": "system", "content": "..."}` |
| `Message(role="user", content="...")` | `{"role": "user", "content": "..."}` |
| `Message(role="assistant", content="文本")` | `{"role": "assistant", "content": "文本"}` |
| `Message(role="assistant", content=[{type:"tool_use",...}])` | `{"role": "assistant", "content": null, "tool_calls": [{id, type:"function", function:{name, arguments}}]}` |
| `Message(role="tool", content="...", tool_call_id="call_xxx")` | `{"role": "tool", "tool_call_id": "call_xxx", "content": "..."}` |

### 3.2 LiteLLM → 内部（from_litellm）

| LiteLLM 格式 | 内部格式 |
|-------------|---------|
| `{"role": "assistant", "content": "文本"}` | `Message(role="assistant", content="文本")` |
| `{"role": "assistant", "tool_calls": [...]}` | `Message(role="assistant", content=[{type:"tool_use",...}])` |

---

## 4. 关键差异总结

| 差异点 | 我们的内部格式 | LiteLLM (OpenAI) 格式 |
|--------|-------------|---------------------|
| Assistant 工具调用 | `content` 列表中放 `tool_use` 块 | 顶层 `tool_calls` 数组，`content` 为 null |
| 工具结果 | `role="tool"`, `tool_call_id` 字段 | 同左（一致） |
| `tool_use.input` | dict 对象 | `function.arguments` 是 JSON 字符串 |
| `tool_use.id` | 在 content 块中 | 在 `tool_calls[].id` 中 |

转换器 (`MessageConverter.to_litellm`) 已处理上述差异，自动完成格式转换。

---

## 5. 消息顺序规则

### 5.1 OpenAI 官方规范

OpenAI 文档要求消息按 `system → user → assistant → user → assistant → ...` 交替出现。
tool 消息放在发起调用的 assistant 消息之后。

### 5.2 实测结果（DeepSeek）

| 场景 | DeepSeek 结果 | 说明 |
|------|-------------|------|
| 连续 user 消息 | ✅ 允许 | 合并处理 |
| 连续 assistant 消息 | ✅ 允许 | 合并处理 |
| tool 后直接跟 user | ✅ 允许 | 跳过 assistant |
| 正常交替 | ✅ 允许 | 标准格式 |

DeepSeek 的 API 比 OpenAI 更宽松，不强制严格交替。

### 5.3 我们的策略

**内部保持规范的交替格式**，不依赖 provider 的宽松行为，确保跨 provider 兼容性。

规范格式：
```
[system]  （可选，仅第一条）
[user]
[assistant] （可能包含 tool_calls）
[tool]      （如果有工具调用，每个 tool_call 对应一条）
[assistant] （工具调用后的回复，或纯文本回复）
[user]
[assistant]
...
```

规则：
1. system 消息只能在最前面（如果有）
2. tool 消息必须紧跟在包含 tool_calls 的 assistant 消息之后
3. tool 消息结束后，下一条应该是 assistant（LLM 基于工具结果生成回复）
4. 不出现连续同角色消息（除非是多条 tool 消息对应多个 tool_call）

### 5.4 工具调用的完整消息序列

```
user        → "北京天气？"
assistant   → tool_calls: [get_weather(city="北京")]
tool        → tool_call_id=call_1, content='{"temp":"25C"}'
assistant   → "北京今天25度"
user        → "谢谢"
assistant   → "不客气！"
```

**注意**：一个 assistant 消息可以包含多个 tool_calls，每个对应一条 tool 消息：
```
assistant   → tool_calls: [get_weather(city="北京"), get_weather(city="上海")]
tool        → tool_call_id=call_1, content='{"temp":"25C"}'
tool        → tool_call_id=call_2, content='{"temp":"28C"}'
assistant   → "北京25度，上海28度"
```
