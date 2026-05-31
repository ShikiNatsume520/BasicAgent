# BasicAgent 核心架构说明

> 基于 Claude Code v2.1.88 源码分析，结合 BA 框架的实际需求，定义核心数据流与模块职责。
> 本文档是实现 `engine/queryloop.py` 和 `engine/queryengine.py` 的设计依据。

---

## 一、内部数据结构

### 1.1 Message — 消息

框架内部统一的消息格式。所有模块之间通过 Message 传递数据，不做格式转换。格式转换仅发生在与外部 LLM API 交互的边界（`client.py`）。

```python
@dataclass
class Message:
    uuid: str                          # 唯一标识，用于去重和链表构建
    parentUuid: Optional[str]          # 父消息 UUID，构成隐式链表
    role: str                          # "system" | "user" | "assistant" | "tool"
    content: str | list[dict]          # 纯文本 或 ContentBlock 列表
    type: str = "message"              # "message" | "compact_boundary" | "tool_result" | "system_init" | "result"
    thinking: str | None = None        # 模型思考过程（DeepSeek reasoning / Claude thinking）
    tool_call_id: str | None = None    # 仅 role="tool" 时使用
    usage: Usage | None = None         # 仅 assistant 消息时携带
    timestamp: float = 0.0            # 创建时间戳
```

**ContentBlock 类型：**
```python
# 纯文本
{"type": "text", "text": "..."}

# 工具调用（仅 assistant 消息 content 列表中）
{"type": "tool_use", "id": "call_xxx", "name": "get_weather", "input": {"city": "北京"}}

# 工具结果 — 不在 content 中使用，而是 role="tool" + tool_call_id（见下文）
```

**各角色消息示例：**
```python
# 系统消息
Message(uuid="...", parentUuid=None, role="system", content="你是一个助手")

# 用户消息
Message(uuid="...", parentUuid="...", role="user", content="北京天气怎么样？")

# Assistant 纯文本
Message(uuid="...", parentUuid="...", role="assistant", content="今天晴天")

# Assistant 工具调用
Message(uuid="...", parentUuid="...", role="assistant", content=[
    {"type": "tool_use", "id": "call_abc", "name": "get_weather", "input": {"city": "北京"}}
])

# 工具结果（OpenAI 兼容格式：role="tool" + tool_call_id）
Message(uuid="...", parentUuid="...", role="tool", content='{"weather":"晴"}', tool_call_id="call_abc")

# compact_boundary（压缩边界标记，由 queryloop 内部生成）
Message(uuid="...", parentUuid=None, role="assistant", content="[compact]", type="compact_boundary")
```

**关键不变量：**
- `parentUuid` 构成隐式链表，从任意消息沿 parentUuid 回溯可达根消息
- 压缩操作必须维护 tool_use 与 tool_result 的配对关系
- `type="compact_boundary"` 的消息 parentUuid = None，表示链的截断点

### 1.2 Usage — Token 使用统计

```python
@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    def __iadd__(self, other: Usage) -> Usage:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_creation_tokens += other.cache_creation_tokens
        return self
```

每次 LLM API 调用返回的 Usage 累加到 QueryEngine 的 `total_usage`，用于监控和压缩触发判断。

### 1.3 ToolUseContext — 工具执行上下文

每个 Agent（主 Agent 或子 Agent）私有的执行环境信息。它本质上是把状态中的部分信息重新聚合在一起（只引用，不拷贝）。

```python
@dataclass
class ToolUseContext:
    agent_id: str                      # 从属的 Agent ID
    cwd: str                           # 当前工作目录
    read_file_state: dict[str, Any]    # 已读取的文件状态缓存
    permission_denials: int = 0        # 权限拒绝次数
    total_usage: Usage                 # 该 Agent 的累计 token 消耗
```

每次 `submitMessage()` 调用时创建新的 ToolUseContext，传递给 queryloop。

### 1.4 QueryParams — 查询参数包

QueryEngine.submitMessage() 在调用 queryloop 前，将离散的上下文组装为 QueryParams。queryloop 接收 QueryParams 作为唯一的输入参数。

