"""历史日线缓存（CSV 格式，仿 scripts/backtest/cache.py）。

每个指数一个 `{index_code}.csv`，列：date,close,open,high,low,volume。
增量 append；同 date 重复行 dedup。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd


CSV_COLUMNS = ["date", "close", "open", "high", "low", "volume"]


def cache_path(cache_dir: Path | str, index_code: str) -> Path:
    return Path(cache_dir) / f"{index_code}.csv"


def read_cache(cache_dir: Path | str, index_code: str) -> pd.DataFrame:
    """读取缓存。文件不存在 → 返回空 DataFrame（保留列结构）。"""
    p = cache_path(cache_dir, index_code)
    if not p.exists():
        return pd.DataFrame(columns=CSV_COLUMNS).set_index("date")
    df = pd.read_csv(p, parse_dates=["date"])
    df = df.set_index("date").sort_index()
    return df


def write_cache(cache_dir: Path | str, index_code: str, df: pd.DataFrame) -> None:
    """写入缓存（覆盖整个文件）。"""
    p = cache_path(cache_dir, index_code)
    p.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    out.index.name = "date"
    out = out.reset_index()
    # 确保列顺序
    cols = [c for c in CSV_COLUMNS if c in out.columns]
    out[cols].to_csv(p, index=False)


def append_daily(cache_dir: Path | str, index_code: str, new_df: pd.DataFrame) -> pd.DataFrame:
    """增量 append；按 date dedup（保留最新）。返回合并后的 DataFrame。"""
    existing = read_cache(cache_dir, index_code)
    new = new_df.copy()
    if not isinstance(new.index, pd.DatetimeIndex):
        new = new.set_index("date")
    merged = pd.concat([existing, new])
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    write_cache(cache_dir, index_code, merged)
    return merged


def latest_date(cache_dir: Path | str, index_code: str):
    """返回缓存中最新一日（pd.Timestamp）。空缓存返回 None。"""
    df = read_cache(cache_dir, index_code)
    if df.empty:
        return None
    return df.index.max()
