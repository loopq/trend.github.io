> Design: ./2026-05-10-faber-gtaa-and-equal-weight-aggregator-design.html

# 共享前置 + B Faber GTAA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Plan 是 self-contained**：每个 task 含完整代码 / 测试 / 验收命令，implementer 不必跳读 design.html。design 仅用于全局背景理解（架构 SVG / 验收标准 / 风险）。

**Goal:** 在 `scripts/backtest/` 落地 Faber GTAA 月线 MA10 趋势策略 + 共享前置（aggregator 字段 + equal-weight 流程 + combined-27 universe + N 策略对比报告），跑出 3 策略对比报告（v9-baseline / v9.3-bear / faber-gtaa）。

**Architecture:** `Strategy` dataclass 加 `aggregator: str` 字段（默认 `"cycle-calmar"` = 现有行为）。`run.py:_run_one_strategy` 按 `aggregator` dispatch 到 `cycle-calmar` 旧逻辑剥离 / `equal-weight` 新增 / `cross-sectional-topk` 占位三条路径。Faber 走 `equal-weight`：单 cycle (M)、27 指数等权 1/N、Decider 信号决定 in/out。

**Tech Stack:** Python 3.9+、pandas、pytest。沿用现有 `scripts/backtest/strategy/` 框架。

**隔离铁律：** 所有改动对 v9-baseline / v9.3-bear / V5-V9 历史入口零行为变更。Task 9 是硬门槛——任何破坏现有数值的改动必须回退。

---

## Pre-flight

- [ ] **P1: 确认当前分支干净 + 现有测试 baseline**

  ```bash
  cd /Users/loopq/dev/git/loopq/trend.github.io
  git status   # 应为 nothing to commit
  source venv/bin/activate
  pytest scripts/backtest/test_*.py --tb=short 2>&1 | tail -3
  ```

  Expected: `44 passed`（base SHA `1bb961c`，旧 plan commit 之后）

---

## Task 1: 注册 universe `combined-27`

**Files:**
- Modify: `scripts/backtest/run.py`（在 `_build_main_online_universe` 函数下方加 `_build_combined_27_universe`，并在 `UNIVERSES` dict 加新 entry）

- [ ] **Step 1: 在 run.py 的 UNIVERSES dict 之前追加新工厂函数**

```python
def _build_combined_27_universe():
    """v9 universe 14 + main-online 16，去重 3 个（创业板50/科创50/中证2000）= 27 个唯一指数。"""
    from scripts.backtest.index_registry import IndexMeta
    return [
        # ---- A 股宽基 8 ----
        IndexMeta("000300", "沪深300",   "cs_index",    "宽基"),
        IndexMeta("000016", "上证50",    "cs_index",    "宽基"),
        IndexMeta("000905", "中证500",   "cs_index",    "宽基"),
        IndexMeta("000852", "中证1000",  "cs_index",    "宽基"),
        IndexMeta("000688", "科创50",    "cs_index",    "宽基"),
        IndexMeta("932000", "中证2000",  "cs_index",    "宽基"),
        IndexMeta("399673", "创业板50",  "sina_index",  "宽基"),
        IndexMeta("899050", "北证50",    "cs_index",    "宽基"),
        # ---- A 股主题 9 ----
        IndexMeta("931151", "光伏产业",  "cs_index",    "主题"),
        IndexMeta("399997", "中证白酒",  "cs_index",    "主题"),
        IndexMeta("399989", "中证医疗",  "cs_index",    "主题"),
        IndexMeta("931079", "5G通信",    "cs_index",    "主题"),
        IndexMeta("399808", "中证新能",  "cs_index",    "主题"),
        IndexMeta("931071", "人工智能",  "cs_index",    "主题"),
        IndexMeta("930721", "CS智汽车",  "cs_index",    "主题"),
        IndexMeta("399967", "中证军工",  "cs_index",    "主题"),
        IndexMeta("399976", "CS新能车",  "sina_index",  "主题"),
        # ---- A 股行业 2 ----
        IndexMeta("000819", "有色金属",  "cs_index",    "行业"),
        IndexMeta("000813", "细分化工",  "cs_index",    "行业"),
        # ---- 港股 3 ----
        IndexMeta("HSI",    "恒生指数",  "hk",          "港股"),
        IndexMeta("HSCEI",  "国企指数",  "hk",          "港股"),
        IndexMeta("HSTECH", "恒生科技",  "hk",          "港股"),
        # ---- 海外宽基 2 ----
        IndexMeta("NDX",    "纳指100",   "us",          "海外宽基"),
        IndexMeta("SPX",    "标普500",   "us",          "海外宽基"),
        # ---- 加密 1 ----
        IndexMeta("BTC",    "比特币",    "crypto",      "加密"),
        # ---- 商品 2 ----
        IndexMeta("XAU",    "黄金现价",  "spot_price",  "商品"),
        IndexMeta("XAG",    "白银现价",  "spot_price",  "商品"),
    ]
```

- [ ] **Step 2: 在 `UNIVERSES` dict 加 entry**

```python
UNIVERSES = {
    "v9": build_v9_registry,
    "main-online": _build_main_online_universe,
    "combined-27": _build_combined_27_universe,   # 新增
}
```

- [ ] **Step 3: 烟测 v9-baseline 在新 universe 跑通（数据缓存命中应秒级；首次会拉部分网络）**

```bash
source venv/bin/activate
python -m scripts.backtest.run --strategy v9-baseline --universe combined-27 --windows 3 2>&1 | tail -5
```

Expected: 输出 `加载 27 个指数数据 ...` + 1 行 `3 年 总 CAGR ...% / MDD ...%` + 退出码 0

- [ ] **Step 4: Commit**

```bash
git add scripts/backtest/run.py
git commit -m "[backtest] T1: 注册 universe combined-27（v9 14 + main-online 16 去重 = 27 个）"
```

---

## Task 2: `Strategy.aggregator` 字段 + `Decider.required_indicators` 字段

**Files:**
- Modify: `scripts/backtest/strategy/protocol.py`

- [ ] **Step 1: 给 Decider Protocol 加 `required_indicators` 字段**

