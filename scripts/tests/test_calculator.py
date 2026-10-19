"""Calculator 单元测试。期望值均为手算（不复用被测实现的公式代码）。"""
import pandas as pd
import pytest

from scripts.calculator import Calculator
from scripts.tests.conftest import make_df

calc = Calculator(lookback_days=250)


def metrics(closes, **kw):
    return calc.calculate_all_metrics(make_df(closes, **kw))


# ---------- 基础指标 ----------

def test_rising_series_basic_metrics():
    m = metrics(range(1, 31))  # 1..30
    assert m["error"] is None
    assert m["current_price"] == 30
    assert m["prev_close"] == 29
    assert m["ma20"] == pytest.approx(20.5)            # mean(11..30)
    assert m["status"] == "YES"
    assert m["change"] == pytest.approx((30 / 29 - 1) * 100)
    assert m["deviation"] == pytest.approx((30 / 20.5 - 1) * 100)
    assert m["status_change"] is None                   # 昨日也在 MA20 上方
    assert m["change_date"] is None and m["interval_change"] is None  # 250 日内从未转变
    assert m["extreme_trend"] == "极强"                 # 连续 3 日最低价 > MA20
    assert m["volume_ratio"] == pytest.approx(1.0)
    assert m["sparkline_prices"] == [float(x) for x in range(11, 31)]


def test_drop_sets_change_date_interval_and_extreme_weak():
    closes = [100] * 25 + [90] * 5                       # 第 25 根（0 起）首次跌破
    df = make_df(closes)
    m = calc.calculate_all_metrics(df)
    assert m["status"] == "NO"
    assert m["ma20"] == pytest.approx(97.5)              # 15×100 + 5×90
    assert m["deviation"] == pytest.approx((90 / 97.5 - 1) * 100)
    assert m["change_date"] == df["date"][25]
    assert m["change_price"] == pytest.approx(99.5)      # 转变日 MA20 = 19×100 + 90
    assert m["interval_change"] == pytest.approx((90 / 99.5 - 1) * 100)
    assert m["status_change"] is None
    assert m["extreme_trend"] == "极弱"


def test_new_breakthrough_today():
    closes = [100] * 25 + [90] * 4 + [120]
    df = make_df(closes)
    m = calc.calculate_all_metrics(df)
    assert m["status"] == "YES"
    assert m["ma20"] == pytest.approx(99.0)              # 15×100 + 4×90 + 120
    assert m["status_change"] == "new_breakthrough"     # 昨日 90 < MA20 98
    assert m["change_date"] == df["date"][29]
    assert m["interval_change"] == pytest.approx((120 / 99 - 1) * 100)
    assert m["extreme_trend"] is None


def test_new_breakdown_today():
    m = metrics([100] * 25 + [110] * 4 + [80])
    assert m["status"] == "NO"
    assert m["ma20"] == pytest.approx(101.0)             # 15×100 + 4×110 + 80
    assert m["status_change"] == "new_breakdown"        # 昨日 110 ≥ MA20 102


def test_extreme_strong_requires_low_above_ma20():
    closes = list(range(1, 31))
    lows = closes[:-1] + [10]                            # 今日最低价刺破 MA20
    assert metrics(closes, lows=lows)["extreme_trend"] is None


def test_volume_ratio():
    m = metrics([100] * 30, volumes=[100] * 29 + [300])
    assert m["volume_ratio"] == pytest.approx(3.0)
    assert metrics([100] * 30, volumes=[0] * 30)["volume_ratio"] is None
    assert calc.calculate_volume_ratio([1, 2, 3, 4, 5]) is None


# ---------- 历史长度边界 ----------

@pytest.mark.parametrize("n, error", [(0, "数据异常"), (19, "数据不足"), (20, None), (21, None)])
def test_history_length_boundaries(n, error):
    m = calc.calculate_all_metrics(make_df([100] * n) if n else make_df([]))
    assert m["error"] == error
    if error:
        assert m["deviation"] is None


def test_none_df_is_data_error():
    assert calc.calculate_all_metrics(None)["error"] == "数据异常"


# ---------- 排序 ----------

def test_sort_by_deviation_ranks_ties_keep_config_order_errors_last():
    items = [
        {"code": "A", "deviation": 1.0},
        {"code": "B", "deviation": 3.0},
        {"code": "C", "deviation": None, "error": "数据异常"},
        {"code": "D", "deviation": 3.0},
    ]
    ranked = calc.sort_by_deviation(items)
    assert [(i["code"], i["rank"]) for i in ranked] == [("B", 1), ("D", 2), ("A", 3), ("C", 4)]


# ---------- B1：前一日偏离率 ----------

def test_prev_deviation_from_previous_bar():
    m = metrics(range(1, 31))                            # 昨收 29，昨日 MA20 = mean(10..29) = 19.5
    assert m["prev_deviation"] == pytest.approx((29 / 19.5 - 1) * 100)


@pytest.mark.parametrize("n, defined", [(20, False), (21, True)])
def test_prev_deviation_needs_21_bars(n, defined):
    assert (metrics([100] * n)["prev_deviation"] is not None) == defined


# ---------- B2：周/月线 MA20 由日线内部重采样，进行中周期不重复计入 ----------

def _discriminating(start, end, high_period, rule):
    """倒数第 20 根周期收盘 1000、其余 100、现价 104：正确 MA20 = (1000+18×100+104)/20 = 145.2 → NO；
    旧算法（丢掉该周期、现价计两次）MA20 = 100.4 → YES"""
    df = make_df([100] * len(pd.bdate_range(start, end)), end=end)
    period = df["date"].dt.to_period(rule)
    df.loc[period == pd.Period(high_period, rule), "close"] = 1000.0
    df.loc[df.index[-1], "close"] = 104.0
    return df


def test_weekly_ma20_counts_current_price_once():
    # 20 个完整周（05-25 起）+ 进行中的一周（10-12 周一 ~ 10-14 周三）；倒数第 20 根 = 06-01 当周
    df = _discriminating("2026-05-25", "2026-10-14", "2026-06-01", "W-SUN")
    weekly, monthly = calc.calculate_all_metrics(df)["big_cycle_status"].split("-", 1)
    assert weekly == "NO" and monthly == "-"          # 月线不足 20 根降级为 "-"


def test_monthly_ma20_counts_current_price_once():
    # 2024-12 ~ 2026-10 共 23 根月线（10 月进行中）；倒数第 20 根 = 2025-03
    df = _discriminating("2024-12-02", "2026-10-14", "2025-03", "M")
    assert calc.calculate_all_metrics(df)["big_cycle_status"] == "YES-NO"


@pytest.mark.parametrize("start, status", [("2026-06-08", "---"), ("2026-06-01", "YES--")])
def test_weekly_needs_20_bars(start, status):
    """19 / 20 个完整周；格式为 f"{周}-{月}"，不足 20 根的周期为 "-"（月线此处均不足）"""
    df = make_df([100] * len(pd.bdate_range(start, "2026-10-16")))
    assert calc.calculate_all_metrics(df)["big_cycle_status"] == status
