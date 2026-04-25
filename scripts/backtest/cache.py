"""本地 pickle 缓存层（V5 引入）。

设计：
    cache_key = "{source}_{code}_{end_date:%Y%m%d}"
    存储位置：scripts/backtest/.cache/{key}.pkl
    缓存范围：标准化后的日线 DataFrame（统一列名 date/open/high/low/close/volume）

    终点固定（DATA_END_DATE = 2026-04-24）→ 缓存永久有效。
    若需更新到新终点，只需改 data_loader.py 的常量并清掉缓存目录。

    选 pickle 不选 parquet：stdlib 自带，不依赖 pyarrow/fastparquet。
"""
from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent / ".cache"


def cache_key(source: str, code: str, end_date: pd.Timestamp) -> str:
    return f"{source}_{code}_{end_date:%Y%m%d}"


def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.pkl"


def cached_load(
    source: str,
    code: str,
    end_date: pd.Timestamp,
    fetcher: Callable[[], Optional[pd.DataFrame]],
) -> Optional[pd.DataFrame]:
    """缓存加载。命中返回缓存；未命中调 fetcher 并写缓存。"""
    key = cache_key(source, code, end_date)
    path = _cache_path(key)

    if path.exists():
        try:
            with path.open("rb") as f:
                df = pickle.load(f)
            if isinstance(df, pd.DataFrame) and not df.empty:
                return df
        except Exception as e:
            logger.warning("Cache read failed for %s: %s. 重新拉取。", key, e)

    df = fetcher()
    if df is None or df.empty:
        return None  # 不缓存空结果，留下次重试机会

    # V9.2 staleness check：不缓存"疑似截断"的数据
    # 数据末日距 end_date 超过 90 天 → 视为不完整（如 AkShare 概率性返回旧快照）
    if "date" in df.columns and len(df) > 0:
        try:
            last_date = pd.to_datetime(df["date"].max())
            if last_date < end_date - pd.Timedelta(days=90):
                logger.warning(
                    "Cache write SKIPPED (stale data): %s last=%s < %s-90d。本次返回原始数据，下次重拉。",
                    key, last_date.date(), end_date.date(),
                )
                return df  # 数据本次仍可用，但不缓存
        except Exception:
            pass  # 日期解析失败就不检查

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("wb") as f:
            pickle.dump(df, f, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as e:
        logger.warning("Cache write failed for %s: %s. 数据本次仍可用。", key, e)

    return df


def has_cache(source: str, code: str, end_date: pd.Timestamp) -> bool:
    return _cache_path(cache_key(source, code, end_date)).exists()


def invalidate(source: str, code: str, end_date: pd.Timestamp) -> bool:
    """清除指定缓存文件。返回是否清除成功。"""
    path = _cache_path(cache_key(source, code, end_date))
    if path.exists():
        path.unlink()
        return True
    return False
