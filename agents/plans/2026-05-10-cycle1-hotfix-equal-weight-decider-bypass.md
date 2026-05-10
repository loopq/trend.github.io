# Cycle 1 Hotfix: equal-weight 路径 Decider bypass bug

> **Single-file plan**（无 design.html）：bug fix 是单点改动，spec/design/plan 高度重合，单件即可。

## Bug 描述

**位置**: `scripts/backtest/window_engine.py:241-251` (`run_portfolio_window_equal_weight`)

**现象**: cycle 1 T6 设计的 equal-weight 路径在 N 年窗口聚合时，每指数构造 `BucketGroup` 调 V2 旧框架 `run_strategy(BucketGroup)`——内部跑的是 `_run_state_machine_and_trade` = **MA20 干净 K 线状态机默认行为**，**完全忽略 `strategy.decider`**。

```python
# 现有错误代码：
single = BucketGroup(
    name=cycle,
    buckets=[Bucket(timeframe=_tf(cycle), capital=INDEX_CAPITAL)],
)
br = run_strategy(data, single, ...)   # ← MA20 默认，不是 Faber/Donchian
```

**发现**: cycle 2 T3 烟测 donchian-200 on combined-27 (3y) 输出 CAGR 15.16% / MDD -15.44%——**与 cycle 1 faber-gtaa 3y 完全一致**。两个不同算法不可能巧合一致；查源码确认两者都被 MA20 默认替换了。

## 影响范围

| 受影响 | 不受影响 |
|---|---|
| ❌ cycle 1 faber-gtaa 全部 N 年 CAGR/MDD（4 窗口 × 2 数值 = 8 个，是 MA20 数据非 Faber） | ✅ v9-baseline / v9.3-bear（走 cycle-calmar 路径，不调 equal-weight） |
| ❌ cycle 1 三策略对比报告 faber 列 + Δ(faber − baseline) 行 + 中文解读 | ✅ T1-T8 隔离断言（v9-baseline / v9.3-bear 数值不变，仍是 MA20-vs-MA20 自洽） |
| ❌ cycle 2 烟测 donchian-200 数值 | ✅ cycle 1 / cycle 2 单元测试（测的是 Decider.decide 单步逻辑，不走窗口聚合） |

## Architecture

**修复**: `run_portfolio_window_equal_weight` 接受 `strategy: Strategy` 参数，用 `run_with_strategy(data, fresh_strategy)` 替换 `run_strategy(data, BucketGroup)`。每指数构造 fresh strategy 实例（fresh decider，清空内部 state 避免跨窗口/跨指数串数据）。

**Fresh decider 策略**: deepcopy decider 实例 + 清空已知 state 字段（`_state_by_cycle` / `_close_buffer_by_cycle`）。比 `type(decider)()` 更稳——支持自定义构造参数（如 `FaberMonthlyMaDecider(window=20)`）。

**隔离铁律**: 修改不能影响 v9-baseline / v9.3-bear（它们走 `_run_cycle_calmar` 路径，不触碰 `run_portfolio_window_equal_weight`）。Task 3 的 5 条隔离断言重跑验证。

**Base SHA**: `1bb961c`（cycle 1 / cycle 2 同基线，本 hotfix 也用同基线）

---

## Pre-flight

- [ ] **P1: 确认当前分支干净 + 现有测试 baseline**

  ```bash
  cd /Users/loopq/dev/git/loopq/trend.github.io
  git status   # 应为 nothing to commit
  source venv/bin/activate
  pytest scripts/backtest/test_*.py --tb=short 2>&1 | tail -3
  ```

  Expected: `74 passed`（cycle 2 T2 后 baseline）

---

## Task 1: TDD 红 - 集成测试验证 decider 真的被调用

**Files:**
- New file: `scripts/backtest/test_equal_weight_integration.py`

- [ ] **Step 1: 创建集成测试文件**

```python
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
    }, index=monthly_idx)
    # 用月线 close 反推 daily 序列（每个月一根 daily K 线对应同月 close）
    daily = monthly.copy()
    weekly = monthly.copy()
    return IndexData(code=code, name=name, daily=daily, weekly=weekly, monthly=monthly)


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
```

