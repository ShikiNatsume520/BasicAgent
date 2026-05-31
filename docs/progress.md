# BasicAgent v1.0 开发进度

## 当前阶段：Phase 1 完成 ✅

v1.0 核心功能已全部实现，可用于实时对话游戏的 LLM 对话服务。

---

## Phase 0 — 基础层 ✅

### 1. 配置系统

**文件：** `src/models/config.py` + `config/` 目录

- `AppConfig` / `ModelConfig` / `CompressionConfig` — frozen dataclass，初始化后不可变
- `get_config()` — 全局共享配置（惰性加载，只读）
- `config/BA_Agent.json` — 模型别名映射（reasoning / flash）
- `config/provider/*.json` — 每个模型的 LiteLLM 配置
- `.env` — API Key

**当前配置：**
- reasoning → `deepseek/deepseek-v4-pro`（1M context）
- flash → `deepseek/deepseek-v4-flash`（128K context）

### 2. 数据模型与格式转换器

**文件：** `src/models/types.py`

**核心数据结构：**
- `Message` — 统一消息格式（uuid / parentUuid / role / content / type / thinking / usage / timestamp）
- `Usage` — Token 使用统计（input / output / cache_read / cache_creation）
- `ToolUseContext` — 工具执行上下文（agent_id / cwd / read_file_state）
- `QueryParams` — 查询参数包（messages / system_prompt / tools / tool_use_context / model_config）
- `ToolDefinition` — 工具定义（name / description / input_schema / is_deferred / is_mcp）
- `StreamChunk` / `ChunkType` — 流式输出

**格式转换器 `MessageConverter`（无状态）：**
- `to_provider()` / `from_provider()` — 内部格式 ↔ Provider 格式
- `to_provider_tools()` — 工具定义转换
- `from_stream_chunks()` — 流式缓冲区 → Message
- OpenAI 兼容路径（openai / deepseek / ollama 等共用）

### 3. LiteLLM 客户端

**文件：** `src/models/client.py`

- `LLMClient` — 绑定模型别名，预计算 API 调用参数
- `chat()` — 非流式调用
- `chat_stream()` — 流式调用，逐 token yield StreamChunk

---

## Phase 1 — 核心引擎 ✅

### 4. QueryEngine

**文件：** `src/engine/queryengine.py`

会话级状态持有者，两种对话模式：

**`chatMessage(user_input)` — 简易对话（推荐游戏使用）：**
- 逐 token 流式输出（`str` token + `Message`）
- 内部调用 `chat_stream()`（压缩管线 + 记忆占位 + 单次 LLM 调用）
- 无工具调用，延迟最低

**`submitMessage(user_input)` — Agent 模式：**
- 7 阶段 async generator
- 消费 `queryloop()`（ReAct 循环，支持工具调用）
- 快照传递 + 即时回写 + 即时持久化

### 5. queryloop / chat / chat_stream

**文件：** `src/engine/query.py`

**`queryloop(params)` — ReAct 循环：**
- 压缩管线 → LLM 流式调用 → 判断 stop_reason → 工具执行 → 循环
- 支持 end_turn / tool_use / max_tokens 三种终止条件
- 工具执行占位（Phase 2 实现）

**`chat_stream(params)` — 简易对话（流式版）：**
- queryloop 的简化版：保留压缩管线 + 记忆占位，去掉循环和工具调用
- 逐 token yield 文本，最后 yield 完整 Message

**`chat(params)` — 简易对话（Message 版）：**
- chat_stream 的包装，只 yield 最终 Message

### 6. TranscriptWriter

**文件：** `src/engine/transcript.py`

- JSONL 持久化（`data/sessions/{session_id}.jsonl`）
- UUID 去重（防止重复写入）
- 100ms 批量刷新（fire-and-forget + 延迟写入）
- `load()` — 从 JSONL 恢复消息（用于 resume）

### 7. SessionManager

**文件：** `src/daemon/session_manager.py`

v1.0 单进程会话管理器（纯 Python API，不绑定 HTTP 框架）：

| 方法 | 说明 |
|------|------|
| `create_session(model_alias, system_prompt)` | 创建会话，返回 session_id |
| `chat(session_id, user_message)` | 简易对话，逐 token 流式输出 |
| `send(session_id, user_message)` | Agent 模式，支持工具调用 |
| `delete(session_id)` | 删除会话 |
| `list_sessions()` | 列出所有会话 |
| `resume_session(session_id)` | 从磁盘恢复会话 |

---

## 测试覆盖

