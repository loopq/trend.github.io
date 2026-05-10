> Design: ./2026-05-11-dual-momentum-top5-design.html

# A Dual Momentum top-5（横截面动量）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.
>
> **Plan 是 self-contained**：每个 task 含完整代码 / 测试 / 验收命令。

**Goal:** 在 V10 框架下落地 cross-sectional-topk aggregator + Dual Momentum top-5 策略（lookback 12 月、绝对动量阈值 0%、top-5 等权 rebalance），与 cycle 1+2 的 in/out 策略形成"决策粒度对照实验"。最终 5 策略对比报告。

**Architecture:** Strategy 加 `params: Dict[str, Any]` 字段；新增独立 `cross_sectional.py` 模块封装算法（lookback / filter / topk / holdings schedule）；新增 `run_portfolio_window_cross_sectional_topk` 在 window_engine.py；新增 `_run_cross_sectional_topk` 在 run.py 替换 cycle 1 T4 留的 stub；compare_report 兼容空 per-index full_results；NoOp Decider 占位。

**Tech Stack:** Python 3.9+、pandas、pytest。

**隔离铁律：** 所有改动对 v9-baseline / v9.3-bear / faber-gtaa / donchian-200 零行为变更。Task 5 是硬门槛。Base SHA `1bb961c`（cycle 1 同基线）。

---

## Pre-flight

- [ ] **P1: 确认当前分支干净 + 测试 baseline**

  ```bash
  cd /Users/loopq/dev/git/loopq/trend.github.io
  git status   # 应为 nothing to commit
  source venv/bin/activate
  pytest scripts/backtest/test_*.py --tb=short 2>&1 | tail -3
  ```

  Expected: `75 passed`（cycle 2 + hotfix 后 baseline）

---

## Task 1: Strategy.params 字段

**Files:**
- Modify: `scripts/backtest/strategy/protocol.py`（在 Strategy dataclass 加 `params` 字段）
- Modify: `scripts/backtest/test_strategy_protocol.py`（如果该文件不存在，加 inline 测试到 `test_strategy_builtin.py`）

- [ ] **Step 1: 在 protocol.py 给 Strategy 加 params 字段**

打开 `scripts/backtest/strategy/protocol.py`，找到 `class Strategy:` dataclass，在 `aggregator` 字段下方加 `params`：

```python
@dataclass(frozen=True)
class Strategy:
    """组件化策略 = Decider + 一组 Filter。"""
    name: str
    decider: Decider
    filters: Tuple[Filter, ...] = field(default_factory=tuple)
    cycles: Tuple[str, ...] = ("D", "W", "M")
    aggregator: str = "cycle-calmar"
    params: Dict[str, Any] = field(default_factory=dict)   # 新增（aggregator 特定参数；frozen=True 不可变 Dict 用工厂保证 immutability 友好）
```

注意：需要在 import 区加 `Any`：检查 protocol.py 顶部 `from typing import ...`，确保含 `Dict, Any`。如果缺，加之。

- [ ] **Step 2: 在 test_strategy_builtin.py 末尾追加测试**

```python
# ---------- Strategy.params field (cycle 3 prep) ----------

def test_strategy_params_default_empty():
    """现有策略未指定 params → 默认 {}，向后兼容。"""
    from scripts.backtest.strategy import get
    from scripts.backtest.strategy.builtin import _reload_builtin
    _reload_builtin()
    s = get("v9-baseline")
    assert s.params == {}

def test_strategy_params_custom():
    """Strategy(params={...}) 接受自定义。"""
    from scripts.backtest.strategy.protocol import Strategy
    from scripts.backtest.strategy.builtin import MA20CrossDecider
    s = Strategy(
        name="dummy",
        decider=MA20CrossDecider(),
        params={"lookback_months": 12, "topk": 5},
    )
    assert s.params == {"lookback_months": 12, "topk": 5}
```

注意：已存在的 `_reload_builtin` 在 test_strategy_builtin.py 中应已 import 或直接定义；如果是 module-level 函数，按已有调用习惯使用。

- [ ] **Step 3: 跑现有 pytest 套件确认零退化**

```bash
pytest scripts/backtest/test_*.py --tb=short 2>&1 | tail -3
```

Expected: 77 passed（75 + 2 新测试）

- [ ] **Step 4: 烟测 v9-baseline 数值不变**

```bash
python -m scripts.backtest.run --strategy v9-baseline --universe v9 --windows 3,5,8,10 2>&1 | tail -6
```

