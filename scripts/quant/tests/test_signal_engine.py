"""信号引擎测试：MA20、周/月线重采样、严格配对信号生成 + LOW/HIGH 语义。"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings, strategies as st

from scripts.backtest.signal import classify_bar
from scripts.quant.signal_engine import (
    PriceValueError,
    SignalAction,
    VALID_POLICY,
    _q,
    compute_ma20,
    decide_policy_state,
    derive_policy_state,
    generate_signal,
    is_finite_price,
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


def test_splice_preserves_ohlc_when_today_in_cache() -> None:
    """plan §3.2：cache 已有当日完整 OHLC 时，splice 仅覆盖 close，保留 high/low/open/volume。

    场景：D+1 morning-reconcile 重跑 close-confirm，cache 已含 D 日真实 OHLC，
    splice 必须保留 LOW/HIGH 真值（这是 close-confirm 用 derive_policy_state 推导的关键）。
    """
    today = pd.Timestamp("2026-01-08")
    df = pd.DataFrame(
        {
            "close": [10.0, 11.0, 100.0],   # today close 暂为 100
            "open": [9.5, 10.5, 99.0],
            "high": [10.5, 11.5, 105.0],    # today high
            "low": [9.0, 10.0, 95.0],       # today low
            "volume": [1000, 1100, 1200],
        },
        index=pd.bdate_range("2026-01-06", periods=3),
    )
    spliced = splice_realtime(df, today_close=12.0, today="2026-01-08")
    row = spliced.loc[today]
    assert row["close"] == 12.0      # close 被覆盖
    assert row["high"] == 105.0      # high 保留
    assert row["low"] == 95.0        # low 保留
    assert row["open"] == 99.0       # open 保留
    assert row["volume"] == 1200     # volume 保留


def test_splice_appends_close_only_when_today_missing() -> None:
    """plan §3.2：cache 未含当日时新增行，仅 close 列有值（high/low NaN）。

    场景：14:48 实时拼接，cache 还是 D-1 截止，新增 D 日行只有 14:48 实时价。
    """
    df = _daily([10.0, 11.0, 12.0])  # 索引 2026-01-01 / 02 / 05
    today_str = "2026-01-06"
    spliced = splice_realtime(df, today_close=13.5, today=today_str)
    today_ts = pd.Timestamp(today_str)
    assert today_ts in spliced.index
    assert spliced.loc[today_ts, "close"] == 13.5
    # high / low 列存在时为 NaN（_daily 没建 high/low 列，此处确认 close 单列时不报错）
    if "high" in spliced.columns:
        assert pd.isna(spliced.loc[today_ts, "high"])
    if "low" in spliced.columns:
        assert pd.isna(spliced.loc[today_ts, "low"])


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
        today_low=10.5,
        today_high=10.5,
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
        today_low=9.5,
        today_high=9.5,
        ma20=10.0,
    )
    assert sig is not None
    assert sig.action == SignalAction.SELL


def test_generate_signal_no_signal_when_state_unchanged() -> None:
    # actual=CASH, policy 维持 CASH（昨日今日都 below）
    assert generate_signal("399997-D", "CASH", "CASH", 9.5, 9.5, 10.0) is None
    # actual=HOLD, policy 维持 HOLD
    assert generate_signal("399997-D", "HOLD", "HOLD", 10.5, 10.5, 10.0) is None


def test_generate_signal_skip_sell_when_actual_cash():
    """跳过 BUY 后 actual=CASH，下穿不发 SELL（尊重现实，§3.2）。"""
    sig = generate_signal(
        bucket_id="399997-D",
        actual_state="CASH",
        yesterday_policy="HOLD",
        today_low=9.5,
        today_high=9.5,
        ma20=10.0,
    )
    assert sig is None


def test_generate_signal_invariant_violation_actual_hold_yesterday_cash() -> None:
    """actual=HOLD 但 yesterday_policy=CASH —— 状态机 bug。"""
    from scripts.quant.state import StateInvariantError
    with pytest.raises(StateInvariantError):
        generate_signal("399997-D", "HOLD", "CASH", 10.5, 10.5, 10.0)


# ---------------- I1: _q / is_finite_price / PriceValueError ----------------


def test_q_aligns_to_4_decimals() -> None:
    """_q 把输入对齐到 4 位价格精度。"""
    assert str(_q(10.0)) == "10.0000"
    assert str(_q(10.12345)) == "10.1235"  # ROUND_HALF_UP


def test_q_handles_numpy_float64() -> None:
    """numpy.float64 输入应该被正确归一化。"""
    val = np.float64(10.0001)
    assert str(_q(val)) == "10.0001"


def test_q_round_half_up_at_5() -> None:
    """ROUND_HALF_UP：0.00005 应该向上到 0.0001（避开 banker rounding 向偶）。"""
    assert str(_q(0.00005)) == "0.0001"


def test_q_rejects_none() -> None:
    with pytest.raises(PriceValueError, match="None"):
        _q(None)


def test_q_rejects_nan() -> None:
    with pytest.raises(PriceValueError, match="not finite"):
        _q(float("nan"))


def test_q_rejects_inf() -> None:
    with pytest.raises(PriceValueError, match="not finite"):
        _q(float("inf"))


def test_is_finite_price_accepts_finite() -> None:
    assert is_finite_price(10.5) is True
    assert is_finite_price(0.0) is True
    assert is_finite_price(np.float64(1.0)) is True
    assert is_finite_price(-1.5) is True


def test_is_finite_price_rejects_invalid() -> None:
    assert is_finite_price(None) is False
    assert is_finite_price(float("nan")) is False
    assert is_finite_price(float("inf")) is False
    assert is_finite_price("abc") is False


# ---------------- I5: GeneratedSignal + generate_signal LOW/HIGH 接口 ----------------


def test_generated_signal_has_low_high_fields() -> None:
    """plan §2.1：GeneratedSignal 字段 today_close → today_low + today_high。"""
    from scripts.quant.signal_engine import GeneratedSignal
    field_names = set(GeneratedSignal.__dataclass_fields__.keys())
    assert "today_low" in field_names
    assert "today_high" in field_names
    assert "today_close" not in field_names


def test_generate_signal_unknown_to_hold_no_signal() -> None:
    """yesterday=UNKNOWN + 干净上 → 升级 HOLD 但不发 BUY 信号（首日观察期）。"""
    sig = generate_signal(
        bucket_id="399997-D",
        actual_state="CASH",
        yesterday_policy="UNKNOWN",
        today_low=11.0,
        today_high=11.5,
        ma20=10.0,
    )
    assert sig is None


def test_generate_signal_unknown_to_cash_no_signal() -> None:
    """yesterday=UNKNOWN + 干净下 → 升级 CASH 但不发 SELL 信号。"""
    sig = generate_signal(
        bucket_id="399997-D",
        actual_state="CASH",
        yesterday_policy="UNKNOWN",
        today_low=8.5,
        today_high=9.0,
        ma20=10.0,
    )
    assert sig is None


def test_generate_signal_cash_to_hold_clean_buy() -> None:
    """yesterday=CASH actual=CASH + 干净上 → BUY，且记录 today_low/today_high。"""
    sig = generate_signal(
        bucket_id="399997-D",
        actual_state="CASH",
        yesterday_policy="CASH",
        today_low=11.0,
        today_high=11.5,
        ma20=10.0,
    )
    assert sig is not None
    assert sig.action == SignalAction.BUY
    assert sig.today_policy == "HOLD"
    assert sig.today_low == 11.0
    assert sig.today_high == 11.5


def test_generate_signal_hold_to_cash_clean_sell() -> None:
    """yesterday=HOLD actual=HOLD + 干净下 → SELL。"""
    sig = generate_signal(
        bucket_id="399997-D",
        actual_state="HOLD",
        yesterday_policy="HOLD",
        today_low=8.0,
        today_high=9.0,
        ma20=10.0,
    )
    assert sig is not None
    assert sig.action == SignalAction.SELL


def test_generate_signal_hold_touching_no_sell() -> None:
    """yesterday=HOLD + 触碰（low<ma20<high）→ 保前态，不发 SELL。"""
    sig = generate_signal(
        bucket_id="399997-D",
        actual_state="HOLD",
        yesterday_policy="HOLD",
        today_low=9.5,
        today_high=10.5,
        ma20=10.0,
    )
    assert sig is None


def test_generate_signal_cash_touching_no_buy() -> None:
    """yesterday=CASH + 触碰 → 保前态，不发 BUY。"""
    sig = generate_signal(
        bucket_id="399997-D",
        actual_state="CASH",
        yesterday_policy="CASH",
        today_low=9.5,
        today_high=10.5,
        ma20=10.0,
    )
    assert sig is None


# ---------------- I2: VALID_POLICY + derive_policy_state ----------------


def test_valid_policy_set() -> None:
    assert VALID_POLICY == frozenset({"HOLD", "CASH", "UNKNOWN"})


# (low, high, ma20, yesterday_policy, expected_today_policy)
_DERIVE_GRID = [
    # 干净-上：触发 HOLD，无论 yesterday
    (10.5, 11.0, 10.0, "HOLD",    "HOLD"),
    (10.5, 11.0, 10.0, "CASH",    "HOLD"),
    (10.5, 11.0, 10.0, "UNKNOWN", "HOLD"),
    # 干净-下：触发 CASH，无论 yesterday
    (9.0, 9.5, 10.0, "HOLD",    "CASH"),
    (9.0, 9.5, 10.0, "CASH",    "CASH"),
    (9.0, 9.5, 10.0, "UNKNOWN", "CASH"),
    # 穿越（low<ma20<high）：保持前态
    (9.5, 10.5, 10.0, "HOLD",    "HOLD"),
    (9.5, 10.5, 10.0, "CASH",    "CASH"),
    (9.5, 10.5, 10.0, "UNKNOWN", "UNKNOWN"),
    # 精确触碰（low==ma20）：算触碰，保前态
    (10.0, 10.5, 10.0, "HOLD", "HOLD"),
    # 精确触碰（high==ma20）：算触碰，保前态
    (9.5, 10.0, 10.0, "CASH", "CASH"),
]


@pytest.mark.parametrize("low,high,ma20,yesterday,expected", _DERIVE_GRID)
def test_derive_policy_state_grid(low, high, ma20, yesterday, expected) -> None:
    assert derive_policy_state(yesterday, low, high, ma20) == expected


def test_derive_policy_state_rejects_invalid_yesterday() -> None:
    with pytest.raises(ValueError, match="invalid yesterday_policy"):
        derive_policy_state("BOGUS", 10.0, 10.5, 10.0)


@given(
    low=st.floats(min_value=0.01, max_value=1e6, allow_nan=False, allow_infinity=False),
    delta=st.floats(min_value=0.0, max_value=1e5, allow_nan=False, allow_infinity=False),
    ma20=st.floats(min_value=0.01, max_value=1e6, allow_nan=False, allow_infinity=False),
    yesterday=st.sampled_from(["HOLD", "CASH", "UNKNOWN"]),
)
@settings(max_examples=300, deadline=None)
def test_derive_dual_with_classify_bar(low, delta, ma20, yesterday) -> None:
    """quant.derive_policy_state 在 _q 4 位精度量化后与 backtest.classify_bar 等价。

    quant 故意用 Decimal 4 位精度避免浮点边界抖动；对偶比较时用相同的量化输入
    喂 backtest，验证语义层等价（而非比较未量化的原始浮点）。
    映射：UP↔HOLD, DOWN↔CASH, None↔yesterday（保前态）。
    """
    high = low + delta
    quant_result = derive_policy_state(yesterday, low, high, ma20)
    # 用 _q 量化后的浮点喂 backtest，公平比较语义
    low_q = float(_q(low))
    high_q = float(_q(high))
    ma20_q = float(_q(ma20))
    bt_result = classify_bar(high_q, low_q, ma20_q)
    if bt_result == "UP":
        assert quant_result == "HOLD"
    elif bt_result == "DOWN":
        assert quant_result == "CASH"
    else:
        assert quant_result == yesterday
