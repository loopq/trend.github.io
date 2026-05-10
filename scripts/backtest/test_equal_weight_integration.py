"""集成测试：验证 equal-weight 路径在 N 年窗口重跑时调用真实 Decider，
而不是被 MA20 默认状态机静默替换（cycle 1 hotfix）。"""

import pandas as pd
import pytest
from typing import Dict, List, Optional, Tuple

from scripts.backtest.data_loader import IndexData
from scripts.backtest.engine import BacktestResult
from scripts.backtest.strategy.protocol import Signal, Strategy


class _AlwaysBuyOnSecondBarDecider:
    """Toy Decider：第 2 根 K 线 BUY、之后永不 SELL。

    cycle 1 bug 下，run_portfolio_window_equal_weight 会用 MA20 默认状态机替换，
    其行为与本 decider 完全不同——MA20 需要"干净 K 线"才发信号。
    若 hotfix 工作正确：本 decider 的 BUY 应在第 2 根 K 线触发，
    持有到窗口末尾；equity_curve 末值 ≈ INDEX_CAPITAL × (final_close / second_bar_close)。
    """
    name = "always-buy-on-second"
    required_indicators: Tuple[Tuple[str, str, int], ...] = ()

    def __init__(self) -> None:
        self._call_count_by_cycle: Dict[str, int] = {}
        self._bought_by_cycle: Dict[str, bool] = {}

    def decide(self, *, cycle: str, bar: pd.Series, position_shares: float) -> Optional[Signal]:
        n = self._call_count_by_cycle.get(cycle, 0) + 1
        self._call_count_by_cycle[cycle] = n
        if n == 2 and not self._bought_by_cycle.get(cycle, False):
            self._bought_by_cycle[cycle] = True
            return Signal(
                action="BUY", cycle=cycle, price=float(bar["close"]),
                bar_date=pd.Timestamp(bar.name) if bar.name is not None else pd.NaT,
            )
        return None


def _make_toy_index_data(code: str, name: str, monthly_closes: List[float]) -> IndexData:
    """构造 toy IndexData：仅 monthly 序列；daily/weekly 用月线 broadcast。"""
    n = len(monthly_closes)
    monthly_idx = pd.date_range(end="2026-04-30", periods=n, freq="ME")
    monthly = pd.DataFrame({
        "open": monthly_closes,
        "high": [c + 1 for c in monthly_closes],
        "low": [c - 1 for c in monthly_closes],
        "close": monthly_closes,
        # ma20 占位（engine._compute_evaluation_start 要求该列存在；
        # 本测试不走 MA20 默认 decider，ma20 数值仅需非 NaN 即可）
        "ma20": monthly_closes,
    }, index=monthly_idx)
    # 用月线 close 反推 daily 序列（每个月一根 daily K 线对应同月 close）
    daily = monthly.copy()
    weekly = monthly.copy()
    return IndexData(
        code=code, name=name, source="toy",
        daily=daily, weekly=weekly, monthly=monthly,
    )


