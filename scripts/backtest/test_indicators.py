"""indicators 模块测试。运行：pytest scripts/backtest/test_indicators.py -v"""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.backtest.indicators import (
    compute_ma,
    resample_weekly,
    resample_monthly,
    is_bear,
)


def _daily_df(start="2024-01-01", n=120, base=100.0):
    dates = pd.bdate_range(start=start, periods=n)
    closes = [base + i * 0.5 for i in range(n)]
    return pd.DataFrame({
        "date": dates,
        "open": closes,
        "high": [c + 1 for c in closes],
        "low":  [c - 1 for c in closes],
        "close": closes,
    })


# ---------- compute_ma ----------

def test_compute_ma_window_5():
    s = pd.Series([1, 2, 3, 4, 5, 6, 7], dtype=float)
    out = compute_ma(s, window=5)
    assert pd.isna(out.iloc[0])
    assert pd.isna(out.iloc[3])
    assert out.iloc[4] == pytest.approx(3.0)
    assert out.iloc[5] == pytest.approx(4.0)
    assert out.iloc[6] == pytest.approx(5.0)


def test_compute_ma_min_periods_equals_window():
    s = pd.Series([1, 2, 3, 4], dtype=float)
    out = compute_ma(s, window=5)
    assert out.isna().all()


# ---------- resample_weekly / resample_monthly ----------

def test_resample_weekly_close_is_friday_close():
    df = _daily_df()
    weekly = resample_weekly(df)
    assert "close" in weekly.columns
    assert weekly.index.is_monotonic_increasing
    last_week_end = weekly.index[-1]
    expected = df[df["date"] <= last_week_end]["close"].iloc[-1]
    assert weekly["close"].iloc[-1] == pytest.approx(expected)


def test_resample_monthly_high_is_max_in_month():
    df = _daily_df()
    monthly = resample_monthly(df)
    first_month_end = monthly.index[0]
    in_month = df[df["date"] <= first_month_end]
    assert monthly["high"].iloc[0] == pytest.approx(in_month["high"].max())


# ---------- 重 resample 截至 today（验证「当月 close = 当日 close」语义） ----------

def test_resample_monthly_on_partial_month_takes_today_close():
    """截到月内某一天，重 resample 的最后一根月线 close = 那天的 close。"""
    df = _daily_df(start="2024-01-01", n=80)
    cutoff = df["date"].iloc[40]
    cutoff_close = df.loc[df["date"] == cutoff, "close"].iloc[0]
    daily_until = df[df["date"] <= cutoff]
    monthly_until = resample_monthly(daily_until)
    assert monthly_until["close"].iloc[-1] == pytest.approx(cutoff_close)


# ---------- is_bear ----------

def test_is_bear_drop_exceeds_eps():
    s = pd.Series([100, 101, 102, 100, 99, 98, 97, 96], dtype=float)
    assert is_bear(s, N=4, eps=0.005) is True


def test_is_bear_flat_within_eps():
    s = pd.Series([100, 100, 100, 100, 100, 100], dtype=float)
    assert is_bear(s, N=4, eps=0.005) is False


def test_is_bear_uptrend_returns_false():
    s = pd.Series([100, 101, 102, 103, 104, 105], dtype=float)
    assert is_bear(s, N=4, eps=0.005) is False


def test_is_bear_drop_below_eps_not_bear():
    s = pd.Series([100, 99.9, 99.85, 99.8, 99.7], dtype=float)
    assert is_bear(s, N=4, eps=0.005) is False


def test_is_bear_insufficient_data_returns_false():
    s = pd.Series([100, 99, 98], dtype=float)
    assert is_bear(s, N=4, eps=0.005) is False


def test_is_bear_skips_leading_nans():
    s = pd.Series([float("nan")] * 5 + [100, 99, 98, 97, 96], dtype=float)
    assert is_bear(s, N=4, eps=0.005) is True
