"""内置 Decider / Filter，并注册标准策略。"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import pandas as pd

from scripts.backtest.indicators import is_bear
from scripts.backtest.strategy.protocol import (
    Decider,
    Filter,
    FilterContext,
    Signal,
    Strategy,
)
from scripts.backtest.strategy.registry import register


_UP = "UP"
_DOWN = "DOWN"


class MA20CrossDecider:
    """干净 K 线方向状态机：low > ma20 = UP；high < ma20 = DOWN；else 触碰。

    UP 翻转 + 空仓 → BUY；DOWN 翻转 + 持仓 → SELL。
    每个 cycle 维护独立状态。
    """

    name = "ma20-cross"

    def __init__(self) -> None:
        self._state_by_cycle: Dict[str, Optional[str]] = {}

    def _classify(self, high: float, low: float, ma20: float) -> Optional[str]:
        if pd.isna(ma20):
            return None
        if low > ma20:
            return _UP
        if high < ma20:
            return _DOWN
        return None

    def decide(self, *, cycle: str, bar: pd.Series, position_shares: float) -> Optional[Signal]:
        ma20 = bar.get("ma20")
        if pd.isna(ma20):
            return None
        new_dir = self._classify(bar["high"], bar["low"], ma20)
        if new_dir is None:
            return None  # 触碰
        prev = self._state_by_cycle.get(cycle)
        if new_dir == prev:
            return None  # 同方向不重复触发
        self._state_by_cycle[cycle] = new_dir
        if new_dir == _UP and position_shares == 0:
            return Signal(action="BUY", cycle=cycle, price=float(bar["close"]),
                          bar_date=pd.Timestamp(bar.name) if bar.name is not None else pd.NaT)
        if new_dir == _DOWN and position_shares > 0:
            return Signal(action="SELL", cycle=cycle, price=float(bar["close"]),
                          bar_date=pd.Timestamp(bar.name) if bar.name is not None else pd.NaT)
        return None


class BearTrendFilter:
    """空头趋势过滤器：

    仅作用于 scope 内 cycle 的 BUY 信号。条件：
        month_close_spliced > month_ma5
        AND ((not weekly_bear) OR (not monthly_bear))

    SELL / scope 外的 cycle / 任意 M cycle BUY 始终放行。
    """

    name = "bear-trend-filter"

    def __init__(
        self,
        scope: Tuple[str, ...] = ("D", "W"),
        weekly_bear_N: int = 4,
        weekly_bear_eps: float = 0.005,
        monthly_bear_N: int = 3,
        monthly_bear_eps: float = 0.005,
    ) -> None:
        self.scope = tuple(scope)
        self.weekly_bear_N = weekly_bear_N
        self.weekly_bear_eps = weekly_bear_eps
        self.monthly_bear_N = monthly_bear_N
        self.monthly_bear_eps = monthly_bear_eps

    def allow(self, signal: Signal, ctx: FilterContext) -> bool:
        if signal.action != "BUY":
            return True
        if signal.cycle not in self.scope:
            return True
        if ctx.month_ma5 is None or pd.isna(ctx.month_ma5):
            return False  # MA5 未就绪 → 严格 suppress
        cond_close = ctx.month_close_spliced > ctx.month_ma5
        weekly_bear = is_bear(ctx.weekly_ma60_series,
                              N=self.weekly_bear_N, eps=self.weekly_bear_eps)
        monthly_bear = is_bear(ctx.monthly_ma20_series,
                               N=self.monthly_bear_N, eps=self.monthly_bear_eps)
        cond_trend = (not weekly_bear) or (not monthly_bear)
        return cond_close and cond_trend
