"""engine.run_with_strategy 集成测试。运行：pytest scripts/backtest/test_strategy_engine.py -v"""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.backtest.data_loader import IndexData
from scripts.backtest.engine import run_with_strategy
from scripts.backtest.indicators import compute_ma, resample_weekly, resample_monthly
from scripts.backtest.strategy import get
import scripts.backtest.strategy.builtin  # noqa: F401  触发注册


def _make_index_data(daily_close_series: pd.Series, code="TEST", name="测试") -> IndexData:
    df = pd.DataFrame({
        "date": daily_close_series.index,
        "open": daily_close_series.values,
        "high": daily_close_series.values + 1,
        "low": daily_close_series.values - 1,
        "close": daily_close_series.values,
    })
    weekly = resample_weekly(df)
    monthly = resample_monthly(df)
    daily = df.set_index("date")
    daily["ma20"] = compute_ma(daily["close"], window=20)
    weekly["ma20"] = compute_ma(weekly["close"], window=20)
    monthly["ma20"] = compute_ma(monthly["close"], window=20)
    return IndexData(code=code, name=name, source="test",
                     daily=daily, weekly=weekly, monthly=monthly)


def _trending_up(n=400):
    """构造 N 个交易日的稳步上升收盘价序列。"""
    dates = pd.bdate_range("2020-01-01", periods=n)
    closes = pd.Series([100 + i * 0.5 for i in range(n)], index=dates)
    return closes


def test_run_with_strategy_v9_baseline_buys_in_uptrend():
    data = _make_index_data(_trending_up())
    strat = get("v9-baseline")
    result = run_with_strategy(data, strat)
    assert result.trade_count >= 0
    # 上升趋势下，至少触发一次 BUY
    buys = [t for t in result.trades if t.action == "BUY"]
    assert len(buys) >= 1


def test_run_with_strategy_v9_3_bear_filters_out_buys_in_falling_then_recovery():
    """构造『先稳定下跌、再翻转上升』的序列，v9.3-bear 在反转初期应过滤掉 BUY。"""
    dates = pd.bdate_range("2020-01-01", periods=400)
    drop = [100 - i * 0.3 for i in range(200)]
    rise_start = drop[-1]
    rise = [rise_start + i * 0.4 for i in range(200)]
    closes = pd.Series(drop + rise, index=dates)
    data = _make_index_data(closes)

    baseline = run_with_strategy(data, get("v9-baseline"))
    bear = run_with_strategy(data, get("v9.3-bear"))

    baseline_buys = sum(1 for t in baseline.trades if t.action == "BUY")
    bear_buys = sum(1 for t in bear.trades if t.action == "BUY")

    assert bear_buys < baseline_buys, (
        f"BearTrendFilter 应过滤掉至少 1 个 BUY，"
        f"但 baseline={baseline_buys} bear={bear_buys}"
    )


def test_run_with_strategy_respects_cycles_subset():
    """只跑 D 周期时，结果不应有 W/M trade。"""
    from scripts.backtest.strategy import Strategy
    from scripts.backtest.strategy.builtin import MA20CrossDecider

    data = _make_index_data(_trending_up())
    strat_d_only = Strategy(name="d-only", decider=MA20CrossDecider(),
                            filters=(), cycles=("D",))
    result = run_with_strategy(data, strat_d_only)
    assert all(t.timeframe == "daily" for t in result.trades)