打开 `scripts/backtest/strategy/protocol.py`，找到 `class Decider(Protocol):` 处，把它改为：

```python
@runtime_checkable
class Decider(Protocol):
    name: str
    required_indicators: Tuple[Tuple[str, str, int], ...] = ()  # (cycle, col_name, window) 列表，默认空
    def decide(self, *, cycle: str, bar: pd.Series, position_shares: float) -> Optional[Signal]:
        """根据当根 K 线和当前持仓决定 BUY / SELL / 无动作。"""
        ...
```

注意：原来的 `name: str` 与 `decide` 方法保持不变，仅在中间插入一行 `required_indicators`。

- [ ] **Step 2: 给 Strategy dataclass 加 `aggregator` 字段（末尾、有默认值）**

找到 `@dataclass(frozen=True) class Strategy:` 处，在 `cycles` 字段下方加 `aggregator`：

```python
@dataclass(frozen=True)
class Strategy:
    """组件化策略 = Decider + 一组 Filter。"""
    name: str
    decider: Decider
    filters: Tuple[Filter, ...] = field(default_factory=tuple)
    cycles: Tuple[str, ...] = ("D", "W", "M")
    aggregator: str = "cycle-calmar"   # "cycle-calmar"|"equal-weight"|"cross-sectional-topk"
```

- [ ] **Step 3: 跑现有 pytest 套件确认零退化（向后兼容验证）**

```bash
pytest scripts/backtest/test_*.py --tb=short 2>&1 | tail -3
```

Expected: `44 passed`

- [ ] **Step 4: 烟测 v9-baseline 数值不变**

```bash
python -m scripts.backtest.run --strategy v9-baseline --universe v9 --windows 3,5,8,10 2>&1 | tail -6
```

Expected 数值（**逐字一致**才能进 Task 3）：
- 3 年: `15.32% / -12.55%`
- 5 年: `10.98% / -19.69%`
- 8 年: `11.51% / -22.12%`
- 10 年: `9.29% / -22.25%`

- [ ] **Step 5: Commit**

```bash
git add scripts/backtest/strategy/protocol.py
git commit -m "[backtest] T2: Strategy 加 aggregator + Decider 加 required_indicators 字段（向后兼容）"
```

---

## Task 3: `_ensure_indicators` helper

**Files:**
- Modify: `scripts/backtest/engine.py`（在 `run_with_strategy` 函数定义之前加 `_ensure_indicators` helper，并在 `run_with_strategy` 函数体首行调用）

- [ ] **Step 1: 在 engine.py 加 `_ensure_indicators` helper**

在 `engine.py` 内 `def run_with_strategy(...)` 这一行之前，加：

```python
def _ensure_indicators(data: IndexData, requirements) -> None:
    """按 decider.required_indicators 在 data.{daily,weekly,monthly} 上加 MA 列。

    requirements: ((cycle, col_name, window), ...)，cycle 取 "D"/"W"/"M"。
    若列已存在则跳过；用 compute_ma 计算并 inplace 赋值。
    """
    for cycle, col_name, window in requirements:
        target_df = {"D": data.daily, "W": data.weekly, "M": data.monthly}[cycle]
        if col_name in target_df.columns:
            continue
        target_df[col_name] = compute_ma(target_df["close"], window=window)
```

- [ ] **Step 2: 在 `run_with_strategy` 函数体首行调用**

在 `def run_with_strategy(...)` 函数体内最前面（在原 `cycles_set = set(strategy.cycles)` 之前）加一行：

```python
def run_with_strategy(
    data: IndexData,
    strategy: _ComposedStrategy,
    min_evaluation_start: Optional[pd.Timestamp] = None,
    index_category: str = "",
) -> BacktestResult:
    """新框架入口：按 strategy.cycles 遍历 bucket，每根 K 线先 decide → 过 filters → 落 trade。"""
    _ensure_indicators(data, getattr(strategy.decider, "required_indicators", ()))   # 新增
    cycles_set = set(strategy.cycles)
    # ... 其余逻辑不变
```

- [ ] **Step 3: 跑现有 pytest 套件确认零退化（现有 `MA20CrossDecider` / `BearTrendFilter` 默认 `required_indicators=()`，helper 跳过）**

```bash
pytest scripts/backtest/test_*.py --tb=short 2>&1 | tail -3
```

Expected: `44 passed`

- [ ] **Step 4: Commit**

```bash
git add scripts/backtest/engine.py
git commit -m "[backtest] T3: engine 新增 _ensure_indicators helper（按 Decider.required_indicators 按需补 MA）"
```

---

## Task 4: `_run_one_strategy` 拆分为 `_run_cycle_calmar` + dispatch

**Files:**
- Modify: `scripts/backtest/run.py`

- [ ] **Step 1: 把现有 `_run_one_strategy` 函数体原样剥离为 `_run_cycle_calmar` 私有函数**

打开 `scripts/backtest/run.py`，把现在的 `_run_one_strategy(strategy_name, universe_name, windows)` 整个函数 **改名** 为 `_run_cycle_calmar(strategy, registry, windows)`，并改签名（接受已构造的 strategy + registry，不再自己 load）：

```python
def _run_cycle_calmar(strategy, registry, windows: List[int]):
    """cycle-calmar 路径（v9-baseline / v9.3-bear 用）：
    每指数 D/W/M 三 cycle 拆开跑 → Calmar 权重切 → 多窗口聚合。
    剥离自原 _run_one_strategy 函数体，逻辑零改动。
    """
    from scripts.backtest.strategy import Strategy as _StrategyCls
    strat = strategy
    strategy_name = strat.name

    logger.info("加载 %d 个指数数据 ...", len(registry))
    index_data: Dict[str, IndexData] = {}
    full_results: Dict[str, List[BacktestResult]] = {}
    for meta in registry:
        data = load_index(meta.code, meta.source, meta.name)
        if data is None or data.daily.empty:
            logger.warning("  %s 数据缺失", meta.code)
            continue
        index_data[meta.code] = data

        cycle_results: List[BacktestResult] = []
        for cycle in strat.cycles:
            cycle_strat = _StrategyCls(
                name=f"{strategy_name}-{cycle}",
                decider=type(strat.decider)(),
                filters=strat.filters,
                cycles=(cycle,),
                aggregator=strat.aggregator,
            )
            try:
                r = run_with_strategy(data, cycle_strat,
                                      min_evaluation_start=MIN_EVALUATION_START,
                                      index_category=meta.category)
            except ValueError as e:
                logger.warning("  %s/%s 回测失败：%s", meta.code, cycle, e)
                continue
            r.strategy_name = cycle
            cycle_results.append(r)

        if cycle_results:
            full_results[meta.code] = cycle_results

    window_results: List[WindowResult] = []
    for n in windows:
        wr = run_portfolio_window(index_data, full_results, n, AS_OF)
        logger.info("  %d 年 总 CAGR %.2f%% / MDD %.2f%%", n, wr.cagr, wr.max_drawdown)
        window_results.append(wr)

    return strat, registry, index_data, full_results, window_results
```

