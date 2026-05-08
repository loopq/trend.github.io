"""close_confirm.py 单元测试：_ma20_for 返回扩展 + baseline 推导 + 错序兜底 + 完成清理。

集成端到端见 test_integration_replay.py。
"""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.quant.close_confirm import _ma20_for


def _ohlc_daily(n: int = 25, *, close: float = 10.0, low_offset: float = -0.5,
                high_offset: float = 0.5, start: str = "2026-01-01") -> pd.DataFrame:
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


# ---------------- I7.1: _ma20_for 返回 (close, low, high, ma20) ----------------


def test_close_confirm_ma20_returns_close_low_high_ma20() -> None:
    """plan §五 I7.1：返回元组长度 4。"""
    df = _ohlc_daily(n=25, close=10.0, low_offset=-0.3, high_offset=0.4)
    result = _ma20_for(df, "D")
    assert len(result) == 4
    close, low, high, ma20 = result
    assert close == pytest.approx(10.0)
    assert low == pytest.approx(9.7)
    assert high == pytest.approx(10.4)
    assert ma20 == pytest.approx(10.0)


def test_close_confirm_ma20_falls_back_low_high_to_close_when_nan() -> None:
    """last 行 low/high NaN（cache 还没更新到 today，14:48 splice 仅 close）→ fallback close。"""
    df = _ohlc_daily(n=20, close=10.0)
    today = pd.Timestamp("2026-02-02")
    new_row = pd.DataFrame({"close": [12.0]}, index=[today])
    spliced = pd.concat([df, new_row]).sort_index()
    close, low, high, ma20 = _ma20_for(spliced, "D")
    assert close == 12.0
    assert low == 12.0
    assert high == 12.0