| 测试文件 | 测试项 | 数量 |
|----------|--------|------|
| `tests/test_queryloop.py` | queryloop Mock 测试（文本/工具调用/多工具/空历史） | 4 |
| `tests/test_engine.py` | QueryEngine + TranscriptWriter 测试 | 5 |
| `tests/test_phase1.py` | 全功能测试（数据结构/配置/LLM/queryloop/engine/session/resume） | 62 |
| `tests/test_chat.py` | chat/chat_stream/chatMessage/多轮对话/速度对比 | 28 |
| `tests/test_roleplay.py` | 角色扮演对话测试（6 轮 NPC 对话） | 6 轮 |

**总计：99 项测试 + 6 轮角色扮演，全部通过。**

---

## 性能数据

### chat vs queryloop（同一 prompt）

| 模式 | 耗时 | 说明 |
|------|------|------|
| chat（简易） | ~2s | 单次调用，无工具开销 |
| queryloop（完整） | ~4.5s | 含工具判断和循环逻辑 |

### 角色扮演测试（6 轮对话）

| 指标 | 数值 |
|------|------|
| 平均首 token 延迟 | 4.54s |
| 平均总耗时 | 5.90s |
| 每轮 token 数 | 32-52 |

---

## 文件结构

```
src/
├── __init__.py
├── models/                    ← Phase 0
│   ├── __init__.py
│   ├── config.py              ← 配置加载
│   ├── types.py               ← 数据模型 + MessageConverter
│   └── client.py              ← LLMClient
├── engine/                    ← Phase 1
│   ├── __init__.py
│   ├── query.py               ← queryloop + chat + chat_stream
│   ├── queryengine.py         ← QueryEngine（会话状态）
│   └── transcript.py          ← TranscriptWriter（JSONL 持久化）
└── daemon/                    ← Phase 1
    ├── __init__.py
    └── session_manager.py     ← SessionManager（会话管理）

config/
├── BA_Agent.json              ← 模型别名映射
├── compression.json           ← 压缩策略（Phase 3 实现）
└── provider/
    ├── deepseek-v4-pro.json
    └── deepseek-v4-flash.json

tests/
├── test_queryloop.py          ← queryloop 单元测试
├── test_engine.py             ← QueryEngine 集成测试
├── test_phase1.py             ← 全功能测试
├── test_chat.py               ← chat 功能测试
└── test_roleplay.py           ← 角色扮演对话测试

docs/
├── api-v1.md                  ← 上层应用开发者 API 文档
├── architecture.md            ← 架构设计文档
├── progress.md                ← 本文档
└── phase0-design.md           ← Phase 0 设计文档

examples/
├── daemon_demo.py             ← SessionManager 使用示例
├── litellm_demo.py            ← LiteLLM 直接用法演示
└── client_demo.py             ← LLMClient 封装用法演示
```

---

## 待完成（后续阶段）

| Phase | 内容 | 状态 |
|-------|------|------|
| Phase 0 | 基础层（配置/模型/客户端） | ✅ 完成 |
| Phase 1 | 核心引擎（QueryEngine/queryloop/chat/SessionManager） | ✅ 完成 |
| Phase 2 | 工具系统（ToolRegistry + 内置工具） | 待实现 |
| Phase 3 | 上下文管理 + 三层压缩 | 待实现 |
| Phase 4 | 记忆系统（用户约束 / MEMORY.md / 子Agent 检索） | 待实现 |
| Phase 5 | SessionManager 子进程隔离 | 待实现 |
| Phase 6 | MCP + SkillTool + 子Agent | 待实现 |
| Phase 7 | HTTP API（FastAPI + SSE）+ Docker | 待实现 |

---

## 关键设计决策

| 决策 | 选择 | 原因 |
|------|------|------|
| Provider 统一 | LiteLLM 归一化为 OpenAI 格式 | v1 场景无功能损失 |
| 转换器设计 | 无状态，provider 作为参数传入 | 同一 converter 可复用 |
| 配置管理 | frozen dataclass + 惰性加载 | 初始化后不可变，全局共享 |
| Message 保留 Pydantic | BaseModel 而非 dataclass | MessageConverter / LLMClient 依赖 model_dump() |
| Usage/QueryParams 用 dataclass | 非 Pydantic | 纯内部数据，不需要序列化 |
| chat vs queryloop 分离 | 两个独立函数 | 简化游戏场景的调用路径 |
| SessionManager 无 HTTP 依赖 | 纯 Python API | 上层应用自行集成 HTTP 框架 |
| 流式输出 | chat_stream 逐 token，chat 只 yield Message | 两种使用场景分离 |