- [ ] **Step 2: 重写 `_run_one_strategy` 为 dispatch 路由**

在 `_run_cycle_calmar` 之后添加新 `_run_one_strategy`：

```python
def _run_one_strategy(strategy_name: str, universe_name: str, windows: List[int]):
    """Dispatch 路由：按 strategy.aggregator 走不同流程。"""
    strat = get_strategy(strategy_name)
    registry = _load_universe(universe_name)

    if strat.aggregator == "cycle-calmar":
        return _run_cycle_calmar(strat, registry, windows)
    elif strat.aggregator == "equal-weight":
        return _run_equal_weight(strat, registry, windows)
    elif strat.aggregator == "cross-sectional-topk":
        raise NotImplementedError("cross-sectional-topk 留给 A 周期实施（Dual Momentum）")
    else:
        raise ValueError(f"unknown aggregator: {strat.aggregator!r}")


def _run_equal_weight(strategy, registry, windows: List[int]):
    """stub，Task 5 实现。"""
    raise NotImplementedError("Task 5 will implement this")
```

- [ ] **Step 3: 跑 v9-baseline / v9.3-bear 在 v9 universe 数值不变（验证 cycle-calmar 路径一字未变）**

```bash
python -m scripts.backtest.run --compare v9-baseline,v9.3-bear --universe v9 --windows 3,5,8,10 2>&1 | tail -10
```

Expected 数值（与 v9universe 报告对照）：
- v9-baseline: 3年 15.32%/-12.55% / 5年 10.98%/-19.69% / 8年 11.51%/-22.12% / 10年 9.29%/-22.25%
- v9.3-bear: 3年 13.28%/-12.43% / 5年 7.88%/-25.29% / 8年 9.98%/-26.45% / 10年 7.95%/-26.73%

**逐字一致**才能进 Task 5。

- [ ] **Step 4: Commit**

```bash
git add scripts/backtest/run.py
git commit -m "[backtest] T4: _run_one_strategy 拆 dispatch（cycle-calmar 路径剥离零改动）"
```

---

## Task 5: `_run_equal_weight` 实现

**Files:**
- Modify: `scripts/backtest/run.py`（替换 Task 4 的 stub `_run_equal_weight`）

- [ ] **Step 1: 替换 `_run_equal_weight` stub 为完整实现**

把 Task 4 加的 stub 替换为：

```python
def _run_equal_weight(strategy, registry, windows: List[int]):
    """equal-weight 路径（Faber GTAA / Donchian 用）：
    单 cycle、每指数 INDEX_CAPITAL 等权满仓 in/out、不用 Calmar 权重。

    要求 strategy.cycles 长度 = 1。
    """
    if len(strategy.cycles) != 1:
        raise ValueError(
            f"equal-weight aggregator requires single cycle, got {strategy.cycles}"
        )
    cycle = strategy.cycles[0]
    strategy_name = strategy.name

    logger.info("加载 %d 个指数数据 ...", len(registry))
    index_data: Dict[str, IndexData] = {}
    full_results: Dict[str, List[BacktestResult]] = {}
    for meta in registry:
        data = load_index(meta.code, meta.source, meta.name)
        if data is None or data.daily.empty:
            logger.warning("  %s 数据缺失", meta.code)
            continue
        index_data[meta.code] = data
        try:
            r = run_with_strategy(
                data, strategy,    # cycles=(cycle,) 时 engine 内只跑该 cycle
                min_evaluation_start=MIN_EVALUATION_START,
                index_category=meta.category,
            )
            # 注意：equal-weight **不**走 compute_allocation，所以不 rewrite r.strategy_name。
            # r.strategy_name 保持 = strategy.name（如 "faber-gtaa"），报告里直接显示策略名。
            full_results[meta.code] = [r]
        except ValueError as e:
            logger.warning("  %s 回测失败：%s", meta.code, e)

    window_results: List[WindowResult] = []
    for n in windows:
        wr = run_portfolio_window_equal_weight(
            index_data, full_results, n, AS_OF, cycle=cycle,
        )
        logger.info("  %d 年 总 CAGR %.2f%% / MDD %.2f%%", n, wr.cagr, wr.max_drawdown)
        window_results.append(wr)

    return strategy, registry, index_data, full_results, window_results
```

并在 `run.py` 顶部 import 处加：

```python
from scripts.backtest.window_engine import (
    INDEX_CAPITAL,
    WindowResult,
    run_portfolio_window,
    run_portfolio_window_equal_weight,   # 新增（Task 6 实现）
)
```

- [ ] **Step 2: 跑现有 pytest 套件零退化（cycle-calmar 路径不动；equal-weight 等 Task 6 联调）**

```bash
pytest scripts/backtest/test_*.py --tb=short 2>&1 | tail -3
```

Expected: `44 passed`（注：因 `run_portfolio_window_equal_weight` 未实现，但只有 `--strategy faber-gtaa` 才会触发，pytest 不调）

- [ ] **Step 3: Commit**

```bash
git add scripts/backtest/run.py
git commit -m "[backtest] T5: 实现 _run_equal_weight（单 cycle + 等权聚合）"
```

---

## Task 6: `run_portfolio_window_equal_weight` 实现

