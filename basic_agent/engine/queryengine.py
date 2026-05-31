"""
QueryEngine — 会话级状态持有者

职责：
- 持有会话的全部状态（mutable_messages, total_usage）
- sendMessage() — 简易对话（逐 token 流式，适用于实时游戏）
- submitMessage() — 7 阶段 ReAct 循环（支持工具调用，适用于 Agent 场景）
- resume() 从 transcript 恢复会话
- 处理 compact_boundary 消息的持久化

不负责：
- 工具注册与执行（Phase 2）
- 会话路由（由 SessionManager 处理）
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import AsyncGenerator, Optional

from src.models.types import (
    Message,
    Usage,
    ToolUseContext,
    QueryParams,
    new_uuid,
)
from src.engine.query import queryloop, chat_stream
from src.engine.transcript import TranscriptWriter


class QueryEngine:
    """
    一个 QueryEngine 实例 = 一个会话

    核心状态：
    - mutable_messages: 持久消息存储（内存中，可被压缩修改）
    - total_usage: 累计 token 消耗

    核心方法：
    - submitMessage(user_input) → async generator，逐步 yield 消息
    - resume() → 从 transcript 恢复会话
    """

    def __init__(
        self,
        session_id: str,
        model_alias: str = "reasoning",
        system_prompt: str = "You are a helpful assistant.",
        cwd: str = ".",
    ):
        # ===== 会话标识 =====
        self.session_id = session_id
        self.conversation_id = new_uuid()

        # ===== 核心状态 =====
        self.mutable_messages: list[Message] = []
        self.total_usage = Usage()

        # ===== 配置 =====
        self.system_prompt = system_prompt
        self.cwd = cwd
        self.model_alias = model_alias

        # ===== 外部依赖 =====
        transcript_path = Path(f"data/sessions/{session_id}.jsonl")
        self.transcript = TranscriptWriter(transcript_path)

        # 占位：Phase 2/3 实现
        # self.tool_registry = ToolRegistry()
        # self.compressor = Compressor()

    async def resume(self):
        """从 transcript 恢复会话"""
        self.mutable_messages = await self.transcript.load()

    def _last_message_uuid(self) -> Optional[str]:
        """获取最后一条消息的 UUID（用于 parentUuid 链接）"""
        return self.mutable_messages[-1].uuid if self.mutable_messages else None

    def _get_model_config(self):
        """获取当前模型配置"""
        from src.models.config import get_config
        config = get_config()
        return config.models.get(self.model_alias)

    async def chatMessage(self, user_input: str) -> AsyncGenerator[str | Message, None]:
        """
        简易对话 — 逐 token 流式输出，适用于实时对话游戏。

        内部调用 chat()（压缩管线 + 记忆占位 + 单次 LLM 调用），
        同时逐 token yield 文本给调用方用于实时显示。

        Yields:
            str: 文本 token（逐个，用于实时显示）
            Message: 最终完整消息（最后一条，用于状态管理）
        """
        model_config = self._get_model_config()
        if not model_config:
            raise ValueError(f"Model '{self.model_alias}' not found in config")

        # 追加用户消息到状态
        user_msg = Message(
            uuid=new_uuid(),
            parentUuid=self._last_message_uuid(),
            role="user",
            content=user_input,
            timestamp=time.time(),
        )
        self.mutable_messages.append(user_msg)
        await self.transcript.record([user_msg])

        # 调用 chat_stream（压缩管线 + 记忆占位 + 逐 token 流式）
        snapshot = list(self.mutable_messages)
        params = QueryParams(
            messages=snapshot,
            system_prompt=self.system_prompt,
            tools=[],
            tool_use_context=ToolUseContext(agent_id=self.session_id, cwd=self.cwd),
            model_config=model_config,
        )

        async for chunk in chat_stream(params):
            if isinstance(chunk, str):
                # token → 透传给调用方
                yield chunk
            elif isinstance(chunk, Message):
                # 处理 compact_boundary 消息
                if chunk.type == "compact_boundary":
                    # compact_boundary 消息需要持久化并更新状态
                    self.mutable_messages.append(chunk)
                    await self.transcript.record([chunk])
                    # 给调用方一个提示，表示发生了压缩
                    yield f"\n[对话历史已压缩: {chunk.content[:50]}...]\n"
                else:
                    # 完整消息 → 回写状态 + 持久化
                    self.mutable_messages.append(chunk)
                    await self.transcript.record([chunk])
                    if chunk.usage:
                        self.total_usage += chunk.usage

        # yield 最终结果标记
        yield Message(
            uuid=new_uuid(),
            parentUuid=self._last_message_uuid(),
            role="assistant",
            content="[done]",
            type="result",
            timestamp=time.time(),
        )

    async def submitMessage(self, user_input: str) -> AsyncGenerator[Message, None]:
        """
        核心方法 — 7 阶段 async generator

        处理一条用户消息的完整流程，逐步 yield 消息给调用方。
        """
        # ── 阶段 1：初始化配置 ──
        model_config = self._get_model_config()
        if not model_config:
            raise ValueError(f"Model '{self.model_alias}' not found in config")

        # ── 阶段 2：构建 ToolUseContext ──
        ctx = ToolUseContext(
            agent_id=self.session_id,
            cwd=self.cwd,
            total_usage=self.total_usage,
        )

        # ── 阶段 3：处理用户输入 ──
        user_msg = Message(
            uuid=new_uuid(),
            parentUuid=self._last_message_uuid(),
            role="user",
            content=user_input,
            timestamp=time.time(),
        )
        self.mutable_messages.append(user_msg)
        await self.transcript.record([user_msg])
        yield user_msg

        # ── 阶段 4：yield 状态消息（可选）──
        # v1.0 暂不实现 system_init 消息

        # ── 阶段 5：核心循环 — 消费 queryloop ──
        snapshot = list(self.mutable_messages)
        params = QueryParams(
            messages=snapshot,
            system_prompt=self.system_prompt,
            tools=[],  # Phase 2 实现工具注册
            tool_use_context=ctx,
            model_config=model_config,
        )

        async for msg in queryloop(params):
            # 处理 compact_boundary 消息
            if msg.type == "compact_boundary":
                # compact_boundary 消息需要持久化并更新状态
                self.mutable_messages.append(msg)
                await self.transcript.record([msg])
                # 给调用方一个系统消息，表示发生了压缩
                yield Message(
                    uuid=new_uuid(),
                    parentUuid=self._last_message_uuid(),
                    role="system",
                    content=f"[对话历史已压缩: {msg.content[:50]}...]",
                    type="system_init",
                    timestamp=time.time(),
                )
            else:
                # 即时回写
                self.mutable_messages.append(msg)
                # 即时持久化
                await self.transcript.record([msg])
                # 累加 usage
                if msg.usage:
                    self.total_usage += msg.usage
                # 即时传递给调用方
                yield msg

        # ── 阶段 6：后处理（占位）──
        # compact_boundary 截断、snip 移除 — Phase 3 实现

        # ── 阶段 7：yield 最终结果 ──
        result_msg = Message(
            uuid=new_uuid(),
            parentUuid=self._last_message_uuid(),
            role="assistant",
            content="[done]",
            type="result",
            timestamp=time.time(),
        )
        yield result_msg
