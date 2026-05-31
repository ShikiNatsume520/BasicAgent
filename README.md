# BasicAgent

轻量级 LLM Agent 对话服务框架，专为实时对话游戏优化。

## 项目愿景

为实时对话游戏和 AI 应用提供一个高性能、可扩展的 Agent 后端框架。

**核心特性：**
- **统一 LLM 接口** — 通过 LiteLLM 接入 OpenAI / DeepSeek / Ollama 等多家模型，配置驱动切换
- **流式输出** — 逐 token 输出，低延迟，适合实时对话场景
- **智能记忆** — 自动压缩对话历史，防止上下文溢出（v1.1 新增）
- **提示词注入** — 灵活的提示词管理，支持多种注入点（v1.1 新增）
- **会话管理** — 多会话隔离，消息持久化，支持会话恢复
- **工具调用** — ReAct 循环，支持自定义工具扩展（规划中）
- **纯 Python API** — 不绑定 HTTP 框架，上层应用自行集成

## 快速开始

### 安装

```bash
# 克隆仓库
git clone https://github.com/ShikiNatsume520/BasicAgent.git
cd BasicAgent

# 创建虚拟环境
conda create -n BA python=3.11
conda activate BA

# 安装依赖
pip install -e ".[dev]"
```

### 配置

在项目根目录创建 `.env` 文件：

```env
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
```

模型配置在 `config/` 目录下，已预置 DeepSeek 模型。

### 最简示例

```python
import asyncio
from src.daemon import SessionManager

async def main():
    manager = SessionManager()

    # 创建会话（设定角色人设）
    session_id = await manager.create_session(
        model_alias="reasoning",
        system_prompt="你是一个游戏商人，称呼玩家为旅行者，回复简短。",
    )

    # 逐 token 流式对话
    async for chunk in manager.chat(session_id, "你好"):
        if isinstance(chunk, str):
            print(chunk, end="", flush=True)

    await manager.delete(session_id)

asyncio.run(main())
```

## 模块结构

```
src/
├── models/                    ← 基础层
│   ├── config.py              ← 配置加载（含 MemoryConfig）
│   ├── types.py               ← 数据模型（Message / Usage / QueryParams）+ 格式转换器
│   └── client.py              ← LLMClient（LiteLLM 封装）
├── engine/                    ← 核心引擎
│   ├── query.py               ← chat / chat_stream（集成压缩管线）+ queryloop（ReAct 循环）
│   ├── queryengine.py         ← QueryEngine（会话状态 + compact_boundary 处理）
│   └── transcript.py          ← TranscriptWriter（JSONL 持久化）
├── memory/                    ← 记忆系统（v1.1 新增）
│   └── compression.py         ← 压缩算法（snip + autocompact）
├── prompts/                   ← 提示词注入（v1.1 新增）
│   └── prompt.py              ← PromptInjector（支持多种注入点）
└── daemon/                    ← 会话管理
    └── session_manager.py     ← SessionManager（纯 Python API）
```

## API 概览

### SessionManager

```python
from src.daemon import SessionManager

manager = SessionManager()

# 创建会话
session_id = await manager.create_session(
    model_alias="reasoning",       # 模型别名（对应 config/BA_Agent.json）
    system_prompt="你是一个助手。",  # 系统提示
)

# 简易对话（逐 token 流式输出，推荐用于游戏）
async for chunk in manager.chat(session_id, "你好"):
    if isinstance(chunk, str):
        print(chunk, end="", flush=True)  # 实时推送 token
    elif chunk.type == "result":
        print()  # 对话结束

# Agent 模式（支持工具调用）
async for msg in manager.send(session_id, "帮我读取文件"):
    print(msg.content)

# 会话管理
await manager.delete(session_id)
await manager.list_sessions()
await manager.resume_session(session_id)
```

### 两种对话模式

| | `chat()` | `send()` |
|---|---|---|
| 适用场景 | 实时对话游戏、简单问答 | Agent、需要工具调用 |
| 工具调用 | 不支持 | 支持 |
| 输出粒度 | 逐 token | 逐条 Message |
| 延迟 | 最低 | 较高 |

## 当前进展

**v1.1 — 记忆压缩系统 ✅ 已完成**

