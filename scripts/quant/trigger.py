"""触发器：交易日历 / 周月末判断 / 决定今日跑哪些 bucket。

设计：交易日历查询通过回调函数注入（is_trading_day_func: date → bool），
方便测试 mock，也方便上线时切换 akshare `tool_trade_date_hist_sina`。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Callable


CalendarFn = Callable[[date], bool]


def is_trading_day(d: date, cal: CalendarFn) -> bool:
    return cal(d)


def is_week_last_trading_day(d: date, cal: CalendarFn) -> bool:
    """今天是否本周最后一个交易日。

    判定：今天是交易日 + 今天到本周日（含）之间没有更晚的交易日。
    """
    if not cal(d):
        return False
    weekday = d.weekday()  # 0=Mon, 6=Sun
    days_until_sunday = 6 - weekday
    for offset in range(1, days_until_sunday + 1):
        future = d + timedelta(days=offset)
        if cal(future):
            return False
    return True


def is_month_last_trading_day(d: date, cal: CalendarFn) -> bool:
    """今天是否本月最后一个交易日。

    判定：今天是交易日 + 今天到本月底之间没有更晚的交易日。
    """
    if not cal(d):
        return False
    # 计算下月 1 日
    if d.month == 12:
        next_month_first = date(d.year + 1, 1, 1)
    else:
        next_month_first = date(d.year, d.month + 1, 1)
    cursor = d + timedelta(days=1)
    while cursor < next_month_first:
        if cal(cursor):
            return False
        cursor += timedelta(days=1)
    return True


def decide_buckets_to_run(d: date, cal: CalendarFn) -> list[str]:
    """根据今天的日期返回需要计算的 bucket 列表。

    周一-周四（非月末）：[D]
    周五（非月末）：[D, W]
    月末交易日（非周五）：[D, M]
    月末交易日 = 周五：[D, W, M]
    非交易日：[]
    """
    if not cal(d):
        return []
    out = ["D"]
    if is_week_last_trading_day(d, cal):
        out.append("W")
    if is_month_last_trading_day(d, cal):
        out.append("M")
    return out