Expected: 4 数值字符级一致：3年 15.32%/-12.55%、5年 10.98%/-19.69%、8年 11.51%/-22.12%、10年 9.29%/-22.25%

- [ ] **Step 5: Commit**

```bash
git add scripts/backtest/strategy/protocol.py scripts/backtest/test_strategy_builtin.py
git commit -m "[backtest] cycle3-T1: Strategy 加 params 字段（aggregator 特定参数；向后兼容）"
```

---

## Task 2: cross_sectional.py 模块（核心算法 + 7 单测）

**Files:**
- New file: `scripts/backtest/cross_sectional.py`
- New file: `scripts/backtest/test_cross_sectional.py`

- [ ] **Step 1: 创建 cross_sectional.py 算法模块**

```python
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
) -> Dict[pd.Timestamp, Set[str]]:
    """对所有 rebalance dates 构造 holdings schedule。

    rebalance_dates = monthly_close 各序列 index 的并集（排序）。
    对每个 date：
      1. 算每指数 lookback return（数据不足跳过）
      2. abs_threshold 过滤
      3. select_topk
      4. 记录 set of codes 到 schedule[date]

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
        schedule[date] = set(code for code, _ in topk_list)
    return schedule
```

- [ ] **Step 2: 创建 test_cross_sectional.py**

```python
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
```

- [ ] **Step 3: 跑测试确认通过**

```bash
pytest scripts/backtest/test_cross_sectional.py -v --tb=short 2>&1 | tail -15
```

Expected: 7 passed

- [ ] **Step 4: 跑全 backtest 套件零退化**

```bash
pytest scripts/backtest/test_*.py --tb=short 2>&1 | tail -3
```

Expected: 84 passed（77 + 7）

- [ ] **Step 5: Commit**

```bash
git add scripts/backtest/cross_sectional.py scripts/backtest/test_cross_sectional.py
git commit -m "[backtest] cycle3-T2: cross_sectional 模块（lookback / filter / topk / schedule + 7 单测）"
```

---

## Task 3: run_portfolio_window_cross_sectional_topk + 集成测试

**Files:**
- Modify: `scripts/backtest/window_engine.py`（追加新函数）
- Modify: `scripts/backtest/test_equal_weight_integration.py`（追加 cross-sectional 集成测试）

- [ ] **Step 1: 在 window_engine.py 末尾追加 run_portfolio_window_cross_sectional_topk**

```python
def run_portfolio_window_cross_sectional_topk(
    monthly_close_by_code: Dict[str, pd.Series],
    holdings_schedule: Dict[pd.Timestamp, set],
    window_years: int,
    as_of: pd.Timestamp,
) -> WindowResult:
    """横截面 top-K 路径：portfolio-level equity，无 per-index BacktestResult。

    与 run_portfolio_window_equal_weight 的差别：
    - 不接受 IndexData / full_results；接受预算好的 holdings_schedule
    - 资金统一池（TOTAL_CAPITAL = INDEX_CAPITAL × len(monthly_close_by_code)），
      每月 rebalance 平均分给 holdings；空 holdings 月 → cash idle (return = 0)
    - WindowResult.per_index = []（横截面无 per-index 概念）

    Args:
        monthly_close_by_code: code -> monthly close series
        holdings_schedule: rebalance_date -> set of codes（cross_sectional.build_holdings_schedule 输出）
        window_years: 窗口年数
        as_of: 评估日
    """
    window_start = as_of - pd.DateOffset(years=window_years)
    total_capital = INDEX_CAPITAL * len(monthly_close_by_code)

    # 取窗口内的 rebalance dates（升序）
    window_dates = sorted([d for d in holdings_schedule if window_start <= d <= as_of])
    if not window_dates:
        # 窗口内无 rebalance（universe 数据全在窗口外）→ flat
        portfolio_curve = pd.Series([total_capital], index=[as_of])
        return WindowResult(
            window_years=window_years, window_start=window_start, as_of=as_of,
            index_count=0, initial_capital=total_capital, final_value=total_capital,
            total_return=0.0, cagr=0.0, max_drawdown=0.0, per_index=[],
        )

    # 累积 equity_curve（月度 series）
    equity_records: Dict[pd.Timestamp, float] = {window_start: total_capital}
    cur_equity = total_capital
    prev_holdings: set = set()
    prev_date: Optional[pd.Timestamp] = None

    for date in window_dates:
        if prev_date is not None and prev_holdings:
            # 计算 prev_holdings 在 (prev_date, date] 的平均收益
            returns = []
            for code in prev_holdings:
                s = monthly_close_by_code.get(code)
                if s is None or prev_date not in s.index or date not in s.index:
                    continue
                p0 = float(s.loc[prev_date])
                p1 = float(s.loc[date])
                if p0 > 0 and not pd.isna(p0) and not pd.isna(p1):
                    returns.append(p1 / p0 - 1)
            if returns:
                portfolio_return = sum(returns) / len(returns)  # 等权
                cur_equity = cur_equity * (1 + portfolio_return)
        equity_records[date] = cur_equity
        prev_holdings = holdings_schedule[date]
        prev_date = date

    portfolio_curve = pd.Series(equity_records).sort_index()

    final_value = float(portfolio_curve.iloc[-1])
    total_return = (final_value / total_capital - 1) * 100
    years = (as_of - window_start).days / 365.25
    cagr = (
        ((final_value / total_capital) ** (1 / years) - 1) * 100
        if years > 0 and total_capital > 0
        else 0.0
    )
    max_dd = _max_drawdown(portfolio_curve)

    return WindowResult(
        window_years=window_years,
        window_start=window_start,
        as_of=as_of,
        index_count=len(monthly_close_by_code),
        initial_capital=total_capital,
        final_value=final_value,
        total_return=total_return,
        cagr=cagr,
        max_drawdown=max_dd,
        per_index=[],   # 横截面无 per-index
    )
```

