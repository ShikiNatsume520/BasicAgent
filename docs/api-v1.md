# BasicAgent v1.0 — 上层应用开发者指南

> 面向：将 BasicAgent 集成到自己应用中的开发者（如 Unity 游戏后端、Web 服务等）

---

## 一、快速开始

### 1.1 安装

```bash
# 方式 1：开发模式（推荐开发阶段）
cd BasicAgent
pip install -e ".[dev]"

# 方式 2：直接安装
pip install /path/to/BasicAgent
```

### 1.2 配置

在项目根目录创建 `.env` 文件，填入 API Key：

```env
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
# OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
```

模型配置在 `config/` 目录下，已预置 DeepSeek 模型。如需添加新模型，参考 `config/provider/` 下的 JSON 文件。

### 1.3 最简示例

```python
import asyncio
from basic_agent.daemon import SessionManager

async def main():
    manager = SessionManager()

    # 创建会话
    session_id = await manager.create_session(
        model_alias="reasoning",
        system_prompt="你是一个友好的游戏NPC。",
    )

    # 发送消息，逐 token 接收
    async for chunk in manager.chat(session_id, "你好"):
        if isinstance(chunk, str):
            print(chunk, end="", flush=True)
        else:
            print()  # 完成

asyncio.run(main())
```

---

## 二、核心 API

### 2.1 SessionManager

会话管理器，是你与 BasicAgent 交互的唯一入口。

```python
from basic_agent.daemon import SessionManager

manager = SessionManager()
```

#### `create_session` — 创建会话

```python
async def create_session(
    model_alias: str = "reasoning",      # 模型别名，对应 config/BA_Agent.json
    system_prompt: str = "You are a helpful assistant.",  # 系统提示
    cwd: str = ".",                      # 工作目录
) -> str:                                # 返回 session_id
```

#### `chat` — 简易对话（推荐用于实时游戏）

逐 token 流式输出，单次 LLM 调用，无工具调用，延迟最低。

```python
async def chat(
    session_id: str,
    user_message: str,
) -> AsyncGenerator[str | Message, None]:
```

**Yields：**
- `str` — 文本 token（逐个，用于实时推送给客户端）
- `Message` — 最终完整消息（最后一条，用于持久化/记录）
- `Message(type="result")` — 结束标记

```python
async for chunk in manager.chat(session_id, "你好"):
    if isinstance(chunk, str):
        # 逐 token：推送给 Unity / WebSocket / SSE
        send_to_client(chunk)
    elif chunk.type == "result":
        # 结束：可以记录日志
        log(f"对话完成")
    else:
        # 完整 Message：存入数据库
        save_to_db(chunk)
```

#### `send` — Agent 模式（支持工具调用）

完整的 ReAct 循环，支持工具调用。适用于需要文件操作、代码执行等能力的场景。

```python
async def send(
    session_id: str,
    user_message: str,
) -> AsyncGenerator[Message, None]:
```

**Yields：** `Message` 对象（包括 assistant 回复、工具调用结果等）

```python
async for msg in manager.send(session_id, "帮我读取 config.json"):
    if msg.role == "assistant":
        print(msg.content)
    elif msg.role == "tool":
        print(f"[工具结果] {msg.content}")
```

#### `delete` — 删除会话

```python
async def delete(session_id: str)
```

#### `list_sessions` — 列出所有会话

```python
async def list_sessions() -> list[str]  # 返回 session_id 列表
```

#### `resume_session` — 从磁盘恢复会话

```python
async def resume_session(session_id: str) -> bool  # 是否恢复成功
```

---

### 2.2 Message

所有交互的数据载体。上层应用主要关心以下字段：

```python
class Message:
    uuid: str                    # 唯一标识
    role: str                    # "user" | "assistant" | "tool"
    content: str | list[dict]    # 文本内容 或 工具调用列表
    type: str                    # "message" | "result"
    thinking: str | None         # 模型思考过程（部分模型支持）
    timestamp: float             # 创建时间戳
```

**字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `uuid` | `str` | 消息唯一 ID，可用于去重 |
| `role` | `str` | `"user"` 用户消息 / `"assistant"` AI 回复 / `"tool"` 工具结果 |
| `content` | `str \| list` | 纯文本回复为 `str`；工具调用为 `list[dict]` |
| `type` | `str` | `"message"` 正常消息 / `"result"` 对话结束标记 |
| `thinking` | `str \| None` | 模型的思考过程（DeepSeek 等支持），通常不需要展示给用户 |
| `timestamp` | `float` | Unix 时间戳 |

**判断对话是否结束：**
```python
if msg.type == "result":
    # 对话结束
```

**判断是否是工具调用：**
```python
if msg.role == "assistant" and isinstance(msg.content, list):
    for block in msg.content:
        if block.get("type") == "tool_use":
            tool_name = block["name"]
            tool_input = block["input"]
```

---

### 2.3 配置

#### 模型别名 (`config/BA_Agent.json`)

```json
{
    "reasoning": "deepseek-v4-pro",
    "flash": "deepseek-v4-flash",
    "multi": null
}
```

