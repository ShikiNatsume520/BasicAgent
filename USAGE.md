# BasicAgent v1.1 使用指南

## 快速开始

### 安装

```bash
# 从 GitHub 安装 v1.1.1 版本
pip install git+https://github.com/ShikiNatsume520/BasicAgent.git@v1.1.1

# 或者在 requirements.txt 中添加
basic-agent @ git+https://github.com/ShikiNatsume520/BasicAgent.git@v1.1.1
```

### 配置

创建 `.env` 文件：

```env
DEEPSEEK_API_KEY=your_api_key_here
```

## 基本使用

### 1. 创建会话管理器

```python
import asyncio
from basic_agent.daemon.session_manager import SessionManager

async def main():
    # 创建会话管理器
    manager = SessionManager()
    
    # 创建会话
    session_id = await manager.create_session(
        model_alias="reasoning",  # 使用 reasoning 模型
        system_prompt="你是一个友好的NPC，名叫小雅。"
    )
    
    print(f"会话已创建: {session_id}")
    
    # 删除会话
    await manager.delete(session_id)

asyncio.run(main())
```

### 2. 流式对话

```python
import asyncio
from basic_agent.daemon.session_manager import SessionManager
from basic_agent.models.types import Message

async def main():
    manager = SessionManager()
    
    # 创建会话
    session_id = await manager.create_session(
        model_alias="reasoning",
        system_prompt="你是一个友好的NPC，名叫小雅。请用简短的话回复。"
    )
    
    # 流式对话
    print("小雅: ", end="", flush=True)
    async for chunk in manager.chat(session_id, "你好！"):
        if isinstance(chunk, str):
            # 逐 token 输出
            print(chunk, end="", flush=True)
        elif isinstance(chunk, Message):
            if chunk.type == "compact_boundary":
                # 对话历史被压缩
                print(f"\n[对话已压缩]")
            elif chunk.type == "result":
                # 对话结束
                print("\n")
    
    # 删除会话
    await manager.delete(session_id)

asyncio.run(main())
```

### 3. 多轮对话

```python
import asyncio
from basic_agent.daemon.session_manager import SessionManager
from basic_agent.models.types import Message

async def main():
    manager = SessionManager()
    
    # 创建会话
    session_id = await manager.create_session(
        model_alias="reasoning",
        system_prompt="你是一个友好的NPC，名叫小雅。请用简短的话回复。"
    )
    
    # 多轮对话
    conversations = [
        "你好！",
        "今天天气真好",
        "你喜欢做什么？",
        "再见！"
    ]
    
    for user_input in conversations:
        print(f"玩家: {user_input}")
        print("小雅: ", end="", flush=True)
        
        async for chunk in manager.chat(session_id, user_input):
            if isinstance(chunk, str):
                print(chunk, end="", flush=True)
            elif isinstance(chunk, Message):
                if chunk.type == "result":
                    print("\n")
    
    # 删除会话
    await manager.delete(session_id)

asyncio.run(main())
```

## 高级功能

### 1. 记忆压缩系统

BasicAgent 会自动管理对话历史，防止上下文溢出：

```python
import asyncio
from basic_agent.daemon.session_manager import SessionManager
from basic_agent.models.types import Message

async def main():
    manager = SessionManager()
    
    # 创建会话
    session_id = await manager.create_session(
        model_alias="reasoning",
        system_prompt="你是一个友好的NPC。"
    )
    
    # 进行多轮对话（当对话历史过长时会自动压缩）
    for i in range(100):
        async for chunk in manager.chat(session_id, f"消息 {i}"):
            if isinstance(chunk, str):
                print(chunk, end="", flush=True)
            elif isinstance(chunk, Message):
                if chunk.type == "compact_boundary":
                    print(f"\n[对话已压缩: {chunk.content[:50]}...]")
                elif chunk.type == "result":
                    print("\n")
    
    # 删除会话
    await manager.delete(session_id)

asyncio.run(main())
```

### 2. 提示词注入

自定义提示词注入规则：

```python
import asyncio
from basic_agent.prompts.prompt import PromptInjector, InjectionPoint, InjectionRule
from basic_agent.daemon.session_manager import SessionManager
from basic_agent.models.types import Message

async def main():
    # 创建注入器
    injector = PromptInjector()
    
    # 设置变量
    injector.set_variable("character_name", "小雅")
    injector.set_variable("location", "森林")
    
    # 添加注入规则
    injector.add_rule(InjectionRule(
        point=InjectionPoint.BEFORE_COMPACT,
        prompt_template="请保持角色 {character_name} 的语气，当前场景是 {location}。",
        priority=10
    ))
    
    # 创建会话管理器
    manager = SessionManager()
    
    # 创建会话
    session_id = await manager.create_session(
        model_alias="reasoning",
        system_prompt="你是一个友好的NPC。"
    )
    
    # 对话
    async for chunk in manager.chat(session_id, "你好！"):
        if isinstance(chunk, str):
            print(chunk, end="", flush=True)
        elif isinstance(chunk, Message):
            if chunk.type == "result":
                print("\n")
    
    # 删除会话
    await manager.delete(session_id)

asyncio.run(main())
```

### 3. 自定义压缩配置

编辑 `config/compression.json`：

