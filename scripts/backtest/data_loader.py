"""数据加载与重采样。只产出标准化 OHLC + MA20，不判定方向。"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from scripts.backtest.cache import cached_load
from scripts.data_fetcher import DataFetcher

BACKTEST_DAYS = 6200  # 约 17 年，见 §4.2.3
DATA_END_DATE = pd.Timestamp("2026-04-24")  # V5：固定数据终点（配合缓存）
THS_START_DATE = "20150101"  # THS 行业数据起点（保证 MA20 预热）

logger = logging.getLogger(__name__)

# 新浪全球指数的 code → 接口 symbol 映射（backtest 专用，不污染生产链路）
GLOBAL_SINA_MAP = {
    "NKY": "日经225指数",
    # 可扩展：韩国 KOSPI、台湾加权、印度 SENSEX 等
}


@dataclass
class IndexData:
    code: str
    name: str
    source: str
    daily: pd.DataFrame   # date(index), open, high, low, close, ma20
    weekly: pd.DataFrame  # bar_date(index), open, high, low, close, ma20
    monthly: pd.DataFrame  # bar_date(index), open, high, low, close, ma20


def _resample_ohlc(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    """按 PeriodIndex(freq) 分组重采样，bar_date = 组内最大交易日（§5.2）。

    freq: 'W-FRI' 或 'M'
    """
    period = pd.PeriodIndex(df["date"], freq=freq)
    grouped = df.groupby(period)
    resampled = grouped.agg(
        bar_date=("date", "max"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
    )
    resampled = resampled.set_index("bar_date").sort_index()
    return resampled


def _attach_ma20(df: pd.DataFrame) -> pd.DataFrame:
    """在 close 列上计算 20 期 MA，首 19 行 NaN。"""
    df = df.copy()
    df["ma20"] = df["close"].rolling(20).mean()
    return df


def _fetch_via_data_fetcher(code: str, source: str, name: str) -> Optional[pd.DataFrame]:
    """走生产 DataFetcher（cs_index / sina_index / hk / us / spot_price / crypto）。"""
    fetcher = DataFetcher()
    df = fetcher.fetch_index(code, source, name=name or code, days=BACKTEST_DAYS)
    if df is None or df.empty:
        return None
    # 截到 DATA_END_DATE
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["date"] <= DATA_END_DATE]
    return df


def _fetch_global_sina(code: str) -> Optional[pd.DataFrame]:
    """新浪全球指数拉取（backtest 专用，不走生产 DataFetcher）。"""
    import akshare as ak

    symbol = GLOBAL_SINA_MAP.get(code)
    if symbol is None:
        return None
    try:
        df = ak.index_global_hist_sina(symbol=symbol)
    except Exception as e:
        logger.warning("global_sina fetch failed for %s: %s", code, e)
        return None
    if df is None or df.empty:
        return None
    df = df[["date", "open", "high", "low", "close", "volume"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df = df[df["date"] <= DATA_END_DATE]
    return df


def _fetch_ths_industry(name: str) -> Optional[pd.DataFrame]:
    """同花顺一级行业历史日线（V5 引入）。

    注意：API 用 name 作 symbol，不是 code。
    失败重试 3 次（线性退避 2/4/6 秒）。
    """
    import akshare as ak

    last_err: Optional[Exception] = None
    for attempt in range(3):
        try:
            df = ak.stock_board_industry_index_ths(
                symbol=name,
                start_date=THS_START_DATE,
                end_date=DATA_END_DATE.strftime("%Y%m%d"),
            )
            if df is not None and not df.empty:
                df = df.rename(columns={
                    "日期": "date",
                    "开盘价": "open",
                    "最高价": "high",
                    "最低价": "low",
                    "收盘价": "close",
                    "成交量": "volume",
                })
                cols = ["date", "open", "high", "low", "close"]
                if "volume" in df.columns:
                    cols.append("volume")
                df = df[cols].copy()
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date").reset_index(drop=True)
                # 截到 DATA_END_DATE 为止（防止 AkShare 返回更新数据）
                df = df[df["date"] <= DATA_END_DATE]
                return df
        except Exception as e:
            last_err = e
            logger.warning("THS %s 拉取第 %d 次失败：%s", name, attempt + 1, e)
        time.sleep(2 * (attempt + 1))

    if last_err:
        logger.warning("THS %s 重试 3 次均失败，最后错误：%s", name, last_err)
    return None


def load_index(code: str, source: str, name: str = "") -> Optional[IndexData]:
    """拉取单个指数并产出日/周/月三份 DataFrame。

    失败返回 None（调用方决定是否 abort）。
    """
    if source == "global_sina":
        daily_raw = cached_load(
            source=source,
            code=code,
            end_date=DATA_END_DATE,
            fetcher=lambda: _fetch_global_sina(code),
        )
    elif source == "ths_industry":
        daily_raw = cached_load(
            source=source,
            code=code,
            end_date=DATA_END_DATE,
            fetcher=lambda: _fetch_ths_industry(name),
        )
    else:
        # cs_index / sina_index / hk / us / spot_price / crypto
        daily_raw = cached_load(
            source=source,
            code=code,
            end_date=DATA_END_DATE,
            fetcher=lambda: _fetch_via_data_fetcher(code, source, name),
        )
    if daily_raw is None or daily_raw.empty:
        return None

    daily = daily_raw[["date", "open", "high", "low", "close"]].copy()
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.sort_values("date").reset_index(drop=True)

    weekly = _resample_ohlc(daily, "W-FRI")
    monthly = _resample_ohlc(daily, "M")

    daily_indexed = daily.set_index("date")

    return IndexData(
        code=code,
        name=name or code,
        source=source,
        daily=_attach_ma20(daily_indexed),
        weekly=_attach_ma20(weekly),
        monthly=_attach_ma20(monthly),
    )