- [ ] **Step 2: 跑测试确认失败（红）**

```bash
pytest scripts/backtest/test_equal_weight_integration.py -v --tb=short 2>&1 | tail -15
```

Expected: 失败原因之一：
- `TypeError: run_portfolio_window_equal_weight() got an unexpected keyword argument 'strategy'`（旧签名不接受 strategy 参数 → 立即暴露 API 缺失）
- 或者：`AssertionError: final_value=10000.00 接近 INDEX_CAPITAL ...`（如果某种原因 strategy 参数被忽略也能跑通调用）

任一失败都验证 bug 存在。

- [ ] **Step 3: 不 commit**（Task 2 一起 commit 测试 + 修复）

---

## Task 2: 修 run_portfolio_window_equal_weight + _run_equal_weight 调用方

**Files:**
- Modify: `scripts/backtest/window_engine.py`（修 `run_portfolio_window_equal_weight` 函数体 + 加 `_fresh_strategy` helper）
- Modify: `scripts/backtest/run.py`（修 `_run_equal_weight` 调用方传 strategy）

- [ ] **Step 1: 在 window_engine.py 顶部加 import**

确认 window_engine.py 顶部已 import `copy`。如果没有，在现有 `import` 块里加：

```python
import copy
```

并加 V10 入口 import：

```python
from scripts.backtest.engine import BacktestResult, run_strategy, run_with_strategy
from scripts.backtest.strategy.protocol import Strategy as _Strategy
```

注意：原来的 `from scripts.backtest.engine import BacktestResult, run_strategy` 改成上面的形式（保留 `run_strategy` 因为旧 `run_portfolio_window` 仍用它）。

- [ ] **Step 2: 在 window_engine.py 加 `_fresh_strategy` helper**

在 `run_portfolio_window_equal_weight` 函数定义之前加：

```python
def _fresh_strategy(strategy: _Strategy) -> _Strategy:
    """复制 strategy + 清空 decider 已知 state 字段，准备窗口重跑。
    
    避免：(1) 跨窗口 buffer 污染（窗口 N 跑完后 buffer 满，窗口 N+1 重跑会带着旧 state）；
          (2) 跨指数 buffer 污染（同 strategy 实例在不同指数间共享 decider 内部 dict）。
    
    清空已知 state 字段名约定（按现有 Decider 实现）：
    - _state_by_cycle: MA20CrossDecider, FaberMonthlyMaDecider 等用
    - _close_buffer_by_cycle: DonchianBreakoutDecider 用
    
    未来加新 state 字段名要更新本 helper（视作 known minor coupling）。
    """
    fresh = copy.deepcopy(strategy)
    for attr in ("_state_by_cycle", "_close_buffer_by_cycle"):
        if hasattr(fresh.decider, attr):
            getattr(fresh.decider, attr).clear()
    return fresh
```

- [ ] **Step 3: 修 `run_portfolio_window_equal_weight` 函数签名 + body**

把现有函数 body 中的 BucketGroup 段：

```python
        # 等权：每指数 INDEX_CAPITAL 起步，单 cycle 跑
        single = BucketGroup(
            name=cycle,
            buckets=[Bucket(timeframe=_tf(cycle), capital=INDEX_CAPITAL)],
        )

        try:
            br = run_strategy(
                data, single,
                min_evaluation_start=window_start,
                index_category=first.index_category,
            )
            eq = br.equity_curve
            actual = br.evaluation_start
        except ValueError:
            ...
```

替换为（同时签名加 `strategy: _Strategy` 参数）：