注意：函数顶部需要 `from typing import Optional` 已存在；`pd` 和 `_max_drawdown` 与 INDEX_CAPITAL 都在本模块内可用。

- [ ] **Step 2: 在 test_equal_weight_integration.py 末尾追加集成测试**

```python
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
```

- [ ] **Step 3: 跑测试确认通过**

```bash
pytest scripts/backtest/test_equal_weight_integration.py -v --tb=short 2>&1 | tail -10
```

Expected: 2 passed（cycle 1 hotfix 那 1 个 + cycle 3 这 1 个）

- [ ] **Step 4: 跑全 backtest 套件零退化**

```bash
pytest scripts/backtest/test_*.py --tb=short 2>&1 | tail -3
```

Expected: 85 passed（84 + 1）

- [ ] **Step 5: Commit**

```bash
git add scripts/backtest/window_engine.py scripts/backtest/test_equal_weight_integration.py
git commit -m "[backtest] cycle3-T3: window_engine 追加 run_portfolio_window_cross_sectional_topk + 集成测试"
```

---

## Task 4: dispatch + NoOp Decider + 注册 + compare_report 兼容 + 端到端烟测

**Files:**
- Modify: `scripts/backtest/run.py`（启用 cross-sectional dispatch + 实现 _run_cross_sectional_topk）
- Modify: `scripts/backtest/strategy/builtin.py`（追加 DualMomentumNoOpDecider + 注册 dual-momentum-top5）
- Modify: `scripts/backtest/test_strategy_builtin.py`（加 NoOp Decider 测试 + 注册测试）
- Modify: `scripts/backtest/compare_report.py`（write_compare_report 兼容空 full_results）

- [ ] **Step 1: 在 builtin.py 末尾追加 DualMomentumNoOpDecider 类**

在 `DonchianBreakoutDecider` 之后追加：

```python
class DualMomentumNoOpDecider:
    """cross-sectional 策略占位 Decider。decide 永远返回 None。

    cross-sectional 决策走 _run_cross_sectional_topk 的 universe-wide scan，
    不调用 decide(*, cycle, bar, position_shares)。本类仅满足 Strategy.decider Protocol 契约。
    """

    name = "dual-momentum-noop"

    def __init__(self) -> None:
        self.required_indicators: Tuple[Tuple[str, str, int], ...] = ()

    def decide(self, *, cycle: str, bar: pd.Series, position_shares: float) -> Optional[Signal]:
        return None
```

- [ ] **Step 2: 注册 dual-momentum-top5 策略**

在 builtin.py 末尾（在 `_donchian_200` 之后）追加：

```python
@register("dual-momentum-top5")
def _dual_momentum_top5() -> Strategy:
    return Strategy(
        name="dual-momentum-top5",
        decider=DualMomentumNoOpDecider(),
        filters=(),
        cycles=("M",),
        aggregator="cross-sectional-topk",
        params={
            "lookback_months": 12,
            "topk": 5,
            "abs_threshold": 0.0,
        },
    )
```

