"""内置 Decider / Filter，并注册标准策略。"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

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


@register("v9-baseline")
def _v9_baseline() -> Strategy:
    return Strategy(
        name="v9-baseline",
        decider=MA20CrossDecider(),
        filters=(),
    )


@register("v9.3-bear")
def _v9_3_bear() -> Strategy:
    return Strategy(
        name="v9.3-bear",
        decider=MA20CrossDecider(),
        filters=(BearTrendFilter(scope=("D", "W")),),
    )


class FaberMonthlyMaDecider:
    """Faber 2007 月线 MA10 趋势跟踪。

    每根月线 K 线：
      close > MA{window} → 状态切 UP；UP 翻转 + 空仓 → BUY
      close ≤ MA{window} → 状态切 DOWN；DOWN 翻转 + 持仓 → SELL
      MA NaN → None（数据不足）

    与 MA20CrossDecider 的区别：
    - 用 close 直接比 MA，不用 low/high "干净 K 线"语义
    - 默认窗口 10 个月（论文原值）
    - 仅跑 monthly cycle（用 strategy.cycles=("M",) 约束）
    """

    name = "faber-monthly-ma"

    def __init__(self, window: int = 10) -> None:
        self.window = window
        self.required_indicators = (("M", f"ma{window}", window),)
        self._state_by_cycle: Dict[str, Optional[str]] = {}

    def decide(self, *, cycle: str, bar: pd.Series, position_shares: float) -> Optional[Signal]:
        ma_col = f"ma{self.window}"
        ma = bar.get(ma_col)
        close = bar.get("close")
        if pd.isna(ma) or pd.isna(close):
            return None
        new_dir = "UP" if close > ma else "DOWN"
        prev = self._state_by_cycle.get(cycle)
        if new_dir == prev:
            return None
        self._state_by_cycle[cycle] = new_dir
        if new_dir == "UP" and position_shares == 0:
            return Signal(action="BUY", cycle=cycle, price=float(close),
                          bar_date=pd.Timestamp(bar.name) if bar.name is not None else pd.NaT)
        if new_dir == "DOWN" and position_shares > 0:
            return Signal(action="SELL", cycle=cycle, price=float(close),
                          bar_date=pd.Timestamp(bar.name) if bar.name is not None else pd.NaT)
        return None


class DonchianBreakoutDecider:
    """Donchian 通道突破（月线版）。

    每根月线 K 线：
      若空仓 + buffer ≥ entry_window：close > max(buffer[-entry_window:]) → BUY
      若持仓 + buffer ≥ exit_window：close < min(buffer[-exit_window:]) → SELL
      close NaN → None
    决策完后追加当月 close 到 buffer，裁剪到最近 max(entry, exit) 个。

    与 FaberMonthlyMaDecider 区别：
    - Faber 比 close vs MA10（均值），Donchian 比 close vs max/min（极值）
    - Faber 的状态翻转高频（均值穿越易触发），Donchian 的状态翻转低频（必须创新高/破新低）
    - Donchian 自维护 close buffer，required_indicators=()，不依赖 _ensure_indicators

    默认 entry=10 / exit=5（月线 10/5 ≈ 日线 200/100，与海龟系统 1 同级别）。
    """

    name = "donchian-breakout-monthly"

    def __init__(self, entry_window: int = 10, exit_window: int = 5) -> None:
        self.entry_window = entry_window
        self.exit_window = exit_window
        self.required_indicators: Tuple[Tuple[str, str, int], ...] = ()
        self._close_buffer_by_cycle: Dict[str, List[float]] = {}

    def decide(self, *, cycle: str, bar: pd.Series, position_shares: float) -> Optional[Signal]:
        close = bar.get("close")
        if pd.isna(close):
            return None

        buf = self._close_buffer_by_cycle.setdefault(cycle, [])
        max_window = max(self.entry_window, self.exit_window)

        signal: Optional[Signal] = None
        if position_shares == 0 and len(buf) >= self.entry_window:
            entry_high = max(buf[-self.entry_window:])
            if close > entry_high:
                signal = Signal(
                    action="BUY", cycle=cycle, price=float(close),
                    bar_date=pd.Timestamp(bar.name) if bar.name is not None else pd.NaT,
                )
        elif position_shares > 0 and len(buf) >= self.exit_window:
            exit_low = min(buf[-self.exit_window:])
            if close < exit_low:
                signal = Signal(
                    action="SELL", cycle=cycle, price=float(close),
                    bar_date=pd.Timestamp(bar.name) if bar.name is not None else pd.NaT,
                )

        # 决策后追加当月 close（避免 look-ahead bias）
        buf.append(float(close))
        if len(buf) > max_window:
            del buf[: len(buf) - max_window]

        return signal


class DualMomentumNoOpDecider:
    """cross-sectional 策略占位 Decider。decide 永远返回 None。

    cross-sectional 决策走 _run_cross_sectional_topk 的 universe-wide scan，
    不调用 decide(*, cycle, bar, position_shares)。本类仅满足 Strategy.decider Protocol 契约。
    """

    name = "dual-momentum-noop"

    def __init__(self) -> None:
        self.required_indicators: Tuple[Tuple[str, str, int], ...] = ()

    def decide(self, *, cycle: str, bar: pd.Series, position_shares: float) -> Optional[Signal]:
        return None


@register("faber-gtaa")
def _faber_gtaa() -> Strategy:
    return Strategy(
        name="faber-gtaa",
        decider=FaberMonthlyMaDecider(window=10),
        filters=(),
        cycles=("M",),
        aggregator="equal-weight",
    )


@register("donchian-200")
def _donchian_200() -> Strategy:
    return Strategy(
        name="donchian-200",
        decider=DonchianBreakoutDecider(entry_window=10, exit_window=5),
        filters=(),
        cycles=("M",),
        aggregator="equal-weight",
    )


@register("dual-momentum-top5")
def _dual_momentum_top5() -> Strategy:
    return Strategy(
        name="dual-momentum-top5",
        decider=DualMomentumNoOpDecider(),
        filters=(),
        cycles=("M",),
        aggregator="cross-sectional-topk",
        params={
            "lookback_months": 12,
            "topk": 5,
            "abs_threshold": 0.0,
        },
    )


@register("dual-momentum-w5w10-stop20")
def _dual_momentum_w5w10_stop20() -> Strategy:
    """dual-momentum-w5w10 + portfolio drawdown -20% 止损（with peak reset）。

    在 w5w10 基础上加 portfolio 层动态止损：
    - 跟踪 portfolio equity 历史最高（peak）
    - 当前 equity / peak - 1 < -20% → 该月强制 cash idle + 重置 peak = 当前 equity
    - 重置 peak 避免触发后永久 cash 锁死，下月可重新跟踪

    回测对比（全期，universe combined-24）：
    - dual-momentum-w5w10:         CAGR +10.12% / MDD -38.72%
    - dual-momentum-w5w10-stop20:  CAGR +10.46% / MDD -38.72% (5y/8y/10y MDD -33.49% → -28.80%)
    详见 agents/results/2026-05-11-dual-momentum-w5w10-stop-loss-v2.html
    """
    return Strategy(
        name="dual-momentum-w5w10-stop20",
        decider=DualMomentumNoOpDecider(),
        filters=(),
        cycles=("M",),
        aggregator="cross-sectional-topk",
        params={
            "lookback_months": 12,
            "topk": 5,
            "abs_threshold": 0.0,
            "trend_filters": [
                {"timeframe": "weekly", "period": 5, "trend_lookback": 2},
                {"timeframe": "weekly", "period": 10, "trend_lookback": 3},
            ],
            "portfolio_stop_pct": 0.20,
        },
    )


@register("dual-momentum-w5w10")
def _dual_momentum_w5w10() -> Strategy:
    """dual-momentum-top5 + 周线 MA5 ∩ MA10 双重右侧趋势过滤。

    每月 rebalance 选 top-5 后，对每个候选做二次确认：
      1. close > 周线 MA5 且 MA5 非空头（MA5[t] >= MA5[t-2]）
      2. close > 周线 MA10 且 MA10 非空头（MA10[t] >= MA10[t-3]）
    两条都满足才持仓；否则该指数 cash idle。

    回测对比（全期，universe combined-24）：
    - baseline dual-momentum-top5: CAGR +8.82% / MDD -51.01%
    - dual-momentum-w5w10:         CAGR +10.12% / MDD -38.72%（CAGR 升 + MDD 降 双赢）
    详见 agents/results/2026-05-11-dual-momentum-w5-derivatives-v4.html
    """
    return Strategy(
        name="dual-momentum-w5w10",
        decider=DualMomentumNoOpDecider(),
        filters=(),
        cycles=("M",),
        aggregator="cross-sectional-topk",
        params={
            "lookback_months": 12,
            "topk": 5,
            "abs_threshold": 0.0,
            "trend_filters": [
                {"timeframe": "weekly", "period": 5, "trend_lookback": 2},
                {"timeframe": "weekly", "period": 10, "trend_lookback": 3},
            ],
        },
    )