**Files:**
- Modify: `scripts/backtest/window_engine.py`（追加新函数 `run_portfolio_window_equal_weight`，复用现有 `IndexContribution / WindowResult / _aggregate_curves / _max_drawdown`）

- [ ] **Step 1: 在 window_engine.py 文件末尾追加新函数**

```python
def run_portfolio_window_equal_weight(
    index_data: Dict[str, IndexData],
    full_results: Dict[str, List[BacktestResult]],
    window_years: int,
    as_of: pd.Timestamp,
    cycle: str,
) -> WindowResult:
    """等权聚合：每指数 INDEX_CAPITAL 起步，单 cycle，不用 Calmar 权重。

    与 run_portfolio_window 的差别：
    - 不调 compute_allocation；每指数 1 个 result（list 长度=1）
    - 在 N 年窗口内用 single-cycle BucketGroup 重跑得到该指数贡献

    Args:
        index_data: code -> IndexData
        full_results: code -> [BacktestResult]（长度 1，单 cycle 跑出）
        window_years: 窗口年数
        as_of: 评估日
        cycle: "D" / "W" / "M" —— 决定窗口内重跑用哪个 timeframe
    """
    window_start = as_of - pd.DateOffset(years=window_years)

    bucket_series: List[pd.Series] = []
    per_index_list: List[IndexContribution] = []

    for code, results in full_results.items():
        if code not in index_data or not results:
            continue
        data = index_data[code]
        first = results[0]

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
            # 该 bucket 在窗口内无法启动（数据不足）→ 闲置现金
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

- [ ] **Step 2: 跑现有 pytest 套件零退化（新函数仅在 equal-weight 路径调用，旧路径不变）**

```bash
pytest scripts/backtest/test_*.py --tb=short 2>&1 | tail -3
```

Expected: `44 passed`

- [ ] **Step 3: Commit**

```bash
git add scripts/backtest/window_engine.py
git commit -m "[backtest] T6: window_engine 新增 run_portfolio_window_equal_weight（不用 Calmar，每指数等权）"
```

---

## Task 7: `FaberMonthlyMaDecider` 实现 + 注册 `faber-gtaa` + 7 个测试

**Files:**
- Modify: `scripts/backtest/strategy/builtin.py`（追加 `FaberMonthlyMaDecider` 类 + `@register("faber-gtaa")` 工厂）
- Modify: `scripts/backtest/test_strategy_builtin.py`（追加 7 个测试 + 1 个注册测试）

- [ ] **Step 1: 写失败测试（先红）**

打开 `scripts/backtest/test_strategy_builtin.py`，在文件末尾追加：

```python
# ---------- FaberMonthlyMaDecider ----------

from scripts.backtest.strategy.builtin import FaberMonthlyMaDecider


def _monthly_bar(close, ma10, name=None):
    """构造月线 K（含 ma10 列；high/low/open 不参与 Faber 决策）。"""
    s = pd.Series({
        "open": close, "high": close + 1, "low": close - 1,
        "close": close, "ma10": ma10,
    })
    if name is not None:
        s.name = name
    return s


class TestFaberMonthlyMaDecider:
    def setup_method(self):
        self.d = FaberMonthlyMaDecider(window=10)

    def test_close_above_ma_no_pos_buy(self):
        sig = self.d.decide(cycle="M", bar=_monthly_bar(110, 100), position_shares=0)
        assert sig is not None
        assert sig.action == "BUY"
        assert sig.cycle == "M"
        assert sig.price == pytest.approx(110)

    def test_close_below_ma_with_pos_sell(self):
        d = FaberMonthlyMaDecider(window=10)
        d.decide(cycle="M", bar=_monthly_bar(110, 100), position_shares=0)  # 先 BUY → state=UP
        sig = d.decide(cycle="M", bar=_monthly_bar(90, 100), position_shares=1.0)
        assert sig is not None
        assert sig.action == "SELL"
        assert sig.price == pytest.approx(90)

    def test_same_dir_no_resignal(self):
        d = FaberMonthlyMaDecider(window=10)
        d.decide(cycle="M", bar=_monthly_bar(110, 100), position_shares=0)  # BUY
        sig = d.decide(cycle="M", bar=_monthly_bar(115, 100), position_shares=1.0)
        assert sig is None

    def test_ma_nan_returns_none(self):
        sig = self.d.decide(cycle="M", bar=_monthly_bar(110, float("nan")), position_shares=0)
        assert sig is None

    def test_close_equals_ma_treated_as_down(self):
        # close == ma 严格不算 UP（必须 close > ma）
        d = FaberMonthlyMaDecider(window=10)
        d.decide(cycle="M", bar=_monthly_bar(110, 100), position_shares=0)  # BUY → state=UP
        sig = d.decide(cycle="M", bar=_monthly_bar(100, 100), position_shares=1.0)
        # close==ma → state→DOWN，UP→DOWN 翻转 + pos>0 → SELL
        assert sig is not None
        assert sig.action == "SELL"

    def test_required_indicators_attr(self):
        assert FaberMonthlyMaDecider().required_indicators == (("M", "ma10", 10),)

    def test_custom_window(self):
        d = FaberMonthlyMaDecider(window=20)
        assert d.required_indicators == (("M", "ma20", 20),)
        # 用 ma20 列而非 ma10
        bar = pd.Series({"open": 110, "high": 111, "low": 109, "close": 110, "ma20": 100})
        sig = d.decide(cycle="M", bar=bar, position_shares=0)
        assert sig is not None and sig.action == "BUY"


def test_faber_gtaa_registered():
    _reload_builtin()
    from scripts.backtest.strategy import get
    s = get("faber-gtaa")
    assert s.name == "faber-gtaa"
    assert s.filters == ()
    assert s.cycles == ("M",)
    assert s.aggregator == "equal-weight"
    assert isinstance(s.decider, FaberMonthlyMaDecider)
    assert s.decider.window == 10
