"""
内置消息格式定义 + 双向转换器

职责：
- 定义框架内部统一的数据模型（Message, ToolDefinition, StreamChunk 等）
- 提供内部格式 ↔ LiteLLM (OpenAI) 格式的双向转换
"""

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Union

from pydantic import BaseModel


# ============================================================
# 辅助函数
# ============================================================


def new_uuid() -> str:
    """生成新的 UUID"""
    return str(uuid.uuid4())


# ============================================================
# 核心数据结构
# ============================================================


@dataclass
class Usage:
    """Token 使用统计"""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    def __iadd__(self, other: "Usage") -> "Usage":
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_creation_tokens += other.cache_creation_tokens
        return self


@dataclass
class ToolUseContext:
    """工具执行上下文（每个 Agent 私有）"""
    agent_id: str
    cwd: str
    read_file_state: dict[str, Any] = field(default_factory=dict)
    permission_denials: int = 0
    total_usage: Usage = field(default_factory=Usage)


@dataclass
class QueryParams:
    """查询参数包，QueryEngine 调用 queryloop 前组装"""
    messages: list["Message"]
    system_prompt: str
    tools: list["ToolDefinition"]
    tool_use_context: ToolUseContext
    model_config: Any          # ModelConfig，用 Any 避免循环导入
    max_tool_rounds: int = 20


# ============================================================
# 消息内容块
# ============================================================


class TextBlock(BaseModel):
    type: str = "text"
    text: str


class ToolUseBlock(BaseModel):
    type: str = "tool_use"
    id: str
    name: str
    input: dict


class ToolResultBlock(BaseModel):
    type: str = "tool_result"
    tool_use_id: str
    content: str
    is_error: bool = False


# ============================================================
# 统一消息格式
# ============================================================


class Message(BaseModel):
    """
    框架内部统一消息格式

    role: "system" | "user" | "assistant" | "tool"
    content: str（纯文本） | list[dict]（ContentBlock 列表）
    thinking: 模型的思考过程（DeepSeek reasoning_content / Claude thinking 等），无则为 None
    tool_call_id: 仅 role="tool" 时使用，关联对应的 tool_use
    uuid: 唯一标识，用于去重和 parentUuid 链表
    parentUuid: 父消息 UUID，构成隐式链表
    type: "message" | "compact_boundary" | "system_init" | "result"
    usage: 仅 assistant 消息时携带的 token 统计
    timestamp: 创建时间戳
    """
    role: str
    content: Union[str, list[dict]]
    thinking: Union[str, None] = None
    tool_call_id: Union[str, None] = None
    uuid: str = ""
    parentUuid: Optional[str] = None
    type: str = "message"
    usage: Optional[Usage] = None
    timestamp: float = 0.0


# ============================================================
# 工具定义
# ============================================================


class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: dict
    is_deferred: bool = True
    is_mcp: bool = False


# ============================================================
# 流式输出
# ============================================================


class ChunkType(str, Enum):
    TEXT = "text"
    THINKING = "thinking"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    STATUS = "status"
    ERROR = "error"
    DONE = "done"


class StreamChunk(BaseModel):
    type: ChunkType
    data: Union[str, dict]


# ============================================================
# 格式转换器
# ============================================================