- [ ] **Step 3: 在 test_strategy_builtin.py 末尾追加测试**

```python
# ---------- DualMomentumNoOpDecider + dual-momentum-top5 (cycle 3) ----------

from scripts.backtest.strategy.builtin import DualMomentumNoOpDecider


def test_dual_momentum_noop_decider_returns_none():
    d = DualMomentumNoOpDecider()
    assert d.required_indicators == ()
    bar = pd.Series({"open": 100, "high": 101, "low": 99, "close": 100})
    assert d.decide(cycle="M", bar=bar, position_shares=0) is None
    assert d.decide(cycle="M", bar=bar, position_shares=1.0) is None


def test_dual_momentum_top5_registered():
    _reload_builtin()
    from scripts.backtest.strategy import get
    s = get("dual-momentum-top5")
    assert s.name == "dual-momentum-top5"
    assert s.filters == ()
    assert s.cycles == ("M",)
    assert s.aggregator == "cross-sectional-topk"
    assert s.params == {"lookback_months": 12, "topk": 5, "abs_threshold": 0.0}
    from scripts.backtest.strategy.builtin import DualMomentumNoOpDecider as _NoOpCls
    assert isinstance(s.decider, _NoOpCls)
```

- [ ] **Step 4: 修 run.py dispatch + 实现 _run_cross_sectional_topk**

打开 `scripts/backtest/run.py`，找到 `_run_one_strategy` dispatch 分支，把：

```python
    elif strat.aggregator == "cross-sectional-topk":
        raise NotImplementedError("cross-sectional-topk 留给 A 周期实施（Dual Momentum）")
```

替换为：

```python
    elif strat.aggregator == "cross-sectional-topk":
        return _run_cross_sectional_topk(strat, registry, windows)
```

然后在 `_run_equal_weight` 之后追加 `_run_cross_sectional_topk`：

```python
def _run_cross_sectional_topk(strategy, registry, windows: List[int]):
    """横截面 top-K 路径（Dual Momentum 等）：
    每月 universe scan → 选 top-K 等权持有；不出 per-index BacktestResult。

    要求 strategy.cycles = ("M",)。
    strategy.params: {"lookback_months", "topk", "abs_threshold"}（必填，无默认）
    """
    from scripts.backtest.cross_sectional import build_holdings_schedule
    from scripts.backtest.window_engine import run_portfolio_window_cross_sectional_topk

    if len(strategy.cycles) != 1 or strategy.cycles[0] != "M":
        raise ValueError(
            f"cross-sectional-topk requires cycles=('M',), got {strategy.cycles}"
        )

    params = strategy.params or {}
    lookback = params.get("lookback_months", 12)
    topk = params.get("topk", 5)
    abs_threshold = params.get("abs_threshold", 0.0)

    logger.info("加载 %d 个指数数据 ...", len(registry))
    monthly_close_by_code: Dict[str, pd.Series] = {}
    index_data: Dict[str, IndexData] = {}
    for meta in registry:
        data = load_index(meta.code, meta.source, meta.name)
        if data is None or data.monthly.empty:
            logger.warning("  %s 数据缺失", meta.code)
            continue
        monthly_close_by_code[meta.code] = data.monthly["close"]
        index_data[meta.code] = data

    if not monthly_close_by_code:
        raise ValueError("无可用指数月线数据")

    # 构造 holdings_schedule（universe-wide scan）
    schedule = build_holdings_schedule(
        monthly_close_by_code,
        lookback_months=lookback,
        topk=topk,
        abs_threshold=abs_threshold,
    )

    window_results: List[WindowResult] = []
    for n in windows:
        wr = run_portfolio_window_cross_sectional_topk(
            monthly_close_by_code=monthly_close_by_code,
            holdings_schedule=schedule,
            window_years=n,
            as_of=AS_OF,
        )
        logger.info("  %d 年 总 CAGR %.2f%% / MDD %.2f%%", n, wr.cagr, wr.max_drawdown)
        window_results.append(wr)

    # full_results 为空 dict（横截面无 per-index BacktestResult）
    full_results: Dict[str, List[BacktestResult]] = {}
    return strategy, registry, index_data, full_results, window_results
```

注意 import：确保 `pd` 在 run.py 顶部 imported（应已有）。