```

跑测试确认失败：

```bash
pytest scripts/backtest/test_strategy_builtin.py::TestFaberMonthlyMaDecider scripts/backtest/test_strategy_builtin.py::test_faber_gtaa_registered -v 2>&1 | tail -10
```

Expected: ImportError on `FaberMonthlyMaDecider`（类未实现）。

- [ ] **Step 2: 实现 `FaberMonthlyMaDecider`**

在 `scripts/backtest/strategy/builtin.py` **末尾** （在 `BearTrendFilter` 之后、`@register("v9-baseline")` 之前）追加：

```python
class FaberMonthlyMaDecider:
    """Faber 2007 月线 MA10 趋势跟踪。

    每根月线 K 线：
      close > MA{window} → 状态切 UP；UP 翻转 + 空仓 → BUY
      close ≤ MA{window} → 状态切 DOWN；DOWN 翻转 + 持仓 → SELL
      MA NaN → None（数据不足）

    与 MA20CrossDecider 的区别：
    - 用 close 直接比 MA，不用 low/high "干净 K 线"语义
    - 默认窗口 10 个月（论文原值）
    - 仅跑 monthly cycle（用 strategy.cycles=("M",) 约束）
    """

    name = "faber-monthly-ma"

    def __init__(self, window: int = 10) -> None:
        self.window = window
        self.required_indicators = (("M", f"ma{window}", window),)
        self._state_by_cycle: Dict[str, Optional[str]] = {}

    def decide(self, *, cycle: str, bar: pd.Series, position_shares: float) -> Optional[Signal]:
        ma_col = f"ma{self.window}"
        ma = bar.get(ma_col)
        close = bar.get("close")
        if pd.isna(ma) or pd.isna(close):
            return None
        new_dir = "UP" if close > ma else "DOWN"
        prev = self._state_by_cycle.get(cycle)
        if new_dir == prev:
            return None
        self._state_by_cycle[cycle] = new_dir
        if new_dir == "UP" and position_shares == 0:
            return Signal(action="BUY", cycle=cycle, price=float(close),
                          bar_date=pd.Timestamp(bar.name) if bar.name is not None else pd.NaT)
        if new_dir == "DOWN" and position_shares > 0:
            return Signal(action="SELL", cycle=cycle, price=float(close),
                          bar_date=pd.Timestamp(bar.name) if bar.name is not None else pd.NaT)
        return None
```

注意：Faber 用 `"BUY"` / `"SELL"` 字符串字面量，与 `MA20CrossDecider` 风格一致——避免新增 `from scripts.backtest.signal import BUY, SELL` import 行。`Signal.action` 字段是 `str` 类型，字面量与常量在功能上等价。

- [ ] **Step 3: 注册 `faber-gtaa` 策略**

在 `builtin.py` 末尾（在 `_v9_3_bear` 之后）追加：

```python
@register("faber-gtaa")
def _faber_gtaa() -> Strategy:
    return Strategy(
        name="faber-gtaa",
        decider=FaberMonthlyMaDecider(window=10),
        filters=(),
        cycles=("M",),
        aggregator="equal-weight",
    )
```

- [ ] **Step 4: 跑测试确认通过**

```bash
pytest scripts/backtest/test_strategy_builtin.py -v --tb=short 2>&1 | tail -8
```

Expected: 全 30 passed（23 原 + 7 Faber + 1 注册测试 = 31，实际看具体计数）

- [ ] **Step 5: 端到端联调（Task 5+6+7 一起验证 equal-weight 路径）**

```bash
python -m scripts.backtest.run --list 2>&1 | grep faber
python -m scripts.backtest.run --strategy faber-gtaa --universe combined-27 --windows 3 2>&1 | tail -5
```

Expected:
- `--list` 输出含 `faber-gtaa` 一行
- `--strategy` 跑通：`加载 27 个指数数据 ...` + `3 年 总 CAGR ...% / MDD ...%`（数值合理：CAGR 通常 +5% ~ +15%，MDD 通常 -10% ~ -25%）

- [ ] **Step 6: Commit**

```bash
git add scripts/backtest/strategy/builtin.py scripts/backtest/test_strategy_builtin.py
git commit -m "[backtest] T7: 实现 FaberMonthlyMaDecider + 注册 faber-gtaa（Faber 2007 月线 MA10 趋势）"
```

---

## Task 8: `compare_report` N 策略支持改造

**Files:**
- Modify: `scripts/backtest/compare_report.py`（改 `render_portfolio_table` / `render_per_index_diff_table` / `write_compare_report` 接受 N≥2 策略）
- Modify: `scripts/backtest/test_compare_report.py`（保留现有 N=2 测试 + 加 1 个 N=3 测试）
- Modify: `scripts/backtest/run.py`（`--compare` 解析改为接受 ≥ 2 个策略名）

- [ ] **Step 1: 加 1 个 N=3 失败测试到 test_compare_report.py（在 `test_filter_hit_table_lists_per_index_stats` 测试之后追加）**

```python
def test_portfolio_table_n3_strategies():
    """3 策略对比，第一个作 base，输出 3 行策略 + 2 行 Δ per 窗口。"""
    a_results = [_make_window_result(3, 14.81, -25.0, 50.0)]
    b_results = [_make_window_result(3, 16.50, -22.0, 60.0)]
    c_results = [_make_window_result(3, 12.00, -20.0, 40.0)]
    md = render_portfolio_table([
        ("v9-baseline", a_results),
        ("v9.3-bear", b_results),
        ("faber-gtaa", c_results),
    ])
    # 三策略名都在
    assert "v9-baseline" in md
    assert "v9.3-bear" in md
    assert "faber-gtaa" in md
    # 两个 Δ 行（每个非 base 策略对 base 一个 Δ）
    assert md.count("Δ") == 2
    # bear vs baseline 的 ΔCAGR = +1.69pp
    assert "+1.69" in md
    # faber vs baseline 的 ΔCAGR = -2.81pp
    assert "-2.81" in md
