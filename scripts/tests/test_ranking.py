"""B1：强度变化 = 前一日名次 − 今日名次，前一日名次由同组 prev_deviation 推导。"""
from scripts import apply_rank_changes
from scripts.calculator import Calculator
from scripts.tests.conftest import make_df

calc = Calculator()


def rows(*specs):
    """specs: (code, deviation, prev_deviation[, error])，按配置顺序"""
    items = [{"code": s[0], "deviation": s[1], "prev_deviation": s[2], "order": i,
              **({"error": s[3]} if len(s) > 3 else {})} for i, s in enumerate(specs)]
    ranked = calc.sort_by_deviation(items)
    apply_rank_changes(ranked)
    return {r["code"]: (r["rank"], r["rank_change"]) for r in ranked}


def test_rank_change_from_previous_deviation():
    assert rows(("A", 3.0, 1.0), ("B", 2.0, 2.0)) == {"A": (1, +1), "B": (2, -1)}


def test_prev_tie_uses_config_order_not_today_order():   # review M1 原复现
    assert rows(("A", 1.0, 0.0), ("B", 2.0, 0.0)) == {"B": (1, +1), "A": (2, -1)}


def test_today_tie_uses_config_order():
    assert rows(("A", 1.0, 0.0), ("B", 1.0, 5.0)) == {"A": (1, +1), "B": (2, -1)}


def test_both_days_tied_is_zero():
    assert rows(("A", 1.0, 1.0), ("B", 1.0, 1.0)) == {"A": (1, 0), "B": (2, 0)}


def test_error_and_missing_prev_are_none_and_excluded():
    got = rows(("A", 1.0, 2.0), ("B", None, None, "数据异常"), ("C", 3.0, None), ("D", 2.0, 1.0))
    assert got == {"C": (1, None), "D": (2, +0), "A": (3, -2), "B": (4, None)}


def group(frames):
    """经 Calculator 计算同组指数并排名（配置顺序 = frames 顺序）"""
    items = [{"code": code, "order": i, **calc.calculate_all_metrics(df)} for i, (code, df) in enumerate(frames)]
    ranked = calc.sort_by_deviation(items)
    apply_rank_changes(ranked)
    return {r["code"]: (r["rank"], r["rank_change"]) for r in ranked}


def test_peer_extra_bar_changes_rank_of_unchanged_index():   # review R3-H1 反例
    a = make_df([100] * 20 + [101], end="2026-10-16")
    btc_full = make_df([100] * 20 + [90, 120], end="2026-10-17", calendar="D")
    btc_to_t = btc_full[btc_full["date"] <= "2026-10-16"]
    assert group([("A", a), ("BTC", btc_full)]) == {"BTC": (1, +1), "A": (2, -1)}
    assert group([("A", a), ("BTC", btc_to_t)]) == {"A": (1, 0), "BTC": (2, 0)}