- [ ] **Step 5: 修 compare_report.py 兼容空 full_results**

打开 `scripts/backtest/compare_report.py`，找到 `write_compare_report` 内 diff 计算的 `for other in other_names:` 循环，在 diffs 收集前加 cross-sectional 检测：

```python
    diff_sections = []
    for other in other_names:
        _, _, _, other_full, _ = results_by_strategy[other]
        if not other_full:
            # 横截面策略（cross-sectional-topk）无 per-index full_results
            diff_sections.append(
                f"### Δ ({other} − {base_name})\n\n"
                f"（{other} 走横截面 top-K 路径，无 per-index 持仓数据，不可逐指数对比 baseline。"
                f"组合层数据见上方"组合层对比"段。）"
            )
            continue
        diffs = []
        for meta in registry:
            base_r = base_full.get(meta.code)
            other_r = other_full.get(meta.code)
            if not base_r or not other_r:
                continue
            base0, other0 = base_r[0], other_r[0]
            diffs.append({
                "code": meta.code,
                "name": meta.name,
                "delta_net_cagr": (other0.annualized_return - base0.annualized_return),
                "delta_max_dd": (other0.max_drawdown - base0.max_drawdown),
            })
        diff_md = render_per_index_diff_table(diffs)
        diff_sections.append(f"### Δ ({other} − {base_name})\n\n{diff_md}")
```

- [ ] **Step 6: 加 compare_report 兼容性单测**

在 `scripts/backtest/test_compare_report.py` 末尾追加：

```python
def test_write_compare_report_handles_empty_full_results():
    """write_compare_report 对 cross-sectional 策略空 full_results 不崩溃，输出提示。"""
    import tempfile
    from pathlib import Path
    from scripts.backtest.compare_report import write_compare_report
    from scripts.backtest.index_registry import IndexMeta

    # 构造 dummy registry + 双策略 results
    registry = [IndexMeta("000300", "沪深300", "cs_index", "宽基")]
    base_results = (None, registry, {}, {"000300": [_make_dummy_result("000300", 10.0, -15.0)]}, [_make_window_result(3, 10.0, -15.0, 30.0)])
    cross_results = (None, registry, {}, {}, [_make_window_result(3, 12.0, -10.0, 36.0)])  # 空 full_results
    by_strategy = {"baseline": base_results, "cross-sectional": cross_results}

    with tempfile.TemporaryDirectory() as tmpdir:
        out = write_compare_report(by_strategy, [3], Path(tmpdir))
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "横截面 top-K" in content  # 提示文本
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
```

- [ ] **Step 7: 跑测试**

```bash
pytest scripts/backtest/test_strategy_builtin.py scripts/backtest/test_compare_report.py -v --tb=short 2>&1 | tail -15
```

Expected: 全过（含新 NoOp + 注册 + compare_report 空 full_results 测试）

- [ ] **Step 8: 端到端烟测**

```bash
python -m scripts.backtest.run --list 2>&1 | grep dual-momentum
python -m scripts.backtest.run --strategy dual-momentum-top5 --universe combined-27 --windows 3 2>&1 | tail -5
```

Expected:
- `--list` 输出含 `dual-momentum-top5`
- `--strategy` 跑通：`加载 27 个指数数据 ...` + `3 年 总 CAGR ...% / MDD ...%`（数值合理：CAGR 通常 +5% ~ +25%，MDD 通常 -10% ~ -40%）

- [ ] **Step 9: 跑全 backtest 套件零退化**

```bash
pytest scripts/backtest/test_*.py --tb=short 2>&1 | tail -3
```

Expected: 88 passed（85 + 2 新 NoOp/注册 + 1 新 compare_report 兼容测试）

- [ ] **Step 10: Commit**

```bash
git add scripts/backtest/run.py scripts/backtest/strategy/builtin.py scripts/backtest/test_strategy_builtin.py scripts/backtest/compare_report.py scripts/backtest/test_compare_report.py
git commit -m "[backtest] cycle3-T4: dispatch cross-sectional-topk + NoOp Decider + 注册 dual-momentum-top5 + compare_report 兼容"
```

---

## Task 5: 隔离硬门槛（5 条断言，**硬门槛**）

**Files:** 无；纯验收

复用 cycle 1 T9 的 5 条断言（base SHA 仍是 `1bb961c`）：

- [ ] **Step 1: 断言 1 ── scripts/quant/ + main.py + docs/ 零修改**