```python
def run_portfolio_window_equal_weight(
    index_data: Dict[str, IndexData],
    full_results: Dict[str, List[BacktestResult]],
    window_years: int,
    as_of: pd.Timestamp,
    cycle: str,
    strategy: _Strategy,   # 新增：V10 Strategy 对象，窗口重跑用真实 Decider
) -> WindowResult:
    """等权聚合：每指数 INDEX_CAPITAL 起步，单 cycle，不用 Calmar 权重。

    与 run_portfolio_window 的差别：
    - 不调 compute_allocation；每指数 1 个 result（list 长度=1）
    - 在 N 年窗口内用真实 V10 Strategy（fresh decider）重跑得到该指数贡献
    
    Args:
        index_data: code -> IndexData
        full_results: code -> [BacktestResult]（长度 1，单 cycle 跑出）
        window_years: 窗口年数
        as_of: 评估日
        cycle: "D" / "W" / "M" —— 决定窗口内重跑用哪个 timeframe
        strategy: V10 Strategy 对象，每指数构造 fresh 实例（避免 buffer 跨指数污染）
    """
    window_start = as_of - pd.DateOffset(years=window_years)

    bucket_series: List[pd.Series] = []
    per_index_list: List[IndexContribution] = []

    for code, results in full_results.items():
        if code not in index_data or not results:
            continue
        data = index_data[code]
        first = results[0]

        # 每指数 fresh strategy（fresh decider，state 清空）
        per_index_strategy = _fresh_strategy(strategy)

        try:
            br = run_with_strategy(
                data, per_index_strategy,
                min_evaluation_start=window_start,
                index_category=first.index_category,
            )
            eq = br.equity_curve
            actual = br.evaluation_start
        except ValueError:
            # 该 strategy 在窗口内无法启动（数据不足）→ 闲置现金
            eq = pd.Series([INDEX_CAPITAL], index=[as_of])
            actual = as_of

        if eq.empty:
            eq = pd.Series([INDEX_CAPITAL], index=[window_start])
            actual = window_start

        # 迟到部分：prepend window_start → INITIAL 条目
        if actual > window_start + pd.Timedelta(days=1) and window_start not in eq.index:
            eq = pd.concat([pd.Series({window_start: INDEX_CAPITAL}), eq]).sort_index()

        index_final = float(eq.iloc[-1])
        bucket_series.append(eq.rename(f"{code}_{cycle}"))

        is_late = actual > window_start + pd.Timedelta(days=1)
        per_index_list.append(IndexContribution(
            code=code,
            name=first.index_name,
            category=first.index_category,
            initial=INDEX_CAPITAL,
            final=index_final,
            return_pct=(index_final / INDEX_CAPITAL - 1) * 100,
            actual_start=actual,
            is_late=is_late,
        ))

    index_count = len(per_index_list)
    initial_capital = index_count * INDEX_CAPITAL
    final_value = sum(p.final for p in per_index_list)
    total_return = (final_value / initial_capital - 1) * 100 if initial_capital > 0 else 0.0
    years = (as_of - window_start).days / 365.25
    cagr = (
        ((final_value / initial_capital) ** (1 / years) - 1) * 100
        if years > 0 and initial_capital > 0
        else 0.0
    )

    portfolio_curve = _aggregate_curves(bucket_series, window_start, as_of)
    max_dd = _max_drawdown(portfolio_curve)

    return WindowResult(
        window_years=window_years,
        window_start=window_start,
        as_of=as_of,
        index_count=index_count,
        initial_capital=initial_capital,
        final_value=final_value,
        total_return=total_return,
        cagr=cagr,
        max_drawdown=max_dd,
        per_index=per_index_list,
    )
```

- [ ] **Step 4: 修 `_run_equal_weight` 调用方**

打开 `scripts/backtest/run.py`，找到 `_run_equal_weight` 函数里调 `run_portfolio_window_equal_weight` 的地方：

```python
    for n in windows:
        wr = run_portfolio_window_equal_weight(
            index_data, full_results, n, AS_OF, cycle=cycle,
        )
```

加 `strategy=strategy` 参数：

```python
    for n in windows:
        wr = run_portfolio_window_equal_weight(
            index_data, full_results, n, AS_OF, cycle=cycle,
            strategy=strategy,   # 新增：传 V10 strategy 给窗口聚合用真实 Decider
        )
```

- [ ] **Step 5: 跑集成测试转绿**

```bash
pytest scripts/backtest/test_equal_weight_integration.py -v --tb=short 2>&1 | tail -10
```

Expected: passed。

- [ ] **Step 6: 跑全 backtest 套件零退化**

```bash
pytest scripts/backtest/test_*.py --tb=short 2>&1 | tail -3
```

Expected: 75 passed（74 + 1 新集成测试）

- [ ] **Step 7: Commit**

