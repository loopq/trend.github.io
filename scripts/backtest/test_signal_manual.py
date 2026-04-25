"""手动测试脚本：覆盖状态机 6 个边界用例（§7 Step 2）。

运行：`python scripts/backtest/test_signal_manual.py`
全部通过才算合格。
"""
from __future__ import annotations

import sys

from scripts.backtest.signal import (
    DirectionState,
    classify_bar,
    decide_action,
    BUY,
    SELL,
    UP,
    DOWN,
)


def _run(name: str, bars, initial_state=None, initial_position=0.0):
    """跑一段 K 线序列，返回 (动作序列, 最终 state)。

    bars: List[(high, low, ma20)]
    """
    state = DirectionState(state=initial_state)
    position = initial_position
    actions = []
    for (h, l, ma) in bars:
        new_dir, flipped = state.update(h, l, ma)
        action = decide_action(flipped, new_dir, position)
        if action == BUY:
            position = 1.0
        elif action == SELL:
            position = 0.0
        actions.append(action)
    return actions, state.state


def _assert(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        sys.exit(1)


def test_first_up_triggers_buy():
    # K 线整根在 MA20 上方 → 首次 UP → BUY
    actions, final = _run("first_up", [(105, 101, 100)])
    _assert(actions == [BUY], f"actions={actions}")
    _assert(final == UP, f"final={final}")
    print("  PASS: first UP → BUY")


def test_first_down_no_action():
    # K 线整根在 MA20 下方 → 首次 DOWN → 无动作（只做多）
    actions, final = _run("first_down", [(99, 95, 100)])
    _assert(actions == [None], f"actions={actions}")
    _assert(final == DOWN, f"final={final}")
    print("  PASS: first DOWN → no action (long-only)")


def test_same_direction_hold():
    # 持续 UP → 首次 BUY，后续无动作
    bars = [(105, 101, 100), (106, 102, 100), (107, 103, 100)]
    actions, _ = _run("same_dir", bars)
    _assert(actions == [BUY, None, None], f"actions={actions}")
    print("  PASS: same direction UP → BUY then hold")


def test_touching_skipped():
    # UP → 触碰（state 不变）→ UP（相同方向，不触发）
    bars = [
        (105, 101, 100),  # UP, BUY
        (102, 98, 100),   # 触碰（low<=ma<=high）
        (108, 102, 100),  # UP again, same direction, no action
    ]
    actions, final = _run("touching", bars)
    _assert(actions == [BUY, None, None], f"actions={actions}")
    _assert(final == UP, f"final={final}")
    print("  PASS: UP → touch → UP stays UP, no re-buy")


def test_up_to_down_sell():
    # UP → DOWN 翻转 → SELL
    bars = [(105, 101, 100), (99, 95, 100)]
    actions, final = _run("up_to_down", bars)
    _assert(actions == [BUY, SELL], f"actions={actions}")
    _assert(final == DOWN, f"final={final}")
    print("  PASS: UP → DOWN → SELL")


def test_down_to_up_buy():
    # DOWN（预热已设）→ UP 翻转 → BUY
    bars = [(99, 95, 100), (105, 101, 100)]
    actions, final = _run("down_to_up", bars, initial_state=DOWN, initial_position=0.0)
    _assert(actions == [None, BUY], f"actions={actions}")
    _assert(final == UP, f"final={final}")
    print("  PASS: DOWN → UP → BUY")


def test_precondition_buy_requires_flat():
    # V2 前置：已持仓时出现 UP 信号不应重复 BUY
    # UP → SELL 后的触碰期 → UP（同方向，或新一次翻转都不应再 BUY，因为这里是 UP 信号）
    # 构造：state=UP → DOWN → 触碰 → DOWN（position=0 时不 SELL）
    bars = [
        (105, 101, 100),  # UP, BUY (pos=1)
        (99, 95, 100),    # DOWN, SELL (pos=0)
        (102, 98, 100),   # 触碰，无动作
        (99.5, 95, 100),  # DOWN, 但 pos=0 且 state 已 DOWN 同方向 → 无动作
    ]
    actions, _ = _run("precondition_sell_flat", bars)
    _assert(actions == [BUY, SELL, None, None], f"actions={actions}")
    print("  PASS: SELL requires shares>0, no re-SELL when flat")


def test_precondition_buy_no_double_buy():
    # UP → 触碰 → 不应再 BUY（同方向 UP 延续）
    bars = [(105, 101, 100), (102, 98, 100), (110, 105, 100)]
    actions, _ = _run("no_double_buy", bars)
    _assert(actions == [BUY, None, None], f"actions={actions}")
    print("  PASS: BUY requires shares==0, no re-BUY when holding")


def test_boundary_equal_triggers_touch():
    # low == ma20 → 算触碰，不是 UP
    _assert(classify_bar(105, 100, 100) is None, "low==ma20 should be touch")
    # high == ma20 → 算触碰，不是 DOWN
    _assert(classify_bar(100, 95, 100) is None, "high==ma20 should be touch")
    # 严格 low > ma20 → UP
    _assert(classify_bar(105, 100.01, 100) == UP, "low>ma20 should be UP")
    # 严格 high < ma20 → DOWN
    _assert(classify_bar(99.99, 95, 100) == DOWN, "high<ma20 should be DOWN")
    print("  PASS: boundary equals are touches, strict inequality is clean")


def main():
    print("Running Signal module manual tests...")
    test_first_up_triggers_buy()
    test_first_down_no_action()
    test_same_direction_hold()
    test_touching_skipped()
    test_up_to_down_sell()
    test_down_to_up_buy()
    test_precondition_buy_requires_flat()
    test_precondition_buy_no_double_buy()
    test_boundary_equal_triggers_touch()
    print("\nAll tests passed.")


if __name__ == "__main__":
    main()