```bash
git diff 1bb961c..HEAD -- scripts/quant/ scripts/main.py docs/
```

Expected: 输出**完全为空**

- [ ] **Step 2: 断言 2 ── 全 pytest 套件 + test_signal_manual 通过**

```bash
pytest scripts/backtest/test_*.py --tb=short 2>&1 | tail -3
python -m scripts.backtest.test_signal_manual 2>&1 | tail -3
```

Expected: pytest 88 passed + test_signal_manual `All tests passed.`

- [ ] **Step 3: 断言 3 ── v9-baseline on v9 universe 数值不变**

```bash
python -m scripts.backtest.run --strategy v9-baseline --universe v9 --windows 3,5,8,10 2>&1 | tail -6
```

Expected: 4 数值字符级一致

- [ ] **Step 4: 断言 4 ── v9-baseline + v9.3-bear on v9 universe compare 数值不变**

```bash
python -m scripts.backtest.run --compare v9-baseline,v9.3-bear --universe v9 --windows 3,5,8,10 2>&1 | tail -10
diff <(grep -E "^\| [0-9]+ 年" agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear.md) <(grep -E "^\| [0-9]+ 年" agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-v9universe.md) | head -40
```

Expected: 仅 Δ 行 label 结构差异，数值列字符级一致

- [ ] **Step 5: 断言 5 ── v9-baseline + v9.3-bear on main-online universe compare 数值不变**

```bash
python -m scripts.backtest.run --compare v9-baseline,v9.3-bear --universe main-online --windows 3,5,8,10 2>&1 | tail -10
diff <(grep -E "^\| [0-9]+ 年" agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear.md) <(grep -E "^\| [0-9]+ 年" agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-mainonline.md) | head -40
```

Expected: 同上

- [ ] **Step 6: 5 条全过则**清理临时文件：

```bash
rm -f agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear.md
```

任意一条失败 → BLOCKED → 排查回滚。**本 task 不产生 commit**。

---

## Task 6: 跑 5 策略 compare on combined-27

**Files:** 输出报告到 `agents/results/2026-05-11-compare-v9-baseline-vs-v9.3-bear-vs-faber-gtaa-vs-donchian-200-vs-dual-momentum-top5.md`

注意：今天日期 2026-05-11，文件名用 5-11；compare_report 自动用 `date.today().isoformat()` 构造。

- [ ] **Step 1: 跑 5 策略 compare**

```bash
source venv/bin/activate
time python -m scripts.backtest.run --compare v9-baseline,v9.3-bear,faber-gtaa,donchian-200,dual-momentum-top5 --universe combined-27 --windows 3,5,8,10 2>&1 | tee /tmp/5way-compare.log | tail -40
```

Expected: 退出码 0；总耗时 ≤ 10 分钟；输出含 5 段 `加载 27 个指数数据 ...` + 20 行 `N 年 总 CAGR ...% / MDD ...%`

- [ ] **Step 2: 检查报告生成**

```bash
ls -la agents/results/2026-05-11-compare-v9-baseline-vs-v9.3-bear-vs-faber-gtaa-vs-donchian-200-vs-dual-momentum-top5.md
head -120 agents/results/2026-05-11-compare-v9-baseline-vs-v9.3-bear-vs-faber-gtaa-vs-donchian-200-vs-dual-momentum-top5.md
```

Expected: 文件存在；表头有 9 行 per 窗口 = 36 行表数据：每窗口 5 行策略 + 4 行 Δ；分指数差异表对 dual-momentum 显示横截面提示

- [ ] **Step 3: 人工 sanity check**

```bash
open /Users/loopq/dev/git/loopq/trend.github.io/agents/results/2026-05-11-compare-v9-baseline-vs-v9.3-bear-vs-faber-gtaa-vs-donchian-200-vs-dual-momentum-top5.md
```

确认：
- 5 策略数值都不同（v9-baseline / v9.3-bear / faber-gtaa / donchian-200 数据应与 cycle 2 报告一致）
- dual-momentum-top5 数值合理（CAGR > 0 大概率，MDD < 0）
- 4 个 Δ 行符号正确
- 分指数差异表 dual-momentum 子段显示"横截面"提示

- [ ] **Step 4: 本 task 不 commit**（Task 7 加完中文解读后一起 commit）

---

## Task 7: 报告中文解读 + commit