```bash
git add scripts/backtest/window_engine.py scripts/backtest/run.py scripts/backtest/test_equal_weight_integration.py
git commit -m "[backtest] cycle1-hotfix: 修 equal-weight 窗口聚合 Decider bypass bug（影响 Faber/Donchian）"
```

---

## Task 3: 5 条 cycle 1 隔离断言重跑

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

Expected: pytest 75 passed + test_signal_manual `All tests passed.`

- [ ] **Step 3: 断言 3 ── v9-baseline on v9 universe 数值不变**

```bash
python -m scripts.backtest.run --strategy v9-baseline --universe v9 --windows 3,5,8,10 2>&1 | tail -6
```

Expected: 3年 15.32%/-12.55%、5年 10.98%/-19.69%、8年 11.51%/-22.12%、10年 9.29%/-22.25% **逐字一致**

- [ ] **Step 4: 断言 4 ── v9-baseline + v9.3-bear on v9 universe 报告数值不变**

```bash
python -m scripts.backtest.run --compare v9-baseline,v9.3-bear --universe v9 --windows 3,5,8,10 2>&1 | tail -10
diff <(grep -E "^\| [0-9]+ 年" agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear.md) <(grep -E "^\| [0-9]+ 年" agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-v9universe.md) | head -40
```

Expected: 仅 Δ 行 label 结构差异，数值列字符级一致

- [ ] **Step 5: 断言 5 ── v9-baseline + v9.3-bear on main-online universe 报告数值不变**

```bash
python -m scripts.backtest.run --compare v9-baseline,v9.3-bear --universe main-online --windows 3,5,8,10 2>&1 | tail -10
diff <(grep -E "^\| [0-9]+ 年" agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear.md) <(grep -E "^\| [0-9]+ 年" agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-mainonline.md) | head -40
```

Expected: 同上

- [ ] **Step 6: 5 条全过则**清理临时报告：

```bash
rm -f agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear.md
```

任意一条失败 → BLOCKED → 排查回滚。

**v9-baseline / v9.3-bear 走 cycle-calmar 路径不调 equal-weight，理论上完全不受影响**。如果数值变了，说明 hotfix 意外改了别的地方——立即回滚。

**本 task 不产生 commit**（纯验证）

---

## Task 4: 重跑三策略报告 + 验证 Donchian ≠ Faber

**Files:** 输出新报告到 `agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-vs-faber-gtaa.md`（覆盖 cycle 1 commit fd60c6c 的旧报告）

- [ ] **Step 1: 跑三策略 compare 命令（用真 Faber 数据）**

```bash
source venv/bin/activate
time python -m scripts.backtest.run --compare v9-baseline,v9.3-bear,faber-gtaa --universe combined-27 --windows 3,5,8,10 2>&1 | tee /tmp/3way-compare-fixed.log | tail -20
```

Expected: 退出码 0；输出含 3 段 `加载 27 个指数数据 ...` + 12 行 `N 年 总 CAGR ...% / MDD ...%`

记录新数字（4 窗口 × 3 策略 = 12 个 CAGR/MDD 对）。

- [ ] **Step 2: 对比 Faber 新数据 vs cycle 1 旧报告**

```bash
# 旧报告（fd60c6c commit 的）
git show fd60c6c:agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-vs-faber-gtaa.md | head -50
# 新报告 head
head -50 agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-vs-faber-gtaa.md
```

期望差异：
- v9-baseline / v9.3-bear 列**完全相同**（验证 hotfix 没影响 cycle-calmar 路径）
- faber-gtaa 列**显著不同**（旧的是 MA20 数据 ≈ 与 baseline 接近；新的是真 Faber，可能差异较大）

- [ ] **Step 3: 验证 Donchian 烟测数字不再与 Faber 一致**

```bash
python -m scripts.backtest.run --strategy donchian-200 --universe combined-27 --windows 3 2>&1 | tail -3
```

Expected: CAGR/MDD 数字与 faber-gtaa 3y 数字**不一致**（如果还一致，bug 没修干净——BLOCK）

- [ ] **Step 4: 不 commit**（Task 5 加完中文解读后一起 commit）

---

## Task 5: 重写 cycle 1 报告中文解读 + commit

