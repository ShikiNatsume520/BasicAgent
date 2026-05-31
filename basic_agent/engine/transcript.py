"""
TranscriptWriter — JSONL 持久化写入器

职责：
- 将消息以 JSONL 格式追加写入文件
- UUID 去重（防止重复写入）
- 100ms 批量刷新（减少磁盘 I/O）
- 从 JSONL 文件恢复消息列表（用于 resume）
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiofiles

from basic_agent.models.types import Message


class TranscriptWriter:
    """
    JSONL 持久化写入器

    文件路径：data/sessions/{session_id}.jsonl
    写入策略：UUID 去重 + 100ms 批量刷新（fire-and-forget）
    """

    def __init__(self, path: Path):
        self.path = path
        self.message_set: set[str] = set()
        self.write_queue: list[Message] = []
        self._drain_task: asyncio.Task | None = None

    async def record(self, messages: list[Message]):
        """将消息加入写入队列（UUID 去重）"""
        for msg in messages:
            if msg.uuid and msg.uuid not in self.message_set:
                self.write_queue.append(msg)
                self.message_set.add(msg.uuid)
        self._schedule_drain()

    def _schedule_drain(self):
        """调度批量刷新（如果当前没有正在执行的刷新任务）"""
        if self._drain_task is None or self._drain_task.done():
            self._drain_task = asyncio.create_task(self._drain())

    async def _drain(self):
        """100ms 后批量写入队列中的消息"""
        await asyncio.sleep(0.1)
        if not self.write_queue:
            return
        batch = self.write_queue[:]
        self.write_queue.clear()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(self.path, "a", encoding="utf-8") as f:
            for msg in batch:
                line = msg.model_dump_json() + "\n"
                await f.write(line)

    async def load(self) -> list[Message]:
        """从 JSONL 文件恢复消息列表（用于 resume）"""
        if not self.path.exists():
            return []
        messages = []
        async with aiofiles.open(self.path, "r", encoding="utf-8") as f:
            async for line in f:
                line = line.strip()
                if line:
                    msg = Message.model_validate_json(line)
                    messages.append(msg)
                    if msg.uuid:
                        self.message_set.add(msg.uuid)
        return messages