```

跑测试确认失败：

```bash
pytest scripts/backtest/test_compare_report.py::test_portfolio_table_n3_strategies -v 2>&1 | tail -5
```

Expected: ValueError 或 assertion 失败（render 还是 N=2 hardcoded）。

- [ ] **Step 2: 改 `render_portfolio_table` 支持 N≥2**

打开 `scripts/backtest/compare_report.py`，把 `render_portfolio_table` 整个函数替换为：

```python
def render_portfolio_table(strategies: Sequence[Tuple[str, list]]) -> str:
    """N 策略对比，每窗口 N+(N-1) 行：N 个策略各一行 + (N-1) 个 Δ 行（每个非 base 策略对 base）。"""
    if len(strategies) < 2:
        raise ValueError("portfolio table requires ≥ 2 strategies")
    base_name, base_windows = strategies[0]
    n_windows = len(base_windows)
    for name, win in strategies[1:]:
        if len(win) != n_windows:
            raise ValueError(f"strategy {name} has {len(win)} windows, expected {n_windows}")

    lines = [
        "| 时间窗 | 策略 | 总 CAGR | 最大回撤 | 总收益 |",
        "|---|---|---|---|---|",
    ]
    for w_idx in range(n_windows):
        years = base_windows[w_idx].window_years
        # N 行各策略
        lines.append(f"| {years} 年 | {base_name} | {_fmt_pct(base_windows[w_idx].cagr)} | {_fmt_pct(base_windows[w_idx].max_drawdown)} | {_fmt_pct(base_windows[w_idx].total_return, signed=True)} |")
        for name, windows in strategies[1:]:
            wr = windows[w_idx]
            lines.append(f"| {years} 年 | {name} | {_fmt_pct(wr.cagr)} | {_fmt_pct(wr.max_drawdown)} | {_fmt_pct(wr.total_return, signed=True)} |")
        # (N-1) 行 Δ
        for name, windows in strategies[1:]:
            wr = windows[w_idx]
            lines.append(
                f"| {years} 年 | Δ ({name} − {base_name}) "
                f"| {_fmt_pct(wr.cagr - base_windows[w_idx].cagr, signed=True)} "
                f"| {_fmt_pct(wr.max_drawdown - base_windows[w_idx].max_drawdown, signed=True)} "
                f"| {_fmt_pct(wr.total_return - base_windows[w_idx].total_return, signed=True)} |"
            )
    return "\n".join(lines)
```

- [ ] **Step 3: 改 `render_per_index_diff_table` 接受多策略 diff**

把 `render_per_index_diff_table` 替换为（保留原 2 策略接口，但参数改为接受 list[(name, diffs)] —— 单策略时也能 work）：

```python
def render_per_index_diff_table(
    diffs: List[Dict],
    *,
    threshold_cagr: float = 1.0,
    threshold_dd: float = 2.0,
) -> str:
    """分指数差异表。仅列 |Δ Net CAGR| ≥ threshold_cagr 或 |Δ MaxDD| ≥ threshold_dd 的指数。

    单策略 diff（diffs 是同一个非 base 策略 vs base 的差值列表）。
    多策略时由 write_compare_report 按 base 策略循环调用 N-1 次。
    """
    significant = [
        d for d in diffs
        if abs(d.get("delta_net_cagr", 0)) >= threshold_cagr
        or abs(d.get("delta_max_dd", 0)) >= threshold_dd
    ]
    if not significant:
        return "（无显著差异指数）"
    lines = [
        "| 指数 | Δ Net CAGR | Δ MaxDD |",
        "|---|---|---|",
    ]
    for d in significant:
        lines.append(
            f"| {d['name']}({d['code']}) "
            f"| {_fmt_pct(d['delta_net_cagr'], signed=True)} "
            f"| {_fmt_pct(d['delta_max_dd'], signed=True)} |"
        )
    return "\n".join(lines)
```

（这个函数保持单策略 diff 接口不变；N≥3 由 `write_compare_report` 多次调用拼接）

- [ ] **Step 4: 改 `write_compare_report` 支持 N≥2 策略**

把 `write_compare_report` 整个函数替换为：

```python
def write_compare_report(
    results_by_strategy: Dict[str, tuple],
    windows: List[int],
    output_dir: Path,
) -> Path:
    """对比报告主入口。N≥2 策略，第一个作为对照基线。

    results_by_strategy: { strategy_name: (strat, registry, index_data, full_results, window_results) }
    """
    names = list(results_by_strategy.keys())
    if len(names) < 2:
        raise ValueError(f"compare expects ≥ 2 strategies, got {names}")
    base_name = names[0]
    other_names = names[1:]

    # 收集每策略的 window_results
    per_strategy_windows = []
    for n in names:
        _, _, _, _, w = results_by_strategy[n]
        per_strategy_windows.append((n, w))
    portfolio_md = render_portfolio_table(per_strategy_windows)

    # registry 与 base full_results
    _, registry, _, base_full, _ = results_by_strategy[base_name]

    # 每个非 base 策略一份分指数 diff 子表
    diff_sections = []
    for other in other_names:
        _, _, _, other_full, _ = results_by_strategy[other]
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

    diff_full_md = "\n\n".join(diff_sections) if diff_sections else "（无）"

    # Filter 命中表占位
    hits: List[Dict] = []
    hits_md = render_filter_hit_table(hits)

    today = date.today().isoformat()
    suffix = "-vs-".join([base_name] + list(other_names))
    out = output_dir / f"{today}-compare-{suffix}.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    md = "\n\n".join([
        f"# 策略对比报告：{base_name} vs " + " vs ".join(other_names),
        f"> 生成日：{today}",
        "## 一、组合层对比",
        portfolio_md,
        "## 二、分指数差异（|ΔCAGR|≥1pp 或 |ΔMaxDD|≥2pp）",
        diff_full_md,
        "## 三、Filter 命中统计",
        hits_md,
    ])
    out.write_text(md, encoding="utf-8")
    return out
```

- [ ] **Step 5: 改 `run.py` 的 `--compare` 解析**

打开 `scripts/backtest/run.py`，找到 `if args.compare:` 分支，把 `if len(names) != 2:` 改为 `if len(names) < 2:` —— 接受任意多策略名。

```python
    if args.compare:
        names = [n.strip() for n in args.compare.split(",") if n.strip()]
        if len(names) < 2:
            raise SystemExit("--compare 需要至少两个策略名（逗号分隔）")
        results_by_strategy = {}
        for n in names:
            results_by_strategy[n] = _run_one_strategy(n, args.universe, windows)
        from scripts.backtest.compare_report import write_compare_report
        write_compare_report(results_by_strategy, windows, RESULTS_DIR)
        return 0