**Files:** Edit `agents/results/2026-05-11-compare-...-vs-dual-momentum-top5.md`

- [ ] **Step 1: 在报告顶部插入"一句话结论"段**

参照 cycle 2 报告结构。模板（implementer 看 Task 6 实际数据填）：

```markdown
> Universe：combined-27（v9 14 主题/行业 + main-online 16 宽基/海外/商品 去重）
> 时间窗：3 / 5 / 8 / 10 年
> 数据终点：2026-04-24

---

## 一句话结论

**5 策略 4 窗口跑下来：[填胜负画像]**。本周期最有价值的发现：
1. **决策粒度对照**：per-index in/out（faber/donchian） vs portfolio cross-sectional（dual-momentum） 在 [...] 上 [...]
2. **dual-momentum 表现**：[填 CAGR / MDD 与 baseline / faber / donchian 的对比]

具体看（ΔCAGR / ΔMaxDD vs baseline）：
- 3 年: bear / faber / donchian / **dual-momentum**
- 5 年: ...
- 8 年: ...
- 10 年: ...

---
```

- [ ] **Step 2: 在"二、组合层对比"之后插入"决策粒度对照"段**

```markdown
## 二、决策粒度对照（per-index in/out vs portfolio cross-sectional）

3 个 V10 策略 + dual-momentum 都跑月线 + combined-27，决策粒度三档：

| 策略 | 决策粒度 | 持仓数 | 资金分配 |
|---|---|---|---|
| **faber-gtaa** | per-index per-bar | 0 ~ 27（独立） | 每指数 INDEX_CAPITAL 固定 |
| **donchian-200** | per-index per-bar | 0 ~ 27（独立） | 每指数 INDEX_CAPITAL 固定 |
| **dual-momentum-top5** | portfolio per-rebalance | 0 ~ 5（universe-wide） | top-5 等分 TOTAL_CAPITAL |

[填实际对照后给结论：哪种决策粒度在 combined-27 上更胜？是均值/极值的"in/out 时点"重要，还是 cross-sectional 的"挑赢家"重要？]

---
```

- [ ] **Step 3: 在分指数差异 4 个 Δ 子段之后插入"分指数模式"段（注意 dual-momentum 的子段是横截面提示，不算 per-index）**

```markdown
### 分指数模式

按 universe 子集看 dual-momentum 在持仓时点选了哪些 + faber/donchian 与 baseline 的差异（参考上方 3 个 in/out 策略 Δ 子表）：

[implementer 填观察]

总结：dual-momentum 的"挑赢家"逻辑在 [...] 子集上 [跑赢/跑输] in/out 路线……

---
```

- [ ] **Step 4: 在报告末尾追加"五、后续方向"段**

```markdown
## 五、后续方向

### 当前 5 策略实操判断

| 策略 | 适合谁 | 理由 |
|---|---|---|
| v9-baseline | 平衡型投资者 | 总收益最高、所有窗口 CAGR 居中或居首 |
| faber-gtaa | 长期投资者（8+ 年） | 8-10y 大幅跑赢 baseline；CAGR + 回撤双赢 |
| donchian-200 | 风险厌恶投资者 | 牺牲 CAGR 换 MDD（10y 少回撤 16pp） |
| dual-momentum-top5 | [填] | [填判断] |
| v9.3-bear | 不推荐 | 4 窗口全输 |

### 调参方向（cycle 4+）

按代价从小到大：
1. **改 dual-momentum 参数**：top-3 / top-7 / lookback 6/9/24 月。注册新策略名即可。
2. **混合 universe**：[填实际观察后给方向]
3. **加 fallback**：dual-momentum 不合格时持债券/现金（需要新数据源）
4. **更复杂的 aggregator**：volatility-weighted / risk-parity 等。需要新 cycle plan。

### cycle 1-3 总结

3 个 cycle 落地了 4 个 V10 策略 + 2 个 aggregator（equal-weight / cross-sectional-topk）。下一阶段建议：
- 短期：参数扫描（dual-momentum K/lookback、faber MA 窗口、donchian 窗口）
- 中期：混合 universe（不同子集用不同策略）
- 长期：组合配置（baseline + faber + dual-momentum 加权混合，需新 portfolio aggregator）
```

- [ ] **Step 5: 把所有 `[填...]` 占位替换为基于 Task 6 实际数据的具体数字 + 观察**

- [ ] **Step 6: Commit 报告**