| Phase | 内容 | 状态 |
|-------|------|------|
| v1.1-Phase 1 | snip 裁剪 + timeout 裁剪 | ✅ |
| v1.1-Phase 2 | microcompact 微压缩 | 占位（v1.1 不实现） |
| v1.1-Phase 3 | autocompact 自动压缩 | ✅ |
| v1.1-Phase 4 | 提示词注入模块 | ✅ |
| v1.1-Phase 5 | QueryEngine 集成 | ✅ |

**v1.0 — 核心引擎 ✅ 已完成**

| Phase | 内容 | 状态 |
|-------|------|------|
| Phase 0 | 配置系统 + 数据模型 + LLMClient | ✅ |
| Phase 1 | QueryEngine + queryloop/chat + TranscriptWriter + SessionManager | ✅ |
| Phase 2 | 工具系统（ToolRegistry + 内置工具） | 待实现 |
| Phase 3 | 上下文管理 + 三层压缩 | 待实现 |
| Phase 4 | 记忆系统 | 待实现 |
| Phase 5 | SessionManager 子进程隔离 | 待实现 |
| Phase 6 | MCP + SkillTool + 子Agent | 待实现 |
| Phase 7 | HTTP API + Docker | 待实现 |

## v1.1 新功能使用指南

### 记忆压缩系统

自动管理对话历史，防止上下文溢出：

```python
from src.memory.compression import snip, autocompact
from src.models.config import get_config

config = get_config()
memory_config = config.compression.memory

# 手动裁剪消息
trimmed_messages = snip(messages, memory_config)

# 自动压缩（当 token 超过阈值时触发）
result_messages, compact_boundary = await autocompact(
    messages, system_prompt, memory_config, llm_client
)

# compact_boundary 会自动持久化到 JSONL 文件
if compact_boundary:
    print(f"对话已压缩: {compact_boundary.content[:50]}...")
```

**配置参数（`config/compression.json`）：**

```json
{
  "memory": {
    "timeout_minutes": 30,        // 旧消息超时时间（分钟）
    "autocompact_threshold": 0.8, // 触发压缩的 token 占比阈值
    "compact_prompt_path": "config/prompts/compact.txt"
  }
}
```

### 提示词注入模块

灵活管理提示词，支持多种注入点：

```python
from src.prompts.prompt import PromptInjector, InjectionPoint, InjectionRule

injector = PromptInjector()

# 设置变量
injector.set_variable("character_name", "小雅")

# 添加注入规则
injector.add_rule(InjectionRule(
    point=InjectionPoint.BEFORE_COMPACT,
    prompt_template="请保持角色 {character_name} 的语气和性格。",
    priority=10
))

# 注入提示词
messages = injector.inject(messages, InjectionPoint.BEFORE_COMPACT)
```

**注入点说明：**

| 注入点 | 说明 | 插入位置 |
|--------|------|----------|
| `BEFORE_COMPACT` | 压缩前注入 | 消息列表开头 |
| `AFTER_COMPACT` | 压缩后注入 | 消息列表末尾 |
| `ON_SCENE_CHANGE` | 场景切换时 | 消息列表末尾 |
| `ON_USER_INPUT` | 用户输入时 | 最后一条用户消息前 |
| `ON_ASSISTANT_RESPONSE` | 助手回复前 | 消息列表末尾 |

**从配置文件加载规则：**

```python
# 创建配置文件 config/prompts/injection_rules.json
{
  "rules": [
    {
      "point": "before_compact",
      "prompt_template": "请保持角色 {character_name} 的语气。",
      "variables": {"character_name": "小雅"},
      "priority": 10
    }
  ]
}

# 加载规则
injector.load_rules("config/prompts/injection_rules.json")
```

### QueryEngine 集成

QueryEngine 已自动集成压缩管线，无需额外配置：

```python
from src.engine.queryengine import QueryEngine

engine = QueryEngine(
    session_id="session_001",
    model_alias="reasoning",
    system_prompt="你是一个友好的NPC。",
    cwd="."
)

# 简易对话（自动处理压缩）
async for chunk in engine.chatMessage("你好"):
    if isinstance(chunk, str):
        print(chunk, end="", flush=True)
    elif isinstance(chunk, Message):
        if chunk.type == "compact_boundary":
            print(f"\n[对话已压缩]")
        elif chunk.type == "result":
            print("\n[对话结束]")
```

## 文档

- [API 开发者指南](docs/api-v1.md) — 面向上层应用开发者的完整 API 文档
- [架构设计](docs/architecture.md) — 核心架构与数据流
- [开发进度](docs/progress.md) — 详细的开发进度记录

## 许可证

MIT
