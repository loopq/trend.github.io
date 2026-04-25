"""回测引擎：按日推进 + 评估期 + 指标计算（V2：无预热，无首日特例）。

所有指标按 §5.4 定义在此计算，Reporter 只做渲染。
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pandas as pd

from scripts.backtest.data_loader import IndexData
from scripts.backtest.signal import BUY, SELL, decide_action
from scripts.backtest.strategies import DAILY, MONTHLY, WEEKLY, Bucket, BUCKET_CAPITAL, Strategy


@dataclass
class Trade:
    date: pd.Timestamp
    timeframe: str
    action: str  # BUY / SELL
    price: float
    shares: float
    cash_after: float
    bar_high: float  # 该周期 K 线的 high（便于人工核对"干净"判定）
    bar_low: float
    bar_ma20: float


@dataclass
class ClosedPair:
    buy_date: pd.Timestamp
    sell_date: pd.Timestamp
    timeframe: str
    buy_price: float
    sell_price: float
    pnl: float


@dataclass
class BacktestResult:
    index_code: str
    index_name: str
    index_category: str  # 规模/主题/行业/策略/风格/综合/补充池
    strategy_name: str   # "D" / "W" / "M"
    evaluation_start: pd.Timestamp
    evaluation_end: pd.Timestamp
    equity_curve: pd.Series
    trades: List[Trade]
    closed_pairs: List[ClosedPair]
    yearly_returns: Dict[int, float]
    total_return: float
    annualized_return: float
    max_drawdown: float
    win_rate: Optional[float]
    trade_count: int
    unrealized_pnl: float
    bh_equity_curve: pd.Series
    bh_yearly_returns: Dict[int, float]
    bh_total_return: float
    bh_annualized_return: float
    bh_max_drawdown: float

    @property
    def beats_bh(self) -> bool:
        """本策略是否跑赢 B&H（按总收益率）。"""
        return self.total_return > self.bh_total_return


def _compute_evaluation_start(data: IndexData,
                              min_start: Optional[pd.Timestamp] = None) -> pd.Timestamp:
    """V2：评估起算日 = max(D/W/M 的 MA20 就绪日, min_start)。

    min_start：可选的最早评估日（如用户限定 2016-01-01）
    """
    readies = []
    for df in (data.daily, data.weekly, data.monthly):
        valid = df.dropna(subset=["ma20"])
        if not valid.empty:
            readies.append(valid.index[0])
    if not readies:
        raise ValueError("MA20 从未就绪，数据不足")
    ma20_latest = max(readies)
    # 评估起点 = 满足 MA20 就绪 + min_start 的第一个日线交易日
    threshold = ma20_latest if min_start is None else max(ma20_latest, min_start)
    daily_after = data.daily[data.daily.index >= threshold]
    if daily_after.empty:
        raise ValueError("无满足条件的评估日")
    return daily_after.index[0]


def _run_state_machine_and_trade(
    bucket: Bucket,
    date: pd.Timestamp,
    bar: pd.Series,
    trades: List[Trade],
    closed_pairs: List[ClosedPair],
    last_buy_by_bucket: Dict[int, Tuple[pd.Timestamp, float]],
) -> None:
    """在某根 K 线上运行状态机并执行交易（V2：无预热，每次调用都可能交易）。

    §2.2.1 显式前置条件：
        BUY 要求 bucket.shares == 0
        SELL 要求 bucket.shares > 0
    这些条件已在 decide_action 中检查。
    """
    if pd.isna(bar.get("ma20")):
        return
    new_dir, flipped = bucket.state.update(bar["high"], bar["low"], bar["ma20"])
    action = decide_action(flipped, new_dir, bucket.shares)
    if action is None:
        return

    if action == BUY:
        shares = bucket.buy_all(bar["close"])
        trades.append(Trade(
            date=date, timeframe=bucket.timeframe, action=BUY,
            price=bar["close"], shares=shares, cash_after=bucket.cash,
            bar_high=bar["high"], bar_low=bar["low"], bar_ma20=bar["ma20"],
        ))
        last_buy_by_bucket[id(bucket)] = (date, bar["close"])
    elif action == SELL:
        shares = bucket.sell_all(bar["close"])
        trades.append(Trade(
            date=date, timeframe=bucket.timeframe, action=SELL,
            price=bar["close"], shares=shares, cash_after=bucket.cash,
            bar_high=bar["high"], bar_low=bar["low"], bar_ma20=bar["ma20"],
        ))
        buy_info = last_buy_by_bucket.pop(id(bucket), None)
        if buy_info is not None:
            buy_date, buy_price = buy_info
            closed_pairs.append(ClosedPair(
                buy_date=buy_date, sell_date=date, timeframe=bucket.timeframe,
                buy_price=buy_price, sell_price=bar["close"],
                pnl=(bar["close"] - buy_price) * shares,
            ))


def _equity_on_date(buckets: List[Bucket], daily_close: float) -> float:
    return sum(b.position_value(daily_close) for b in buckets)


def _yearly_returns_from_curve(equity_curve: pd.Series) -> Dict[int, float]:
    result = {}
    by_year = equity_curve.groupby(equity_curve.index.year)
    for year, series in by_year:
        start_val = series.iloc[0]
        end_val = series.iloc[-1]
        if start_val == 0:
            result[year] = 0.0
        else:
            result[year] = (end_val / start_val - 1) * 100
    return result


def _total_return(equity_curve: pd.Series) -> float:
    if equity_curve.empty or equity_curve.iloc[0] == 0:
        return 0.0
    return (equity_curve.iloc[-1] / equity_curve.iloc[0] - 1) * 100


def _cagr(equity_curve: pd.Series) -> float:
    if equity_curve.empty or equity_curve.iloc[0] == 0:
        return 0.0
    days = (equity_curve.index[-1] - equity_curve.index[0]).days
    if days <= 0:
        return 0.0
    years = days / 365.25
    ratio = equity_curve.iloc[-1] / equity_curve.iloc[0]
    if ratio <= 0:
        return -100.0
    return (ratio ** (1 / years) - 1) * 100


def _max_drawdown(equity_curve: pd.Series) -> float:
    if equity_curve.empty:
        return 0.0
    running_max = equity_curve.cummax()
    drawdown = (equity_curve / running_max - 1) * 100
    return float(drawdown.min())


def _win_rate(closed_pairs: List[ClosedPair]) -> Optional[float]:
    if not closed_pairs:
        return None
    wins = sum(1 for p in closed_pairs if p.pnl > 0)
    return wins / len(closed_pairs) * 100


def _unrealized_pnl(buckets: List[Bucket], final_close: float,
                    last_buy_by_bucket: Dict[int, Tuple[pd.Timestamp, float]]) -> float:
    total = 0.0
    for bucket in buckets:
        if bucket.shares <= 0:
            continue
        buy_info = last_buy_by_bucket.get(id(bucket))
        if buy_info is None:
            continue
        _, buy_price = buy_info
        total += (final_close - buy_price) * bucket.shares
    return total


def _buy_and_hold_curve(data: IndexData, evaluation_start: pd.Timestamp,
                       capital: float) -> pd.Series:
    daily_eval = data.daily[data.daily.index >= evaluation_start]
    if daily_eval.empty:
        return pd.Series(dtype=float)
    entry_price = daily_eval["close"].iloc[0]
    if entry_price <= 0:
        return pd.Series(dtype=float)
    shares = capital / entry_price
    return (daily_eval["close"] * shares).rename("bh_equity")


def run_strategy(data: IndexData, strategy: Strategy,
                 min_evaluation_start: Optional[pd.Timestamp] = None,
                 index_category: str = "") -> BacktestResult:
    """V2：单周期独立策略。state=None 起步，第一根干净 K 线触发信号。

    min_evaluation_start：可选，限定评估不早于该日期
    index_category：指数类别（用于 summary 聚合）
    """
    evaluation_start = _compute_evaluation_start(data, min_evaluation_start)

    strat = copy.deepcopy(strategy)

    trades: List[Trade] = []
    closed_pairs: List[ClosedPair] = []
    last_buy_by_bucket: Dict[int, Tuple[pd.Timestamp, float]] = {}
    equity_records: Dict[pd.Timestamp, float] = {}

    buckets_by_tf = {b.timeframe: b for b in strat.buckets}
    daily_range = data.daily[data.daily.index >= evaluation_start]

    weekly_set = set(data.weekly.index)
    monthly_set = set(data.monthly.index)

    for date, daily_bar in daily_range.iterrows():
        if DAILY in buckets_by_tf:
            _run_state_machine_and_trade(
                buckets_by_tf[DAILY], date, daily_bar,
                trades, closed_pairs, last_buy_by_bucket,
            )

        if date in weekly_set and WEEKLY in buckets_by_tf:
            weekly_bar = data.weekly.loc[date]
            _run_state_machine_and_trade(
                buckets_by_tf[WEEKLY], date, weekly_bar,
                trades, closed_pairs, last_buy_by_bucket,
            )

        if date in monthly_set and MONTHLY in buckets_by_tf:
            monthly_bar = data.monthly.loc[date]
            _run_state_machine_and_trade(
                buckets_by_tf[MONTHLY], date, monthly_bar,
                trades, closed_pairs, last_buy_by_bucket,
            )

        equity_records[date] = _equity_on_date(strat.buckets, daily_bar["close"])

    equity_curve = pd.Series(equity_records).sort_index()

    yearly = _yearly_returns_from_curve(equity_curve)
    total_ret = _total_return(equity_curve)
    ann_ret = _cagr(equity_curve)
    mdd = _max_drawdown(equity_curve)
    wr = _win_rate(closed_pairs)
    final_close = data.daily["close"].iloc[-1] if not data.daily.empty else 0.0
    unrealized = _unrealized_pnl(strat.buckets, final_close, last_buy_by_bucket)

    # B&H 基准用单桶资金 ($10k)
    bh_curve = _buy_and_hold_curve(data, evaluation_start, capital=BUCKET_CAPITAL)
    bh_yearly = _yearly_returns_from_curve(bh_curve) if not bh_curve.empty else {}
    bh_total = _total_return(bh_curve) if not bh_curve.empty else 0.0
    bh_cagr = _cagr(bh_curve) if not bh_curve.empty else 0.0
    bh_mdd = _max_drawdown(bh_curve) if not bh_curve.empty else 0.0

    return BacktestResult(
        index_code=data.code,
        index_name=data.name,
        index_category=index_category,
        strategy_name=strat.name,
        evaluation_start=evaluation_start,
        evaluation_end=equity_curve.index[-1] if not equity_curve.empty else evaluation_start,
        equity_curve=equity_curve,
        trades=trades,
        closed_pairs=closed_pairs,
        yearly_returns=yearly,
        total_return=total_ret,
        annualized_return=ann_ret,
        max_drawdown=mdd,
        win_rate=wr,
        trade_count=len(closed_pairs),
        unrealized_pnl=unrealized,
        bh_equity_curve=bh_curve,
        bh_yearly_returns=bh_yearly,
        bh_total_return=bh_total,
        bh_annualized_return=bh_cagr,
        bh_max_drawdown=bh_mdd,
    )
