# BasicAgent

一个轻量级的 LLM Agent 框架，基于 LiteLLM 提供统一的大模型调用接口，支持会话管理、流式输出和工具调用。

## 项目愿景

为实时对话游戏和 AI 应用提供一个高性能、可扩展的 Agent 后端框架。

**核心特性：**
- **统一 LLM 接口** — 通过 LiteLLM 接入 OpenAI / DeepSeek / Ollama 等多家模型，配置驱动切换
- **流式输出** — 逐 token 输出，低延迟，适合实时对话场景
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
│   ├── config.py              ← 配置加载（模型别名 + provider 配置）
│   ├── types.py               ← 数据模型（Message / Usage / QueryParams）+ 格式转换器
│   └── client.py              ← LLMClient（LiteLLM 封装）
├── engine/                    ← 核心引擎
│   ├── query.py               ← chat / chat_stream（简易对话）+ queryloop（ReAct 循环）
│   ├── queryengine.py         ← QueryEngine（会话状态 + submitMessage + chatMessage）
│   └── transcript.py          ← TranscriptWriter（JSONL 持久化）
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

## 文档

- [API 开发者指南](docs/api-v1.md) — 面向上层应用开发者的完整 API 文档
- [架构设计](docs/architecture.md) — 核心架构与数据流
- [开发进度](docs/progress.md) — 详细的开发进度记录

## 许可证

MIT
