"""
角色扮演对话测试

模拟游戏中的 NPC 角色对话，测试 chat 的流式输出和输出质量。

测试场景：
1. 初次见面打招呼
2. 询问商品信息
3. 讨价还价
4. 闲聊（角色记忆）
5. 离开告别

运行方式：
    conda activate BA_py311
    python tests/test_roleplay.py
"""

import sys
import asyncio
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.daemon import SessionManager


# ============================================================
# 角色设定
# ============================================================

CHARACTER_NAME = "莉莉安"
PLAYER_NICKNAME = "旅行者"

SYSTEM_PROMPT = f"""你现在扮演一个游戏角色，严格遵守以下人设：

【基本信息】
- 名字：{CHARACTER_NAME}
- 身份：星落镇的魔法药剂商人
- 年龄：外表看起来 20 岁左右，实际已经活了 300 年
- 种族：半精灵

【性格】
- 开朗热情，喜欢开玩笑
- 对客人非常殷勤，会主动推销商品
- 有点小财迷，但心地善良
- 偶尔会透露一些古老的传说和秘密

【说话风格】
- 称呼玩家为"{PLAYER_NICKNAME}"
- 语气活泼，喜欢用语气词（诶嘿、哎呀、嘻嘻）
- 偶尔夹杂一些魔法相关的比喻
- 回复简短，每次不超过 3 句话（模拟游戏对话）
- 不使用 markdown 格式，纯文本对话

【记忆】
- 记住和{PLAYER_NICKNAME}的所有对话内容
- 如果{PLAYER_NICKNAME}提过之前的事，要表现出记得

【禁忌】
- 不承认自己是 AI 或语言模型
- 不跳出角色
- 不使用英文"""

# 测试用例：(用户输入, 期望的输出特征)
TEST_CASES = [
    {
        "input": "你好，你是谁？",
        "expect": "应该自我介绍为莉莉安，称呼玩家为旅行者",
    },
    {
        "input": "你这里有什么好东西卖？",
        "expect": "应该介绍魔法药剂商品，语气热情",
    },
    {
        "input": "治疗药水多少钱？太贵了吧，便宜点呗",
        "expect": "应该讨价还价，表现出财迷但可能让步",
    },
    {
        "input": "你在这里卖了多久的药了？",
        "expect": "应该提到自己活了 300 年，可能讲一些过去的事",
    },
    {
        "input": "上次你跟我说的那个古代传说是真的吗？",
        "expect": "应该延续之前的对话（即使没有上次对话，也要合理回应）",
    },
    {
        "input": "好的，谢谢你莉莉安，我先走了",
        "expect": "应该道别，表现出热情和期待下次光临",
    },
]


# ============================================================
# 测试逻辑
# ============================================================


async def run_roleplay_test():
    print("=" * 60)
    print(f"  角色扮演测试：{CHARACTER_NAME}（魔法药剂商人）")
    print(f"  玩家昵称：{PLAYER_NICKNAME}")
    print("=" * 60)

    manager = SessionManager()
    session_id = await manager.create_session(
        model_alias="reasoning",
        system_prompt=SYSTEM_PROMPT,
    )
    print(f"\n  会话已创建: {session_id[:8]}...")
    print(f"  测试用例数: {len(TEST_CASES)}\n")

    results = []

    for i, case in enumerate(TEST_CASES, 1):
        user_input = case["input"]
        expect = case["expect"]

        print(f"{'─' * 60}")
        print(f"  [{i}/{len(TEST_CASES)}] {PLAYER_NICKNAME}: {user_input}")
        print(f"  期望: {expect}")
        print(f"{'─' * 60}")
        print(f"  {CHARACTER_NAME}: ", end="", flush=True)

        # 流式输出
        tokens = []
        t0 = time.time()
        first_token_time = None

        async for chunk in manager.chat(session_id, user_input):
            if isinstance(chunk, str):
                if first_token_time is None:
                    first_token_time = time.time() - t0
                tokens.append(chunk)
                print(chunk, end="", flush=True)

        elapsed = time.time() - t0
        full_text = "".join(tokens)

        print(f"\n")
        print(f"  [耗时] 首token: {first_token_time:.2f}s | 总耗时: {elapsed:.2f}s | token数: {len(tokens)}")
        print()

        results.append({
            "turn": i,
            "input": user_input,
            "output": full_text,
            "first_token_latency": first_token_time,
            "total_latency": elapsed,
            "token_count": len(tokens),
        })

    # 汇总
    print("=" * 60)
    print("  测试汇总")
    print("=" * 60)

    for r in results:
        print(f"  第{r['turn']}轮 | 首token {r['first_token_latency']:.2f}s | "
              f"总耗时 {r['total_latency']:.2f}s | {r['token_count']} tokens | "
              f"{r['output'][:30]}...")

    avg_first = sum(r["first_token_latency"] for r in results) / len(results)
    avg_total = sum(r["total_latency"] for r in results) / len(results)
    print(f"\n  平均首 token 延迟: {avg_first:.2f}s")
    print(f"  平均总耗时: {avg_total:.2f}s")

    # 验证多轮记忆
    engine = manager.sessions[session_id]
    msg_count = len(engine.mutable_messages)
    print(f"  累计消息数: {msg_count} 条（{len(TEST_CASES)} 轮对话）")

    # 清理
    await manager.delete(session_id)
    print(f"\n  会话已删除，测试完成。\n")


# ============================================================
# 主入口
# ============================================================


if __name__ == "__main__":
    asyncio.run(run_roleplay_test())