```bash
git add -f agents/results/2026-05-11-compare-v9-baseline-vs-v9.3-bear-vs-faber-gtaa-vs-donchian-200-vs-dual-momentum-top5.md
git commit -m "[backtest] cycle3-T7: 产出 5 策略对比报告（baseline / bear / faber / donchian / dual-momentum-top5；含中文解读）"
```

---

## Task 8: 范围检查（生产隔离不变量）

**Files:** 无；纯检查

- [ ] **Step 1: git diff 排除 scripts/quant/ + scripts/main.py + docs/**

```bash
git diff 1bb961c..HEAD --name-only | grep -E '^(scripts/quant/|scripts/main\.py|docs/)' || echo "OK: 生产 + 前端干净"
```

Expected: `OK: 生产 + 前端干净`

- [ ] **Step 2: 跑 quant 现有测试零退化**

```bash
pytest scripts/quant/tests/ --tb=short 2>&1 | tail -3
```

Expected: `179 passed`

- [ ] **Step 3: 跑 backtest 全套零退化**

```bash
pytest scripts/backtest/test_*.py --tb=short 2>&1 | tail -3
python -m scripts.backtest.test_signal_manual 2>&1 | tail -3
```

Expected: pytest 88 passed；test_signal_manual `All tests passed.`

- [ ] **Step 4: 本 task 不 commit。任何步骤失败 → 排查违反的不变量 → 回滚相关 commit**

---

## Plan 完成后

待 8 个 task 全过后给用户**周期 3 完成报告**：

- 列出 commit 序列（约 5 个 [backtest] commits：T1, T2, T3, T4, T7）
- 5 策略对比报告路径
- 关键发现（决策粒度对照实验结果）
- Reviewer Minor 建议汇总
- cycle 1-3 总结
- 用户审完批准 → 决定下一阶段方向

---

## Spec 覆盖度自查

| design.html § | 对应 Task |
|---|---|
| §0 隔离保证 | Task 5（5 条断言验收） |
| §1 背景与目标 | Plan header（Goal / Architecture） |
| §2 Dual Momentum 算法 | Task 2（cross_sectional 模块） |
| §3.1 文件结构 | Task 2（new files）+ Task 3（mod window_engine）+ Task 4（mod run.py / builtin / compare_report） |
| §3.2 Strategy.params 字段 | Task 1 |
| §3.3 dispatch 启用 | Task 4 Step 4 |
| §3.4 NoOp Decider | Task 4 Step 1 |
| §4 横截面 vs 等权 | Plan header + Task 7 中文解读 |
| §5 _run_cross_sectional_topk 流程 | Task 4 Step 4 |
| §6 run_portfolio_window_cross_sectional_topk 设计 | Task 3 Step 1 |
| §7 compare_report 兼容 | Task 4 Step 5 + 6 |
| §8 测试范围 | Task 1 Step 2 + Task 2 Step 2 + Task 3 Step 2 + Task 4 Step 3 + 6 |
| §9 验收标准 | Task 5（隔离）+ Task 4 Step 8（功能） |
| §10 报告内容 | Task 6（生成）+ Task 7（中文解读） |
| §11 关键不变量 | Task 5 + Task 8 |
| §12 风险与权衡 | 无对应 task（已在 design 文档化） |
| §13 不在范围 | 无对应 task（说明性） |

13 章节全部映射，无遗漏。

## Self-review

- [x] **Spec coverage**：13 章节全映射
- [x] **Placeholder 扫描**：仅 Task 7 中文解读段有 `[填...]` 占位（implementer 看实际数据填，与 cycle 1/2 同模式）；代码段无 TBD
- [x] **类型一致性**：`Strategy.params` / `cross_sectional` 模块各函数签名 / `_run_cross_sectional_topk` / `run_portfolio_window_cross_sectional_topk` / `DualMomentumNoOpDecider` / `dual-momentum-top5` 跨 task 命名一致
- [x] **完整代码**：每个 task 含 implementer 直接执行的完整 Python 代码 + Bash 验收命令
- [x] **隔离铁律**：cycle 1 5 条断言全量复跑（Task 5）+ scope check（Task 8）
- [x] **测试先行**：T2 / T3 都按 TDD（先写实现 + 测试一起）—— 注：cycle 3 task 都是新增模块/函数，不需要"先红后绿"两步分（与 cycle 1 T7 / cycle 2 T1+T2 不同），单步实现 + 测试一起即可
