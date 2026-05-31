# Phase 0 设计说明：项目骨架 + 数据模型

## 目标

建立项目结构、定义核心数据模型，为后续所有模块提供统一的数据基础。

## 1. 项目结构

```
E:/Code/BasicAgent/
├── pyproject.toml                 # 项目元数据 + 依赖声明
├── requirements.txt               # Docker 用，锁定版本
├── config/
│   └── default.json               # 默认配置（模型、压缩参数、存储路径等）
├── src/
│   ├── __init__.py
│   ├── config.py                  # 配置加载器（JSON + 环境变量覆盖）
│   └── models/
│       ├── __init__.py
│       └── client.py                # 基于LiteLLM的客户端，负责与LLM交互，处理请求和响应
│
├── tests/
|   └── test_models.py
└── .env                       # 环境变量配置文件, 主要用于存储各类敏感信息，如 API Key、数据库连接等
    
```

其余模块目录（providers/、engine/、tools/ 等）在对应阶段创建，Phase 0 只建 models。

## 2. 依赖选型

| 包 | 用途 | 选型理由 |
|---|------|---------|
| litellm | 统一 LLM 接口 | 支持 Anthropic/OpenAI/Google，流式 tool_call 归一化为 OpenAI 格式 |
| fastapi | HTTP 框架 | 原生 async，SSE 支持好 |
| uvicorn[standard] | ASGI 服务器 | FastAPI 标配 |
| sse-starlette | SSE 支持 | 比手动 StreamingResponse 更规范 |
| aiofiles | 异步文件 I/O | 全异步架构需要 |
| pydantic | 数据模型 | 类型安全 + JSON 序列化，FastAPI 原生集成 |
| tiktoken | Token 计数 | 上下文窗口管理、压缩触发判断 |
| mcp | MCP 协议 SDK | Phase 6 用，提前声明 |

Python 版本：3.11+（需要 TaskGroup、ExceptionGroup 等特性）

## 3. 核心数据模型设计

### 3.1 消息内容块（Content Blocks）

LLM 的消息中包含多种内容类型，需要统一建模：

```python
# 三类ContentBlock

## 纯文本
TextBlock: { type: "text", text: str }

## 工具调用（Assistant 发出）
ToolUseBlock: { type: "tool_use", id: str, name: str, input: dict }

## 工具结果（User 返回）
ToolResultBlock: { type: "tool_result", tool_use_id: str, content: str, is_error: bool }
```

**设计决策：** content 字段统一用 `str | list[TextBlock | ToolUseBlock | ToolResultBlock]`。
- 单一文本内容时直接存 str（简化序列化）
- 包含工具调用/结果时存 list

### 3.2 统一消息格式

```python
Message:
{
  role: "system" | "user" | "assistant" | "tool"
  content: str | list[ContentBlock]
}

```

**关于 role="tool"：** LiteLLM 在非流式模式下可能返回 role="tool" 的消息，但在流式模式下工具结果是通过 user 消息中的 ToolResultBlock 传递的。我们内部统一用 user + ToolResultBlock 的方式，仅在调用 LiteLLM API 时做格式转换。

### 3.3 工具定义

```python
ToolDefinition:
  name: str
  description: str
  input_schema: dict    # JSON Schema 格式

  is_deferred: bool = True # 是否延迟加载, 默认被延迟
  is_async: bool = False    # 是否可以异步执行，读异步，写同步。
  is_mcp: bool = False      # 是否是 MCP 工具
  is_meta: bool = False      # 是否是内置工具

  call(input: dict) -> dict:
    """工具执行函数"""
```

这个结构直接映射到 LiteLLM API 的 tools 参数格式。

### 3.4 会话配置

```python
SessionConfig:
  available_tools: list[str]    # 预计算出来的工具池
  disabled_tools: list[str]     # 禁用列表
  system_prompt: str | None     # 系统提示
  model: str                    # 模型标识，使用别名，本框架内部应该分为2+1个模型，第三个为多模态模型。
```

### 3.5 流式输出

