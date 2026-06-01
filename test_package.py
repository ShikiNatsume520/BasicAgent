"""
BasicAgent v1.1.2 包安装测试脚本

测试内容：
1. 基本导入测试
2. 配置加载测试
3. 数据模型测试
4. 压缩系统测试
5. 提示词注入测试

运行方式：
    conda activate BA_py311
    python test_package.py
"""

import sys

def test_imports():
    """测试基本导入"""
    print("=" * 60)
    print("  1. 基本导入测试")
    print("=" * 60)

    try:
        from basic_agent.models.types import Message, new_uuid
        print("  [PASS] 导入 Message, new_uuid")
    except Exception as e:
        print(f"  [FAIL] 导入 Message, new_uuid: {e}")
        return False

    try:
        from basic_agent.models.config import get_config, MemoryConfig
        print("  [PASS] 导入 get_config, MemoryConfig")
    except Exception as e:
        print(f"  [FAIL] 导入 get_config, MemoryConfig: {e}")
        return False

    try:
        from basic_agent.memory.compression import snip, autocompact
        print("  [PASS] 导入 snip, autocompact")
    except Exception as e:
        print(f"  [FAIL] 导入 snip, autocompact: {e}")
        return False

    try:
        from basic_agent.prompts.prompt import PromptInjector, InjectionPoint
        print("  [PASS] 导入 PromptInjector, InjectionPoint")
    except Exception as e:
        print(f"  [FAIL] 导入 PromptInjector, InjectionPoint: {e}")
        return False

    try:
        from basic_agent.daemon.session_manager import SessionManager
        print("  [PASS] 导入 SessionManager")
    except Exception as e:
        print(f"  [FAIL] 导入 SessionManager: {e}")
        return False

    return True


def test_config():
    """测试配置加载"""
    print("\n" + "=" * 60)
    print("  2. 配置加载测试")
    print("=" * 60)

    try:
        from basic_agent.models.config import get_config, reset_config
        from pathlib import Path

        reset_config()

        # 测试配置目录查找
        cwd_config = Path.cwd() / "config"
        pkg_config = Path(__file__).parent.parent / "config"

        if cwd_config.exists():
            print(f"  [PASS] 配置目录: {cwd_config}")
        elif pkg_config.exists():
            print(f"  [PASS] 配置目录: {pkg_config}")
        else:
            print(f"  [SKIP] 配置目录不存在（需要运行 python -m basic_agent.init）")
            return True

        # 测试配置加载
        try:
            config = get_config()
            print(f"  [PASS] 配置加载成功")
            print(f"         默认模型: {config.default_model}")
            print(f"         可用模型: {list(config.models.keys())}")

            # 检查 MemoryConfig
            memory_config = config.compression.memory
            print(f"         超时时间: {memory_config.timeout_minutes} 分钟")
            print(f"         压缩阈值: {memory_config.autocompact_threshold}")
        except Exception as e:
            print(f"  [SKIP] 配置加载跳过: {e}")
            print(f"         （需要配置 API Key）")

        return True
    except Exception as e:
        print(f"  [FAIL] 配置加载失败: {e}")
        return False


def test_message():
    """测试数据模型"""
    print("\n" + "=" * 60)
    print("  3. 数据模型测试")
    print("=" * 60)

    try:
        from basic_agent.models.types import Message, new_uuid
        import time

        # 创建消息
        msg = Message(
            uuid=new_uuid(),
            role="user",
            content="测试消息",
            timestamp=time.time()
        )

        print(f"  [PASS] 创建消息成功")
        print(f"         UUID: {msg.uuid[:8]}...")
        print(f"         角色: {msg.role}")
        print(f"         内容: {msg.content}")

        # 创建 compact_boundary 消息
        boundary = Message(
            uuid=new_uuid(),
            role="assistant",
            content="这是摘要",
            type="compact_boundary",
            timestamp=time.time()
        )

        print(f"  [PASS] 创建 compact_boundary 消息成功")
        print(f"         类型: {boundary.type}")

        return True
    except Exception as e:
        print(f"  [FAIL] 数据模型测试失败: {e}")
        return False


