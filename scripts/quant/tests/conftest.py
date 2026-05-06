"""pytest fixtures shared across quant tests.

约定：
- 所有 fixture 写入 tmp_path，不污染真仓库
- 时间相关 fixture 全部固定到 2026-04-25 14:48 UTC+8
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[3]


# 2026 节假日集合（清明 + 劳动；用于 synth_history 自动跳过）
_NON_TRADING_DAYS_2026 = frozenset({
    date(2026, 4, 4), date(2026, 4, 5), date(2026, 4, 6),    # 清明 3 天连休
    date(2026, 5, 1), date(2026, 5, 2), date(2026, 5, 3),    # 劳动节
    date(2026, 5, 4), date(2026, 5, 5),                      # 劳动节调休
})


def _is_trading_day_2026(d: date) -> bool:
    """简化判断：周末或 2026 节假日 → 非交易日。"""
    return d.weekday() < 5 and d not in _NON_TRADING_DAYS_2026


@pytest.fixture
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture
def quant_config_path() -> Path:
    return PROJECT_ROOT / "scripts" / "quant" / "config.yaml"


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """临时 data/quant 根目录，含三个标准子目录。"""
    root = tmp_path / "data" / "quant"
    for sub in ("cache", "signals", "notify-outbox"):
        (root / sub).mkdir(parents=True)
    return root


@pytest.fixture
def write_json():
    """方便测试用例写入 fixture json。"""
    def _w(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return _w


@pytest.fixture
def synth_history_df():
    """合成日线 DataFrame（仅交易日，价格序列可控）。

    返回标准列：date(index), close, open, high, low, volume。
    自动跳过周末 + 2026 节假日（清明/劳动）。
    """
    def _synth(
        start: str | date,
        end: str | date,
        *,
        base_price: float = 100.0,
        step: float = 0.0,
        extra_skip: Iterable[date] | None = None,
    ) -> pd.DataFrame:
        if isinstance(start, str):
            start = date.fromisoformat(start)
        if isinstance(end, str):
            end = date.fromisoformat(end)
        skip = set(extra_skip or [])
        rows = []
        d = start
        i = 0
        while d <= end:
            if _is_trading_day_2026(d) and d not in skip:
                p = base_price + i * step
                rows.append({"date": pd.Timestamp(d), "close": p, "open": p, "high": p, "low": p, "volume": 0})
                i += 1
            d += timedelta(days=1)
        df = pd.DataFrame(rows)
        if df.empty:
            return df.set_index(pd.DatetimeIndex([], name="date"))
        df = df.set_index("date").sort_index()
        return df
    return _synth


@pytest.fixture
def synth_realtime_dict():
    """合成 realtime fixture dict（兼容 FixtureFetcher 期望的格式）。

    indices_codes / etfs_codes 任意子集均可；price 可整体设置或按 code 单独覆盖。
    """
    def _synth(
        date_str: str,
        indices_codes: list[str],
        etfs_codes: list[str],
        *,
        price: float = 100.0,
        etf_price: float = 1.0,
        price_overrides: dict[str, float] | None = None,
        etf_overrides: dict[str, float] | None = None,
    ) -> dict:
        ts = f"{date_str}T14:48:00+08:00"
        ov_idx = price_overrides or {}
        ov_etf = etf_overrides or {}
        return {
            "indices": {
                code: {
                    "name": code,
                    "price": float(ov_idx.get(code, price)),
                    "change_pct": 0.0,
                    "timestamp": ts,
                }
                for code in indices_codes
            },
            "etfs": {
                code: {
                    "name": code,
                    "price": float(ov_etf.get(code, etf_price)),
                    "change_pct": 0.0,
                    "timestamp": ts,
                }
                for code in etfs_codes
            },
        }
    return _synth
