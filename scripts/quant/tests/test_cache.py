from __future__ import annotations

import pandas as pd
import pytest

from scripts.quant.cache import (
    append_daily,
    cache_path,
    latest_date,
    read_cache,
    write_cache,
)


def _make_df(dates, closes):
    df = pd.DataFrame({"close": closes, "open": closes, "high": closes, "low": closes, "volume": [0]*len(dates)})
    df.index = pd.to_datetime(dates)
    df.index.name = "date"
    return df


def test_read_cache_missing_returns_empty(tmp_data_dir):
    df = read_cache(tmp_data_dir / "cache", "399997")
    assert df.empty


def test_write_then_read_roundtrip(tmp_data_dir):
    cache_dir = tmp_data_dir / "cache"
    df = _make_df(["2026-04-21", "2026-04-22"], [1.0, 1.1])
    write_cache(cache_dir, "399997", df)
    loaded = read_cache(cache_dir, "399997")
    assert len(loaded) == 2
    assert loaded["close"].iloc[1] == pytest.approx(1.1)


def test_append_daily_extends_existing(tmp_data_dir):
    cache_dir = tmp_data_dir / "cache"
    df1 = _make_df(["2026-04-21", "2026-04-22"], [1.0, 1.1])
    write_cache(cache_dir, "399997", df1)
    df2 = _make_df(["2026-04-23"], [1.2])
    merged = append_daily(cache_dir, "399997", df2)
    assert len(merged) == 3
    assert merged.index[-1] == pd.Timestamp("2026-04-23")


def test_append_daily_dedups_same_date_keeps_latest(tmp_data_dir):
    cache_dir = tmp_data_dir / "cache"
    df1 = _make_df(["2026-04-21"], [1.0])
    write_cache(cache_dir, "399997", df1)
    df2 = _make_df(["2026-04-21"], [99.0])  # 同日新数据
    merged = append_daily(cache_dir, "399997", df2)
    assert len(merged) == 1
    assert merged["close"].iloc[0] == 99.0


def test_latest_date_empty_returns_none(tmp_data_dir):
    assert latest_date(tmp_data_dir / "cache", "399997") is None


def test_latest_date_returns_max(tmp_data_dir):
    cache_dir = tmp_data_dir / "cache"
    df = _make_df(["2026-04-20", "2026-04-22", "2026-04-21"], [1.0, 1.2, 1.1])
    write_cache(cache_dir, "399997", df)
    assert latest_date(cache_dir, "399997") == pd.Timestamp("2026-04-22")


def test_cache_path_format(tmp_data_dir):
    p = cache_path(tmp_data_dir / "cache", "399997")
    assert p.name == "399997.csv"
