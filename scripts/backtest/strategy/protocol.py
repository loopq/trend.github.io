"""策略框架协议。Decider 决定原始信号；Filter 过滤准入；Strategy 是组合配置。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, Tuple, runtime_checkable

import pandas as pd


@dataclass(frozen=True)
class Signal:
    """Decider 输出的原始信号（未过滤）。"""
    action: str       # "BUY" | "SELL"
    cycle: str        # "D" | "W" | "M"
    price: float      # 触发当根 K 线的 close
    bar_date: pd.Timestamp


@dataclass
class FilterContext:
    """Filter 决策时需要的上下文。engine 在每个回测点构建。"""
    today: pd.Timestamp
    today_close: float                    # 当日日 K close
    month_close_spliced: float            # 当日 close 拼到月线末尾后的「当月 close」
    month_ma5: Optional[float]            # 月线 5MA 在当月的最新值（可能 NaN）
    weekly_ma60_series: pd.Series         # 周线序列上的 MA60（截至 today）
    monthly_ma20_series: pd.Series        # 月线序列上的 MA20（截至 today）


@runtime_checkable
class Decider(Protocol):
    name: str
    required_indicators: Tuple[Tuple[str, str, int], ...] = ()  # (cycle, col_name, window) 列表，默认空
    def decide(self, *, cycle: str, bar: pd.Series, position_shares: float) -> Optional[Signal]:
        """根据当根 K 线和当前持仓决定 BUY / SELL / 无动作。

        bar: pd.Series，至少含 high / low / close / ma20。
        position_shares: 当前 bucket 的持仓量（>0 视为持仓，==0 视为空仓）。
        """
        ...


@runtime_checkable
class Filter(Protocol):
    name: str
    def allow(self, signal: Signal, ctx: FilterContext) -> bool:
        """True = 信号放行；False = suppress。"""
        ...


@dataclass(frozen=True)
class Strategy:
    """组件化策略 = Decider + 一组 Filter。

    cycles 控制本策略在哪些周期上跑。filter 可由 cycle 自身在 allow 内做判断。
    """
    name: str
    decider: Decider
    filters: Tuple[Filter, ...] = field(default_factory=tuple)
    cycles: Tuple[str, ...] = ("D", "W", "M")
    aggregator: str = "cycle-calmar"   # "cycle-calmar"|"equal-weight"|"cross-sectional-topk"
