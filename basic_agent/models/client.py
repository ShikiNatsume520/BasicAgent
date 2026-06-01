# -*- coding: utf-8 -*-
"""
LiteLLM 客户端

职责：
- 绑定一个模型别名，初始化时从全局配置读取完整模型信息并预计算 API 调用参数
- 提供流式 / 非流式两种调用方式
- 接收已转换的 provider 格式 messages，直接调用 API
- 流式模式下负责 tool_call 的缓冲拼接和 thinking 的捕获

不负责：
- 配置加载（由 config.py 的 get_config() 处理）
- 消息格式转换（由 types.py 的 MessageConverter 处理）
"""

from __future__ import annotations

import json
from typing import AsyncIterator

import litellm

from basic_agent.models.config import get_config
from basic_agent.models.types import (
    StreamChunk,
    ChunkType,
    MessageConverter,
)


class LLMClient:
    """
    绑定一个模型别名的 LLM 客户端

    初始化时从全局共享配置中读取该别名对应模型的完整信息，
    预计算 API 调用参数，后续调用直接使用。

    使用方式：
        client = LLMClient("reasoning")

        # 通过 client.converter 转换消息
        litellm_msgs = client.converter.to_provider(messages)

        # 非流式
        raw_response = await client.chat(litellm_msgs)

        # 流式
        async for raw_chunk in client.chat_stream(litellm_msgs):
            ...
    """

    def __init__(self, model_alias: str):
        config = get_config()
        if model_alias not in config.models:
            raise ValueError(
                f"Model alias '{model_alias}' not found. "
                f"Available: {list(config.models.keys())}"
            )

        mc = config.models[model_alias]
        self.model_alias = model_alias
        self.provider = mc.provider
        self.max_tokens = mc.max_tokens
        self.converter = MessageConverter()

        # 预计算 API 基础参数，后续调用直接展开
        self._base_kwargs: dict = {"model": mc.litellm_model}
        if mc.api_base:
            self._base_kwargs["api_base"] = mc.api_base
        if mc.api_key:
            self._base_kwargs["api_key"] = mc.api_key

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> dict:
        """
        非流式调用

        Args:
            messages: 已转换为 provider 格式的消息列表
            tools: 已转换为 provider 格式的工具列表
            temperature: 温度参数
            max_tokens: 最大输出 token 数

        Returns:
            Provider 原始 response message dict
        """
        kwargs = {
            **self._base_kwargs,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if tools:
            kwargs["tools"] = tools
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        response = await litellm.acompletion(**kwargs)
        return response.choices[0].message.model_dump()

    async def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """
        流式调用

        Args:
            messages: 已转换为 provider 格式的消息列表
            tools: 已转换为 provider 格式的工具列表
            temperature: 温度参数
            max_tokens: 最大输出 token 数

        Yields:
            StreamChunk：THINKING（思考过程）、TEXT（文本增量）、
                        TOOL_USE（完整工具调用）、DONE（结束）
        """
        kwargs = {
            **self._base_kwargs,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        response = await litellm.acompletion(**kwargs)

        # 工具调用缓冲区
        tool_calls_buffer: dict[int, dict] = {}
        # 思考过程缓冲区
        thinking_parts: list[str] = []

        async for chunk in response:
            delta = chunk.choices[0].delta

            # 思考过程（DeepSeek reasoning_content / Claude thinking）
            reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "thinking", None)
            if reasoning:
                thinking_parts.append(reasoning)

            # 文本增量 → 立即 yield
            if delta.content:
                yield StreamChunk(type=ChunkType.TEXT, data=delta.content)

            # 工具调用 → 缓冲
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_buffer:
                        tool_calls_buffer[idx] = {"id": "", "name": "", "arguments": ""}
                    if tc.id:
                        tool_calls_buffer[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_calls_buffer[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            tool_calls_buffer[idx]["arguments"] += tc.function.arguments

        # 流结束后输出缓冲内容

        # 思考过程（如果有）
        if thinking_parts:
            yield StreamChunk(type=ChunkType.THINKING, data="".join(thinking_parts))

        # 工具调用（如果有）
        for idx in sorted(tool_calls_buffer.keys()):
            tc = tool_calls_buffer[idx]
            try:
                args = json.loads(tc["arguments"])
            except json.JSONDecodeError:
                args = {"_raw": tc["arguments"]}
            yield StreamChunk(
                type=ChunkType.TOOL_USE,
                data={"id": tc["id"], "name": tc["name"], "input": args},
            )

        yield StreamChunk(type=ChunkType.DONE, data="")