class MessageConverter:
    """
    Provider 感知的双向消息转换器（无状态）

    职责：
    - 内部 Message ↔ 各 provider 原生格式的双向转换
    - 工具定义的格式转换
    - 流式缓冲区到内部 Message 的转换

    设计：
    - 通过 provider 参数路由到不同的转换方法
    - OpenAI 兼容的 provider（openai / deepseek / ollama 等）共用同一路径
    - 未来需要原生能力时（如 Claude extended thinking），新增对应 provider 路径即可

    使用方式：
        converter = MessageConverter()
        litellm_msgs = converter.to_provider(messages, provider="deepseek")
        internal_msg = converter.from_provider(raw_response, provider="deepseek")
    """

    # OpenAI 兼容的 provider 列表（共用同一转换路径）
    _OPENAI_COMPAT = {"openai", "deepseek", "ollama", "ollama_chat", "azure"}

    def __init__(self):
        pass

    # ----------------------------------------------------------
    # 对外接口：内部格式 ↔ Provider 格式
    # ----------------------------------------------------------

    def to_provider(self, messages: list[Message], provider: str = "openai") -> list[dict]:
        """
        内部 Message 列表 → Provider 原生格式

        根据 provider 参数路由到不同的转换方法。
        """
        if provider in self._OPENAI_COMPAT:
            return self._to_openai(messages)
        raise ValueError(f"Unsupported provider: {provider}")

    def from_provider(self, raw_message: dict, provider: str = "openai") -> Message:
        """
        单条 Provider 原生响应 → 内部 Message

        根据 provider 参数路由到不同的转换方法。
        """
        if provider in self._OPENAI_COMPAT:
            return self._from_openai(raw_message)
        raise ValueError(f"Unsupported provider: {provider}")

    def to_provider_tools(self, tools: list[ToolDefinition], provider: str = "openai") -> list[dict]:
        """
        内部 ToolDefinition 列表 → Provider 原生 tools 格式
        """
        if provider in self._OPENAI_COMPAT:
            return self._to_openai_tools(tools)
        raise ValueError(f"Unsupported provider: {provider}")

    # ----------------------------------------------------------
    # 工具方法（与 provider 无关）
    # ----------------------------------------------------------

    @staticmethod
    def from_stream_chunks(
        tool_calls_buffer: dict,
        thinking: Union[str, None] = None,
    ) -> Message:
        """
        从流式缓冲区构造内部 Message

        chat_stream() 负责缓冲拼接，调用此方法将结果转为 Message。
        """
        if not tool_calls_buffer:
            return Message(uuid=new_uuid(), role="assistant", content="", thinking=thinking, timestamp=time.time())

        blocks: list[dict] = []
        for idx in sorted(tool_calls_buffer.keys()):
            tc = tool_calls_buffer[idx]
            try:
                args = json.loads(tc["arguments"])
            except json.JSONDecodeError:
                args = {"_raw": tc["arguments"]}
            blocks.append({
                "type": "tool_use",
                "id": tc["id"],
                "name": tc["name"],
                "input": args,
            })
        return Message(uuid=new_uuid(), role="assistant", content=blocks, thinking=thinking, timestamp=time.time())

    @staticmethod
    def make_tool_result_message(tool_use_id: str, content: str, is_error: bool = False) -> Message:
        """
        构造工具结果消息（用于 ReAct 循环中注入 tool_result）
        """
        return Message(
            uuid=new_uuid(),
            role="tool",
            content=content,
            tool_call_id=tool_use_id,
            timestamp=time.time(),
        )

    # ----------------------------------------------------------
    # OpenAI 兼容路径（当前所有 provider 共用）
    # ----------------------------------------------------------

    @staticmethod
    def _to_openai(messages: list[Message]) -> list[dict]:
        """
        内部 Message → OpenAI 格式

        转换规则：
        - 普通消息：{"role": ..., "content": ...}
        - Assistant 工具调用：content 中的 tool_use 块 → 顶层 tool_calls 数组
        - 工具结果：{"role": "tool", "tool_call_id": ..., "content": ...}
        - 思考过程：thinking → reasoning_content（非空时）
        """
        result = []
        for msg in messages:
            d: dict = {"role": msg.role}

            if msg.role == "assistant" and isinstance(msg.content, list):
                text_parts = []
                tool_calls = []
                for block in msg.content:
                    if isinstance(block, dict):
                        if block.get("type") == "tool_use":
                            tool_calls.append({
                                "id": block["id"],
                                "type": "function",
                                "function": {
                                    "name": block["name"],
                                    "arguments": json.dumps(block["input"], ensure_ascii=False),
                                },
                            })
                        elif block.get("type") == "text":
                            text_parts.append(block["text"])

                d["content"] = " ".join(text_parts) if text_parts else None
                if tool_calls:
                    d["tool_calls"] = tool_calls

            elif msg.role == "tool":
                d["content"] = msg.content
                if msg.tool_call_id:
                    d["tool_call_id"] = msg.tool_call_id

            else:
                d["content"] = msg.content

            # 思考过程
            if msg.role == "assistant" and msg.thinking:
                d["reasoning_content"] = msg.thinking

            result.append(d)
        return result

    @staticmethod
    def _from_openai(raw_message: dict) -> Message:
        """
        OpenAI 格式响应 → 内部 Message

        处理要点：
        - 纯文本：content 直接是 str
        - 工具调用：tool_calls 顶层字段 → content 列表中的 tool_use 块
        - 思考过程：reasoning_content / thinking → thinking 字段
        """
        content = raw_message.get("content") or ""
        tool_calls = raw_message.get("tool_calls")
        thinking = (
            raw_message.get("reasoning_content")
            or raw_message.get("thinking")
            or None
        )

        if tool_calls:
            blocks: list[dict] = []
            if content:
                blocks.append({"type": "text", "text": content})
            for tc in tool_calls:
                blocks.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["function"]["name"],
                    "input": json.loads(tc["function"]["arguments"]),
                })
            return Message(uuid=new_uuid(), role="assistant", content=blocks, thinking=thinking, timestamp=time.time())

        return Message(role="assistant", content=content, thinking=thinking)

    @staticmethod
    def _to_openai_tools(tools: list[ToolDefinition]) -> list[dict]:
        """内部 ToolDefinition → OpenAI tools 格式"""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in tools
        ]

    # ----------------------------------------------------------
    # 未来扩展点：其他 provider 的原生路径
    # ----------------------------------------------------------
    # def _to_anthropic(self, messages): ...
    # def _from_anthropic(self, raw): ...
    # def _to_gemini(self, messages): ...
    # def _from_gemini(self, raw): ...
