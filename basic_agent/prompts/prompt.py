# -*- coding: utf-8 -*-
"""
提示词注入模块

职责：
- 动态注入提示词到对话中
- 支持变量替换（如 {character_name}, {scene} 等）
- 支持条件注入（根据上下文决定是否注入）
- 支持多个注入点（before_compact, after_compact, on_scene_change 等）

设计原则：
- 提示词注入是无状态的，每次调用独立处理
- 注入的提示词作为特殊消息插入到消息列表中
- 支持配置文件定义注入规则
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from basic_agent.models.types import Message, new_uuid


class InjectionPoint(str, Enum):
    """注入点枚举"""
    BEFORE_COMPACT = "before_compact"      # 压缩前注入
    AFTER_COMPACT = "after_compact"        # 压缩后注入
    ON_SCENE_CHANGE = "on_scene_change"    # 场景切换时注入
    ON_USER_INPUT = "on_user_input"        # 用户输入时注入
    ON_ASSISTANT_RESPONSE = "on_assistant_response"  # 助手回复前注入


@dataclass
class InjectionRule:
    """注入规则"""
    point: InjectionPoint           # 注入点
    prompt_template: str            # 提示词模板
    variables: dict[str, str] = field(default_factory=dict)  # 变量值
    condition: Optional[str] = None  # 条件表达式（暂不实现，预留接口）
    priority: int = 0               # 优先级（数字越大优先级越高）


class PromptInjector:
    """
    提示词注入器

    使用方式：
        injector = PromptInjector()
        injector.load_rules("config/prompts/injection_rules.json")
        injector.set_variable("character_name", "Alice")

        # 在压缩前注入
        messages = injector.inject(messages, InjectionPoint.BEFORE_COMPACT)
    """

    def __init__(self):
        self._rules: list[InjectionRule] = []
        self._variables: dict[str, str] = {}
        self._custom_handlers: dict[InjectionPoint, Callable] = {}

    def load_rules(self, rules_path: str) -> None:
        """
        从 JSON 文件加载注入规则

        JSON 格式：
        {
            "rules": [
                {
                    "point": "before_compact",
                    "prompt_template": "请保持角色 {character_name} 的语气...",
                    "variables": {"character_name": "Alice"},
                    "priority": 10
                }
            ]
        }
        """
        path = Path(rules_path)
        if not path.exists():
            return

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for rule_data in data.get("rules", []):
            rule = InjectionRule(
                point=InjectionPoint(rule_data["point"]),
                prompt_template=rule_data["prompt_template"],
                variables=rule_data.get("variables", {}),
                condition=rule_data.get("condition"),
                priority=rule_data.get("priority", 0),
            )
            self._rules.append(rule)

        # 按优先级排序
        self._rules.sort(key=lambda r: r.priority, reverse=True)

    def add_rule(self, rule: InjectionRule) -> None:
        """添加单条注入规则"""
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority, reverse=True)

    def set_variable(self, name: str, value: str) -> None:
        """设置变量值"""
        self._variables[name] = value

    def set_variables(self, variables: dict[str, str]) -> None:
        """批量设置变量值"""
        self._variables.update(variables)

    def register_handler(
        self, point: InjectionPoint, handler: Callable[[list[Message]], list[Message]]
    ) -> None:
        """
        注册自定义处理函数

        Args:
            point: 注入点
            handler: 处理函数，接收消息列表，返回处理后的消息列表
        """
        self._custom_handlers[point] = handler

    def inject(
        self,
        messages: list[Message],
        point: InjectionPoint,
        context: Optional[dict[str, Any]] = None,
    ) -> list[Message]:
        """
        在指定注入点注入提示词

        Args:
            messages: 消息列表
            point: 注入点
            context: 额外上下文（可选）

        Returns:
            注入后的消息列表
        """
        # 合并变量：实例变量 + 规则变量 + 上下文变量
        all_variables = dict(self._variables)
        if context:
            all_variables.update(context)

        # 找到适用于该注入点的规则
        applicable_rules = [r for r in self._rules if r.point == point]

        # 如果没有规则，直接返回
        if not applicable_rules and point not in self._custom_handlers:
            return messages

        # 执行自定义处理函数（如果有）
        if point in self._custom_handlers:
            messages = self._custom_handlers[point](messages)

        # 注入提示词
        # 收集所有需要注入的消息
        injection_messages = []
        for rule in applicable_rules:
            # 合并规则变量和全局变量
            rule_variables = dict(all_variables)
            rule_variables.update(rule.variables)

            # 替换变量
            prompt_text = rule.prompt_template
            for var_name, var_value in rule_variables.items():
                prompt_text = prompt_text.replace(f"{{{var_name}}}", var_value)

            # 创建注入消息
            injection_msg = Message(
                uuid=new_uuid(),
                role="system",
                content=prompt_text,
                type="prompt_injection",
                timestamp=0.0,  # 注入消息不参与时间计算
            )
            injection_messages.append(injection_msg)

        # 根据注入点决定插入位置
        if point == InjectionPoint.BEFORE_COMPACT:
            # 在压缩前注入：插入到消息列表开头（保持优先级顺序）
            messages = injection_messages + messages
        elif point == InjectionPoint.AFTER_COMPACT:
            # 在压缩后注入：插入到消息列表末尾
            messages = messages + injection_messages
        elif point == InjectionPoint.ON_SCENE_CHANGE:
            # 场景切换时注入：插入到消息列表末尾
            messages = messages + injection_messages
        elif point == InjectionPoint.ON_USER_INPUT:
            # 用户输入时注入：插入到最后一条用户消息之前
            for i in range(len(messages) - 1, -1, -1):
                if messages[i].role == "user":
                    for j, msg in enumerate(injection_messages):
                        messages.insert(i + j, msg)
                    break
            else:
                messages.extend(injection_messages)
        elif point == InjectionPoint.ON_ASSISTANT_RESPONSE:
            # 助手回复前注入：插入到消息列表末尾
            messages = messages + injection_messages

        return messages

    def inject_for_compact(
        self,
        messages: list[Message],
        context: Optional[dict[str, Any]] = None,
    ) -> list[Message]:
        """
        为压缩操作注入提示词的便捷方法

        在压缩前注入 BEFORE_COMPACT，在压缩后注入 AFTER_COMPACT
        """
        messages = self.inject(messages, InjectionPoint.BEFORE_COMPACT, context)
        return messages

    def clear_rules(self) -> None:
        """清空所有规则"""
        self._rules.clear()

    def clear_variables(self) -> None:
        """清空所有变量"""
        self._variables.clear()

    def get_rules(self) -> list[InjectionRule]:
        """获取所有规则"""
        return list(self._rules)
