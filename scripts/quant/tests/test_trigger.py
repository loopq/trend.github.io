"""触发器测试：交易日历 / 周末 / 月末 / 14:48 跑哪些 bucket。"""
from __future__ import annotations

from datetime import date

import pytest

from scripts.quant.trigger import (
    decide_buckets_to_run,
    is_month_last_trading_day,
    is_trading_day,
    is_week_last_trading_day,
)


# Mock 交易日历：2026-04 月（用作 fixture）
# 2026-04-30 周四 = 月末交易日（5/1-5/4 是清明/劳动节假期）
APRIL_2026_TRADING_DAYS = {
    date(2026, 4, 1), date(2026, 4, 2), date(2026, 4, 3),  # 4/4-7 清明
    date(2026, 4, 7), date(2026, 4, 8), date(2026, 4, 9), date(2026, 4, 10),
    date(2026, 4, 13), date(2026, 4, 14), date(2026, 4, 15), date(2026, 4, 16), date(2026, 4, 17),
    date(2026, 4, 20), date(2026, 4, 21), date(2026, 4, 22), date(2026, 4, 23), date(2026, 4, 24),
    date(2026, 4, 27), date(2026, 4, 28), date(2026, 4, 29), date(2026, 4, 30),
    # 5/1-5/3 劳动节，5/4 周一恢复
    date(2026, 5, 4), date(2026, 5, 5), date(2026, 5, 6), date(2026, 5, 7), date(2026, 5, 8),
}


def cal(d: date) -> bool:
    return d in APRIL_2026_TRADING_DAYS


def test_is_trading_day_with_calendar() -> None:
    assert is_trading_day(date(2026, 4, 17), cal) is True   # 周五
    assert is_trading_day(date(2026, 4, 18), cal) is False  # 周六
    assert is_trading_day(date(2026, 4, 4), cal) is False   # 清明假


def test_is_week_last_trading_day_normal_friday() -> None:
    # 4/17 周五是当周最后交易日
    assert is_week_last_trading_day(date(2026, 4, 17), cal) is True
    # 4/16 周四不是
    assert is_week_last_trading_day(date(2026, 4, 16), cal) is False


def test_is_week_last_trading_day_friday_holiday_falls_back_to_thursday() -> None:
    # 假设 4/3 周五是清明（本日历里 4/3 是交易日，举不出该例，构造 mock）
    custom = {date(2026, 5, 11), date(2026, 5, 12), date(2026, 5, 13), date(2026, 5, 14)}
    # 5/15 周五假；5/14 周四是当周最后交易日
    assert is_week_last_trading_day(date(2026, 5, 14), lambda d: d in custom) is True


def test_is_month_last_trading_day_regular() -> None:
    # 4/30 周四 = 月末（5/1-3 假，5/4 进入下个月）
    assert is_month_last_trading_day(date(2026, 4, 30), cal) is True
    assert is_month_last_trading_day(date(2026, 4, 29), cal) is False


def test_decide_buckets_to_run_normal_weekday() -> None:
    # 周一-周四，非月末
    buckets = decide_buckets_to_run(date(2026, 4, 16), cal)  # 周四
    assert buckets == ["D"]


def test_decide_buckets_to_run_friday_non_month_end() -> None:
    # 4/17 周五，非月末
    buckets = decide_buckets_to_run(date(2026, 4, 17), cal)
    assert sorted(buckets) == ["D", "W"]


def test_decide_buckets_to_run_month_end_thursday_also_week_end() -> None:
    # 4/30 周四 = 月末交易日；5/1 周五是劳动节，5/2-3 周末
    # → 4/30 既是周末最后交易日（W）又是月末最后交易日（M）
    buckets = decide_buckets_to_run(date(2026, 4, 30), cal)
    assert sorted(buckets) == ["D", "M", "W"]


def test_decide_buckets_to_run_month_end_pure_thursday() -> None:
    # 构造：6/30 周二 = 月末（7/1 周三恢复交易），6/30 不是周末最后
    custom = {
        date(2026, 6, 29), date(2026, 6, 30),  # 周一周二（月末）
        date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3),  # 下月周三-周五
    }
    buckets = decide_buckets_to_run(date(2026, 6, 30), lambda d: d in custom)
    assert sorted(buckets) == ["D", "M"]


def test_decide_buckets_to_run_month_end_friday() -> None:
    # 构造：5/29 周五 = 月末（mock 周五就是月末交易日）
    custom = {
        date(2026, 5, 25), date(2026, 5, 26), date(2026, 5, 27),
        date(2026, 5, 28), date(2026, 5, 29),  # 周五月末
        date(2026, 6, 1), date(2026, 6, 2),
    }
    buckets = decide_buckets_to_run(date(2026, 5, 29), lambda d: d in custom)
    assert sorted(buckets) == ["D", "M", "W"]


def test_decide_buckets_to_run_non_trading_day_returns_empty() -> None:
    # 周六
    buckets = decide_buckets_to_run(date(2026, 4, 18), cal)
    assert buckets == []


def test_is_week_last_trading_day_non_trading_returns_false() -> None:
    # 周六本身非交易日 → False
    assert is_week_last_trading_day(date(2026, 4, 18), cal) is False


def test_is_month_last_trading_day_non_trading_returns_false() -> None:
    # 5/1（劳动节假日）非交易日 → False
    assert is_month_last_trading_day(date(2026, 5, 1), cal) is False


def test_is_month_last_trading_day_year_end_december() -> None:
    # 验证 12 月跨年逻辑
    custom = {date(2026, 12, 30), date(2026, 12, 31), date(2027, 1, 4)}
    assert is_month_last_trading_day(date(2026, 12, 31), lambda d: d in custom) is True
    assert is_month_last_trading_day(date(2026, 12, 30), lambda d: d in custom) is False