```python
@dataclass
class QueryParams:
    messages: list[Message]            # 压缩后的完整上下文（快照）
    system_prompt: str                 # 系统提示
    tools: list[ToolDefinition]        # 当前会话启用的工具定义
    tool_use_context: ToolUseContext   # 工具执行上下文
    model_config: ModelConfig          # 模型配置（litellm_model, api_base, max_tokens 等）
    max_tool_rounds: int = 20          # 最大工具调用轮次
```

### 1.5 ToolDefinition — 工具定义

```python
@dataclass
class ToolDefinition:
    name: str
    description: str
    input_schema: dict                 # JSON Schema
    is_deferred: bool = True           # 是否延迟加载（MCP 工具默认延迟）
    is_mcp: bool = False               # 是否 MCP 工具
```

### 1.6 辅助函数

```python
def new_uuid() -> str:
    """生成新的 UUID"""
    return str(uuid.uuid4())
```

---

## 二、QueryEngine — 会话级状态持有者

### 2.1 定位

一个 QueryEngine 实例 = 一个会话 = 一个子进程。

QueryEngine 是会话的"大脑"，持有该会话的全部状态，驱动消息的生命周期。

### 2.2 核心状态

```python
class QueryEngine:
    # ===== 会话标识 =====
    session_id: str                    # 会话唯一标识
    conversation_id: str               # 对话唯一标识（/clear 时重新生成）

    # ===== 核心状态 =====
    mutable_messages: list[Message]    # 持久消息存储（内存中，可被压缩修改）
    total_usage: Usage                 # 累计 token 消耗

    # ===== 外部依赖 =====
    llm_client: LLMClient             # LiteLLM 客户端（绑定模型别名）
    converter: MessageConverter        # 格式转换器（无状态）
    transcript: TranscriptWriter       # JSONL 持久化写入器
    tool_registry: ToolRegistry        # 工具注册表（Phase 2 实现）
    compressor: Compressor             # 压缩器（Phase 3 实现）
```

### 2.3 submitMessage — 核心异步生成器

```python
async def submitMessage(self, user_input: str) -> AsyncGenerator[Message, None]:
```

这是 QueryEngine 唯一的核心方法。它是一个 **async generator**，逐步 yield 消息给调用方（SessionManager → HTTP SSE → Unity）。

**7 阶段结构：**

```
阶段 1：初始化配置
    │  读取 system_prompt、model_config
    ▼
阶段 2：构建 ToolUseContext
    │  每次 submitMessage 创建新的上下文
    ▼
阶段 3：处理用户输入
    │  创建 user_message → append 到 mutable_messages → 写入 transcript
    ▼
阶段 4：yield 状态消息
    │  yield system_init 消息（可选，UI 显示"思考中"）
    ▼
阶段 5：核心循环 — 消费 queryloop
    │  snapshot = list(mutable_messages)        ← 快照
    │  async for msg in queryloop(params):      ← 消费生成器
    │      mutable_messages.append(msg)         ← 回写
    │      record_transcript([msg])             ← 持久化
    │      total_usage += msg.usage             ← 累加
    │      yield msg                            ← 给调用方
    ▼
阶段 6：后处理
    │  处理 compact_boundary → 截断 mutable_messages
    │  处理 snip → 移除标记的消息
    ▼
阶段 7：yield 最终结果
       yield result 消息
```

**关键设计：**
- **快照传递**：`snapshot = list(mutable_messages)` 传给 queryloop，queryloop 在独立副本上演化
- **即时回写**：queryloop 每 yield 一条消息，立即 append 到 mutable_messages
- **即时持久化**：每条消息 append 后立即写入 transcript
- **即时传递**：每条消息 yield 给调用方，实现流式输出
- **后处理**：queryloop 结束后，处理 compact_boundary 截断和 snip 移除

---

## 三、queryLoop — Agent 执行循环

### 3.1 定位

queryLoop 是一个 **无状态的 async generator 函数**（不是类的方法），由 QueryEngine 调用。

