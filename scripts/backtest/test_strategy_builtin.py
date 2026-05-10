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