```json
{
  "snip": {
    "window_tokens": 100000
  },
  "microcompact": {
    "max_tool_result_tokens": 5000
  },
  "memory": {
    "timeout_minutes": 30,
    "autocompact_threshold": 0.8,
    "compact_prompt_path": "config/prompts/compact.txt"
  },
  "tier3": {
    "mode": "auto",
    "threshold": 0.8
  }
}
```

### 4. 自定义压缩提示词

编辑 `config/prompts/compact.txt`：

```
你是一个对话历史压缩助手。请将以下对话压缩成简洁的摘要。

## 压缩要求
1. 保持角色语气和性格特征
2. 保留重要事实和约定
3. 记录情感状态变化
4. 保持时间线清晰

## 对话历史
{conversation_history}

## 压缩后的摘要
```

## API 参考

### SessionManager

#### 创建会话

```python
session_id = await manager.create_session(
    model_alias="reasoning",       # 模型别名
    system_prompt="你是一个助手。",  # 系统提示
    cwd="."                        # 工作目录
)
```

#### 流式对话

```python
async for chunk in manager.chat(session_id, "用户消息"):
    if isinstance(chunk, str):
        print(chunk, end="", flush=True)  # 逐 token 输出
    elif isinstance(chunk, Message):
        if chunk.type == "result":
            print()  # 对话结束
```

#### Agent 模式（支持工具调用）

```python
async for msg in manager.send(session_id, "用户消息"):
    print(msg.content)
```

#### 会话管理

```python
# 删除会话
await manager.delete(session_id)

# 列出所有会话
sessions = await manager.list_sessions()

# 恢复会话
await manager.resume_session(session_id)
```

### Message 对象

```python
class Message:
    role: str                    # "user" | "assistant" | "system" | "tool"
    content: str | list[dict]    # 消息内容
    type: str                    # "message" | "compact_boundary" | "result"
    uuid: str                    # 唯一标识
    timestamp: float             # 时间戳
```

### 压缩系统

#### snip 裁剪

```python
from basic_agent.memory.compression import snip
from basic_agent.models.config import get_config

config = get_config()
memory_config = config.compression.memory

# 裁剪消息
trimmed_messages = snip(messages, memory_config)
```

#### autocompact 自动压缩

```python
from basic_agent.memory.compression import autocompact

# 自动压缩（当 token 超过阈值时触发）
result_messages, compact_boundary = await autocompact(
    messages,
    system_prompt,
    memory_config,
    llm_client
)
```

### 提示词注入

#### PromptInjector

```python
from basic_agent.prompts.prompt import PromptInjector, InjectionPoint, InjectionRule

injector = PromptInjector()

# 设置变量
injector.set_variable("character_name", "小雅")

# 添加规则
injector.add_rule(InjectionRule(
    point=InjectionPoint.BEFORE_COMPACT,
    prompt_template="请保持角色 {character_name} 的语气。",
    priority=10
))

# 注入提示词
messages = injector.inject(messages, InjectionPoint.BEFORE_COMPACT)
```

#### 注入点

| 注入点 | 说明 | 插入位置 |
|--------|------|----------|
| `BEFORE_COMPACT` | 压缩前注入 | 消息列表开头 |
| `AFTER_COMPACT` | 压缩后注入 | 消息列表末尾 |
| `ON_SCENE_CHANGE` | 场景切换时 | 消息列表末尾 |
| `ON_USER_INPUT` | 用户输入时 | 最后一条用户消息前 |
| `ON_ASSISTANT_RESPONSE` | 助手回复前 | 消息列表末尾 |

## 配置说明

### 模型配置

编辑 `config/BA_Agent.json`：

```json
{
  "reasoning": "deepseek-v4-pro",
  "flash": "deepseek-v4-flash"
}
```

### Provider 配置

编辑 `config/provider/deepseek-v4-pro.json`：

```json
{
  "litellm_model": "deepseek/deepseek-v4-pro",
  "api_base": null,
  "max_tokens": 1000000,
  "api_key_env": "DEEPSEEK_API_KEY"
}
```

## 常见问题

### Q: 如何防止对话历史无限增长？

A: BasicAgent 会自动处理：
1. **snip**：裁剪旧的 compact_boundary 之前的消息
2. **autocompact**：当 token 超过阈值时自动压缩

### Q: 压缩后会丢失重要信息吗？

A: 不会。压缩提示词会指导 LLM 保留：
- 重要事实和约定
- 角色情感状态
- 未完成的任务
- 用户偏好

### Q: 如何自定义压缩行为？

A: 编辑 `config/prompts/compact.txt` 文件，调整压缩提示词。

### Q: 支持哪些 LLM 提供商？

A: 通过 LiteLLM 支持所有主流提供商：
- DeepSeek
- OpenAI
- Anthropic
- Google Gemini
- Ollama（本地模型）

## 示例代码

完整的示例代码可以在 `examples/` 目录中找到：

- `daemon_demo.py` — SessionManager 使用示例
- `litellm_demo.py` — LiteLLM 直接用法演示
- `client_demo.py` — LLMClient 封装用法演示

## 技术支持

如有问题，请提交 GitHub Issue：
https://github.com/ShikiNatsume520/BasicAgent/issues
