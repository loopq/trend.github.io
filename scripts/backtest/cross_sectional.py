"""横截面动量算法（cross-sectional momentum）。

封装 Dual Momentum / 类横截面策略的核心计算：
- compute_lookback_return: 单指数在某 rebalance 时点的 lookback 期收益
- filter_qualifying: 按绝对动量阈值过滤合格标的
- select_topk: 按收益降序选 top-K
- build_holdings_schedule: 多月 rebalance 持仓字典
"""

from typing import Dict, Iterable, List, Optional, Set, Tuple
import pandas as pd


def compute_lookback_return(
    monthly_close: pd.Series,
    rebalance_date: pd.Timestamp,
    lookback_months: int,
) -> Optional[float]:
    """计算指数在 rebalance_date 时点的 lookback 期收益。

    要求：
    - rebalance_date 必须在 monthly_close.index 中
    - 该 date 之前必须有至少 lookback_months 个有效数据点

    返回：(close[t] / close[t-L] - 1)，否则 None（数据不足/无效）。
    """
    if rebalance_date not in monthly_close.index:
        return None
    idx = monthly_close.index.get_loc(rebalance_date)
    if idx < lookback_months:
        return None
    past = float(monthly_close.iloc[idx - lookback_months])
    current = float(monthly_close.iloc[idx])
    if past <= 0 or pd.isna(past) or pd.isna(current):
        return None
    return (current / past) - 1.0


def filter_qualifying(
    returns_by_code: Dict[str, float],
    abs_threshold: float,
) -> Dict[str, float]:
    """绝对动量过滤：仅保留 return >= abs_threshold 的指数。"""
    return {code: r for code, r in returns_by_code.items() if r >= abs_threshold}


def select_topk(
    returns_by_code: Dict[str, float],
    topk: int,
) -> List[Tuple[str, float]]:
    """按 return 降序排序，取 top-K。

    返回 list of (code, return) 元组（保持顺序），长度 ≤ topk。
    若合格指数 < topk，返回所有合格。
    """
    sorted_items = sorted(returns_by_code.items(), key=lambda x: x[1], reverse=True)
    return sorted_items[:topk]


def build_holdings_schedule(
    monthly_close_by_code: Dict[str, pd.Series],
    lookback_months: int,
    topk: int,
    abs_threshold: float = 0.0,
    trend_filter_fn=None,
) -> Dict[pd.Timestamp, Set[str]]:
    """对所有 rebalance dates 构造 holdings schedule。

    rebalance_dates = monthly_close 各序列 index 的并集（排序）。
    对每个 date：
      1. 算每指数 lookback return（数据不足跳过）
      2. abs_threshold 过滤
      3. select_topk
      4. 如有 trend_filter_fn，对 top-K 做二次过滤
      5. 记录 set of codes 到 schedule[date]

    trend_filter_fn: Optional[Callable[[str, pd.Timestamp], bool]]
      接受 (code, rebalance_date) 返回 bool。True = 通过过滤；False = 排除。
      默认 None 不过滤。

    返回 {date -> set of codes}（空 set 表示该月无合格 → cash idle）。
    """
    all_dates = sorted(set().union(*[s.index for s in monthly_close_by_code.values()]))
    schedule: Dict[pd.Timestamp, Set[str]] = {}
    for date in all_dates:
        returns_by_code: Dict[str, float] = {}
        for code, monthly_close in monthly_close_by_code.items():
            r = compute_lookback_return(monthly_close, date, lookback_months)
            if r is not None:
                returns_by_code[code] = r
        qualifying = filter_qualifying(returns_by_code, abs_threshold)
        topk_list = select_topk(qualifying, topk)
        codes = set(code for code, _ in topk_list)
        if trend_filter_fn is not None:
            codes = {c for c in codes if trend_filter_fn(c, date)}
        schedule[date] = codes
    return schedule


def make_ma_trend_filter(close_by_code: Dict[str, pd.Series], period: int, trend_lookback: int):
    """Factory: 返回 (code, rebalance_date) → bool 的过滤函数。

    条件：close > MA(period) 且 MA(period) 非空头（MA[t] >= MA[t-trend_lookback]）。
    数据不足 → False。

    Args:
        close_by_code: code -> close 序列（daily/weekly/monthly 都可，由调用方决定）
        period: MA 周期（如 5/10/20/60）
        trend_lookback: "非空头"判定的回看窗口（约 period × 1/3）

    用法：
        f_w5 = make_ma_trend_filter(weekly_close_by_code, 5, 2)
        f_w10 = make_ma_trend_filter(weekly_close_by_code, 10, 3)
        combined = lambda c, d: f_w5(c, d) and f_w10(c, d)  # AND 双重确认
    """
    def filter_fn(code: str, rebalance_date: pd.Timestamp) -> bool:
        s = close_by_code.get(code)
        if s is None:
            return False
        sub = s[s.index <= rebalance_date]
        if len(sub) < period + trend_lookback:
            return False
        close = float(sub.iloc[-1])
        ma_now = float(sub.iloc[-period:].mean())
        ma_then = float(sub.iloc[-(period + trend_lookback):-trend_lookback].mean())
        if pd.isna(close) or pd.isna(ma_now) or pd.isna(ma_then):
            return False
        return close > ma_now and ma_now >= ma_then
    return filter_fn


def combine_filters_and(*filters):
    """组合多个 filter，所有都通过才返回 True（AND 逻辑）。"""
    def fn(code: str, rebalance_date: pd.Timestamp) -> bool:
        return all(f(code, rebalance_date) for f in filters)
    return fn