```

- [ ] **Step 6: 跑测试 + 现有 v9universe 报告数值不变（validate N=2 路径 backward compat）**

```bash
pytest scripts/backtest/test_compare_report.py -v 2>&1 | tail -5
python -m scripts.backtest.run --compare v9-baseline,v9.3-bear --universe v9 --windows 3,5,8,10 2>&1 | tail -10
```

Expected:
- pytest: 4 passed
- CLI 跑出报告，组合层数值与之前 v9universe 报告**逐字一致**

- [ ] **Step 7: Commit**

```bash
git add scripts/backtest/compare_report.py scripts/backtest/test_compare_report.py scripts/backtest/run.py
git commit -m "[backtest] T8: compare_report 改 N≥2 策略支持（第一个作 base）"
```

---

## Task 9: 回归验证（隔离不变量 5 条断言，**硬门槛**）

**Files:** 无新增；纯验收

- [ ] **Step 1: 断言 1 ── scripts/quant/ + main.py + docs/ 零修改**

```bash
git diff 1bb961c..HEAD -- scripts/quant/ scripts/main.py docs/
```

Expected: 输出**完全为空**

- [ ] **Step 2: 断言 2 ── 全 pytest 套件通过**

```bash
pytest scripts/backtest/test_*.py --tb=short 2>&1 | tail -3
python -m scripts.backtest.test_signal_manual 2>&1 | tail -3
```

Expected: pytest 不少于 52 passed（44 原 + 7 Faber + 1 注册 + 1 N=3 compare = 53）+ test_signal_manual `All tests passed.`

- [ ] **Step 3: 断言 3 ── v9-baseline on v9 universe 数值不变**

```bash
python -m scripts.backtest.run --strategy v9-baseline --universe v9 --windows 3,5,8,10 2>&1 | tail -6
```

Expected: 3年 15.32%/-12.55%、5年 10.98%/-19.69%、8年 11.51%/-22.12%、10年 9.29%/-22.25% **逐字一致**

- [ ] **Step 4: 断言 4 ── v9-baseline + v9.3-bear on v9 universe 报告数值不变**

```bash
python -m scripts.backtest.run --compare v9-baseline,v9.3-bear --universe v9 --windows 3,5,8,10 2>&1 | tail -10
diff <(grep -E "^\| [0-9]+ 年" agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear.md) <(grep -E "^\| [0-9]+ 年" agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-v9universe.md) | head -20
```

Expected: diff 仅 markdown 格式差异（如 `**−` 加粗符号），数值列**逐字一致**

- [ ] **Step 5: 断言 5 ── v9-baseline + v9.3-bear on main-online universe 数值不变**

```bash
python -m scripts.backtest.run --compare v9-baseline,v9.3-bear --universe main-online --windows 3,5,8,10 2>&1 | tail -10
diff <(grep -E "^\| [0-9]+ 年" agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear.md) <(grep -E "^\| [0-9]+ 年" agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-mainonline.md) | head -20
```

Expected: 同上

- [ ] **Step 6: 5 条全过才进 Task 10。任意一条失败 → BLOCKED → 排查回滚相关 commit**

5 条全过则**删除** Step 4/5 跑出的临时裸文件名报告：

```bash
rm -f agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear.md
```

**本 task 不产生 commit**（纯验证）

---

## Task 10: 跑 3 策略 compare on combined-27

**Files:** 输出报告到 `agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-vs-faber-gtaa.md`

- [ ] **Step 1: 跑 compare 命令**

```bash
source venv/bin/activate
time python -m scripts.backtest.run --compare v9-baseline,v9.3-bear,faber-gtaa --universe combined-27 --windows 3,5,8,10 2>&1 | tee /tmp/3way-compare.log | tail -20
```

Expected: 退出码 0；总耗时 ≤ 5 分钟（27 指数 × 3 策略，缓存全有时纯 CPU；含 lazy ctx 优化后 v9.3-bear ~30s）；输出含 `加载 27 个指数数据 ...` × 3 + 12 行 `N 年 总 CAGR ...% / MDD ...%`

- [ ] **Step 2: 检查报告文件生成**

```bash
ls -la agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-vs-faber-gtaa.md
head -50 agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-vs-faber-gtaa.md
```

Expected: 文件存在；表头有 5 行 per 窗口 = 20 行表数据：每窗口 3 行策略 + 2 行 Δ（v9.3-bear vs baseline、faber vs baseline）

- [ ] **Step 3: 人工 sanity check**

打开报告：
```bash
open /Users/loopq/dev/git/loopq/trend.github.io/agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-vs-faber-gtaa.md
```

确认：
- 三策略数值有差异（不全相同）
- faber-gtaa 数值合理（CAGR > 0、MaxDD < 0）
- Δ 行符号正确（`+` 表示 faber 比 baseline 高）

- [ ] **Step 4: 本 task 不 commit 报告（Task 11 加完中文解读后一起 commit）**

---

## Task 11: 报告中文解读 + commit

**Files:** Edit `agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-vs-faber-gtaa.md`（在三章节之间插入中文解读段落）

- [ ] **Step 1: 用 Read + Edit 在报告顶部（"# 策略对比报告" 之后）插入"一句话结论"段**

参照已有 `agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-mainonline.md` 的解读结构。模板：

```markdown
> Universe：combined-27（v9 14 主题/行业 + main-online 16 宽基/海外/商品 去重）
> 时间窗：3 / 5 / 8 / 10 年
> 数据终点：2026-04-24

---

## 一句话结论

**[根据实际数据填]**：v9.3-bear 全输 baseline、faber-gtaa [赢/输/部分赢]。Faber 这条"加新策略提收益"路线在 [4 个/部分窗口] 上 [跑赢/打平/跑输] baseline。

具体看：
- 3 年 ΔCAGR = X.XXpp / ΔMaxDD = X.XXpp
- 5 年 ΔCAGR = X.XXpp / ΔMaxDD = X.XXpp
- 8 年 ΔCAGR = X.XXpp / ΔMaxDD = X.XXpp
- 10 年 ΔCAGR = X.XXpp / ΔMaxDD = X.XXpp

