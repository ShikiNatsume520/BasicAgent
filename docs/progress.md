# BasicAgent 开发进度

## 当前阶段：v1.1 完成 ✅

v1.1 是专为 LLM 对话游戏优化的分支，实现了记忆裁剪压缩机制和提示词注入模块。

---

## v1.1 — 记忆与压缩系统 ✅

### 1. 配置层扩展

**文件：** `src/models/config.py` + `config/compression.json`

- 新增 `MemoryConfig` 数据类
  - `timeout_minutes: int = 30` — 低价值旧消息超时时间（分钟）
  - `autocompact_threshold: float = 0.8` — 触发自动压缩的 token 占比阈值
  - `compact_prompt_path: str = "config/prompts/compact.txt"` — 压缩指令提示词路径
- `CompressionConfig` 新增 `memory: MemoryConfig` 字段

**配置文件：** `config/compression.json`
```json
{
  "memory": {
    "timeout_minutes": 30,
    "autocompact_threshold": 0.8,
    "compact_prompt_path": "config/prompts/compact.txt"
  }
}
```

### 2. 压缩管线

**文件：** `src/memory/compression.py`

**`snip(messages, config)` — 消息裁剪：**
- 找到最近的 `compact_boundary` 消息（`type="compact_boundary"`）
- 裁剪该消息之前的所有消息（boundary 本身保留）
- 基于 `timeout_minutes` 裁剪 boundary 后面的超时旧消息
- 对消息快照操作，不修改原始 `mutable_messages`

**`microcompact(messages, config)` — 微压缩（占位）：**
- v1.1 不实现，直接返回原消息
- 后续版本将实现：压缩单条过长的工具结果、截断过长的代码块

**`autocompact(messages, system_prompt, config, llm_client)` — 自动压缩：**
- 估算当前 token 数（system_prompt + messages）
- 当超过阈值（`max_tokens * autocompact_threshold`）时触发压缩
- 先执行 snip 裁剪
- 加载压缩提示词，将 snip 后的消息发送给 LLM 生成摘要
- 将摘要封装成 `compact_boundary` 消息返回
- `compact_boundary` 会返回给 QueryEngine 并持久化到 JSONL 文件

### 3. 提示词注入模块

**文件：** `src/prompts/prompt.py`

**`PromptInjector` 类：**
- `load_rules(rules_path)` — 从 JSON 文件加载注入规则
- `add_rule(rule)` — 添加单条注入规则
- `set_variable(name, value)` — 设置变量值
- `set_variables(variables)` — 批量设置变量值
- `register_handler(point, handler)` — 注册自定义处理函数
- `inject(messages, point, context)` — 在指定注入点注入提示词

**注入点（`InjectionPoint` 枚举）：**
- `BEFORE_COMPACT` — 压缩前注入（插入到消息列表开头）
- `AFTER_COMPACT` — 压缩后注入（插入到消息列表末尾）
- `ON_SCENE_CHANGE` — 场景切换时注入
- `ON_USER_INPUT` — 用户输入时注入（插入到最后一条用户消息之前）
- `ON_ASSISTANT_RESPONSE` — 助手回复前注入

**变量替换：**
- 支持 `{variable_name}` 格式的变量替换
- 优先级：规则变量 > 实例变量 > 上下文变量

### 4. QueryEngine 集成

**文件：** `src/engine/queryengine.py`

- `chatMessage()` 和 `submitMessage()` 方法集成压缩管线
- 处理 `compact_boundary` 消息的持久化
- 压缩发生时给调用方提示信息

**压缩管线流程：**
1. `snip` — 裁剪 boundary 之前的消息 + 超时旧消息
2. `microcompact` — 占位，直接透传
3. `autocompact` — 当 token 超过阈值时自动触发压缩

### 5. 压缩提示词

**文件：** `config/prompts/compact.txt`

专为角色扮演场景设计的压缩提示词：
- 保持角色语气、说话风格和性格特征
- 保留重要事实、约定、承诺
- 记录角色情感状态和关系变化
- 保持时间线清晰

---

## v1.0 — 核心功能 ✅

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

### v1.1 测试

