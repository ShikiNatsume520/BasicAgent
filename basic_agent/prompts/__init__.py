# -*- coding: utf-8 -*-
"""
提示词注入模块

职责：
- 动态注入提示词到对话中
- 支持变量替换
- 支持条件注入
"""

from basic_agent.prompts.prompt import PromptInjector, InjectionPoint

__all__ = ["PromptInjector", "InjectionPoint"]