**Files:** Edit `agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-vs-faber-gtaa.md`（覆盖 cycle 1 fd60c6c 的内容）

- [ ] **Step 1: 重写"一句话结论"段（顶部）基于 Task 4 真实 Faber 数据**

模板：

```markdown
> Universe：combined-27（v9 14 主题/行业 + main-online 16 宽基/海外/商品 去重）
> 时间窗：3 / 5 / 8 / 10 年
> 数据终点：2026-04-24
> ⚠️ 本报告于 2026-05-10 重生成（修复 cycle 1 equal-weight 路径 Decider bypass bug，旧报告 fd60c6c faber 列不可信）

---

## 一句话结论

**[基于真实 Faber 数据填]**：v9.3-bear 全输 baseline X.XX ~ X.XXpp（与 cycle 1 一致）；faber-gtaa [赢/输/部分赢] baseline。

具体看（ΔCAGR / ΔMaxDD vs baseline）：
- 3 年: bear ΔCAGR = X.XXpp / ΔMaxDD = X.XXpp; faber ΔCAGR = X.XXpp / ΔMaxDD = X.XXpp
- 5 年: ...
- 8 年: ...
- 10 年: ...

[填 Faber 整体表现的简短判断：与 baseline 的差距、与 v9.3-bear 路线的对比]

---
```

- [ ] **Step 2: 重写"二、与 v9.3-bear 路线对照"段**

参考 cycle 1 旧报告结构，但 faber 一行的 ΔCAGR 数字换成新数据。

- [ ] **Step 3: 重写"分指数模式"段**

打开新报告查看 Δ(faber-gtaa − v9-baseline) 子表的实际数据，按 universe 子集（A 股宽基/主题/港股/美股/加密商品）填入 真实 per-index 观察，替换 cycle 1 旧报告里基于 MA20-vs-MA20 巧合数据的错误观察。

- [ ] **Step 4: 重写"四、后续方向"段**

- 当前 Faber 实操判断段：基于真实数据重写（Faber 是否值得替换 baseline / 在哪些 universe 子集生效）
- 调参方向 4 条保持原样

- [ ] **Step 5: 把所有 `[填...]` 占位用真实数据替换**

- [ ] **Step 6: Commit 报告**

```bash
git add -f agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-vs-faber-gtaa.md
git commit -m "[backtest] cycle1-hotfix: 重生成 Faber 三策略对比报告（修 Decider bypass bug 后真实数据）"
```

---

## Task 6: 范围检查 + 完成报告

**Files:** 无；纯检查

- [ ] **Step 1: 全部 commit 后再次 git diff 排除 scripts/quant/ + scripts/main.py + docs/**

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

Expected: pytest 75 passed；test_signal_manual `All tests passed.`

- [ ] **Step 4: 给用户 hotfix 完成报告**

包含：
- bug 描述（窗口聚合 BucketGroup → MA20 默认状态机替换 Decider）
- 修复 commit SHA + 涉及文件
- cycle 1 真实 Faber 数据 vs 旧（错误）数据对比表
- cycle 2 烟测验证 Donchian ≠ Faber 的新数字
- 影响范围确认（v9-baseline / v9.3-bear 不变）
- 下一步建议（继续 cycle 2 T3 烟测重测）

**本 task 不 commit**

---

## Plan 完成后

cycle 1 数据修复完毕。回到 cycle 2 task 流水线：
- 重置 task #16 (cycle 2 T3) 为 in_progress
- 重新跑 T3 烟测，验证 donchian-200 数字与 Faber 不同
- 继续 T4-T7

---

## Self-review

- [x] **Bug root cause**：清晰定位到 window_engine.py:241-251 的 BucketGroup 调用走 V2 框架
- [x] **修复策略**：deepcopy + 清空已知 state 字段（最简实用，已知 minor coupling 文档化）
- [x] **隔离保证**：v9-baseline / v9.3-bear 走 cycle-calmar 路径不动；Task 3 5 条断言重跑验证
- [x] **测试先行**：Task 1 加集成测试明确钉住"decider 真的被调用"不变量，未来防回归
- [x] **报告修复**：Task 4-5 重生成 cycle 1 三策略报告 + 真实数据中文解读