---
```

- [ ] **Step 2: 在"二、分指数差异"章节之前插入"vs bear 路线对照"段**

```markdown
## 二、与 v9.3-bear 路线对照

之前 v9.3-bear "加 BearTrendFilter 减信号" 路线在 v9 universe 全输 -1.3 ~ -3.1pp（所有 14 指数都跑输基础策略，证明该方向反）。

本周期换 Faber "加新策略提收益" 路线，结果：

| 路线 | 思路 | combined-27 上 ΔCAGR (vs baseline) |
|---|---|---|
| v9.3-bear（已弃） | 加过滤器、减信号 | 3年 [-X.XXpp] / 5年 [-X.XXpp] / 8年 [-X.XXpp] / 10年 [-X.XXpp] |
| faber-gtaa（本周期） | 加新策略、换 Decider | 3年 [Y.YYpp] / 5年 [Y.YYpp] / 8年 [Y.YYpp] / 10年 [Y.YYpp] |

[填实际数据后给结论：哪个路线更接近"提收益"目标？]

---
```

- [ ] **Step 3: 在分指数差异表之后插入"分指数模式分析"段**

```markdown
### 分指数模式

按 universe 子集看 faber-gtaa vs baseline：
- A 股宽基（沪深300/上证50/中证500/中证1000/中证2000/创业板50/科创50/北证50）：[填观察]
- A 股主题/行业（光伏/白酒/医疗/5G/...）：[填观察]
- 港股（HSI/HSCEI/HSTECH）：[填观察]
- 美股（NDX/SPX）：[填观察]
- 加密 / 商品（BTC/XAU/XAG）：[填观察]

---
```

- [ ] **Step 4: 在报告末尾追加"后续方向"段**

```markdown
## 四、后续方向

### 当前 Faber 实操判断

[填：Faber GTAA 是否值得替换 baseline？或仅在某 universe 子集生效？]

### 调参方向（未来策略变体）

按代价从小到大：

1. **改 MA 窗口**：MA10 → MA12（Faber 论文有提变体）/ MA8（更激进）。注册新策略 `faber-gtaa-ma12` / `faber-gtaa-ma8` 即可，框架支持。
2. **混合 universe**：仅在大盘宽基 / 港股 子集应用 Faber，主题/行业仍用 baseline。需要 universe-aware 配置（新 spec）。
3. **加 stop-loss**：Faber 原版无止损。可加"持仓回撤超 N% 强制清仓"。
4. **下一周期：C Donchian 200（突破策略）+ A Dual Momentum（横截面动量）**——按之前规划进行。
```

- [ ] **Step 5: 把上面所有 `[填...]` 占位都替换为基于实际数据的具体数字和结论**（implementer 看着数据填）

- [ ] **Step 6: Commit 报告**

```bash
git add -f agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-vs-faber-gtaa.md
git commit -m "[backtest] T11: 产出 v9-baseline vs v9.3-bear vs faber-gtaa 三策略对比报告（含中文解读）"
```

---

## Task 12: 范围检查（生产隔离不变量）

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

Expected: `179 passed`（与 base SHA `1bb961c` 时一致）

- [ ] **Step 3: 跑 backtest 全套零退化**

```bash
pytest scripts/backtest/test_*.py --tb=short 2>&1 | tail -3
python -m scripts.backtest.test_signal_manual 2>&1 | tail -3
```

Expected: pytest 不少于 53 passed；test_signal_manual `All tests passed.`

- [ ] **Step 4: 本 task 不 commit。如任何步骤失败 → 排查违反的不变量 → 回滚相关 commit**

---

## Plan 完成后

待 12 个 task 全部 PASS 后，给用户**周期 1 完成报告**：

- 列出 commit 序列（约 10 个 [backtest] commits）
- 三策略对比报告：`/Users/loopq/dev/git/loopq/trend.github.io/agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-vs-faber-gtaa.md`
- 用户审完批准 → 进 C 周期（Donchian 200）

---

## Spec 覆盖度自查（writing-plans skill 要求）

| design.html § | 对应 Task |
|---|---|
| §0 隔离铁律 | Task 9（5 条断言验收） |
| §1 背景与目标 | Plan header（Goal / Architecture） |
| §2 Universe combined-27 | Task 1 |
| §3 aggregator 字段 + dispatch SVG | Task 2（字段）+ Task 4（dispatch） |
| §4 dispatch 代码 | Task 4 |
| §5 equal-weight 流程 | Task 5（_run_equal_weight）+ Task 6（portfolio aggregator） |
| §6.1 FaberMonthlyMaDecider | Task 7 |
| §6.2 注册 faber-gtaa | Task 7 Step 3 |
| §6.3 required_indicators 协议 + _ensure_indicators | Task 2（协议）+ Task 3（helper） |
| §6.4 测试 case 表 | Task 7 Step 1（7 个测试） |
| §7 报告 N 策略改造 | Task 8 |
| §8.1 隔离断言 5 条 | Task 9 |
| §8.2 新功能验收 4 条 | Task 7 Step 5 + Task 10 |
| §9 测试范围 | Task 9 Step 2 + Task 12 Step 3 |
| §10 报告内容 | Task 11 |
| §11 关键不变量 | Task 12 |
| §12 风险表 | 无对应 task（已在 design 文档化） |
| §13 不在范围 | 无对应 task（说明性） |

13 章节全部映射，无遗漏。

## Self-review

- [x] **Spec coverage**：13 章节全映射
- [x] **Placeholder 扫描**：无 TBD / TODO；所有代码片段完整
- [x] **类型一致性**：`aggregator` / `required_indicators` / `_run_equal_weight` / `run_portfolio_window_equal_weight` / `FaberMonthlyMaDecider` / `faber-gtaa` 跨 task 命名一致
- [x] **完整代码**：每个 task 含 implementer 直接执行的完整 Python 代码 + Bash 验收命令；无需跳读 design.html 拿代码（design.html 仅用于全局背景）
