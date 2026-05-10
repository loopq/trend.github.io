"""横截面动量算法单测。"""
import pandas as pd
import pytest

from scripts.backtest.cross_sectional import (
    compute_lookback_return,
    filter_qualifying,
    select_topk,
    build_holdings_schedule,
)


def _monthly_series(closes, start="2024-01-31"):
    """构造月线 close 序列。"""
    idx = pd.date_range(start=start, periods=len(closes), freq="ME")
    return pd.Series(closes, index=idx)


# ---- compute_lookback_return ----

def test_compute_lookback_return_basic():
    s = _monthly_series([100, 110, 120, 130, 140])
    # rebalance at idx=3 (close=130), lookback=3 → past = idx 0 = 100
    r = compute_lookback_return(s, s.index[3], lookback_months=3)
    assert r == pytest.approx(0.30)  # 130/100 - 1


def test_compute_lookback_return_insufficient_data():
    """idx < lookback_months → None。"""
    s = _monthly_series([100, 110, 120])
    r = compute_lookback_return(s, s.index[1], lookback_months=3)
    assert r is None


def test_compute_lookback_return_date_not_in_index():
    s = _monthly_series([100, 110, 120, 130])
    r = compute_lookback_return(s, pd.Timestamp("2030-01-01"), lookback_months=2)
    assert r is None


# ---- filter_qualifying ----

def test_filter_qualifying_above_threshold():
    rets = {"A": 0.10, "B": -0.05, "C": 0.0, "D": 0.20}
    out = filter_qualifying(rets, abs_threshold=0.0)
    assert set(out.keys()) == {"A", "C", "D"}  # >= 0.0
    out2 = filter_qualifying(rets, abs_threshold=0.05)
    assert set(out2.keys()) == {"A", "D"}


# ---- select_topk ----

def test_select_topk_by_return():
    rets = {"A": 0.10, "B": 0.30, "C": 0.05, "D": 0.20}
    top2 = select_topk(rets, topk=2)
    assert [code for code, _ in top2] == ["B", "D"]  # 降序


def test_select_topk_fewer_than_k():
    rets = {"A": 0.10, "B": 0.30}
    top5 = select_topk(rets, topk=5)
    assert len(top5) == 2
    assert [code for code, _ in top5] == ["B", "A"]


# ---- build_holdings_schedule ----

def test_build_holdings_schedule_topk_per_month():
    """3 个指数月线，lookback=2，topk=2，预期每月选 top-2。"""
    closes_by_code = {
        "A": _monthly_series([100, 110, 130, 150]),  # 月度涨幅 +10/+18/+15
        "B": _monthly_series([100, 105, 115, 110]),  # +5/+10/-4
        "C": _monthly_series([100, 120, 100, 90]),   # +20/-17/-10
    }
    schedule = build_holdings_schedule(closes_by_code, lookback_months=2, topk=2, abs_threshold=0.0)
    # 4 个月份；前 2 个月 lookback=2 数据不足
    dates = sorted(schedule.keys())
    assert schedule[dates[0]] == set()  # idx=0, lookback=2 → 不足
    assert schedule[dates[1]] == set()  # idx=1, lookback=2 → 不足（需 idx >= 2）
    # idx=2: A=130/100-1=0.30; B=115/100-1=0.15; C=100/100-1=0.0; 全合格、top-2 = {A, B}
    assert schedule[dates[2]] == {"A", "B"}
    # idx=3: A=150/110-1=0.36; B=110/105-1=~0.048; C=90/120-1=-0.25; 合格 {A,B}, top-2 = {A,B}
    assert schedule[dates[3]] == {"A", "B"}


def test_build_holdings_schedule_empty_no_qualifying():
    """所有指数 return < abs_threshold → 空 set。"""
    closes_by_code = {
        "A": _monthly_series([100, 90, 80, 70]),  # 全跌
        "B": _monthly_series([100, 95, 90, 85]),
    }
    schedule = build_holdings_schedule(closes_by_code, lookback_months=2, topk=2, abs_threshold=0.0)
    dates = sorted(schedule.keys())
    # idx=2 / idx=3 all returns < 0 → 空
    assert schedule[dates[2]] == set()
    assert schedule[dates[3]] == set()