```python
ChunkType: "text" | "tool_use" | "tool_result" | "status" | "error" | "done"

StreamChunk:
  type: ChunkType
  data: str | dict
```

- `text`：LLM 的文本增量，data 是 str
- `tool_use`：完整的工具调用（缓冲完成后一次性发出），data 是 `{"id": ..., "name": ..., "input": ...}`
- `tool_result`：工具执行结果，data 是 `{"tool_use_id": ..., "content": ...}`
- `status`：状态信息（如 "正在执行工具..."），data 是 str
- `error`：错误信息，data 是 str
- `done`：流结束标记，data 是 ""

### 3.6 会话元数据

```python
SessionMeta:
  id: str
  created_at: float         # time.time()
  model: str
  provider: str
  message_count: int
```

## 4. 配置系统设计

### 配置层级

```
config/
├── BA_Agent.json              # 框架级配置：三个模型别名指向哪个模型
├── provider/                  # 每个模型/供应商的具体配置
│   ├── gpt-4.json
│   ├── ollama-llama3.json
│   └── ...
├── compression.json           # 压缩策略配置（全局默认）
└── default.json               # 其他全局默认配置（存储路径等）
```

加载顺序：`BA_Agent.json` → `provider/{model}.json` → `.env` 环境变量覆盖敏感字段

### 4.1 框架配置 (config/BA_Agent.json)

定义框架内置的三个模型别名，指向具体的 provider 配置文件名：

```json
{
  "reasoning_model": "gpt-4",
  "flash_model": "gpt-4o-mini",
  "multi_model": "gpt-4o"
}
```

- `reasoning_model`：需要深度推理的场景（如 Context Collapse 分组）
- `flash_model`：轻量快速场景（如 Session Compact 提取、标题生成）
- `multi_model`：多模态场景（图片理解等）

### 4.2 供应商配置 (config/provider/{name}.json)

每个模型一份配置文件，文件名对应 BA_Agent.json 中的值：

```json
// config/provider/gpt-4.json
{
  "litellm_model": "openai/gpt-4",
  "api_base": null,
  "max_tokens": 128000,
  "api_key_env": "OPENAI_API_KEY"
}

// config/provider/ollama-llama3.json
{
  "litellm_model": "ollama_chat/llama3",
  "api_base": "http://localhost:11434",
  "max_tokens": 8192,
  "api_key_env": null
}
```

- `litellm_model`：LiteLLM 的 model string（含 provider 前缀）
- `api_base`：自定义端点（中转站、Ollama 等），null 表示用默认
- `max_tokens`：该模型的 context window 大小
- `api_key_env`：API Key 对应的环境变量名，null 表示不需要

### 4.3 压缩策略配置 (config/compression.json)

```json
{
  "snip": {
    "window_tokens": 100000
  },
  "microcompact": {
    "max_tool_result_tokens": 5000
  },
  "tier3": {
    "mode": "auto",
    "threshold": 0.8
  }
}
```

### 4.4 环境变量 (.env)

```env
# API Keys（不写入配置文件）
OPENAI_API_KEY=sk-xxx
ANTHROPIC_API_KEY=sk-ant-xxx

# 可选：覆盖 BA_Agent.json 中的模型别名
# BA_REASONING_MODEL=ollama-llama3
```

### 4.5 配置加载流程

```python
1. 读取 BA_Agent.json → 得到 {reasoning: "gpt-4", flash: "gpt-4o-mini", multi: "gpt-4o"}
2. 对每个别名，读取 provider/{name}.json → 得到 litellm_model, api_base, max_tokens
3. 从 .env 读取 api_key_env 指定的环境变量 → 得到 API Key
4. 组装成完整的模型配置供 client.py 使用
```

## 5. 已确认的设计决策

1. **content 字段**：内部统一用 `list[ContentBlock]`，在 LiteLLM 调用层做格式转换
2. **provider 配置**：支持自定义 `api_base`，用于中转站和本地模型
3. **compression_config**：全局默认值在 `config/compression.json`，per-model 可选覆盖
4. **tiktoken**：用于本地粗略估算 token 量，判断是否触发压缩
