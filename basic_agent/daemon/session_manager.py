# -*- coding: utf-8 -*-
"""
SessionManager — v1.0 单进程会话管理器

职责：
- 管理 session_id → QueryEngine 实例的路由表
- 创建/删除会话
- 路由消息到对应的 QueryEngine
- 透传流式结果

v1.0 简化：SessionManager 和 QueryEngine 在同一进程内运行，
通过 asyncio Task 隔离，不实现真正的子进程 fork。
"""

from __future__ import annotations

from typing import AsyncGenerator

from basic_agent.models.types import Message, new_uuid
from basic_agent.engine.queryengine import QueryEngine


class SessionManager:
    """v1.0 单进程会话管理器"""

    def __init__(self):
        self.sessions: dict[str, QueryEngine] = {}

    async def create_session(
        self,
        model_alias: str = "reasoning",
        system_prompt: str = "You are a helpful assistant.",
        cwd: str = ".",
    ) -> str:
        """创建会话，返回 session_id"""
        session_id = new_uuid()
        engine = QueryEngine(
            session_id=session_id,
            model_alias=model_alias,
            system_prompt=system_prompt,
            cwd=cwd,
        )
        self.sessions[session_id] = engine
        return session_id

    async def send(
        self, session_id: str, user_message: str
    ) -> AsyncGenerator[Message, None]:
        """路由消息到对应的 QueryEngine（ReAct 模式，支持工具调用）"""
        engine = self.sessions.get(session_id)
        if not engine:
            raise ValueError(f"Session '{session_id}' not found")
        async for msg in engine.submitMessage(user_message):
            yield msg

    async def chat(
        self, session_id: str, user_message: str
    ) -> AsyncGenerator[str | Message, None]:
        """
        简易对话模式（逐 token 流式输出，适用于实时游戏）

        Yields:
            str: 文本 token（逐个）
            Message: 最终完整消息 + result 标记
        """
        engine = self.sessions.get(session_id)
        if not engine:
            raise ValueError(f"Session '{session_id}' not found")
        async for chunk in engine.chatMessage(user_message):
            yield chunk

    async def delete(self, session_id: str):
        """删除会话"""
        self.sessions.pop(session_id, None)

    async def list_sessions(self) -> list[str]:
        """查询所有存活会话的 session_id"""
        return list(self.sessions.keys())

    async def resume_session(self, session_id: str) -> bool:
        """从 transcript 恢复会话"""
        engine = self.sessions.get(session_id)
        if not engine:
            return False
        await engine.resume()
        return True
