"""builtin Decider / Filter 测试。运行：pytest scripts/backtest/test_strategy_builtin.py -v"""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.backtest.strategy.builtin import MA20CrossDecider


def _bar(high, low, ma20, close=None):
    return pd.Series({
        "high": high, "low": low, "ma20": ma20,
        "close": close if close is not None else (high + low) / 2,
        "open": (high + low) / 2,
    })


# ---------- MA20CrossDecider ----------

class TestMA20CrossDecider:
    def setup_method(self):
        self.d = MA20CrossDecider()

    def test_first_clean_up_no_position_returns_buy(self):
        # 干净-上 + 空仓 → BUY（首次翻转）
        sig = self.d.decide(cycle="D", bar=_bar(105, 101, 100, close=104), position_shares=0)
        assert sig is not None
        assert sig.action == "BUY"
        assert sig.cycle == "D"
        assert sig.price == pytest.approx(104)

    def test_first_clean_down_no_position_no_signal(self):
        # 干净-下 + 空仓 → 不交易（只做多）
        sig = self.d.decide(cycle="D", bar=_bar(99, 95, 100), position_shares=0)
        assert sig is None

    def test_clean_up_with_position_no_resignal(self):
        # 持仓中 + 同方向 UP → 无信号
        d = MA20CrossDecider()
        d.decide(cycle="D", bar=_bar(105, 101, 100), position_shares=0)  # 先 BUY
        sig = d.decide(cycle="D", bar=_bar(106, 102, 100), position_shares=1.0)
        assert sig is None

    def test_clean_down_with_position_returns_sell(self):
        d = MA20CrossDecider()
        d.decide(cycle="D", bar=_bar(105, 101, 100), position_shares=0)  # 先 BUY
        sig = d.decide(cycle="D", bar=_bar(99, 95, 100, close=96), position_shares=1.0)
        assert sig is not None
        assert sig.action == "SELL"
        assert sig.price == pytest.approx(96)

    def test_touch_does_not_change_state(self):
        d = MA20CrossDecider()
        d.decide(cycle="D", bar=_bar(105, 101, 100), position_shares=0)  # BUY → state=UP
        # 触碰：low<=ma<=high
        sig = d.decide(cycle="D", bar=_bar(103, 99, 100), position_shares=1.0)
        assert sig is None
        # 触碰后再来一根 UP → 同方向不再 BUY
        sig2 = d.decide(cycle="D", bar=_bar(108, 102, 100), position_shares=1.0)
        assert sig2 is None

    def test_ma20_nan_returns_none(self):
        sig = self.d.decide(cycle="D", bar=_bar(105, 101, float("nan")), position_shares=0)
        assert sig is None

    def test_separate_state_per_cycle(self):
        """D / W / M 状态机互不干扰。"""
        d = MA20CrossDecider()
        d.decide(cycle="D", bar=_bar(105, 101, 100), position_shares=0)
        # W 第一次见 UP，应给 BUY
        sig = d.decide(cycle="W", bar=_bar(105, 101, 100, close=104), position_shares=0)
        assert sig is not None and sig.action == "BUY" and sig.cycle == "W"

    def test_boundary_low_equals_ma20_is_touch(self):
        sig = self.d.decide(cycle="D", bar=_bar(105, 100, 100), position_shares=0)
        assert sig is None  # low==ma20 算触碰

    def test_boundary_high_equals_ma20_is_touch(self):
        sig = self.d.decide(cycle="D", bar=_bar(100, 95, 100), position_shares=0)
        assert sig is None  # high==ma20 算触碰


# ---------- BearTrendFilter ----------

from scripts.backtest.strategy.builtin import BearTrendFilter
from scripts.backtest.strategy.protocol import Signal, FilterContext


def _ctx(*, today_close, month_ma5, weekly_ma60_series, monthly_ma20_series):
    """构造 FilterContext，month_close_spliced = today_close。"""
    return FilterContext(
        today=pd.Timestamp("2024-06-15"),
        today_close=today_close,
        month_close_spliced=today_close,
        month_ma5=month_ma5,
        weekly_ma60_series=weekly_ma60_series,
        monthly_ma20_series=monthly_ma20_series,
    )


def _flat_series(value: float, length: int = 12) -> pd.Series:
    return pd.Series([value] * length, dtype=float)


def _falling_series(start: float, drop_pct: float, length: int = 12) -> pd.Series:
    """从 start 线性下跌 drop_pct（最终值 = start * (1 - drop_pct)）。"""
    end = start * (1 - drop_pct)
    return pd.Series([start + (end - start) * i / (length - 1) for i in range(length)], dtype=float)