它接收 QueryParams（上下文快照），在内部独立演化，只 yield 新产生的消息。

### 3.2 内部状态

```python
@dataclass
class State:
    """queryLoop 每次迭代的局部状态，不与外部共享"""
    messages: list[Message]                    # 本次迭代的消息列表（快照演化）
    tool_use_context: ToolUseContext
    max_output_tokens_recovery_count: int = 0  # max_tokens 恢复尝试次数
```

### 3.3 函数签名

```python
async def queryloop(params: QueryParams) -> AsyncGenerator[Message, None]:
```

### 3.4 循环逻辑

```
state.messages = list(params.messages)  ← 深拷贝，独立演化

while True:
    │
    ├── 步骤 1：压缩管线
    │   messages_for_query = get_messages_after_compact_boundary(state.messages)
    │   messages_for_query = apply_tool_result_budget(messages_for_query)
    │   messages_for_query = snip_compact(messages_for_query)
    │   messages_for_query = microcompact(messages_for_query)
    │   messages_for_query = autocompact(messages_for_query)
    │
    ├── 步骤 2：调用 LLM API（流式）
    │   收集 assistant_content、usage、stop_reason
    │
    ├── 步骤 3：构建 assistant_message
    │   state.messages.append(assistant_message)
    │   yield assistant_message  ← 【只 yield 新消息】
    │
    ├── 步骤 4：判断 stop_reason
    │   │
    │   ├── end_turn → return（生成器结束）
    │   │
    │   ├── tool_use →
    │   │   for tool_use in extract_tool_uses(assistant_content):
    │   │       tool_result = await execute_tool(tool_use, ctx)
    │   │       tool_result_msg = Message(role="tool", content=result, tool_call_id=id)
    │   │       state.messages.append(tool_result_msg)
    │   │       yield tool_result_msg  ← 【只 yield 新消息】
    │   │   continue  ← 下一轮迭代（重新调用 API）
    │   │
    │   ├── max_tokens →
    │   │   if recovery_count < 3:
    │   │       注入 "[继续提示]" → continue
    │   │   else:
    │   │       return（强制结束）
    │   │
    │   └── 其他 → return
```

### 3.5 关键行为

| 行为 | 说明 |
|------|------|
| **无状态** | 不维护 messages 历史，不修改外部状态，只负责"产生"消息 |
| **只 yield 新消息** | 不 yield 传入的历史消息，只 yield 本轮新产生的 assistant/tool_result |
| **压缩管线在循环内** | 每次迭代开始前都运行压缩管线（因为工具执行可能大幅增加 context） |
| **流式 LLM 调用** | 内部使用 streaming 拼接 tool_call，但对外 yield 的是完整的 assistant 消息 |
| **并行工具执行** | 多个 tool_use 在同一轮响应中时，可并行执行 |
| **max_tokens 恢复** | 输出被截断时，注入继续提示，最多重试 3 次 |
| **compact_boundary** | 压缩器可以 yield compact_boundary 消息，queryloop 会正确处理并传递 |

### 3.6 与 Claude Code 源码的对应关系

| Claude Code (TypeScript) | BA (Python) |
|--------------------------|-------------|
| `QueryEngine.mutableMessages` | `engine.mutable_messages` |
| `State.messages` (queryLoop 内部) | `state.messages` |
| `const snapshot = [...this.mutableMessages]` | `snapshot = list(engine.mutable_messages)` |
| `async function* queryLoop()` | `async def queryloop()` |
| `for await (const msg of queryLoop(...))` | `async for msg in queryloop(...)` |
| `stopReason === 'end_turn'` | `stop_reason == "end_turn"` |
| `stopReason === 'tool_use'` | `stop_reason == "tool_use"` |
| `compact_boundary` type | `type="compact_boundary"` |
| `parentUuid` chain | `parentUuid` chain |

---

## 四、Transcript 持久化

### 4.1 JSONL 文件格式

