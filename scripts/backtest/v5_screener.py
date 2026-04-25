"""V5 筛选引擎：90 个 THS 一级行业全量回测 + 多维排序。

输出：SectorMetrics 列表（每行业一项）
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd

from scripts.backtest.data_loader import IndexData, load_index
from scripts.backtest.engine import BacktestResult, run_strategy
from scripts.backtest.index_registry import IndexMeta
from scripts.backtest.reporter import compute_allocation
from scripts.backtest.strategies import all_strategies

logger = logging.getLogger(__name__)

MIN_EVALUATION_START = pd.Timestamp("2016-01-01")
TRADING_DAYS_PER_YEAR = 252


@dataclass
class SectorMetrics:
    code: str
    name: str
    eval_start: pd.Timestamp
    eval_end: pd.Timestamp
    n_daily_bars: int

    # 资产层面
    annual_volatility: float        # 年化波动率（%）

    # B&H
    bh_total_return: float
    bh_cagr: float
    bh_max_drawdown: float

    # 三策略
    d_total_return: Optional[float]
    d_cagr: Optional[float]
    d_max_drawdown: Optional[float]
    d_calmar: Optional[float]
    d_alpha: Optional[float]
    d_trade_count: Optional[int]

    w_total_return: Optional[float]
    w_alpha: Optional[float]
    w_calmar: Optional[float]

    m_total_return: Optional[float]
    m_alpha: Optional[float]
    m_calmar: Optional[float]

    # 综合
    best_strategy: str              # D/W/M 哪个最强（按 alpha）
    best_alpha: float
    best_calmar: float
    best_return: float

    # Calmar 权重快照（V4.1 算法应用到本行业）
    calmar_weights: dict            # {"D": w, "W": w, "M": w}

    # 类别（V8 引入；V5 保持向后兼容默认空字符串）
    category: str = ""


def _annual_volatility(daily_close: pd.Series) -> float:
    """年化波动率（%）= 日 log 收益率标准差 × √252 × 100"""
    log_ret = np.log(daily_close).diff().dropna()
    if log_ret.empty:
        return 0.0
    return float(log_ret.std() * math.sqrt(TRADING_DAYS_PER_YEAR) * 100)


def _safe_calmar(ret_pct: Optional[float], mdd_pct: Optional[float]) -> Optional[float]:
    if ret_pct is None or mdd_pct is None:
        return None
    mdd_abs = abs(mdd_pct)
    if mdd_abs < 0.01:
        mdd_abs = 0.01
    return ret_pct / mdd_abs


def screen_sector(meta: IndexMeta) -> Optional[SectorMetrics]:
    """跑单个行业的所有指标。失败返回 None。"""
    try:
        data = load_index(meta.code, meta.source, meta.name)
    except Exception as e:
        logger.error("load %s 失败：%s", meta.code, e)
        return None
    if data is None or data.daily.empty:
        return None

    # 评估区间内的日线数据
    eval_daily = data.daily[data.daily.index >= MIN_EVALUATION_START]
    if eval_daily.empty:
        return None

    eval_start = eval_daily.index[0]
    eval_end = eval_daily.index[-1]

    # 年化波动率（评估区间内）
    sigma = _annual_volatility(eval_daily["close"])

    # 跑三策略
    results: List[BacktestResult] = []
    for strat in all_strategies():
        try:
            r = run_strategy(
                data, strat,
                min_evaluation_start=MIN_EVALUATION_START,
                index_category=meta.category,
            )
            results.append(r)
        except ValueError as e:
            logger.warning("[%s/%s] strategy 跳过：%s", meta.code, strat.name, e)

    if not results:
        return None

    # B&H 数据（任取一个策略的 bh 字段，三个相同）
    first = results[0]
    bh_total = first.bh_total_return
    bh_cagr = first.bh_annualized_return
    bh_mdd = first.bh_max_drawdown

    by = {r.strategy_name: r for r in results}

    def metric(s):
        return by.get(s)

    d, w, m = metric("D"), metric("W"), metric("M")

    def alpha(r):
        return None if r is None else (r.total_return - bh_total)

    d_alpha = alpha(d)
    w_alpha = alpha(w)
    m_alpha = alpha(m)

    # 最强策略（按 alpha 取最大）
    candidates = [
        (n, a, by[n]) for n, a in [("D", d_alpha), ("W", w_alpha), ("M", m_alpha)]
        if a is not None
    ]
    best_name, best_alpha_val, best_r = max(candidates, key=lambda x: x[1])

    # Calmar 权重（V4.1 算法）
    alloc = compute_allocation(results)
    calmar_weights = {n: alloc.get(n, {}).get("weight", 0.0) for n in ("D", "W", "M")}

    return SectorMetrics(
        code=meta.code,
        name=meta.name,
        eval_start=eval_start,
        eval_end=eval_end,
        n_daily_bars=len(eval_daily),
        annual_volatility=sigma,
        bh_total_return=bh_total,
        bh_cagr=bh_cagr,
        bh_max_drawdown=bh_mdd,
        d_total_return=d.total_return if d else None,
        d_cagr=d.annualized_return if d else None,
        d_max_drawdown=d.max_drawdown if d else None,
        d_calmar=_safe_calmar(d.annualized_return if d else None,
                              d.max_drawdown if d else None),
        d_alpha=d_alpha,
        d_trade_count=d.trade_count if d else None,
        w_total_return=w.total_return if w else None,
        w_alpha=w_alpha,
        w_calmar=_safe_calmar(w.annualized_return if w else None,
                              w.max_drawdown if w else None),
        m_total_return=m.total_return if m else None,
        m_alpha=m_alpha,
        m_calmar=_safe_calmar(m.annualized_return if m else None,
                              m.max_drawdown if m else None),
        best_strategy=best_name,
        best_alpha=best_alpha_val,
        best_return=best_r.total_return,
        best_calmar=_safe_calmar(best_r.annualized_return, best_r.max_drawdown) or 0.0,
        calmar_weights=calmar_weights,
        category=meta.category,
    )