def _buy(cycle: str = "D") -> Signal:
    return Signal(action="BUY", cycle=cycle, price=100.0, bar_date=pd.Timestamp("2024-06-15"))


def _sell(cycle: str = "D") -> Signal:
    return Signal(action="SELL", cycle=cycle, price=100.0, bar_date=pd.Timestamp("2024-06-15"))


class TestBearTrendFilter:
    def setup_method(self):
        self.f = BearTrendFilter()  # default scope=("D","W"), N=4/3, eps=0.005

    # SELL 始终放行
    def test_sell_d_always_allowed(self):
        ctx = _ctx(today_close=80, month_ma5=100,
                   weekly_ma60_series=_falling_series(100, 0.10),
                   monthly_ma20_series=_falling_series(100, 0.10))
        assert self.f.allow(_sell("D"), ctx) is True

    def test_sell_w_always_allowed(self):
        ctx = _ctx(today_close=80, month_ma5=100,
                   weekly_ma60_series=_falling_series(100, 0.10),
                   monthly_ma20_series=_falling_series(100, 0.10))
        assert self.f.allow(_sell("W"), ctx) is True

    # M cycle BUY 始终放行（不在 scope 里）
    def test_m_buy_always_allowed(self):
        ctx = _ctx(today_close=80, month_ma5=100,
                   weekly_ma60_series=_falling_series(100, 0.10),
                   monthly_ma20_series=_falling_series(100, 0.10))
        assert self.f.allow(_buy("M"), ctx) is True

    # ---- D/W BUY × {month_close vs ma5} × {weekly_bear, monthly_bear} ----

    def test_d_buy_close_above_ma5_both_non_bear_pass(self):
        ctx = _ctx(today_close=110, month_ma5=100,
                   weekly_ma60_series=_flat_series(100),
                   monthly_ma20_series=_flat_series(100))
        assert self.f.allow(_buy("D"), ctx) is True

    def test_w_buy_close_above_ma5_both_non_bear_pass(self):
        ctx = _ctx(today_close=110, month_ma5=100,
                   weekly_ma60_series=_flat_series(100),
                   monthly_ma20_series=_flat_series(100))
        assert self.f.allow(_buy("W"), ctx) is True

    def test_d_buy_close_below_ma5_blocked(self):
        ctx = _ctx(today_close=99, month_ma5=100,
                   weekly_ma60_series=_flat_series(100),
                   monthly_ma20_series=_flat_series(100))
        assert self.f.allow(_buy("D"), ctx) is False

    def test_d_buy_close_equals_ma5_blocked(self):
        # 严格 > ：等号视为不满足
        ctx = _ctx(today_close=100, month_ma5=100,
                   weekly_ma60_series=_flat_series(100),
                   monthly_ma20_series=_flat_series(100))
        assert self.f.allow(_buy("D"), ctx) is False

    def test_d_buy_close_above_ma5_weekly_bear_only_still_pass(self):
        # 周线空头但月线非空头 → cond_trend = (not True) or (not False) = True
        ctx = _ctx(today_close=110, month_ma5=100,
                   weekly_ma60_series=_falling_series(100, 0.10),
                   monthly_ma20_series=_flat_series(100))
        assert self.f.allow(_buy("D"), ctx) is True

    def test_d_buy_close_above_ma5_monthly_bear_only_still_pass(self):
        ctx = _ctx(today_close=110, month_ma5=100,
                   weekly_ma60_series=_flat_series(100),
                   monthly_ma20_series=_falling_series(100, 0.10))
        assert self.f.allow(_buy("D"), ctx) is True

    def test_d_buy_close_above_ma5_both_bear_blocked(self):
        ctx = _ctx(today_close=110, month_ma5=100,
                   weekly_ma60_series=_falling_series(100, 0.10),
                   monthly_ma20_series=_falling_series(100, 0.10))
        assert self.f.allow(_buy("D"), ctx) is False

    def test_month_ma5_nan_blocks_buy(self):
        # MA5 未就绪 → 月线 C > MA5 无法判定 → 严格 suppress
        ctx = _ctx(today_close=110, month_ma5=float("nan"),
                   weekly_ma60_series=_flat_series(100),
                   monthly_ma20_series=_flat_series(100))
        assert self.f.allow(_buy("D"), ctx) is False

    def test_custom_scope_only_d(self):
        f = BearTrendFilter(scope=("D",))
        ctx = _ctx(today_close=99, month_ma5=100,
                   weekly_ma60_series=_flat_series(100),
                   monthly_ma20_series=_flat_series(100))
        # W 不在 scope，不该 block
        assert f.allow(_buy("W"), ctx) is True
        assert f.allow(_buy("D"), ctx) is False
