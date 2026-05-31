"""
提示词注入模块测试脚本

测试内容：
1. PromptInjector 基本功能
2. 注入规则加载
3. 变量替换
4. 不同注入点的行为
5. 自定义处理函数

运行方式：
    conda activate BA_py311
    python tests/test_prompt_injection.py
"""

import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models.types import Message, new_uuid
from src.prompts.prompt import PromptInjector, InjectionPoint, InjectionRule


# ============================================================
# 测试工具
# ============================================================

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} — {detail}")


def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def _make_message(role: str, content: str, msg_type: str = "message") -> Message:
    """创建测试消息"""
    return Message(
        uuid=new_uuid(),
        role=role,
        content=content,
        type=msg_type,
    )


# ============================================================
# 1. 基本功能
# ============================================================


def test_basic_injection():
    section("1. 基本注入功能")

    injector = PromptInjector()

    # 添加规则
    injector.add_rule(InjectionRule(
        point=InjectionPoint.BEFORE_COMPACT,
        prompt_template="请保持角色 {character_name} 的语气。",
        variables={"character_name": "Alice"},
        priority=10,
    ))

    messages = [
        _make_message("user", "你好"),
        _make_message("assistant", "你好！"),
    ]

    result = injector.inject(messages, InjectionPoint.BEFORE_COMPACT)

    check("注入后消息数量增加", len(result) == 3, f"got {len(result)}")
    check("注入消息在开头", result[0].type == "prompt_injection")
    check("变量替换成功", "Alice" in result[0].content)
    check("原消息保留", result[1].content == "你好")


def test_multiple_rules():
    section("2. 多规则注入")

    injector = PromptInjector()

    # 添加多个规则
    injector.add_rule(InjectionRule(
        point=InjectionPoint.BEFORE_COMPACT,
        prompt_template="规则1: {var1}",
        variables={"var1": "值1"},
        priority=10,
    ))
    injector.add_rule(InjectionRule(
        point=InjectionPoint.BEFORE_COMPACT,
        prompt_template="规则2: {var2}",
        variables={"var2": "值2"},
        priority=20,  # 更高优先级
    ))

    messages = [_make_message("user", "测试")]

    result = injector.inject(messages, InjectionPoint.BEFORE_COMPACT)

    check("多规则注入", len(result) == 3, f"got {len(result)}")
    check("高优先级规则在前", "规则2" in result[0].content)
    check("低优先级规则在后", "规则1" in result[1].content)


# ============================================================
# 2. 变量替换
# ============================================================


def test_variable_replacement():
    section("3. 变量替换")

    injector = PromptInjector()

    # 设置全局变量
    injector.set_variable("scene", "森林")
    injector.set_variable("mood", "神秘")

    injector.add_rule(InjectionRule(
        point=InjectionPoint.BEFORE_COMPACT,
        prompt_template="当前场景: {scene}, 氛围: {mood}",
    ))

    messages = [_make_message("user", "测试")]

    result = injector.inject(messages, InjectionPoint.BEFORE_COMPACT)

    check("全局变量替换", "森林" in result[0].content)
    check("多个变量替换", "神秘" in result[0].content)


def test_batch_variables():
    section("4. 批量设置变量")

    injector = PromptInjector()

    injector.set_variables({
        "char": "Bob",
        "location": "城市",
    })

    injector.add_rule(InjectionRule(
        point=InjectionPoint.BEFORE_COMPACT,
        prompt_template="{char} 在 {location}",
    ))

    messages = [_make_message("user", "测试")]

    result = injector.inject(messages, InjectionPoint.BEFORE_COMPACT)

    check("批量变量替换", "Bob" in result[0].content and "城市" in result[0].content)


# ============================================================
# 3. 不同注入点
# ============================================================