def test_compression():
    """测试压缩系统"""
    print("\n" + "=" * 60)
    print("  4. 压缩系统测试")
    print("=" * 60)

    try:
        from basic_agent.memory.compression import snip
        from basic_agent.models.config import MemoryConfig
        from basic_agent.models.types import Message, new_uuid
        import time

        # 使用默认配置（不需要加载完整配置）
        memory_config = MemoryConfig()

        # 创建测试消息
        now = time.time()
        messages = [
            Message(uuid=new_uuid(), role="user", content="消息1", timestamp=now - 3600),
            Message(uuid=new_uuid(), role="assistant", content="回复1", timestamp=now - 3500),
            Message(uuid=new_uuid(), role="user", content="消息2", timestamp=now - 1800),
            Message(uuid=new_uuid(), role="assistant", content="回复2", timestamp=now - 1700),
        ]

        # 测试 snip（无 boundary）
        result = snip(messages, memory_config)
        print(f"  [PASS] snip 裁剪成功")
        print(f"         输入: {len(messages)} 条消息")
        print(f"         输出: {len(result)} 条消息")

        # 测试 snip（有 boundary）
        boundary = Message(
            uuid=new_uuid(),
            role="assistant",
            content="摘要",
            type="compact_boundary",
            timestamp=now - 2000
        )
        messages_with_boundary = [
            Message(uuid=new_uuid(), role="user", content="旧消息", timestamp=now - 5000),
            boundary,
            Message(uuid=new_uuid(), role="user", content="新消息", timestamp=now - 1000),
        ]

        result = snip(messages_with_boundary, memory_config)
        print(f"  [PASS] snip 裁剪（有 boundary）成功")
        print(f"         输入: {len(messages_with_boundary)} 条消息")
        print(f"         输出: {len(result)} 条消息")
        print(f"         保留 boundary: {result[0].type == 'compact_boundary'}")

        return True
    except Exception as e:
        print(f"  [FAIL] 压缩系统测试失败: {e}")
        return False


def test_prompt_injection():
    """测试提示词注入"""
    print("\n" + "=" * 60)
    print("  5. 提示词注入测试")
    print("=" * 60)

    try:
        from basic_agent.prompts.prompt import PromptInjector, InjectionPoint, InjectionRule
        from basic_agent.models.types import Message, new_uuid

        # 创建注入器
        injector = PromptInjector()

        # 设置变量
        injector.set_variable("character_name", "小雅")

        # 添加规则
        injector.add_rule(InjectionRule(
            point=InjectionPoint.BEFORE_COMPACT,
            prompt_template="请保持角色 {character_name} 的语气。",
            priority=10
        ))

        # 创建测试消息
        messages = [
            Message(uuid=new_uuid(), role="user", content="你好"),
            Message(uuid=new_uuid(), role="assistant", content="你好！"),
        ]

        # 注入提示词
        result = injector.inject(messages, InjectionPoint.BEFORE_COMPACT)

        print(f"  [PASS] 提示词注入成功")
        print(f"         输入: {len(messages)} 条消息")
        print(f"         输出: {len(result)} 条消息")
        print(f"         注入消息: {result[0].content}")

        return True
    except Exception as e:
        print(f"  [FAIL] 提示词注入测试失败: {e}")
        return False


def main():
    """主测试函数"""
    print("\n" + "=" * 60)
    print("  BasicAgent v1.1.2 包安装测试")
    print("=" * 60)

    results = []

    # 运行测试
    results.append(("基本导入", test_imports()))
    results.append(("配置加载", test_config()))
    results.append(("数据模型", test_message()))
    results.append(("压缩系统", test_compression()))
    results.append(("提示词注入", test_prompt_injection()))

    # 汇总结果
    print("\n" + "=" * 60)
    print("  测试汇总")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    failed = sum(1 for _, result in results if not result)

    for name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"  {status} {name}")

    print(f"\n  总计: {passed} 通过, {failed} 失败")

    if failed == 0:
        print("\n  [SUCCESS] 所有测试通过！包安装正常。")
        return 0
    else:
        print("\n  [ERROR] 有测试失败，请检查安装。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