| 测试文件 | 测试项 | 数量 |
|----------|--------|------|
| `tests/test_compression.py` | snip 裁剪/timeout 裁剪/autocompact 触发/compact_boundary 生成 | 17 |
| `tests/test_prompt_injection.py` | 基本注入/多规则/变量替换/注入点/自定义处理/规则加载 | 20 |

**v1.1 小计：37 项测试，全部通过。**

### v1.0 测试

| 测试文件 | 测试项 | 数量 |
|----------|--------|------|
| `tests/test_queryloop.py` | queryloop Mock 测试（文本/工具调用/多工具/空历史） | 4 |
| `tests/test_engine.py` | QueryEngine + TranscriptWriter 测试 | 5 |
| `tests/test_phase1.py` | 全功能测试（数据结构/配置/LLM/queryloop/engine/session/resume） | 62 |
| `tests/test_chat.py` | chat/chat_stream/chatMessage/多轮对话/速度对比 | 28 |
| `tests/test_roleplay.py` | 角色扮演对话测试（6 轮 NPC 对话） | 6 轮 |

**v1.0 小计：99 项测试 + 6 轮角色扮演，全部通过。**

**总计：136 项测试 + 6 轮角色扮演，全部通过。**

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
│   ├── config.py              ← 配置加载（含 MemoryConfig）
│   ├── types.py               ← 数据模型 + MessageConverter
│   └── client.py              ← LLMClient
├── engine/                    ← Phase 1
│   ├── __init__.py
│   ├── query.py               ← queryloop + chat + chat_stream（集成压缩管线）
│   ├── queryengine.py         ← QueryEngine（会话状态 + compact_boundary 处理）
│   └── transcript.py          ← TranscriptWriter（JSONL 持久化）
├── memory/                    ← v1.1 新增
│   ├── __init__.py
│   └── compression.py         ← 压缩管线（snip + microcompact + autocompact）
├── prompts/                   ← v1.1 新增
│   ├── __init__.py
│   └── prompt.py              ← 提示词注入模块（PromptInjector）
└── daemon/                    ← Phase 1
    ├── __init__.py
    └── session_manager.py     ← SessionManager（会话管理）

config/
├── BA_Agent.json              ← 模型别名映射
├── compression.json           ← 压缩策略 + 记忆配置
├── prompts/                   ← v1.1 新增
│   └── compact.txt            ← 压缩提示词
└── provider/
    ├── deepseek-v4-pro.json
    └── deepseek-v4-flash.json

tests/
├── test_queryloop.py          ← queryloop 单元测试
├── test_engine.py             ← QueryEngine 集成测试
├── test_phase1.py             ← 全功能测试
├── test_chat.py               ← chat 功能测试
├── test_roleplay.py           ← 角色扮演对话测试
├── test_compression.py        ← v1.1 压缩管线测试
└── test_prompt_injection.py   ← v1.1 提示词注入测试

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

### v1.1 后续（继续优化对话游戏分支）

| Phase | 内容 | 状态 |
|-------|------|------|
| v1.1-Phase 1 | snip 裁剪 + timeout 裁剪 | ✅ 完成 |
| v1.1-Phase 2 | microcompact 微压缩 | 占位（v1.1 不实现） |
| v1.1-Phase 3 | autocompact 自动压缩 | ✅ 完成 |
| v1.1-Phase 4 | 提示词注入模块 | ✅ 完成 |
| v1.1-Phase 5 | QueryEngine 集成 | ✅ 完成 |

### v2.0 后续（在 v1.0 基础上继续开发）

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

### v1.1 设计决策

| 决策 | 选择 | 原因 |
|------|------|------|
| snip 操作只修改快照 | 不修改 `mutable_messages` | 保证历史数据不丢失，支持 resume |
| compact_boundary 持久化 | 返回给 QueryEngine 并记录到 JSONL | 下次 snip 可以找到最近的 boundary |
| autocompact 异步执行 | 需要调用 LLM API | 压缩是耗时操作，使用 async/await |
| 提示词注入可扩展 | 通过配置文件定义注入规则 | 支持动态调整注入行为 |
| 压缩管线位置 | `src/memory/compression.py` | 独立模块，便于后续扩展 |
| 提示词注入位置 | `src/prompts/prompt.py` | 独立模块，便于后续扩展 |

### v1.0 设计决策

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
