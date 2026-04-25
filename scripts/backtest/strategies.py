"""策略定义：D/W/M 三种单周期独立策略（V2）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from scripts.backtest.signal import DirectionState

DAILY = "daily"
WEEKLY = "weekly"
MONTHLY = "monthly"

BUCKET_CAPITAL = 10000.0  # 每个桶 $10k（V2 修订）


@dataclass
class Bucket:
    timeframe: str
    capital: float
    shares: float = 0.0
    cash: float = 0.0
    state: DirectionState = field(default_factory=DirectionState)

    def __post_init__(self):
        if self.cash == 0.0 and self.shares == 0.0:
            self.cash = self.capital  # 空仓起步

    def position_value(self, price: float) -> float:
        return self.shares * price + self.cash

    def buy_all(self, price: float) -> float:
        if self.cash <= 0 or price <= 0:
            return 0.0
        new_shares = self.cash / price
        self.shares += new_shares
        self.cash = 0.0
        return new_shares

    def sell_all(self, price: float) -> float:
        if self.shares <= 0 or price <= 0:
            return 0.0
        sold = self.shares
        self.cash += sold * price
        self.shares = 0.0
        return sold


@dataclass
class Strategy:
    name: str
    buckets: List[Bucket]


def d_strategy() -> Strategy:
    return Strategy(name="D", buckets=[Bucket(timeframe=DAILY, capital=BUCKET_CAPITAL)])


def w_strategy() -> Strategy:
    return Strategy(name="W", buckets=[Bucket(timeframe=WEEKLY, capital=BUCKET_CAPITAL)])


def m_strategy() -> Strategy:
    return Strategy(name="M", buckets=[Bucket(timeframe=MONTHLY, capital=BUCKET_CAPITAL)])


def all_strategies() -> List[Strategy]:
    return [d_strategy(), w_strategy(), m_strategy()]