def test_equal_weight_uses_real_decider_not_ma20_default():
    """硬测试：toy Decider 必须真的被调用，equity_curve 反映其行为，
    而不是被 MA20 默认状态机静默替换。

    场景：单指数、月线、close 单调上涨 100→200（10 根月线）。
    - 真实 Decider（_AlwaysBuyOnSecondBarDecider）：第 2 根 BUY @ 110，持有到末尾 → final ≈ INDEX_CAPITAL × 200/110
    - MA20 默认状态机（cycle 1 bug）：M cycle MA20 在 10 根 K 线下根本没建立（要 20 根）→ 全程不交易 → final = INDEX_CAPITAL（无变动）
    """
    from scripts.backtest.window_engine import (
        run_portfolio_window_equal_weight, INDEX_CAPITAL,
    )

    closes = list(range(100, 210, 10))  # 100, 110, ..., 200 共 12 根
    data = _make_toy_index_data("TEST001", "测试指数", closes)
    index_data = {"TEST001": data}

    # 模拟 _run_equal_weight 第一阶段：strategy + first BacktestResult
    strategy = Strategy(
        name="toy-strat",
        decider=_AlwaysBuyOnSecondBarDecider(),
        filters=(),
        cycles=("M",),
        aggregator="equal-weight",
    )
    # toy first result（_run_equal_weight 全历史跑出，但 run_portfolio_window_equal_weight
    # 实际只用其 index_category；其余字段填 dummy 即可）
    first = BacktestResult(
        index_code="TEST001", index_name="测试指数", index_category="测试",
        strategy_name="toy-strat",
        evaluation_start=data.daily.index[0], evaluation_end=data.daily.index[-1],
        equity_curve=pd.Series([INDEX_CAPITAL], index=[data.daily.index[0]]),
        trades=[], closed_pairs=[], yearly_returns={},
        total_return=0.0, annualized_return=0.0, max_drawdown=0.0,
        win_rate=0.0, trade_count=0, unrealized_pnl=0.0,
        bh_equity_curve=pd.Series(dtype=float), bh_yearly_returns={},
        bh_total_return=0.0, bh_annualized_return=0.0, bh_max_drawdown=0.0,
    )
    full_results = {"TEST001": [first]}

    as_of = data.daily.index[-1]
    # window 覆盖全部 12 根月线
    window_years = 2  # 12 月 ≈ 1 年，给 2 年留余量

    wr = run_portfolio_window_equal_weight(
        index_data=index_data,
        full_results=full_results,
        window_years=window_years,
        as_of=as_of,
        cycle="M",
        strategy=strategy,   # ← 修复后新增的参数
    )

    # 真实 Decider：第 2 根 BUY @ 110，持有到 200，final ≈ 10000 × (200/110) ≈ 18181
    # bug 下 MA20：全程不交易，final ≈ 10000（误差 < 1%）
    final_value = wr.final_value
    assert final_value > 15000, (
        f"final_value={final_value:.2f} 接近 INDEX_CAPITAL，说明 Decider 没被调用，"
        f"很可能是 MA20 默认状态机替换的 bug。期望 ~18000+（toy decider BUY @ 110 持有到 200）"
    )
    # 上限验收（避免 over-shoot 异常）
    assert final_value < 22000, (
        f"final_value={final_value:.2f} 异常高，可能是 BUY 价格不对（如用了第 1 根 close=100 而非第 2 根 110）"
    )


# ---- cross-sectional-topk integration test ----

def test_cross_sectional_topk_window_basic():
    """3 个 toy 指数 + topk=2 + lookback=2，验证 portfolio equity 累积逻辑。"""
    from scripts.backtest.window_engine import (
        run_portfolio_window_cross_sectional_topk, INDEX_CAPITAL,
    )
    from scripts.backtest.cross_sectional import build_holdings_schedule

    # 4 个月，3 指数
    closes_by_code = {
        "A": pd.Series([100, 110, 130, 150],
                       index=pd.date_range("2024-01-31", periods=4, freq="ME")),
        "B": pd.Series([100, 105, 115, 110],
                       index=pd.date_range("2024-01-31", periods=4, freq="ME")),
        "C": pd.Series([100, 120, 100, 90],
                       index=pd.date_range("2024-01-31", periods=4, freq="ME")),
    }
    schedule = build_holdings_schedule(closes_by_code, lookback_months=2, topk=2, abs_threshold=0.0)
    # idx 0/1: 数据不足空；idx 2/3: holdings = {A,B}

    as_of = closes_by_code["A"].index[-1]  # 2024-04-30
    wr = run_portfolio_window_cross_sectional_topk(
        monthly_close_by_code=closes_by_code,
        holdings_schedule=schedule,
        window_years=1,  # 覆盖 4 个月
        as_of=as_of,
    )

    # initial_capital = 3 * INDEX_CAPITAL = 30000
    assert wr.initial_capital == 3 * INDEX_CAPITAL
    # idx=2 holdings = {A,B}（在 idx=2 的 rebalance 时点确定持仓 → 但 idx=2 时刻 cur_equity 还没增长，因为 prev_holdings = 空）
    # idx=3: prev_holdings = {A,B}, A return = 150/130-1 = 0.1538, B return = 110/115-1 = -0.0435,
    #   mean ≈ 0.0552; cur_equity = 30000 * 1.0552 ≈ 31655.5
    assert wr.final_value > 30000  # 增长（A 主导）
    assert wr.final_value < 35000  # 不应过度增长（B 拉后腿）
    assert wr.index_count == 3
    assert wr.per_index == []  # 横截面无 per-index
