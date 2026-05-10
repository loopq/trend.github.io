"""共用指标计算：MA / 重采样 / is_bear。

设计参考：agents/plans/2026-05-10-quant-strategy-framework-design.md §3
"""
from __future__ import annotations

import pandas as pd


def compute_ma(series: pd.Series, *, window: int) -> pd.Series:
    """N 周期简单移动平均。前 N-1 行为 NaN（min_periods=window）。"""
    return series.rolling(window=window, min_periods=window).mean()


def _resample_ohlc(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    """按 PeriodIndex(freq) 分组重采样，bar_date = 组内最大交易日。

    与 data_loader._resample_ohlc 同口径（V2 设计）。

    注意：当 df 截到月内某一天时，最后一组（当月）的 bar_date 即为截止日，
    close 即为该日 close——这就是「当月 close = 当日 close」的语义来源，
    无需另写 splice 函数。
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


def resample_weekly(daily_df: pd.DataFrame) -> pd.DataFrame:
    """周线重采样（W-FRI 锚点）。daily_df 需含 date / open / high / low / close。"""
    return _resample_ohlc(daily_df, "W-FRI")


def resample_monthly(daily_df: pd.DataFrame) -> pd.DataFrame:
    """月线重采样（M 锚点）。"""
    return _resample_ohlc(daily_df, "M")


def is_bear(ma_series: pd.Series, *, N: int, eps: float) -> bool:
    """N 周期斜率法：drop_rate = (ma[t-N] - ma[t]) / ma[t-N]，drop > eps 才是空头。

    数据不足（< N+1 个非空 MA 值）→ 返回 False（冷启动不误杀）。
    """
    valid = ma_series.dropna()
    if len(valid) < N + 1:
        return False
    ma_now = float(valid.iloc[-1])
    ma_then = float(valid.iloc[-N - 1])
    if ma_then == 0:
        return False
    drop_rate = (ma_then - ma_now) / ma_then
    return drop_rate > eps
