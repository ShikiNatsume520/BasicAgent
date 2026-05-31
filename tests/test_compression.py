"""
压缩管线测试脚本

测试内容：
1. snip 裁剪逻辑
2. microcompact 占位函数
3. autocompact 触发条件
4. compact_boundary 消息生成
5. timeout 裁剪

运行方式：
    conda activate BA_py311
    python tests/test_compression.py
"""

import sys
import asyncio
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models.types import Message, new_uuid
from src.models.config import get_config, reset_config, MemoryConfig
from src.memory.compression import snip, microcompact, autocompact


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


def _make_message(role: str, content: str, msg_type: str = "message", timestamp: float = None) -> Message:
    """创建测试消息"""
    return Message(
        uuid=new_uuid(),
        role=role,
        content=content,
        type=msg_type,
        timestamp=timestamp or time.time(),
    )


# ============================================================
# 1. snip 裁剪逻辑
# ============================================================


def test_snip_basic():
    section("1. snip 基本裁剪")

    # 创建测试消息
    now = time.time()
    messages = [
        _make_message("user", "消息1", timestamp=now - 3600),  # 1小时前
        _make_message("assistant", "回复1", timestamp=now - 3500),
        _make_message("user", "消息2", timestamp=now - 1800),  # 30分钟前
        _make_message("assistant", "回复2", timestamp=now - 1700),
        _make_message("user", "消息3", timestamp=now - 600),   # 10分钟前
        _make_message("assistant", "回复3", timestamp=now - 500),
    ]

    config = MemoryConfig(timeout_minutes=0)  # 禁用时间裁剪

    # 没有 boundary 时，返回所有消息
    result = snip(messages, config)
    check("没有 boundary 时返回所有消息", len(result) == 6, f"got {len(result)}")

    # 添加 boundary
    boundary = _make_message("assistant", "这是摘要", msg_type="compact_boundary", timestamp=now - 2000)
    messages_with_boundary = [
        _make_message("user", "旧消息1", timestamp=now - 5000),
        _make_message("assistant", "旧回复1", timestamp=now - 4900),
        boundary,
        _make_message("user", "新消息1", timestamp=now - 1000),
        _make_message("assistant", "新回复1", timestamp=now - 900),
    ]

    result = snip(messages_with_boundary, config)
    check("裁剪 boundary 之前的消息", len(result) == 3, f"got {len(result)}")
    check("保留 boundary 消息", result[0].type == "compact_boundary")
    check("保留 boundary 之后的消息", result[1].content == "新消息1")


def test_snip_timeout():
    section("2. snip 时间裁剪")

    now = time.time()
    config = MemoryConfig(timeout_minutes=30)  # 30分钟超时

    # 创建消息：boundary + 超时消息 + 新消息
    boundary = _make_message("assistant", "这是摘要", msg_type="compact_boundary", timestamp=now - 3600)
    messages = [
        boundary,
        _make_message("user", "超时消息1", timestamp=now - 3600),  # 1小时前，超时
        _make_message("assistant", "超时回复1", timestamp=now - 3500),  # 超时
        _make_message("user", "新消息1", timestamp=now - 600),   # 10分钟前，未超时
        _make_message("assistant", "新回复1", timestamp=now - 500),  # 未超时
    ]

    result = snip(messages, config)
    check("保留 boundary", result[0].type == "compact_boundary")
    check("裁剪超时消息", len(result) == 3, f"got {len(result)}")
    check("保留未超时消息", result[1].content == "新消息1")


def test_snip_empty():
    section("3. snip 空消息处理")

    config = MemoryConfig()

    result = snip([], config)
    check("空消息列表返回空", len(result) == 0)


def test_snip_single_boundary():
    section("4. snip 单个 boundary")

    now = time.time()
    config = MemoryConfig(timeout_minutes=0)

    boundary = _make_message("assistant", "这是摘要", msg_type="compact_boundary", timestamp=now)
    result = snip([boundary], config)
    check("单个 boundary 返回自身", len(result) == 1)
    check("保留 boundary 类型", result[0].type == "compact_boundary")


# ============================================================
# 2. microcompact 占位函数
# ============================================================


def test_microcompact():
    section("5. microcompact 占位函数")

    config = MemoryConfig()
    messages = [
        _make_message("user", "测试消息"),
        _make_message("assistant", "测试回复"),
    ]

    result = microcompact(messages, config)
    check("microcompact 返回原消息", result == messages)


# ============================================================
# 3. autocompact 异步测试
# ============================================================


async def test_autocompact_no_compress():
    section("6. autocompact 不触发压缩")

    config = MemoryConfig(autocompact_threshold=0.8)

    # 创建少量消息（不会触发压缩）
    messages = [
        _make_message("user", "你好"),
        _make_message("assistant", "你好！"),
    ]

    # Mock LLM client
    class MockStreamChunk:
        def __init__(self, chunk_type, data):
            self.type = chunk_type
            self.data = data

    class MockLLMClient:
        max_tokens = 1000000
        async def chat_stream(self, messages):
            yield MockStreamChunk('text', '摘要')

    llm_client = MockLLMClient()

    result_messages, compact_boundary = await autocompact(
        messages, "你是一个助手。", config, llm_client
    )

    check("不触发压缩时返回原消息", len(result_messages) == 2)
    check("不触发压缩时无 boundary", compact_boundary is None)


async def test_autocompact_with_compress():
    section("7. autocompact 触发压缩")

    # 设置低阈值以触发压缩
    config = MemoryConfig(autocompact_threshold=0.001)  # 极低阈值

    # 创建足够多的消息以触发压缩
    messages = []
    for i in range(100):
        messages.append(_make_message("user", f"消息{i} " * 100))
        messages.append(_make_message("assistant", f"回复{i} " * 100))

    # Mock LLM client
    class MockStreamChunk:
        def __init__(self, chunk_type, data):
            self.type = chunk_type
            self.data = data

    class MockLLMClient:
        max_tokens = 1000000
        async def chat_stream(self, messages):
            yield MockStreamChunk('text', '这是压缩后的摘要')

    llm_client = MockLLMClient()

    result_messages, compact_boundary = await autocompact(
        messages, "你是一个助手。", config, llm_client
    )

    check("触发压缩时返回 boundary", compact_boundary is not None)
    if compact_boundary:
        check("boundary 类型正确", compact_boundary.type == "compact_boundary")
        check("boundary 包含摘要", "摘要" in compact_boundary.content)
        check("结果包含 boundary", result_messages[0].type == "compact_boundary")


# ============================================================
# 主测试函数
# ============================================================


async def main():
    print("\n" + "="*60)
    print("  BasicAgent v1.1 压缩管线测试")
    print("="*60)

    # 同步测试
    test_snip_basic()
    test_snip_timeout()
    test_snip_empty()
    test_snip_single_boundary()
    test_microcompact()

    # 异步测试
    await test_autocompact_no_compress()
    await test_autocompact_with_compress()

    # 汇总
    print(f"\n{'='*60}")
    print(f"  测试汇总: {passed} 通过, {failed} 失败")
    print(f"{'='*60}")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