def test_injection_points():
    section("5. 不同注入点")

    injector = PromptInjector()

    # BEFORE_COMPACT
    injector.add_rule(InjectionRule(
        point=InjectionPoint.BEFORE_COMPACT,
        prompt_template="压缩前提示",
        priority=10,
    ))

    # AFTER_COMPACT
    injector.add_rule(InjectionRule(
        point=InjectionPoint.AFTER_COMPACT,
        prompt_template="压缩后提示",
        priority=10,
    ))

    messages = [
        _make_message("user", "消息1"),
        _make_message("assistant", "回复1"),
    ]

    # 测试 BEFORE_COMPACT
    result_before = injector.inject(messages, InjectionPoint.BEFORE_COMPACT)
    check("BEFORE_COMPACT 在开头注入", result_before[0].content == "压缩前提示")

    # 测试 AFTER_COMPACT
    result_after = injector.inject(messages, InjectionPoint.AFTER_COMPACT)
    check("AFTER_COMPACT 在末尾注入", result_after[-1].content == "压缩后提示")


def test_user_input_injection():
    section("6. 用户输入注入点")

    injector = PromptInjector()

    injector.add_rule(InjectionRule(
        point=InjectionPoint.ON_USER_INPUT,
        prompt_template="用户输入提示",
        priority=10,
    ))

    messages = [
        _make_message("user", "第一条消息"),
        _make_message("assistant", "回复"),
        _make_message("user", "第二条消息"),
    ]

    result = injector.inject(messages, InjectionPoint.ON_USER_INPUT)

    check("ON_USER_INPUT 在最后一条用户消息前注入", result[2].content == "用户输入提示")
    check("原用户消息位置正确", result[3].content == "第二条消息")


# ============================================================
# 4. 自定义处理函数
# ============================================================


def test_custom_handler():
    section("7. 自定义处理函数")

    injector = PromptInjector()

    # 注册自定义处理函数
    def custom_handler(messages):
        # 在每条消息前添加标记
        return messages

    injector.register_handler(InjectionPoint.BEFORE_COMPACT, custom_handler)

    messages = [_make_message("user", "测试")]

    result = injector.inject(messages, InjectionPoint.BEFORE_COMPACT)

    check("自定义处理函数执行", len(result) == 1)  # 没有规则，只有自定义处理


# ============================================================
# 5. 规则文件加载
# ============================================================


def test_load_rules():
    section("8. 从文件加载规则")

    # 创建临时规则文件
    rules_data = {
        "rules": [
            {
                "point": "before_compact",
                "prompt_template": "从文件加载的规则: {var}",
                "variables": {"var": "测试值"},
                "priority": 5,
            }
        ]
    }

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump(rules_data, f, ensure_ascii=False)
        temp_path = f.name

    try:
        injector = PromptInjector()
        injector.load_rules(temp_path)

        messages = [_make_message("user", "测试")]
        result = injector.inject(messages, InjectionPoint.BEFORE_COMPACT)

        check("从文件加载规则", len(result) == 2, f"got {len(result)}")
        check("规则内容正确", "测试值" in result[0].content)
    finally:
        Path(temp_path).unlink()


# ============================================================
# 6. 清空功能
# ============================================================


def test_clear():
    section("9. 清空功能")

    injector = PromptInjector()

    injector.add_rule(InjectionRule(
        point=InjectionPoint.BEFORE_COMPACT,
        prompt_template="测试规则",
    ))
    injector.set_variable("test", "value")

    check("添加规则后有规则", len(injector.get_rules()) == 1)

    injector.clear_rules()
    check("清空规则后无规则", len(injector.get_rules()) == 0)

    injector.clear_variables()
    check("清空变量后无变量", len(injector._variables) == 0)


# ============================================================
# 主测试函数
# ============================================================


def main():
    print("\n" + "="*60)
    print("  BasicAgent v1.1 提示词注入模块测试")
    print("="*60)

    test_basic_injection()
    test_multiple_rules()
    test_variable_replacement()
    test_batch_variables()
    test_injection_points()
    test_user_input_injection()
    test_custom_handler()
    test_load_rules()
    test_clear()

    # 汇总
    print(f"\n{'='*60}")
    print(f"  测试汇总: {passed} 通过, {failed} 失败")
    print(f"{'='*60}")

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
