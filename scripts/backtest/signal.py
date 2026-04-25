"""方向状态机。classify_bar 纯函数 + DirectionState。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

UP = "UP"
DOWN = "DOWN"
BUY = "BUY"
SELL = "SELL"


def classify_bar(high: float, low: float, ma20: Optional[float]) -> Optional[str]:
    """返回 'UP'（干净-上）/ 'DOWN'（干净-下）/ None（触碰或 MA20 未就绪）。

    边界（§2.1）：
        干净-上：low > ma20
        干净-下：high < ma20
        触碰：low <= ma20 <= high（含边界）
    """
    if ma20 is None:
        return None
    if low > ma20:
        return UP
    if high < ma20:
        return DOWN
    return None


@dataclass
class DirectionState:
    """单一时间维度的方向状态。"""
    state: Optional[str] = None  # UP / DOWN / None

    def update(self, high: float, low: float, ma20: Optional[float]) -> Tuple[Optional[str], bool]:
        """更新状态。

        返回 (new_dir, flipped)：
            new_dir: 当前 bar 的干净方向（None 表示触碰，不更新 state）
            flipped: 本次调用是否发生状态翻转（含首次从 None 初始化为 UP/DOWN）
        """
        new_dir = classify_bar(high, low, ma20)
        if new_dir is None:
            return None, False
        if new_dir == self.state:
            return new_dir, False
        self.state = new_dir
        return new_dir, True


def decide_action(flipped: bool, new_dir: Optional[str], position: float) -> Optional[str]:
    """根据翻转结果和当前持仓决定交易动作（只做多）。

    - UP（含首次）且空仓 → BUY
    - DOWN（含首次）且持仓 → SELL
    - 否则 → None
    """
    if not flipped or new_dir is None:
        return None
    if new_dir == UP and position == 0:
        return BUY
    if new_dir == DOWN and position > 0:
        return SELL
    return None
