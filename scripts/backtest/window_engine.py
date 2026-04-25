"""多窗口组合回测：按 V4.1 Calmar 权重在过去 N 年窗口内跑每个指数。

流程：
  1. 每个指数 $10,000 固定分配，内部按 Calmar 权重在 D/W/M 间切
  2. 窗口 = [today - N 年, today]
  3. 某指数 MA20 就绪日晚于 window_start 时标记为"迟到"，其 $10,000 在迟到期间等价闲置现金
  4. 组合净值曲线 = 各 bucket 净值曲线按日求和（含闲置现金部分）
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd

from scripts.backtest.data_loader import IndexData
from scripts.backtest.engine import BacktestResult, run_strategy
from scripts.backtest.reporter import compute_allocation
from scripts.backtest.strategies import DAILY, MONTHLY, WEEKLY, Bucket, Strategy

logger = logging.getLogger(__name__)

INDEX_CAPITAL = 10000.0


@dataclass
class IndexContribution:
    code: str
    name: str
    category: str
    initial: float
    final: float
    return_pct: float
    actual_start: pd.Timestamp
    is_late: bool


@dataclass
class WindowResult:
    window_years: int
    window_start: pd.Timestamp
    as_of: pd.Timestamp
    index_count: int
    initial_capital: float
    final_value: float
    total_return: float
    cagr: float
    max_drawdown: float
    per_index: List[IndexContribution]


def _tf(name: str) -> str:
    return {"D": DAILY, "W": WEEKLY, "M": MONTHLY}[name]


def run_portfolio_window(
    index_data: Dict[str, IndexData],
    full_results: Dict[str, List[BacktestResult]],
    window_years: int,
    as_of: pd.Timestamp,
) -> WindowResult:
    """按 Calmar 权重在 N 年窗口内回测组合。

    Args:
        index_data: 已拉取的 IndexData 字典（按 code）
        full_results: 按完整历史跑出的 BacktestResult（用于计算 Calmar 权重）
        window_years: 窗口年数
        as_of: 评估日（通常是今天）
    """
    window_start = as_of - pd.DateOffset(years=window_years)

    bucket_series: List[pd.Series] = []
    per_index_list: List[IndexContribution] = []

    for code, results in full_results.items():
        if code not in index_data:
            continue
        # 注：V9 起不再"仅赢家"过滤——手动池要包含全部用户指定，
        # 即使全策略 CAGR ≤ 0 也保留为 $10k 闲置现金

        allocation = compute_allocation(results)
        data = index_data[code]
        first = results[0]

        index_final = 0.0
        index_actual_start: Optional[pd.Timestamp] = None
        active_strategies = 0  # 该 index 实际参与的策略数

        for strat_name, info in allocation.items():
            if info["excluded"] or info["weight"] == 0:
                continue
            active_strategies += 1

            bucket_cap = info["amount"]
            single = Strategy(
                name=strat_name,
                buckets=[Bucket(timeframe=_tf(strat_name), capital=bucket_cap)],
            )

            try:
                br = run_strategy(
                    data, single,
                    min_evaluation_start=window_start,
                    index_category=first.index_category,
                )
                eq = br.equity_curve
                actual = br.evaluation_start
            except ValueError:
                # 该 bucket 在窗口内无法启动（数据不足）→ 闲置现金
                eq = pd.Series([bucket_cap], index=[as_of])
                actual = as_of

            if eq.empty:
                eq = pd.Series([bucket_cap], index=[window_start])
                actual = window_start

            if index_actual_start is None or actual < index_actual_start:
                index_actual_start = actual

            # 迟到部分：prepend 一个 window_start → initial 的条目（如 actual_start > window_start）
            if actual > window_start + pd.Timedelta(days=1) and window_start not in eq.index:
                eq = pd.concat([pd.Series({window_start: bucket_cap}), eq]).sort_index()

            final_val = float(eq.iloc[-1])
            index_final += final_val
            bucket_series.append(eq.rename(f"{code}_{strat_name}"))

        # 修复：如该 index 三策略全被 Calmar 剔除（CAGR ≤ 0）→ 视为 $10k 闲置现金
        if active_strategies == 0:
            index_final = INDEX_CAPITAL
            index_actual_start = as_of  # 标记"全期闲置"
            # 也加入一个 idle 净值曲线（用于聚合 + max_drawdown 准确）
            idle_eq = pd.Series([INDEX_CAPITAL, INDEX_CAPITAL], index=[window_start, as_of])
            bucket_series.append(idle_eq.rename(f"{code}_idle"))

        if index_actual_start is None:
            index_actual_start = as_of

        is_late = index_actual_start > window_start + pd.Timedelta(days=1)
        per_index_list.append(IndexContribution(
            code=code,
            name=first.index_name,
            category=first.index_category,
            initial=INDEX_CAPITAL,
            final=index_final,
            return_pct=(index_final / INDEX_CAPITAL - 1) * 100,
            actual_start=index_actual_start,
            is_late=is_late,
        ))

    index_count = len(per_index_list)
    initial_capital = index_count * INDEX_CAPITAL
    final_value = sum(p.final for p in per_index_list)
    total_return = (final_value / initial_capital - 1) * 100 if initial_capital > 0 else 0.0
    years = (as_of - window_start).days / 365.25
    cagr = (
        ((final_value / initial_capital) ** (1 / years) - 1) * 100
        if years > 0 and initial_capital > 0
        else 0.0
    )

    portfolio_curve = _aggregate_curves(bucket_series, window_start, as_of)
    max_dd = _max_drawdown(portfolio_curve)

    return WindowResult(
        window_years=window_years,
        window_start=window_start,
        as_of=as_of,
        index_count=index_count,
        initial_capital=initial_capital,
        final_value=final_value,
        total_return=total_return,
        cagr=cagr,
        max_drawdown=max_dd,
        per_index=per_index_list,
    )


def _aggregate_curves(
    series_list: List[pd.Series],
    window_start: pd.Timestamp,
    as_of: pd.Timestamp,
) -> pd.Series:
    """合并多个 bucket 曲线为组合总净值曲线。

    对齐方法：union 日期索引 + forward fill。
    """
    if not series_list:
        return pd.Series([], dtype=float)

    df = pd.concat(series_list, axis=1).sort_index()
    df = df.ffill()
    # 对非常早期的 NaN（理论不该有），填 0
    df = df.fillna(0.0)
    portfolio = df.sum(axis=1)
    portfolio = portfolio[(portfolio.index >= window_start) & (portfolio.index <= as_of)]
    return portfolio


def _max_drawdown(curve: pd.Series) -> float:
    if curve.empty:
        return 0.0
    running_max = curve.cummax()
    dd = (curve / running_max - 1) * 100
    return float(dd.min())