每条消息一行 JSON：
```json
{"uuid": "...", "parentUuid": "...", "role": "user", "content": "...", "type": "message", "timestamp": 1234567890.0}
```

文件路径：`data/sessions/{session_id}.jsonl`

### 4.2 TranscriptWriter

```python
class TranscriptWriter:
    path: Path                         # JSONL 文件路径
    message_set: set[str]              # 已写入的 UUID 集合（去重）
    write_queue: list[Message]         # 写入缓冲队列
```

**写入策略：**
- UUID 去重：跳过已写入的消息（防止重复 append）
- 100ms 批量刷新：fire-and-forget + 延迟批量写入（减少磁盘 I/O 次数）

### 4.3 resume — 从 transcript 恢复会话

```python
async def load_conversation_for_resume(session_id: str) -> list[Message]:
```

**恢复流程：**
1. 读取 JSONL → `Map<uuid, Message>`
2. 找出所有叶子节点（即没有parentUuid指向的节点），然后按照timestamp排序，找到最新的叶子节点
3. 根据最新的叶子节点，进行逆向重建消息链。compact_boundary 消息的parentUuid 为空.所以很自然的成为根节点。
4. 应用 preservedSegment 重链接（孤儿消息重链接到 boundary）
5. 处理 snip：移除被 snip 的消息，子消息重链接到祖先
6. 从叶节点沿 parentUuid 回溯，重建消息链

### 4.4 /clear — 新建会话

```python
async def clear_conversation(engine: QueryEngine):
```

**行为：**
1. 旧 JSONL 文件保留在磁盘上（不删除，resume 可用）
2. 生成新的 session_id
3. 新的 transcript_path 指向新文件
4. mutable_messages 清空
5. conversation_id 重新生成

---

## 五、进程模型与通信

### 5.1 进程结构

```
Daemon 进程 (SessionManager)
    │
    ├── fork → 子进程 A (QueryEngine, session_id=aaa)
    ├── fork → 子进程 B (QueryEngine, session_id=bbb)
    └── fork → 子进程 C (QueryEngine, session_id=ccc)
```

### 5.2 进程间通信

Daemon 与子进程之间通过 pipe 通信：

```
Daemon                        子进程 (QueryEngine)
  │                                │
  │── send(session_id, msg) ──────→│ submitMessage(msg)
  │                                │   for await chunk in queryloop():
  │←── StreamChunk (text) ─────────│     yield chunk
  │←── StreamChunk (tool_use) ─────│
  │←── StreamChunk (text) ─────────│
  │←── StreamChunk (done) ─────────│
```

### 5.3 v1.0 简化：单进程模式

v1.0 阶段，为降低复杂度，**不实现真正的子进程 fork**。SessionManager 和 QueryEngine 在同一进程内运行，通过 asyncio Task 隔离：

```python
# v1.0: 单进程，asyncio Task 隔离
class SessionManager:
    sessions: dict[str, QueryEngine]    # session_id → QueryEngine 实例

    async def send(self, session_id, msg) -> AsyncIterator[StreamChunk]:
        engine = self.sessions[session_id]
        async for message in engine.submitMessage(msg):
            yield convert_to_stream_chunk(message)
```

后续版本再迁移到真正的子进程模型。

---

