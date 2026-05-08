"""signal_generator.py 单元测试：MA20 频率计算 + first-write-wins baseline + bar_validation + derive 接入。

集成端到端测试见 test_integration_replay.py（plan §四 4.2）。
"""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.quant.config import load_config
from scripts.quant.signal_generator import (
    _apply_baseline_first_write_wins,
    _ma20_for_frequency,
    _validate_bar,
)
from scripts.quant.state import init_positions


@pytest.fixture
def cfg(quant_config_path):
    return load_config(quant_config_path)


def _ohlc_daily(n: int = 25, *, close: float = 10.0, low_offset: float = -0.5,
                high_offset: float = 0.5, start: str = "2026-01-01") -> pd.DataFrame:
    """构造含 OHLC 的 daily DF（n 个工作日）。"""
    dates = pd.bdate_range(start, periods=n)
    return pd.DataFrame(
        {
            "close": [close] * n,
            "open": [close] * n,
            "high": [close + high_offset] * n,
            "low": [close + low_offset] * n,
            "volume": [1000] * n,
        },
        index=dates,
    )


# ---------------- I6.1: _ma20_for_frequency 返回 (close, low, high, ma20) ----------------


def test_ma20_for_frequency_returns_close_low_high_ma20() -> None:
    """plan §2.3 I6.1：返回元组长度 4，按 (close, low, high, ma20) 顺序。"""
    df = _ohlc_daily(n=25, close=10.0, low_offset=-0.5, high_offset=0.5)
    result = _ma20_for_frequency(df, "D")
    assert len(result) == 4
    close, low, high, ma20 = result
    assert close == pytest.approx(10.0)
    assert low == pytest.approx(9.5)
    assert high == pytest.approx(10.5)
    assert ma20 == pytest.approx(10.0)


def test_ma20_for_frequency_falls_back_low_high_to_close_when_nan() -> None:
    """plan §3.2：last 行 low/high 为 NaN（盘中 splice 新增行）→ fallback 为 close。

    场景：14:48 splice_realtime 在 cache 末尾追加 today 行，仅 close 有值，
    high/low 是 NaN。_ma20_for_frequency 必须 fallback 而非把 NaN 透传。
    """
    df = _ohlc_daily(n=20, close=10.0, low_offset=-0.5, high_offset=0.5)
    today = pd.Timestamp("2026-02-02")
    new_row = pd.DataFrame({"close": [12.0]}, index=[today])  # 只 close 列
    spliced = pd.concat([df, new_row]).sort_index()
    close, low, high, ma20 = _ma20_for_frequency(spliced, "D")
    assert close == 12.0
    assert low == 12.0   # fallback 为 close
    assert high == 12.0  # fallback 为 close
    assert not pd.isna(ma20)


def test_ma20_for_frequency_weekly() -> None:
    """W 频率：取每周最后一个交易日，OHLC 同步。"""
    df = _ohlc_daily(n=140, close=10.0, low_offset=-0.5, high_offset=0.5)
    result = _ma20_for_frequency(df, "W")
    assert len(result) == 4


def test_ma20_for_frequency_monthly() -> None:
    """M 频率：取每月末。"""
    df = _ohlc_daily(n=600, close=10.0, low_offset=-0.5, high_offset=0.5)
    result = _ma20_for_frequency(df, "M")
    assert len(result) == 4


# ---------------- I6.2: first-write-wins baseline ----------------


def test_signal_generator_writes_baseline_on_first_run(cfg) -> None:
    """plan §3.3.1：当日 baseline 未写入时，把 policy_state 快照到 baseline。"""
    book = init_positions(cfg)
    bucket_ids = list(book.buckets.keys())
    book.buckets[bucket_ids[0]].policy_state = "HOLD"
    book.buckets[bucket_ids[1]].policy_state = "CASH"
    today_str = "2026-05-08"

    _apply_baseline_first_write_wins(book, today_str)

    assert book.buckets[bucket_ids[0]].policy_baseline_today == "HOLD"
    assert book.buckets[bucket_ids[0]].policy_baseline_date == today_str
    assert book.buckets[bucket_ids[1]].policy_baseline_today == "CASH"
    assert book.buckets[bucket_ids[1]].policy_baseline_date == today_str


def test_signal_generator_keeps_baseline_on_intraday_rerun(cfg) -> None:
    """plan §3.3.1：当日已写入 baseline → 盘中重跑不覆盖（first-write-wins）。

    场景：14:48 跑了一次，policy_state 从 HOLD 升级到 CASH（实际下穿）；
    14:55 重跑，baseline 必须保持第一次的 HOLD（"昨日"），不被新 policy_state 覆盖。
    """
    book = init_positions(cfg)
    bucket = book.buckets["399997-D"]
    today_str = "2026-05-08"
    # 第一次跑后状态
    bucket.policy_baseline_today = "HOLD"
    bucket.policy_baseline_date = today_str
    bucket.policy_state = "CASH"   # 第一次跑后 policy_state 已变

    _apply_baseline_first_write_wins(book, today_str)

    # baseline 不被覆盖
    assert bucket.policy_baseline_today == "HOLD"
    assert bucket.policy_baseline_date == today_str


def test_signal_generator_overwrites_baseline_on_new_day(cfg) -> None:
    """跨日：baseline_date 不等于 today → 用今日 policy_state 重写。"""
    book = init_positions(cfg)
    bucket = book.buckets["399997-D"]
    bucket.policy_baseline_today = "HOLD"
    bucket.policy_baseline_date = "2026-05-07"   # 昨日的 baseline
    bucket.policy_state = "CASH"

    _apply_baseline_first_write_wins(book, "2026-05-08")

    assert bucket.policy_baseline_today == "CASH"
    assert bucket.policy_baseline_date == "2026-05-08"


# ---------------- I6.3: bar_validation ----------------


def test_validate_bar_accepts_valid_ohlc() -> None:
    """合法 bar：low/high/ma20 都 finite 且 low <= high → 返回 None。"""
    assert _validate_bar(low=9.5, high=10.5, ma20=10.0) is None
    assert _validate_bar(low=10.0, high=10.0, ma20=10.0) is None  # 平盘 K 线
    assert _validate_bar(low=0.01, high=1e6, ma20=500.0) is None


def test_validate_bar_rejects_nan_low() -> None:
    assert _validate_bar(low=float("nan"), high=10.0, ma20=10.0) == "data_invalid"


def test_validate_bar_rejects_nan_high() -> None:
    assert _validate_bar(low=10.0, high=float("nan"), ma20=10.0) == "data_invalid"


def test_validate_bar_rejects_nan_ma20() -> None:
    assert _validate_bar(low=10.0, high=10.5, ma20=float("nan")) == "data_invalid"


def test_validate_bar_rejects_inf() -> None:
    assert _validate_bar(low=float("inf"), high=10.0, ma20=10.0) == "data_invalid"
    assert _validate_bar(low=10.0, high=float("-inf"), ma20=10.0) == "data_invalid"


def test_validate_bar_rejects_low_greater_than_high() -> None:
    """low > high 是数据错误（K 线不可能）。"""
    assert _validate_bar(low=11.0, high=10.0, ma20=10.0) == "data_invalid"


def test_validate_bar_rejects_none() -> None:
    assert _validate_bar(low=None, high=10.0, ma20=10.0) == "data_invalid"