`create_session(model_alias="reasoning")` 中的 `model_alias` 对应这里的 key。

#### 模型配置 (`config/provider/*.json`)

每个模型一个文件，包含 LiteLLM 路由信息：

```json
{
    "litellm_model": "deepseek/deepseek-v4-pro",
    "api_base": null,
    "max_tokens": 100000,
    "api_key_env": "DEEPSEEK_API_KEY"
}
```

#### 环境变量 (`.env`)

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key |
| `OPENAI_API_KEY` | OpenAI API Key（如使用 OpenAI 模型） |

---

## 三、集成示例

### 3.1 Unity 游戏后端（FastAPI + SSE）

```python
from fastapi import FastAPI
from sse_starlette.sse import EventSourceResponse
from basic_agent.daemon import SessionManager

app = FastAPI()
manager = SessionManager()

@app.post("/sessions")
async def create(system_prompt: str = "你是一个游戏NPC。"):
    sid = await manager.create_session(model_alias="reasoning", system_prompt=system_prompt)
    return {"session_id": sid}

@app.post("/sessions/{sid}/chat")
async def chat(sid: str, body: dict):
    content = body.get("content", "")

    async def stream():
        async for chunk in manager.chat(sid, content):
            if isinstance(chunk, str):
                yield {"event": "token", "data": chunk}
            elif chunk.type == "result":
                yield {"event": "done", "data": "[DONE]"}

    return EventSourceResponse(stream())

@app.delete("/sessions/{sid}")
async def delete(sid: str):
    await manager.delete(sid)
    return {"status": "ok"}
```

### 3.2 WebSocket 实时对话

```python
import asyncio
import websockets
from basic_agent.daemon import SessionManager

manager = SessionManager()

async def handler(websocket):
    sid = await manager.create_session(
        model_alias="reasoning",
        system_prompt="你是一个游戏商人。",
    )

    async for message in websocket:
        async for chunk in manager.chat(sid, message):
            if isinstance(chunk, str):
                await websocket.send(chunk)       # 逐 token 推送
            elif chunk.type == "result":
                await websocket.send("[END]")     # 结束标记

asyncio.run(websockets.serve(handler, "localhost", 8765))
```

### 3.3 命令行对话

```python
import asyncio
from basic_agent.daemon import SessionManager

async def main():
    manager = SessionManager()
    sid = await manager.create_session(
        model_alias="reasoning",
        system_prompt="你是一个友好的助手。",
    )

    print("输入 'quit' 退出\n")
    while True:
        user_input = input("You: ")
        if user_input.lower() == "quit":
            break

        print("AI: ", end="", flush=True)
        async for chunk in manager.chat(sid, user_input):
            if isinstance(chunk, str):
                print(chunk, end="", flush=True)
            elif chunk.type == "result":
                print("\n")

    await manager.delete(sid)

asyncio.run(main())
```

---

## 四、chat vs send 选型

| 特性 | `chat()` | `send()` |
|------|----------|----------|
| 适用场景 | 实时对话游戏、简单问答 | Agent、需要工具调用 |
| 工具调用 | 不支持 | 支持 |
| 循环 | 无（单次调用） | ReAct 多轮循环 |
| 输出粒度 | 逐 token (`str`) | 逐条 `Message` |
| 延迟 | 最低 | 较高（含工具执行） |
| 推荐用途 | **游戏对话**、聊天机器人 | 代码助手、文件操作 |

**建议：** 游戏项目使用 `chat()`，需要工具能力时再切换到 `send()`。

---

## 五、数据持久化

### 会话消息历史

自动持久化到 `data/sessions/{session_id}.jsonl`（JSONL 格式，每条消息一行）。

### 恢复会话

```python
# 创建 SessionManager 后，通过 session_id 恢复
sid = "之前的 session_id"
await manager.create_session(...)  # 先创建
await manager.resume_session(sid)  # 从磁盘恢复消息历史
```

### 消息格式（JSONL 每行）

```json
{"uuid":"abc-123","parentUuid":null,"role":"user","content":"你好","type":"message","timestamp":1717000000.0}
{"uuid":"def-456","parentUuid":"abc-123","role":"assistant","content":"你好！有什么我能帮忙的？","type":"message","timestamp":1717000001.0}
```

---

## 六、模块结构

```
basic_agent/
├── daemon/
│   └── session_manager.py    ← SessionManager（唯一入口）
├── engine/
│   ├── query.py              ← chat() + queryloop()
│   ├── queryengine.py        ← QueryEngine（会话状态）
│   └── transcript.py         ← TranscriptWriter（JSONL 持久化）
├── models/
│   ├── types.py              ← Message, Usage, QueryParams 等
│   ├── config.py             ← 配置加载
│   └── client.py             ← LLMClient（LiteLLM 封装）
└── config/
    ├── BA_Agent.json          ← 模型别名映射
    ├── compression.json       ← 压缩策略（Phase 3）
    └── provider/              ← 每个模型的配置
```

**上层应用只需关心：** `SessionManager` + `Message` + 配置文件。