## 六、数据流总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                         QueryEngine                                  │
│                                                                      │
│  mutable_messages: [m1, m2, m3, ..., mN]   ← 会话持久消息           │
│                                                                      │
│  submitMessage(user_input):                                          │
│    │                                                                 │
│    ├─ 阶段 1-2：配置 + ToolUseContext                                │
│    │                                                                 │
│    ├─ 阶段 3：user_msg → append(mutable_messages) → transcript       │
│    │                                                                 │
│    ├─ 阶段 5：snapshot = list(mutable_messages)                      │
│    │   async for msg in queryloop(QueryParams(snapshot, ...)):       │
│    │       │                                                         │
│    │       ├─ mutable_messages.append(msg)    ← 回写                 │
│    │       ├─ record_transcript([msg])        ← 持久化               │
│    │       ├─ total_usage += msg.usage        ← 统计                 │
│    │       └─ yield msg                      ← 给调用方              │
│    │                                                                 │
│    ├─ 阶段 6：compact_boundary 截断 + snip 移除                      │
│    │                                                                 │
│    └─ 阶段 7：yield result                                          │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                          queryloop                                   │
│                                                                      │
│  state.messages = list(params.messages)  ← 独立副本                  │
│                                                                      │
│  while True:                                                         │
│    │                                                                 │
│    ├─ 压缩管线(state.messages) → messages_for_query                  │
│    │                                                                 │
│    ├─ LLM 流式调用 → assistant_content + usage + stop_reason         │
│    │                                                                 │
│    ├─ 构建 assistant_message                                         │
│    │   state.messages.append(assistant_message)                      │
│    │   yield assistant_message        ← 【只 yield 新消息】          │
│    │                                                                 │
│    ├─ if end_turn → return                                           │
│    │                                                                 │
│    └─ if tool_use:                                                   │
│        ├─ execute_tool() → result                                    │
│        ├─ tool_result_msg = Message(role="tool", ...)                │
│        │   state.messages.append(tool_result_msg)                    │
│        │   yield tool_result_msg      ← 【只 yield 新消息】          │
│        └─ continue                                                   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 七、模块依赖关系

```
                    ┌──────────────────┐
                    │  SessionManager  │  (Daemon)
                    │  (Phase 5)       │
                    └────────┬─────────┘
                             │ 调用
                    ┌────────▼─────────┐
                    │   QueryEngine    │  (每个会话一个实例)
                    │  (Phase 5)       │
                    └──┬────┬────┬─────┘
                       │    │    │
            ┌──────────┘    │    └──────────┐
            ▼               ▼               ▼
    ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
    │  queryloop   │ │  Compressor  │ │ Transcript   │
    │  (Phase 1)   │ │  (Phase 3)   │ │ Writer       │
    └──────┬───────┘ └──────────────┘ │ (Phase 1)    │
           │                          └──────────────┘
           │ 调用
    ┌──────▼───────┐
    │  LLMClient   │
    │  (Phase 0)   │
    └──────┬───────┘
           │ 调用
    ┌──────▼───────┐
    │   litellm    │
    └──────────────┘
```

---

## 八、与现有代码的对接

### 8.1 已实现的模块

| 模块 | 文件 | 状态 |
|------|------|------|
| Message / ToolDefinition / StreamChunk | `src/models/types.py` | ✅ 已实现（需补充 uuid/parentUuid/type/usage 字段） |
| MessageConverter | `src/models/types.py` | ✅ 已实现 |
| AppConfig / ModelConfig | `src/models/config.py` | ✅ 已实现 |
| LLMClient | `src/models/client.py` | ✅ 已实现 |

### 8.2 需要修改的现有代码

**`src/models/types.py` — Message 需要扩展：**
```python
# 当前缺少的字段：
class Message(BaseModel):
    uuid: str                          # ← 新增
    parentUuid: str | None = None      # ← 新增
    type: str = "message"              # ← 新增
    usage: Usage | None = None         # ← 新增
    timestamp: float = 0.0             # ← 新增
    # 保留现有字段
    role: str
    content: Union[str, list[dict]]
    thinking: Union[str, None] = None
    tool_call_id: Union[str, None] = None
```

### 8.3 待实现的模块（按 Phase）

| Phase | 模块 | 文件 |
|-------|------|------|
| 1 | queryloop | `src/engine/queryloop.py` |
| 1 | TranscriptWriter | `src/engine/transcript.py` |
| 1 | QueryEngine 骨架 | `src/engine/queryengine.py` |
| 2 | ToolRegistry + 内置工具 | `src/tools/` |
| 3 | Compressor | `src/context/compression.py` |
| 4 | Memory System | `src/memory/` |
| 5 | SessionManager | `src/daemon/session_manager.py` |
| 6 | MCP + SkillTool | `src/tools/mcp/` |
| 7 | HTTP API + Docker | `src/server/` |