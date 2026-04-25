"""信号引擎测试：MA20、周/月线重采样、严格配对信号生成。"""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.quant.signal_engine import (
    SignalAction,
    compute_ma20,
    decide_policy_state,
    generate_signal,
    resample_to_monthly_close,
    resample_to_weekly_close,
    splice_realtime,
)


def _daily(prices: list[float], start: str = "2026-01-01") -> pd.DataFrame:
    """构造 daily DF，索引 = 工作日序列。"""
    dates = pd.bdate_range(start, periods=len(prices))
    return pd.DataFrame({"close": prices}, index=dates)


def test_compute_ma20_basic() -> None:
    df = _daily(list(range(1, 41)))  # 40 个工作日，prices 1..40
    df = compute_ma20(df)
    assert "ma20" in df.columns
    # 第 20 个交易日的 ma20 = mean(1..20) = 10.5
    assert df["ma20"].iloc[19] == pytest.approx(10.5)
    # 第 40 个 = mean(21..40) = 30.5
    assert df["ma20"].iloc[39] == pytest.approx(30.5)


def test_compute_ma20_insufficient_data() -> None:
    df = _daily([1.0] * 5)
    df = compute_ma20(df)
    # 前 19 行的 ma20 应该是 NaN
    assert df["ma20"].isna().all()


def test_splice_realtime_appends_today() -> None:
    df = _daily([10.0, 11.0, 12.0])
    today_close = 13.5
    today = "2026-01-08"
    spliced = splice_realtime(df, today_close, today)
    assert spliced.iloc[-1]["close"] == 13.5
    assert spliced.index[-1] == pd.Timestamp("2026-01-08")
    assert len(spliced) == 4


def test_splice_realtime_overwrites_today_if_present() -> None:
    df = _daily([10.0, 11.0, 12.0], start="2026-01-06")
    spliced = splice_realtime(df, 99.0, "2026-01-08")
    assert spliced.iloc[-1]["close"] == 99.0
    assert len(spliced) == 3


def test_decide_policy_state_above_ma20_is_hold() -> None:
    assert decide_policy_state(close=10.5, ma20=10.0) == "HOLD"


def test_decide_policy_state_at_or_below_ma20_is_cash() -> None:
    assert decide_policy_state(close=10.0, ma20=10.0) == "CASH"
    assert decide_policy_state(close=9.5, ma20=10.0) == "CASH"


def test_resample_weekly_takes_friday_close() -> None:
    # 2026-01-05(Mon) - 2026-01-09(Fri), close 1..5; 2026-01-12 - 2026-01-16, close 6..10
    df = _daily([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], start="2026-01-05")
    weekly = resample_to_weekly_close(df)
    # 周线终值 = 周五收盘
    assert weekly.iloc[0]["close"] == 5
    assert weekly.iloc[1]["close"] == 10
    assert len(weekly) == 2


def test_resample_monthly_takes_month_end_close() -> None:
    # 2026-01: 1, 2; 2026-02: 3, 4 — 取月末收盘
    dates = pd.to_datetime(["2026-01-15", "2026-01-30", "2026-02-15", "2026-02-27"])
    df = pd.DataFrame({"close": [1, 2, 3, 4]}, index=dates)
    monthly = resample_to_monthly_close(df)
    assert monthly.iloc[0]["close"] == 2
    assert monthly.iloc[1]["close"] == 4


# ---------------- generate_signal 严格配对 ----------------


def test_generate_signal_buy_when_cash_and_uptrend() -> None:
    sig = generate_signal(
        bucket_id="399997-D",
        actual_state="CASH",
        yesterday_policy="CASH",
        today_close=10.5,
        ma20=10.0,
    )
    assert sig is not None
    assert sig.action == SignalAction.BUY
    assert sig.today_policy == "HOLD"
    assert sig.yesterday_policy == "CASH"


def test_generate_signal_sell_when_hold_and_downtrend() -> None:
    sig = generate_signal(
        bucket_id="399997-D",
        actual_state="HOLD",
        yesterday_policy="HOLD",
        today_close=9.5,
        ma20=10.0,
    )
    assert sig is not None
    assert sig.action == SignalAction.SELL


def test_generate_signal_no_signal_when_state_unchanged() -> None:
    # actual=CASH, policy 维持 CASH（昨日今日都 below）
    assert generate_signal("399997-D", "CASH", "CASH", 9.5, 10.0) is None
    # actual=HOLD, policy 维持 HOLD
    assert generate_signal("399997-D", "HOLD", "HOLD", 10.5, 10.0) is None


def test_generate_signal_skip_sell_when_actual_cash():
    """跳过 BUY 后 actual=CASH，下穿不发 SELL（尊重现实，§3.2）。"""
    sig = generate_signal(
        bucket_id="399997-D",
        actual_state="CASH",
        yesterday_policy="HOLD",
        today_close=9.5,
        ma20=10.0,
    )
    assert sig is None


def test_generate_signal_invariant_violation_actual_hold_yesterday_cash() -> None:
    """actual=HOLD 但 yesterday_policy=CASH —— 状态机 bug。"""
    from scripts.quant.state import StateInvariantError
    with pytest.raises(StateInvariantError):
        generate_signal("399997-D", "HOLD", "CASH", 10.5, 10.0)
