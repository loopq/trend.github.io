"""compare_report 测试。运行：pytest scripts/backtest/test_compare_report.py -v"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from scripts.backtest.compare_report import (
    render_portfolio_table,
    render_per_index_diff_table,
    render_filter_hit_table,
)


def _make_window_result(years, cagr, mdd, total_return):
    """构造满足渲染所需的最小 WindowResult-like 对象。"""
    class _W:
        pass
    w = _W()
    w.window_years = years
    w.window_start = pd.Timestamp("2021-04-25")
    w.as_of = pd.Timestamp("2026-04-25")
    w.cagr = cagr
    w.max_drawdown = mdd
    w.total_return = total_return
    w.initial_capital = 140000.0
    w.final_value = 140000.0 * (1 + total_return / 100)
    w.per_index = []
    return w


def test_portfolio_table_includes_strategy_names_and_delta():
    a_results = [_make_window_result(3, 14.81, -25.0, 50.0)]
    b_results = [_make_window_result(3, 16.50, -22.0, 60.0)]
    md = render_portfolio_table([("v9-baseline", a_results), ("v9.3-bear", b_results)])
    assert "v9-baseline" in md
    assert "v9.3-bear" in md
    assert "Δ" in md
    assert "+1.69" in md or "1.69" in md  # cagr 差


def test_per_index_diff_table_filters_significant_only():
    diffs = [
        {"code": "931151", "name": "光伏产业", "delta_net_cagr": 2.5, "delta_max_dd": -1.0},
        {"code": "000819", "name": "有色金属", "delta_net_cagr": 0.3, "delta_max_dd": -0.5},  # 不显著
    ]
    md = render_per_index_diff_table(diffs, threshold_cagr=1.0, threshold_dd=2.0)
    assert "光伏产业" in md
    assert "有色金属" not in md


def test_filter_hit_table_lists_per_index_stats():
    hits = [
        {"code": "931151", "name": "光伏产业",
         "buy_candidates": 20, "suppressed": 5,
         "suppress_rate": 25.0, "hindsight_60d_avg_return": -3.5},
    ]
    md = render_filter_hit_table(hits)
    assert "光伏产业" in md
    assert "25.0" in md
    assert "-3.5" in md


def test_portfolio_table_n3_strategies():
    """3 策略对比，第一个作 base，输出 3 行策略 + 2 行 Δ per 窗口。"""
    a_results = [_make_window_result(3, 14.81, -25.0, 50.0)]
    b_results = [_make_window_result(3, 16.50, -22.0, 60.0)]
    c_results = [_make_window_result(3, 12.00, -20.0, 40.0)]
    md = render_portfolio_table([
        ("v9-baseline", a_results),
        ("v9.3-bear", b_results),
        ("faber-gtaa", c_results),
    ])
    # 三策略名都在
    assert "v9-baseline" in md
    assert "v9.3-bear" in md
    assert "faber-gtaa" in md
    # 两个 Δ 行（每个非 base 策略对 base 一个 Δ）
    assert md.count("Δ") == 2
    # bear vs baseline 的 ΔCAGR = +1.69pp
    assert "+1.69" in md
    # faber vs baseline 的 ΔCAGR = -2.81pp
    assert "-2.81" in md
