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


def test_write_compare_report_handles_empty_full_results():
    """write_compare_report 对 cross-sectional 策略空 full_results 不崩溃，输出提示。"""
    import tempfile
    from pathlib import Path
    from scripts.backtest.compare_report import write_compare_report
    from scripts.backtest.index_registry import IndexMeta

    registry = [IndexMeta("000300", "沪深300", "cs_index", "宽基")]
    base_results = (None, registry, {}, {"000300": [_make_dummy_result("000300", 10.0, -15.0)]}, [_make_window_result(3, 10.0, -15.0, 30.0)])
    cross_results = (None, registry, {}, {}, [_make_window_result(3, 12.0, -10.0, 36.0)])
    by_strategy = {"baseline": base_results, "cross-sectional": cross_results}

    with tempfile.TemporaryDirectory() as tmpdir:
        out = write_compare_report(by_strategy, [3], Path(tmpdir))
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "横截面 top-K" in content
        assert "组合层对比" in content


def _make_dummy_result(code, cagr, mdd):
    """make_compare_report test 用的 dummy BacktestResult。"""
    from scripts.backtest.engine import BacktestResult
    return BacktestResult(
        index_code=code, index_name=code, index_category="dummy",
        strategy_name="dummy", evaluation_start=pd.Timestamp("2020-01-01"),
        evaluation_end=pd.Timestamp("2026-04-30"),
        equity_curve=pd.Series(dtype=float), trades=[], closed_pairs=[],
        yearly_returns={}, total_return=0.0, annualized_return=cagr,
        max_drawdown=mdd, win_rate=0.0, trade_count=0, unrealized_pnl=0.0,
        bh_equity_curve=pd.Series(dtype=float), bh_yearly_returns={},
        bh_total_return=0.0, bh_annualized_return=0.0, bh_max_drawdown=0.0,
    )
