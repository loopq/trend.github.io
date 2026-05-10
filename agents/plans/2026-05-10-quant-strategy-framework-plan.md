# Quant 策略框架 + 空头过滤回测 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `scripts/backtest/` 里把 D/W/M 硬编码三策略改造为「Decider + FilterChain」可注册的组件化框架，落地 `v9.3-bear` 策略（在 D/W BUY 上加月线 C > MA5 与空头过滤），跑出 `v9.3-bear` vs `v9-baseline` 的对比报告。生产 `scripts/quant/` 不修改。

**Architecture:** 在 backtest 内新增 `strategy/` 子包（protocol / registry / builtin）+ 共用 `indicators.py`（MA / 重采样 / splice / is_bear）+ 新统一 CLI `run.py` + 对比报告 `compare_report.py`。旧 `engine.run_strategy(data, BucketGroup)` 保留以维护 V5/V6/V8/V9 历史入口；新 `engine.run_with_strategy(data, Strategy)` 走新框架。**回归门槛**：`v9-baseline` 在新框架下跑出的组合 CAGR / Net CAGR / MaxDD 必须与历史 `agents/results/v9-manual-result.md` 差异 < 0.01 个百分点，否则禁止生成对比报告。

**Tech Stack:** Python 3, pandas, pytest（新增 test 走 pytest 风格；旧 `test_signal_manual.py` 不动）。

**Spec 来源:** `agents/plans/2026-05-10-quant-strategy-framework-design.md`（已批准）。

---

## File Structure

**Create**

| Path | Responsibility |
|---|---|
| `scripts/backtest/indicators.py` | `compute_ma` / `resample_weekly` / `resample_monthly` / `is_bear` 四个纯函数 |
| `scripts/backtest/strategy/__init__.py` | re-export `Strategy` / `Decider` / `Filter` / `FilterContext` / `register` / `get` / `list_all` |
| `scripts/backtest/strategy/protocol.py` | `Decider` Protocol、`Filter` Protocol、`Strategy` dataclass、`FilterContext` dataclass、`Signal` dataclass |
| `scripts/backtest/strategy/registry.py` | `_STRATEGIES` 全局表 + `register` / `get` / `list_all` |
| `scripts/backtest/strategy/builtin.py` | `MA20CrossDecider`、`BearTrendFilter`、`@register("v9-baseline")`、`@register("v9.3-bear")` |
| `scripts/backtest/run.py` | 统一 CLI（`--list` / `--strategy` / `--compare` / `--universe` / `--windows`） |
| `scripts/backtest/compare_report.py` | 三张表（组合层 / 分指数差异 / Filter 命中）的 Markdown 生成器 |
| `scripts/backtest/test_indicators.py` | indicators 五个函数的 pytest 测试 |
| `scripts/backtest/test_strategy_registry.py` | 注册表 pytest 测试 |
| `scripts/backtest/test_strategy_builtin.py` | `MA20CrossDecider`（9 个边界）+ `BearTrendFilter`（≥ 10 个组合）pytest 测试 |
| `scripts/backtest/test_strategy_engine.py` | `engine.run_with_strategy` 端到端 pytest 测试 |
| `scripts/backtest/test_compare_report.py` | 对比报告渲染 pytest 测试 |

**Modify**

| Path | Change |
|---|---|
| `scripts/backtest/strategies.py` | `Strategy` → `BucketGroup`（rename） |
| `scripts/backtest/engine.py` | 类型 hint 跟 rename 走；新增 `run_with_strategy(data, Strategy) -> BacktestResult` |
| `scripts/backtest/data_loader.py` | `_resample_ohlc` / `_attach_ma20` 内部改为调用 `indicators.py`（行为不变） |
| `scripts/backtest/run_backtest.py` | import 改 `BucketGroup`（rename 跟随） |
| `scripts/backtest/run_v5.py` | 同上 |
| `scripts/backtest/run_v6.py` | 同上 |
| `scripts/backtest/run_v6_friction.py` | 同上 |
| `scripts/backtest/run_v8.py` | 同上 |
| `scripts/backtest/run_v9.py` | 同上 |
| `scripts/backtest/run_v9_detail.py` | 同上 |
| `scripts/backtest/run_windows.py` | 同上 |
| `scripts/backtest/CLAUDE.md` | 加新框架使用方式 + 旧 `run_v*` 标"历史复现专用" |

**Forbidden**

不允许修改 `scripts/quant/` 下任何文件、不允许修改 `scripts/main.py`、不允许修改前端 `docs/` 下任何文件。

---

## Task 1: indicators 模块

**Files:**
- Create: `scripts/backtest/indicators.py`
- Create: `scripts/backtest/test_indicators.py`

**重要语义说明**：「当月 close = 当日 close」这个口径不通过单独的 `splice` 函数实现，而是在 Task 9 `_build_filter_context` 里用 `data.daily.loc[:today]` 重新 resample 出 monthly_until——重 resample 自动把当月的 partial K 线合成最后一根月线，其 close 即等于当日 close。这样不会有「拿上月 close 改写当月」的歧义。

- [ ] **Step 1: 写 4 个纯函数的失败测试**

写 `scripts/backtest/test_indicators.py`：

```python
"""indicators 模块测试。运行：pytest scripts/backtest/test_indicators.py -v"""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.backtest.indicators import (
    compute_ma,
    resample_weekly,
    resample_monthly,
    is_bear,
)


def _daily_df(start="2024-01-01", n=120, base=100.0):
    dates = pd.bdate_range(start=start, periods=n)
    closes = [base + i * 0.5 for i in range(n)]
    return pd.DataFrame({
        "date": dates,
        "open": closes,
        "high": [c + 1 for c in closes],
        "low":  [c - 1 for c in closes],
        "close": closes,
    })


# ---------- compute_ma ----------

def test_compute_ma_window_5():
    s = pd.Series([1, 2, 3, 4, 5, 6, 7], dtype=float)
    out = compute_ma(s, window=5)
    assert pd.isna(out.iloc[0])
    assert pd.isna(out.iloc[3])
    assert out.iloc[4] == pytest.approx(3.0)
    assert out.iloc[5] == pytest.approx(4.0)
    assert out.iloc[6] == pytest.approx(5.0)


def test_compute_ma_min_periods_equals_window():
    s = pd.Series([1, 2, 3, 4], dtype=float)
    out = compute_ma(s, window=5)
    assert out.isna().all()


# ---------- resample_weekly / resample_monthly ----------

def test_resample_weekly_close_is_friday_close():
    df = _daily_df()
    weekly = resample_weekly(df)
    assert "close" in weekly.columns
    assert weekly.index.is_monotonic_increasing
    # 周线 close 应等于该周内最后一个交易日的 close
    last_week_end = weekly.index[-1]
    expected = df[df["date"] <= last_week_end]["close"].iloc[-1]
    assert weekly["close"].iloc[-1] == pytest.approx(expected)


def test_resample_monthly_high_is_max_in_month():
    df = _daily_df()
    monthly = resample_monthly(df)
    first_month_end = monthly.index[0]
    in_month = df[df["date"] <= first_month_end]
    assert monthly["high"].iloc[0] == pytest.approx(in_month["high"].max())


# ---------- 重 resample 截至 today（验证「当月 close = 当日 close」语义） ----------

def test_resample_monthly_on_partial_month_takes_today_close():
    """截到月内某一天，重 resample 的最后一根月线 close = 那天的 close。"""
    df = _daily_df(start="2024-01-01", n=80)
    cutoff = df["date"].iloc[40]  # 第 40 个交易日（约 2024-02-末附近，月内）
    cutoff_close = df.loc[df["date"] == cutoff, "close"].iloc[0]
    daily_until = df[df["date"] <= cutoff]
    monthly_until = resample_monthly(daily_until)
    # 最后一根的 close = cutoff 当日的 close（因为它是该月内截到的最后一根日 K）
    assert monthly_until["close"].iloc[-1] == pytest.approx(cutoff_close)


# ---------- is_bear ----------

def test_is_bear_drop_exceeds_eps():
    s = pd.Series([100, 101, 102, 100, 99, 98, 97, 96], dtype=float)
    assert is_bear(s, N=4, eps=0.005) is True   # 100 → 96, drop 4%


def test_is_bear_flat_within_eps():
    s = pd.Series([100, 100, 100, 100, 100, 100], dtype=float)
    assert is_bear(s, N=4, eps=0.005) is False


def test_is_bear_uptrend_returns_false():
    s = pd.Series([100, 101, 102, 103, 104, 105], dtype=float)
    assert is_bear(s, N=4, eps=0.005) is False


def test_is_bear_drop_below_eps_not_bear():
    # 跌 0.3% < eps 0.5%
    s = pd.Series([100, 99.9, 99.85, 99.8, 99.7], dtype=float)
    assert is_bear(s, N=4, eps=0.005) is False


def test_is_bear_insufficient_data_returns_false():
    s = pd.Series([100, 99, 98], dtype=float)  # 长度 3 < N+1=5
    assert is_bear(s, N=4, eps=0.005) is False


def test_is_bear_skips_leading_nans():
    s = pd.Series([float("nan")] * 5 + [100, 99, 98, 97, 96], dtype=float)
    # 最近 5 个非空：100→99→98→97→96，N=4 → drop 4%
    assert is_bear(s, N=4, eps=0.005) is True
```

- [ ] **Step 2: 跑测试确认全部失败**

```bash
pytest scripts/backtest/test_indicators.py -v
```
Expected: ImportError (`No module named 'scripts.backtest.indicators'`).

- [ ] **Step 3: 实现 indicators.py**

写 `scripts/backtest/indicators.py`：

```python
"""共用指标计算：MA / 重采样 / is_bear。

设计参考：agents/plans/2026-05-10-quant-strategy-framework-design.md §3
"""
from __future__ import annotations

import pandas as pd


def compute_ma(series: pd.Series, *, window: int) -> pd.Series:
    """N 周期简单移动平均。前 N-1 行为 NaN（min_periods=window）。"""
    return series.rolling(window=window, min_periods=window).mean()


def _resample_ohlc(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    """按 PeriodIndex(freq) 分组重采样，bar_date = 组内最大交易日。

    与 data_loader._resample_ohlc 同口径（V2 设计）。

    注意：当 df 截到月内某一天时，最后一组（当月）的 bar_date 即为截止日，
    close 即为该日 close——这就是「当月 close = 当日 close」的语义来源，
    无需另写 splice 函数。
    """
    period = pd.PeriodIndex(df["date"], freq=freq)
    grouped = df.groupby(period)
    resampled = grouped.agg(
        bar_date=("date", "max"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
    )
    resampled = resampled.set_index("bar_date").sort_index()
    return resampled


def resample_weekly(daily_df: pd.DataFrame) -> pd.DataFrame:
    """周线重采样（W-FRI 锚点）。daily_df 需含 date / open / high / low / close。"""
    return _resample_ohlc(daily_df, "W-FRI")


def resample_monthly(daily_df: pd.DataFrame) -> pd.DataFrame:
    """月线重采样（M 锚点）。"""
    return _resample_ohlc(daily_df, "M")


def is_bear(ma_series: pd.Series, *, N: int, eps: float) -> bool:
    """N 周期斜率法：drop_rate = (ma[t-N] - ma[t]) / ma[t-N]，drop > eps 才是空头。

    数据不足（< N+1 个非空 MA 值）→ 返回 False（冷启动不误杀）。
    """
    valid = ma_series.dropna()
    if len(valid) < N + 1:
        return False
    ma_now = float(valid.iloc[-1])
    ma_then = float(valid.iloc[-N - 1])
    if ma_then == 0:
        return False
    drop_rate = (ma_then - ma_now) / ma_then
    return drop_rate > eps
```

- [ ] **Step 4: 跑测试确认全部通过**

```bash
pytest scripts/backtest/test_indicators.py -v
```
Expected: 11 passed（compute_ma 2 + resample_weekly 1 + resample_monthly 1 + resample_partial 1 + is_bear 6）.

- [ ] **Step 5: Commit**

```bash
git add scripts/backtest/indicators.py scripts/backtest/test_indicators.py
git commit -m "[backtest] 新增 indicators 模块（MA/重采样/is_bear）"
```

---

## Task 2: data_loader 切到 indicators

**Files:**
- Modify: `scripts/backtest/data_loader.py:37-59`

- [ ] **Step 1: 替换 _resample_ohlc 与 _attach_ma20 内部实现**

`data_loader.py` 内部 `_resample_ohlc` 和 `_attach_ma20` 删掉，改为转调 indicators。打开文件，把第 37-59 行（含 `_resample_ohlc` 和 `_attach_ma20` 两个函数定义）替换为：

```python
from scripts.backtest.indicators import (
    _resample_ohlc as _ohlc_resample,
    compute_ma,
)


def _resample_ohlc(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    return _ohlc_resample(df, freq)


def _attach_ma20(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ma20"] = compute_ma(df["close"], window=20)
    return df
```

保留 thin wrapper 是为了不影响 `data_loader.py` 内 `_resample_ohlc(daily, "W-FRI")` 等已有调用点。

- [ ] **Step 2: 跑现有 backtest 老入口确认行为不变**

```bash
python -m scripts.backtest.test_signal_manual
```
Expected: `All tests passed.`（state machine 不依赖 MA 实现细节，但确认 import 链没坏）

```bash
pytest scripts/backtest/test_indicators.py -v
```
Expected: 11 passed.

- [ ] **Step 3: 数值一致性 smoke test（手工，可选）**

如有时间：跑一遍 `python -m scripts.backtest.run_v9` 并人工对比 `agents/results/v9-manual-result.md` 与历史 git 版本（`git diff HEAD~1 -- agents/results/v9-manual-result.md`）；如无差异即通过。如担心耗时，跳过这步交给 Task 12 的回归门槛验证。

- [ ] **Step 4: Commit**

```bash
git add scripts/backtest/data_loader.py
git commit -m "[backtest] data_loader 内部 MA/重采样切到 indicators（行为不变）"
```

---

## Task 3: rename Strategy → BucketGroup

**目的**：让出 `Strategy` 这个类名给新框架。旧 `Strategy(name, buckets=[Bucket])` 实际是 bucket 容器，叫 `BucketGroup` 更准确。

**Files:**
- Modify: `scripts/backtest/strategies.py`
- Modify: `scripts/backtest/engine.py`
- Modify: `scripts/backtest/window_engine.py`（**反思补登记**：原清单只列 `run_*.py`，但 `window_engine.py` 也 import 并实例化 `Strategy`，需一并更新）
- Modify: `scripts/backtest/run_backtest.py`
- Modify: `scripts/backtest/run_v5.py`
- Modify: `scripts/backtest/run_v6.py`
- Modify: `scripts/backtest/run_v6_friction.py`
- Modify: `scripts/backtest/run_v8.py`
- Modify: `scripts/backtest/run_v9.py`
- Modify: `scripts/backtest/run_v9_detail.py`
- Modify: `scripts/backtest/run_windows.py`

- [ ] **Step 1: strategies.py 改类名**

打开 `scripts/backtest/strategies.py`，将第 48-52 行：

```python
@dataclass
class Strategy:
    name: str
    buckets: List[Bucket]
```

替换为：

```python
@dataclass
class BucketGroup:
    name: str
    buckets: List[Bucket]


# 兼容 alias：旧名字保留指向新类，避免直接引用旧 Strategy 的代码立刻坏
Strategy = BucketGroup
```

并把 `d_strategy / w_strategy / m_strategy` 三个 factory 的返回类型 hint 从 `Strategy` 改为 `BucketGroup`：

```python
def d_strategy() -> BucketGroup:
    return BucketGroup(name="D", buckets=[Bucket(timeframe=DAILY, capital=BUCKET_CAPITAL)])

def w_strategy() -> BucketGroup:
    return BucketGroup(name="W", buckets=[Bucket(timeframe=WEEKLY, capital=BUCKET_CAPITAL)])

def m_strategy() -> BucketGroup:
    return BucketGroup(name="M", buckets=[Bucket(timeframe=MONTHLY, capital=BUCKET_CAPITAL)])

def all_strategies() -> List[BucketGroup]:
    return [d_strategy(), w_strategy(), m_strategy()]
```

- [ ] **Step 2: engine.py 改 import + 类型 hint**

打开 `scripts/backtest/engine.py`，第 15 行：

```python
from scripts.backtest.strategies import DAILY, MONTHLY, WEEKLY, Bucket, BUCKET_CAPITAL, Strategy
```

改为：

```python
from scripts.backtest.strategies import DAILY, MONTHLY, WEEKLY, Bucket, BUCKET_CAPITAL, BucketGroup
```

第 217 行函数签名：

```python
def run_strategy(data: IndexData, strategy: Strategy,
```

改为：

```python
def run_strategy(data: IndexData, strategy: BucketGroup,
```

- [ ] **Step 3: 各 run_*.py 改 import**

对以下 8 个文件，找到 `from scripts.backtest.strategies import ... Strategy ...` 这一行（其中 `Strategy` 与其它符号同行），将 `Strategy` 替换为 `BucketGroup`。如果文件没有 import `Strategy`，跳过。

对每个文件用 grep 确认是否需改：

```bash
grep -n "from scripts.backtest.strategies import" scripts/backtest/run_*.py
```

对所有命中含 `Strategy` 的行，把 `Strategy` 改为 `BucketGroup`。例如 `run_v6_friction.py:29`：

```python
from scripts.backtest.strategies import DAILY, MONTHLY, WEEKLY, Bucket, Strategy, all_strategies
```

改为：

```python
from scripts.backtest.strategies import DAILY, MONTHLY, WEEKLY, Bucket, BucketGroup, all_strategies
```

- [ ] **Step 4: 跑老入口烟测**

```bash
python -m scripts.backtest.test_signal_manual
```
Expected: `All tests passed.`

```bash
python -c "from scripts.backtest.engine import run_strategy; from scripts.backtest.strategies import all_strategies, BucketGroup; print('ok')"
```
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add scripts/backtest/strategies.py scripts/backtest/engine.py scripts/backtest/run_*.py
git commit -m "[backtest] Strategy 类重命名为 BucketGroup（让出 Strategy 给新框架；保留 alias 兼容）"
```

---

## Task 4: 策略协议层

**Files:**
- Create: `scripts/backtest/strategy/__init__.py`
- Create: `scripts/backtest/strategy/protocol.py`

- [ ] **Step 1: 写 protocol.py**

```python
"""策略框架协议。Decider 决定原始信号；Filter 过滤准入；Strategy 是组合配置。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, Tuple, runtime_checkable

import pandas as pd


@dataclass(frozen=True)
class Signal:
    """Decider 输出的原始信号（未过滤）。"""
    action: str       # "BUY" | "SELL"
    cycle: str        # "D" | "W" | "M"
    price: float      # 触发当根 K 线的 close
    bar_date: pd.Timestamp


@dataclass
class FilterContext:
    """Filter 决策时需要的上下文。engine 在每个回测点构建。"""
    today: pd.Timestamp
    today_close: float                    # 当日日 K close
    month_close_spliced: float            # 当日 close 拼到月线末尾后的「当月 close」
    month_ma5: Optional[float]            # 月线 5MA 在当月的最新值（可能 NaN）
    weekly_ma60_series: pd.Series         # 周线序列上的 MA60（截至 today）
    monthly_ma20_series: pd.Series        # 月线序列上的 MA20（截至 today）


@runtime_checkable
class Decider(Protocol):
    name: str
    def decide(self, *, cycle: str, bar: pd.Series, position_shares: float) -> Optional[Signal]:
        """根据当根 K 线和当前持仓决定 BUY / SELL / 无动作。

        bar: pd.Series，至少含 high / low / close / ma20。
        position_shares: 当前 bucket 的持仓量（>0 视为持仓，==0 视为空仓）。
        """
        ...


@runtime_checkable
class Filter(Protocol):
    name: str
    def allow(self, signal: Signal, ctx: FilterContext) -> bool:
        """True = 信号放行；False = suppress。"""
        ...


@dataclass(frozen=True)
class Strategy:
    """组件化策略 = Decider + 一组 Filter。

    cycles 控制本策略在哪些周期上跑。filter 可由 cycle 自身在 allow 内做判断。
    """
    name: str
    decider: Decider
    filters: Tuple[Filter, ...] = field(default_factory=tuple)
    cycles: Tuple[str, ...] = ("D", "W", "M")
```

- [ ] **Step 2: 写 __init__.py（暂只 re-export）**

```python
"""组件化策略框架。

用法：
    from scripts.backtest.strategy import Strategy, get
    strat = get("v9-baseline")
"""
from scripts.backtest.strategy.protocol import (
    Decider,
    Filter,
    FilterContext,
    Signal,
    Strategy,
)

__all__ = ["Decider", "Filter", "FilterContext", "Signal", "Strategy"]
```

- [ ] **Step 3: 烟测 import**

```bash
python -c "from scripts.backtest.strategy import Strategy, Decider, Filter, FilterContext, Signal; print('ok')"
```
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add scripts/backtest/strategy/__init__.py scripts/backtest/strategy/protocol.py
git commit -m "[backtest] 新增 strategy/protocol（Decider/Filter/Strategy/FilterContext）"
```

---

## Task 5: 注册表

**Files:**
- Create: `scripts/backtest/strategy/registry.py`
- Create: `scripts/backtest/test_strategy_registry.py`
- Modify: `scripts/backtest/strategy/__init__.py`

- [ ] **Step 1: 写注册表测试**

```python
"""注册表测试。运行：pytest scripts/backtest/test_strategy_registry.py -v"""
from __future__ import annotations

import pytest

from scripts.backtest.strategy import Strategy
from scripts.backtest.strategy.registry import register, get, list_all, _reset_for_test


class _DummyDecider:
    name = "dummy"
    def decide(self, *, cycle, bar, position_shares):
        return None


@pytest.fixture(autouse=True)
def _clean_registry():
    _reset_for_test()
    yield
    _reset_for_test()


def test_register_and_get():
    @register("foo")
    def _f():
        return Strategy(name="foo", decider=_DummyDecider())
    s = get("foo")
    assert s.name == "foo"


def test_register_duplicate_raises():
    @register("dup")
    def _f1():
        return Strategy(name="dup", decider=_DummyDecider())
    with pytest.raises(ValueError, match="dup"):
        @register("dup")
        def _f2():
            return Strategy(name="dup", decider=_DummyDecider())


def test_get_unknown_raises():
    with pytest.raises(KeyError, match="unknown"):
        get("unknown")


def test_list_all_returns_sorted_names():
    @register("b")
    def _b():
        return Strategy(name="b", decider=_DummyDecider())
    @register("a")
    def _a():
        return Strategy(name="a", decider=_DummyDecider())
    assert list_all() == ["a", "b"]
```

- [ ] **Step 2: 跑测试确认失败**

```bash
pytest scripts/backtest/test_strategy_registry.py -v
```
Expected: ImportError on `scripts.backtest.strategy.registry`.

- [ ] **Step 3: 实现 registry.py**

```python
"""策略注册表。@register 装饰器 + get / list_all。"""
from __future__ import annotations

from typing import Callable, Dict, List

from scripts.backtest.strategy.protocol import Strategy

_FACTORIES: Dict[str, Callable[[], Strategy]] = {}


def register(name: str) -> Callable[[Callable[[], Strategy]], Callable[[], Strategy]]:
    def deco(factory: Callable[[], Strategy]) -> Callable[[], Strategy]:
        if name in _FACTORIES:
            raise ValueError(f"strategy {name!r} already registered")
        _FACTORIES[name] = factory
        return factory
    return deco


def get(name: str) -> Strategy:
    if name not in _FACTORIES:
        raise KeyError(f"unknown strategy: {name!r} (known: {sorted(_FACTORIES)})")
    return _FACTORIES[name]()


def list_all() -> List[str]:
    return sorted(_FACTORIES)


def _reset_for_test() -> None:
    """仅供测试夹具用。"""
    _FACTORIES.clear()
```

- [ ] **Step 4: 在 __init__.py 加 re-export**

打开 `scripts/backtest/strategy/__init__.py`，把内容替换为：

```python
"""组件化策略框架。

用法：
    from scripts.backtest.strategy import Strategy, get
    strat = get("v9-baseline")
"""
from scripts.backtest.strategy.protocol import (
    Decider,
    Filter,
    FilterContext,
    Signal,
    Strategy,
)
from scripts.backtest.strategy.registry import (
    register,
    get,
    list_all,
)

__all__ = [
    "Decider", "Filter", "FilterContext", "Signal", "Strategy",
    "register", "get", "list_all",
]
```

- [ ] **Step 5: 跑测试确认通过**

```bash
pytest scripts/backtest/test_strategy_registry.py -v
```
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add scripts/backtest/strategy/registry.py scripts/backtest/strategy/__init__.py scripts/backtest/test_strategy_registry.py
git commit -m "[backtest] 新增 strategy/registry（register/get/list_all + 单测）"
```

---

## Task 6: MA20CrossDecider

**Files:**
- Create: `scripts/backtest/strategy/builtin.py`
- Create: `scripts/backtest/test_strategy_builtin.py`

- [ ] **Step 1: 先写 Decider 部分的失败测试**

```python
"""builtin Decider / Filter 测试。运行：pytest scripts/backtest/test_strategy_builtin.py -v"""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.backtest.strategy.builtin import MA20CrossDecider


def _bar(high, low, ma20, close=None):
    return pd.Series({
        "high": high, "low": low, "ma20": ma20,
        "close": close if close is not None else (high + low) / 2,
        "open": (high + low) / 2,
    })


# ---------- MA20CrossDecider ----------

class TestMA20CrossDecider:
    def setup_method(self):
        self.d = MA20CrossDecider()

    def test_first_clean_up_no_position_returns_buy(self):
        # 干净-上 + 空仓 → BUY（首次翻转）
        sig = self.d.decide(cycle="D", bar=_bar(105, 101, 100, close=104), position_shares=0)
        assert sig is not None
        assert sig.action == "BUY"
        assert sig.cycle == "D"
        assert sig.price == pytest.approx(104)

    def test_first_clean_down_no_position_no_signal(self):
        # 干净-下 + 空仓 → 不交易（只做多）
        sig = self.d.decide(cycle="D", bar=_bar(99, 95, 100), position_shares=0)
        assert sig is None

    def test_clean_up_with_position_no_resignal(self):
        # 持仓中 + 同方向 UP → 无信号
        d = MA20CrossDecider()
        d.decide(cycle="D", bar=_bar(105, 101, 100), position_shares=0)  # 先 BUY
        sig = d.decide(cycle="D", bar=_bar(106, 102, 100), position_shares=1.0)
        assert sig is None

    def test_clean_down_with_position_returns_sell(self):
        d = MA20CrossDecider()
        d.decide(cycle="D", bar=_bar(105, 101, 100), position_shares=0)  # 先 BUY
        sig = d.decide(cycle="D", bar=_bar(99, 95, 100, close=96), position_shares=1.0)
        assert sig is not None
        assert sig.action == "SELL"
        assert sig.price == pytest.approx(96)

    def test_touch_does_not_change_state(self):
        d = MA20CrossDecider()
        d.decide(cycle="D", bar=_bar(105, 101, 100), position_shares=0)  # BUY → state=UP
        # 触碰：low<=ma<=high
        sig = d.decide(cycle="D", bar=_bar(103, 99, 100), position_shares=1.0)
        assert sig is None
        # 触碰后再来一根 UP → 同方向不再 BUY
        sig2 = d.decide(cycle="D", bar=_bar(108, 102, 100), position_shares=1.0)
        assert sig2 is None

    def test_ma20_nan_returns_none(self):
        sig = self.d.decide(cycle="D", bar=_bar(105, 101, float("nan")), position_shares=0)
        assert sig is None

    def test_separate_state_per_cycle(self):
        """D / W / M 状态机互不干扰。"""
        d = MA20CrossDecider()
        d.decide(cycle="D", bar=_bar(105, 101, 100), position_shares=0)
        # W 第一次见 UP，应给 BUY
        sig = d.decide(cycle="W", bar=_bar(105, 101, 100, close=104), position_shares=0)
        assert sig is not None and sig.action == "BUY" and sig.cycle == "W"

    def test_boundary_low_equals_ma20_is_touch(self):
        sig = self.d.decide(cycle="D", bar=_bar(105, 100, 100), position_shares=0)
        assert sig is None  # low==ma20 算触碰

    def test_boundary_high_equals_ma20_is_touch(self):
        sig = self.d.decide(cycle="D", bar=_bar(100, 95, 100), position_shares=0)
        assert sig is None  # high==ma20 算触碰
```

- [ ] **Step 2: 跑测试确认失败**

```bash
pytest scripts/backtest/test_strategy_builtin.py::TestMA20CrossDecider -v
```
Expected: ImportError on `scripts.backtest.strategy.builtin`.

- [ ] **Step 3: 实现 MA20CrossDecider（在 builtin.py）**

```python
"""内置 Decider / Filter，并注册标准策略。"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import pandas as pd

from scripts.backtest.indicators import is_bear
from scripts.backtest.strategy.protocol import (
    Decider,
    Filter,
    FilterContext,
    Signal,
    Strategy,
)
from scripts.backtest.strategy.registry import register


_UP = "UP"
_DOWN = "DOWN"


class MA20CrossDecider:
    """干净 K 线方向状态机：low > ma20 = UP；high < ma20 = DOWN；else 触碰。

    UP 翻转 + 空仓 → BUY；DOWN 翻转 + 持仓 → SELL。
    每个 cycle 维护独立状态。
    """

    name = "ma20-cross"

    def __init__(self) -> None:
        self._state_by_cycle: Dict[str, Optional[str]] = {}

    def _classify(self, high: float, low: float, ma20: float) -> Optional[str]:
        if pd.isna(ma20):
            return None
        if low > ma20:
            return _UP
        if high < ma20:
            return _DOWN
        return None

    def decide(self, *, cycle: str, bar: pd.Series, position_shares: float) -> Optional[Signal]:
        ma20 = bar.get("ma20")
        if pd.isna(ma20):
            return None
        new_dir = self._classify(bar["high"], bar["low"], ma20)
        if new_dir is None:
            return None  # 触碰
        prev = self._state_by_cycle.get(cycle)
        if new_dir == prev:
            return None  # 同方向不重复触发
        self._state_by_cycle[cycle] = new_dir
        if new_dir == _UP and position_shares == 0:
            return Signal(action="BUY", cycle=cycle, price=float(bar["close"]),
                          bar_date=pd.Timestamp(bar.name) if bar.name is not None else pd.NaT)
        if new_dir == _DOWN and position_shares > 0:
            return Signal(action="SELL", cycle=cycle, price=float(bar["close"]),
                          bar_date=pd.Timestamp(bar.name) if bar.name is not None else pd.NaT)
        return None
```

- [ ] **Step 4: 跑测试确认 MA20CrossDecider 部分通过**

```bash
pytest scripts/backtest/test_strategy_builtin.py::TestMA20CrossDecider -v
```
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/backtest/strategy/builtin.py scripts/backtest/test_strategy_builtin.py
git commit -m "[backtest] 实现 MA20CrossDecider（与现有 signal.classify_bar 等价）"
```

---

## Task 7: BearTrendFilter

**Files:**
- Modify: `scripts/backtest/strategy/builtin.py`
- Modify: `scripts/backtest/test_strategy_builtin.py`

- [ ] **Step 1: 追加 BearTrendFilter 失败测试**

在 `test_strategy_builtin.py` 末尾追加：

```python
# ---------- BearTrendFilter ----------

from scripts.backtest.strategy.builtin import BearTrendFilter
from scripts.backtest.strategy.protocol import Signal, FilterContext


def _ctx(*, today_close, month_ma5, weekly_ma60_series, monthly_ma20_series):
    """构造 FilterContext，month_close_spliced = today_close。"""
    return FilterContext(
        today=pd.Timestamp("2024-06-15"),
        today_close=today_close,
        month_close_spliced=today_close,
        month_ma5=month_ma5,
        weekly_ma60_series=weekly_ma60_series,
        monthly_ma20_series=monthly_ma20_series,
    )


def _flat_series(value: float, length: int = 12) -> pd.Series:
    return pd.Series([value] * length, dtype=float)


def _falling_series(start: float, drop_pct: float, length: int = 12) -> pd.Series:
    """从 start 线性下跌 drop_pct（最终值 = start * (1 - drop_pct)）。"""
    end = start * (1 - drop_pct)
    return pd.Series([start + (end - start) * i / (length - 1) for i in range(length)], dtype=float)


def _buy(cycle: str = "D") -> Signal:
    return Signal(action="BUY", cycle=cycle, price=100.0, bar_date=pd.Timestamp("2024-06-15"))


def _sell(cycle: str = "D") -> Signal:
    return Signal(action="SELL", cycle=cycle, price=100.0, bar_date=pd.Timestamp("2024-06-15"))


class TestBearTrendFilter:
    def setup_method(self):
        self.f = BearTrendFilter()  # default scope=("D","W"), N=4/3, eps=0.005

    # SELL 始终放行
    def test_sell_d_always_allowed(self):
        ctx = _ctx(today_close=80, month_ma5=100,
                   weekly_ma60_series=_falling_series(100, 0.10),
                   monthly_ma20_series=_falling_series(100, 0.10))
        assert self.f.allow(_sell("D"), ctx) is True

    def test_sell_w_always_allowed(self):
        ctx = _ctx(today_close=80, month_ma5=100,
                   weekly_ma60_series=_falling_series(100, 0.10),
                   monthly_ma20_series=_falling_series(100, 0.10))
        assert self.f.allow(_sell("W"), ctx) is True

    # M cycle BUY 始终放行（不在 scope 里）
    def test_m_buy_always_allowed(self):
        ctx = _ctx(today_close=80, month_ma5=100,
                   weekly_ma60_series=_falling_series(100, 0.10),
                   monthly_ma20_series=_falling_series(100, 0.10))
        assert self.f.allow(_buy("M"), ctx) is True

    # ---- D/W BUY × {month_close vs ma5} × {weekly_bear, monthly_bear} ----

    def test_d_buy_close_above_ma5_both_non_bear_pass(self):
        ctx = _ctx(today_close=110, month_ma5=100,
                   weekly_ma60_series=_flat_series(100),
                   monthly_ma20_series=_flat_series(100))
        assert self.f.allow(_buy("D"), ctx) is True

    def test_w_buy_close_above_ma5_both_non_bear_pass(self):
        ctx = _ctx(today_close=110, month_ma5=100,
                   weekly_ma60_series=_flat_series(100),
                   monthly_ma20_series=_flat_series(100))
        assert self.f.allow(_buy("W"), ctx) is True

    def test_d_buy_close_below_ma5_blocked(self):
        ctx = _ctx(today_close=99, month_ma5=100,
                   weekly_ma60_series=_flat_series(100),
                   monthly_ma20_series=_flat_series(100))
        assert self.f.allow(_buy("D"), ctx) is False

    def test_d_buy_close_equals_ma5_blocked(self):
        # 严格 > ：等号视为不满足
        ctx = _ctx(today_close=100, month_ma5=100,
                   weekly_ma60_series=_flat_series(100),
                   monthly_ma20_series=_flat_series(100))
        assert self.f.allow(_buy("D"), ctx) is False

    def test_d_buy_close_above_ma5_weekly_bear_only_still_pass(self):
        # 周线空头但月线非空头 → cond_trend = (not True) or (not False) = True
        ctx = _ctx(today_close=110, month_ma5=100,
                   weekly_ma60_series=_falling_series(100, 0.10),
                   monthly_ma20_series=_flat_series(100))
        assert self.f.allow(_buy("D"), ctx) is True

    def test_d_buy_close_above_ma5_monthly_bear_only_still_pass(self):
        ctx = _ctx(today_close=110, month_ma5=100,
                   weekly_ma60_series=_flat_series(100),
                   monthly_ma20_series=_falling_series(100, 0.10))
        assert self.f.allow(_buy("D"), ctx) is True

    def test_d_buy_close_above_ma5_both_bear_blocked(self):
        ctx = _ctx(today_close=110, month_ma5=100,
                   weekly_ma60_series=_falling_series(100, 0.10),
                   monthly_ma20_series=_falling_series(100, 0.10))
        assert self.f.allow(_buy("D"), ctx) is False

    def test_month_ma5_nan_blocks_buy(self):
        # MA5 未就绪 → 月线 C > MA5 无法判定 → 严格 suppress
        ctx = _ctx(today_close=110, month_ma5=float("nan"),
                   weekly_ma60_series=_flat_series(100),
                   monthly_ma20_series=_flat_series(100))
        assert self.f.allow(_buy("D"), ctx) is False

    def test_custom_scope_only_d(self):
        f = BearTrendFilter(scope=("D",))
        ctx = _ctx(today_close=99, month_ma5=100,
                   weekly_ma60_series=_flat_series(100),
                   monthly_ma20_series=_flat_series(100))
        # W 不在 scope，不该 block
        assert f.allow(_buy("W"), ctx) is True
        assert f.allow(_buy("D"), ctx) is False
```

- [ ] **Step 2: 跑测试确认失败**

```bash
pytest scripts/backtest/test_strategy_builtin.py::TestBearTrendFilter -v
```
Expected: ImportError on `BearTrendFilter`.

- [ ] **Step 3: 在 builtin.py 追加 BearTrendFilter**

在 `scripts/backtest/strategy/builtin.py` 末尾（在 `MA20CrossDecider` 之后）追加：

```python
class BearTrendFilter:
    """空头趋势过滤器：

    仅作用于 scope 内 cycle 的 BUY 信号。条件：
        month_close_spliced > month_ma5
        AND ((not weekly_bear) OR (not monthly_bear))

    SELL / scope 外的 cycle / 任意 M cycle BUY 始终放行。
    """

    name = "bear-trend-filter"

    def __init__(
        self,
        scope: Tuple[str, ...] = ("D", "W"),
        weekly_bear_N: int = 4,
        weekly_bear_eps: float = 0.005,
        monthly_bear_N: int = 3,
        monthly_bear_eps: float = 0.005,
    ) -> None:
        self.scope = tuple(scope)
        self.weekly_bear_N = weekly_bear_N
        self.weekly_bear_eps = weekly_bear_eps
        self.monthly_bear_N = monthly_bear_N
        self.monthly_bear_eps = monthly_bear_eps

    def allow(self, signal: Signal, ctx: FilterContext) -> bool:
        if signal.action != "BUY":
            return True
        if signal.cycle not in self.scope:
            return True
        if ctx.month_ma5 is None or pd.isna(ctx.month_ma5):
            return False  # MA5 未就绪 → 严格 suppress
        cond_close = ctx.month_close_spliced > ctx.month_ma5
        weekly_bear = is_bear(ctx.weekly_ma60_series,
                              N=self.weekly_bear_N, eps=self.weekly_bear_eps)
        monthly_bear = is_bear(ctx.monthly_ma20_series,
                               N=self.monthly_bear_N, eps=self.monthly_bear_eps)
        cond_trend = (not weekly_bear) or (not monthly_bear)
        return cond_close and cond_trend
```

- [ ] **Step 4: 跑测试确认通过**

```bash
pytest scripts/backtest/test_strategy_builtin.py -v
```
Expected: 9（Decider）+ 12（Filter）= 21 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/backtest/strategy/builtin.py scripts/backtest/test_strategy_builtin.py
git commit -m "[backtest] 实现 BearTrendFilter（D/W BUY 加月线C>MA5 + 双空头过滤）"
```

---

## Task 8: 注册内置策略

**Files:**
- Modify: `scripts/backtest/strategy/builtin.py`
- Modify: `scripts/backtest/test_strategy_builtin.py`

- [ ] **Step 1: 写策略注册测试**

> **修订记录**：原 plan 草稿用 `importlib.import_module`，但因 `import_module` 对已 cache 的模块是 no-op，一旦 `test_strategy_registry.py` 的 autouse fixture 清空 `_FACTORIES`，本测试就会读到空注册表。改为 `_reset_for_test() + importlib.reload`，主动重跑顶层 `@register`。

在 `test_strategy_builtin.py` 末尾追加：

```python
# ---------- 内置策略注册 ----------

def _reload_builtin():
    """强制重新执行 builtin 模块顶层 @register，避免 registry fixture
    清空 _FACTORIES 之后下次 import 拿到空的注册表。"""
    from scripts.backtest.strategy.registry import _reset_for_test
    import importlib
    import scripts.backtest.strategy.builtin as _b
    _reset_for_test()
    importlib.reload(_b)


def test_v9_baseline_registered():
    _reload_builtin()
    from scripts.backtest.strategy import get
    s = get("v9-baseline")
    assert s.name == "v9-baseline"
    assert s.filters == ()
    assert s.cycles == ("D", "W", "M")


def test_v9_3_bear_registered():
    _reload_builtin()
    from scripts.backtest.strategy import get
    s = get("v9.3-bear")
    assert s.name == "v9.3-bear"
    assert len(s.filters) == 1
    assert s.filters[0].name == "bear-trend-filter"
    assert s.cycles == ("D", "W", "M")
```

- [ ] **Step 2: 跑测试确认失败**

```bash
pytest scripts/backtest/test_strategy_builtin.py -v -k "registered"
```
Expected: KeyError on `unknown strategy: 'v9-baseline'`.

- [ ] **Step 3: 在 builtin.py 末尾追加注册**

```python
@register("v9-baseline")
def _v9_baseline() -> Strategy:
    return Strategy(
        name="v9-baseline",
        decider=MA20CrossDecider(),
        filters=(),
    )


@register("v9.3-bear")
def _v9_3_bear() -> Strategy:
    return Strategy(
        name="v9.3-bear",
        decider=MA20CrossDecider(),
        filters=(BearTrendFilter(scope=("D", "W")),),
    )
```

- [ ] **Step 4: 跑测试确认通过**

```bash
pytest scripts/backtest/test_strategy_builtin.py -v
```
Expected: 23 passed（21 旧 + 2 新）。

注意：`_reload_builtin()` 已主动消除测试顺序耦合——无论 registry 测试在前还是在后，每个 builtin 注册测试都从 `_reset_for_test()` 干净状态开始 + reload 重建注册。验证：`pytest test_strategy_builtin.py test_strategy_registry.py -v` 与 `pytest test_strategy_registry.py test_strategy_builtin.py -v` 都应通过。

- [ ] **Step 5: Commit**

```bash
git add scripts/backtest/strategy/builtin.py scripts/backtest/test_strategy_builtin.py
git commit -m "[backtest] 注册 v9-baseline / v9.3-bear 策略"
```

---

## Task 9: engine.run_with_strategy

**Files:**
- Modify: `scripts/backtest/engine.py`
- Create: `scripts/backtest/test_strategy_engine.py`

- [ ] **Step 1: 写端到端集成测试**

```python
"""engine.run_with_strategy 集成测试。运行：pytest scripts/backtest/test_strategy_engine.py -v"""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.backtest.data_loader import IndexData
from scripts.backtest.engine import run_with_strategy
from scripts.backtest.indicators import compute_ma, resample_weekly, resample_monthly
from scripts.backtest.strategy import get
import scripts.backtest.strategy.builtin  # noqa: F401  触发注册


def _make_index_data(daily_close_series: pd.Series, code="TEST", name="测试") -> IndexData:
    df = pd.DataFrame({
        "date": daily_close_series.index,
        "open": daily_close_series.values,
        "high": daily_close_series.values + 1,
        "low": daily_close_series.values - 1,
        "close": daily_close_series.values,
    })
    weekly = resample_weekly(df)
    monthly = resample_monthly(df)
    daily = df.set_index("date")
    daily["ma20"] = compute_ma(daily["close"], window=20)
    weekly["ma20"] = compute_ma(weekly["close"], window=20)
    monthly["ma20"] = compute_ma(monthly["close"], window=20)
    return IndexData(code=code, name=name, source="test",
                     daily=daily, weekly=weekly, monthly=monthly)


def _trending_up(n=400):
    """构造 N 个交易日的稳步上升收盘价序列。"""
    dates = pd.bdate_range("2020-01-01", periods=n)
    closes = pd.Series([100 + i * 0.5 for i in range(n)], index=dates)
    return closes


def test_run_with_strategy_v9_baseline_buys_in_uptrend():
    data = _make_index_data(_trending_up())
    strat = get("v9-baseline")
    result = run_with_strategy(data, strat)
    assert result.trade_count >= 0
    # 上升趋势下，至少触发一次 BUY
    buys = [t for t in result.trades if t.action == "BUY"]
    assert len(buys) >= 1


def test_run_with_strategy_v9_3_bear_filters_out_buys_in_falling_then_recovery():
    """构造『先稳定下跌、再翻转上升』的序列，v9.3-bear 在反转初期应过滤掉 BUY。"""
    dates = pd.bdate_range("2020-01-01", periods=400)
    drop = [100 - i * 0.3 for i in range(200)]
    rise_start = drop[-1]
    rise = [rise_start + i * 0.4 for i in range(200)]
    closes = pd.Series(drop + rise, index=dates)
    data = _make_index_data(closes)

    baseline = run_with_strategy(data, get("v9-baseline"))
    bear = run_with_strategy(data, get("v9.3-bear"))

    baseline_buys = sum(1 for t in baseline.trades if t.action == "BUY")
    bear_buys = sum(1 for t in bear.trades if t.action == "BUY")

    assert bear_buys < baseline_buys, (
        f"BearTrendFilter 应过滤掉至少 1 个 BUY，"
        f"但 baseline={baseline_buys} bear={bear_buys}"
    )


def test_run_with_strategy_respects_cycles_subset():
    """只跑 D 周期时，结果不应有 W/M trade。"""
    from scripts.backtest.strategy import Strategy
    from scripts.backtest.strategy.builtin import MA20CrossDecider

    data = _make_index_data(_trending_up())
    strat_d_only = Strategy(name="d-only", decider=MA20CrossDecider(),
                            filters=(), cycles=("D",))
    result = run_with_strategy(data, strat_d_only)
    assert all(t.timeframe == "daily" for t in result.trades)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
pytest scripts/backtest/test_strategy_engine.py -v
```
Expected: ImportError on `run_with_strategy`.

- [ ] **Step 3: 在 engine.py 实现 run_with_strategy**

打开 `scripts/backtest/engine.py`，在文件末尾追加：

```python
# === 新框架入口（V10 组件化策略） =========================================

from scripts.backtest.indicators import compute_ma, resample_weekly, resample_monthly
from scripts.backtest.strategy.protocol import (
    FilterContext,
    Signal as _StrategySignal,
    Strategy as _ComposedStrategy,
)


_TF_TO_CYCLE = {DAILY: "D", WEEKLY: "W", MONTHLY: "M"}
_CYCLE_TO_TF = {v: k for k, v in _TF_TO_CYCLE.items()}


def _build_filter_context(
    *, today: pd.Timestamp, daily: pd.DataFrame,
) -> FilterContext:
    """从 daily 截到 today 后重新 resample 出 weekly_until / monthly_until。

    这个方式自动保证「当月 close = today 的日 K close」语义，无未来数据泄漏。
    每个回测日重 resample 一次（pandas resample 是 O(n)，14 指数 × ~1万 K 线
    总开销可接受；先正确，再优化）。
    """
    today_close = float(daily.loc[today, "close"])
    daily_until = daily.loc[:today].reset_index().rename(columns={daily.index.name or "index": "date"})
    if "date" not in daily_until.columns:
        # daily 的 index 名可能是 None，确保有 date 列
        daily_until = daily.loc[:today].copy()
        daily_until["date"] = daily_until.index
        daily_until = daily_until.reset_index(drop=True)

    weekly_until = resample_weekly(daily_until)
    monthly_until = resample_monthly(daily_until)

    month_ma5_series = compute_ma(monthly_until["close"], window=5)
    month_ma5 = float(month_ma5_series.iloc[-1]) if len(month_ma5_series.dropna()) > 0 else float("nan")
    weekly_ma60_series = compute_ma(weekly_until["close"], window=60)
    monthly_ma20_series = compute_ma(monthly_until["close"], window=20)

    return FilterContext(
        today=today,
        today_close=today_close,
        month_close_spliced=float(monthly_until["close"].iloc[-1]) if len(monthly_until) else today_close,
        month_ma5=month_ma5,
        weekly_ma60_series=weekly_ma60_series,
        monthly_ma20_series=monthly_ma20_series,
    )


def run_with_strategy(
    data: IndexData,
    strategy: _ComposedStrategy,
    min_evaluation_start: Optional[pd.Timestamp] = None,
    index_category: str = "",
) -> BacktestResult:
    """新框架入口：按 strategy.cycles 遍历 bucket，每根 K 线先 decide → 过 filters → 落 trade。

    复用 _compute_evaluation_start / 各类指标计算（CAGR/MaxDD/胜率），保证与旧 run_strategy 同口径。
    """
    cycles_set = set(strategy.cycles)
    timeframes = [tf for tf in (DAILY, WEEKLY, MONTHLY) if _TF_TO_CYCLE[tf] in cycles_set]

    # 与 run_strategy 保持同样的"评估起点 = max(D/W/M 的 MA20 就绪日, min_start)"
    evaluation_start = _compute_evaluation_start(data, min_evaluation_start)

    # 每 cycle 一个 Bucket（仅记账用，不依赖 BucketGroup）
    buckets: Dict[str, Bucket] = {tf: Bucket(timeframe=tf, capital=BUCKET_CAPITAL) for tf in timeframes}

    trades: List[Trade] = []
    closed_pairs: List[ClosedPair] = []
    last_buy_by_bucket: Dict[int, Tuple[pd.Timestamp, float]] = {}
    equity_records: Dict[pd.Timestamp, float] = {}

    daily_range = data.daily[data.daily.index >= evaluation_start]
    weekly_set = set(data.weekly.index)
    monthly_set = set(data.monthly.index)

    for date, daily_bar in daily_range.iterrows():
        # 构造一次 FilterContext（D / W / M 共享，因为 today 不变）
        ctx = _build_filter_context(today=date, daily=data.daily)

        for tf in timeframes:
            if tf == DAILY:
                bar = daily_bar
            elif tf == WEEKLY:
                if date not in weekly_set:
                    continue
                bar = data.weekly.loc[date]
            else:  # MONTHLY
                if date not in monthly_set:
                    continue
                bar = data.monthly.loc[date]

            cycle = _TF_TO_CYCLE[tf]
            bucket = buckets[tf]
            sig = strategy.decider.decide(cycle=cycle, bar=bar, position_shares=bucket.shares)
            if sig is None:
                continue
            # 过 filter
            if not all(f.allow(sig, ctx) for f in strategy.filters):
                continue
            # 落 trade
            if sig.action == "BUY":
                shares = bucket.buy_all(bar["close"])
                trades.append(Trade(date=date, timeframe=tf, action="BUY",
                                    price=float(bar["close"]), shares=shares,
                                    cash_after=bucket.cash,
                                    bar_high=float(bar["high"]),
                                    bar_low=float(bar["low"]),
                                    bar_ma20=float(bar["ma20"])))
                last_buy_by_bucket[id(bucket)] = (date, float(bar["close"]))
            elif sig.action == "SELL":
                shares = bucket.sell_all(bar["close"])
                trades.append(Trade(date=date, timeframe=tf, action="SELL",
                                    price=float(bar["close"]), shares=shares,
                                    cash_after=bucket.cash,
                                    bar_high=float(bar["high"]),
                                    bar_low=float(bar["low"]),
                                    bar_ma20=float(bar["ma20"])))
                buy_info = last_buy_by_bucket.pop(id(bucket), None)
                if buy_info is not None:
                    buy_date, buy_price = buy_info
                    closed_pairs.append(ClosedPair(
                        buy_date=buy_date, sell_date=date, timeframe=tf,
                        buy_price=buy_price, sell_price=float(bar["close"]),
                        pnl=(float(bar["close"]) - buy_price) * shares,
                    ))

        equity_records[date] = sum(b.position_value(daily_bar["close"]) for b in buckets.values())

    equity_curve = pd.Series(equity_records).sort_index()
    yearly = _yearly_returns_from_curve(equity_curve)
    total_ret = _total_return(equity_curve)
    ann_ret = _cagr(equity_curve)
    mdd = _max_drawdown(equity_curve)
    wr = _win_rate(closed_pairs)
    final_close = data.daily["close"].iloc[-1] if not data.daily.empty else 0.0
    unrealized = _unrealized_pnl(list(buckets.values()), final_close, last_buy_by_bucket)

    bh_curve = _buy_and_hold_curve(data, evaluation_start, capital=BUCKET_CAPITAL)
    bh_yearly = _yearly_returns_from_curve(bh_curve) if not bh_curve.empty else {}
    bh_total = _total_return(bh_curve) if not bh_curve.empty else 0.0
    bh_cagr = _cagr(bh_curve) if not bh_curve.empty else 0.0
    bh_mdd = _max_drawdown(bh_curve) if not bh_curve.empty else 0.0

    return BacktestResult(
        index_code=data.code,
        index_name=data.name,
        index_category=index_category,
        strategy_name=strategy.name,
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
```

- [ ] **Step 4: 跑测试确认通过**

```bash
pytest scripts/backtest/test_strategy_engine.py -v
```
Expected: 3 passed.

- [ ] **Step 5: 全量回归确认 engine 改动没破坏旧入口**

```bash
python -m scripts.backtest.test_signal_manual
pytest scripts/backtest/test_indicators.py scripts/backtest/test_strategy_registry.py scripts/backtest/test_strategy_builtin.py scripts/backtest/test_strategy_engine.py -v
```
Expected: 全部通过。

- [ ] **Step 6: Commit**

```bash
git add scripts/backtest/engine.py scripts/backtest/test_strategy_engine.py
git commit -m "[backtest] engine 新增 run_with_strategy（接受 Strategy 对象，复用旧指标计算）"
```

---

## Task 10: 统一 CLI run.py

**Files:**
- Create: `scripts/backtest/run.py`

- [ ] **Step 1: 实现 run.py**

```python
"""Backtest 统一 CLI（V10 组件化策略入口）。

用法：
    python -m scripts.backtest.run --list
    python -m scripts.backtest.run --strategy v9-baseline --universe v9 --windows 3,5,8,10
    python -m scripts.backtest.run --compare v9-baseline,v9.3-bear --universe v9 --windows 3,5,8,10

旧入口（run_v5/v6/v8/v9 等）保留作为历史复现专用。
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Dict, List

import pandas as pd

import scripts.backtest.strategy.builtin  # noqa: F401  触发策略注册

from scripts.backtest.data_loader import IndexData, load_index
from scripts.backtest.engine import BacktestResult, run_with_strategy
from scripts.backtest.strategy import get as get_strategy, list_all
from scripts.backtest.v9_registry import build_v9_registry
from scripts.backtest.window_engine import (
    INDEX_CAPITAL,
    WindowResult,
    run_portfolio_window,
)

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS_DIR = PROJECT_ROOT / "agents" / "results"

AS_OF = pd.Timestamp("2026-04-25")
MIN_EVALUATION_START = pd.Timestamp("2016-01-01")
DEFAULT_WINDOWS = [3, 5, 8, 10]

UNIVERSES = {"v9": build_v9_registry}


def _load_universe(name: str):
    if name not in UNIVERSES:
        raise SystemExit(f"unknown universe {name!r}, known: {sorted(UNIVERSES)}")
    return UNIVERSES[name]()


def _run_one_strategy(strategy_name: str, universe_name: str, windows: List[int]):
    registry = _load_universe(universe_name)
    strat = get_strategy(strategy_name)

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
            r = run_with_strategy(data, strat,
                                  min_evaluation_start=MIN_EVALUATION_START,
                                  index_category=meta.category)
            full_results[meta.code] = [r]  # 列表为兼容 window_engine 接口
        except ValueError as e:
            logger.warning("  %s 回测失败：%s", meta.code, e)

    window_results: List[WindowResult] = []
    for n in windows:
        wr = run_portfolio_window(index_data, full_results, n, AS_OF)
        logger.info("  %d 年 总 CAGR %.2f%% / MDD %.2f%%", n, wr.cagr, wr.max_drawdown)
        window_results.append(wr)

    return strat, registry, index_data, full_results, window_results


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest 统一 CLI（V10 组件化策略）")
    parser.add_argument("--list", action="store_true", help="列出已注册策略并退出")
    parser.add_argument("--strategy", help="跑单策略：策略名（如 v9-baseline）")
    parser.add_argument("--compare", help="对比两个策略：A,B（如 v9-baseline,v9.3-bear）")
    parser.add_argument("--universe", default="v9", help=f"Universe 名（{sorted(UNIVERSES)}）")
    parser.add_argument("--windows", default="3,5,8,10",
                        help="时间窗口（年），逗号分隔。默认 3,5,8,10")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s - %(message)s")

    if args.list:
        for name in list_all():
            print(name)
        return 0

    windows = [int(x) for x in args.windows.split(",") if x.strip()]

    if args.strategy and args.compare:
        raise SystemExit("--strategy 与 --compare 不能同时指定")

    if args.strategy:
        _run_one_strategy(args.strategy, args.universe, windows)
        logger.info("单策略 %s 完成（详情报告生成由 Task 13 处理）", args.strategy)
        return 0

    if args.compare:
        names = [n.strip() for n in args.compare.split(",") if n.strip()]
        if len(names) != 2:
            raise SystemExit("--compare 需要恰好两个策略名（逗号分隔）")
        results_by_strategy = {}
        for n in names:
            results_by_strategy[n] = _run_one_strategy(n, args.universe, windows)
        # 报告生成由 Task 12 实现的 compare_report.write_compare_report 处理
        from scripts.backtest.compare_report import write_compare_report
        write_compare_report(results_by_strategy, windows, RESULTS_DIR)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 烟测 --list**

```bash
python -m scripts.backtest.run --list
```
Expected: 输出含 `v9-baseline` 和 `v9.3-bear` 两行。

- [ ] **Step 3: 烟测 --strategy（可选；首次跑可能需数据缓存预热，可跳过到 Task 12）**

```bash
python -m scripts.backtest.run --strategy v9-baseline --universe v9 --windows 3
```
Expected: 加载 14 指数 → 跑 3 年窗口 → 打印 `总 CAGR ...% / MDD ...%`。

- [ ] **Step 4: Commit**

```bash
git add scripts/backtest/run.py
git commit -m "[backtest] 新增 run.py 统一 CLI（--list/--strategy/--compare）"
```

---

## Task 11: 对比报告生成器

**Files:**
- Create: `scripts/backtest/compare_report.py`
- Create: `scripts/backtest/test_compare_report.py`

- [ ] **Step 1: 写报告渲染失败测试**

```python
"""compare_report 测试。运行：pytest scripts/backtest/test_compare_report.py -v"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from scripts.backtest.compare_report import (
    render_portfolio_table,
    render_per_index_diff_table,
    render_filter_hit_table,
)


def _make_window_result(years, cagr, mdd, total_return):
    """构造满足渲染所需的最小 WindowResult-like 对象。"""
    class _W:
        pass
    w = _W()
    w.window_years = years
    w.window_start = pd.Timestamp("2021-04-25")
    w.as_of = pd.Timestamp("2026-04-25")
    w.cagr = cagr
    w.max_drawdown = mdd
    w.total_return = total_return
    w.initial_capital = 140000.0
    w.final_value = 140000.0 * (1 + total_return / 100)
    w.per_index = []
    return w


def test_portfolio_table_includes_strategy_names_and_delta():
    a_results = [_make_window_result(3, 14.81, -25.0, 50.0)]
    b_results = [_make_window_result(3, 16.50, -22.0, 60.0)]
    md = render_portfolio_table([("v9-baseline", a_results), ("v9.3-bear", b_results)])
    assert "v9-baseline" in md
    assert "v9.3-bear" in md
    assert "Δ" in md
    assert "+1.69" in md or "1.69" in md  # cagr 差


def test_per_index_diff_table_filters_significant_only():
    diffs = [
        {"code": "931151", "name": "光伏产业", "delta_net_cagr": 2.5, "delta_max_dd": -1.0},
        {"code": "000819", "name": "有色金属", "delta_net_cagr": 0.3, "delta_max_dd": -0.5},  # 不显著
    ]
    md = render_per_index_diff_table(diffs, threshold_cagr=1.0, threshold_dd=2.0)
    assert "光伏产业" in md
    assert "有色金属" not in md


def test_filter_hit_table_lists_per_index_stats():
    hits = [
        {"code": "931151", "name": "光伏产业",
         "buy_candidates": 20, "suppressed": 5,
         "suppress_rate": 25.0, "hindsight_60d_avg_return": -3.5},
    ]
    md = render_filter_hit_table(hits)
    assert "光伏产业" in md
    assert "25.0" in md
    assert "-3.5" in md
```

- [ ] **Step 2: 跑测试确认失败**

```bash
pytest scripts/backtest/test_compare_report.py -v
```
Expected: ImportError on `compare_report`.

- [ ] **Step 3: 实现 compare_report.py**

```python
"""对比报告生成器：组合层 / 分指数差异 / Filter 命中三张表。"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Dict, List, Sequence, Tuple


def _fmt_pct(v: float, signed: bool = False) -> str:
    if v is None:
        return "-"
    fmt = "+.2f" if signed else ".2f"
    return f"{v:{fmt}}%"


def render_portfolio_table(strategies: Sequence[Tuple[str, list]]) -> str:
    """组合层对比表。每窗口 3 行：A / B / Δ。

    strategies: [(name, [WindowResult, ...]), ...]，长度 == 2。
    """
    if len(strategies) != 2:
        raise ValueError("portfolio table requires exactly 2 strategies")
    name_a, win_a = strategies[0]
    name_b, win_b = strategies[1]
    if len(win_a) != len(win_b):
        raise ValueError("two strategies must have same #windows")
    lines = [
        "| 时间窗 | 策略 | 总 CAGR | 最大回撤 | 总收益 |",
        "|---|---|---|---|---|",
    ]
    for wa, wb in zip(win_a, win_b):
        years = wa.window_years
        lines.append(f"| {years} 年 | {name_a} | {_fmt_pct(wa.cagr)} | {_fmt_pct(wa.max_drawdown)} | {_fmt_pct(wa.total_return, signed=True)} |")
        lines.append(f"| {years} 年 | {name_b} | {_fmt_pct(wb.cagr)} | {_fmt_pct(wb.max_drawdown)} | {_fmt_pct(wb.total_return, signed=True)} |")
        lines.append(f"| {years} 年 | Δ | {_fmt_pct(wb.cagr - wa.cagr, signed=True)} | {_fmt_pct(wb.max_drawdown - wa.max_drawdown, signed=True)} | {_fmt_pct(wb.total_return - wa.total_return, signed=True)} |")
    return "\n".join(lines)


def render_per_index_diff_table(
    diffs: List[Dict],
    *,
    threshold_cagr: float = 1.0,
    threshold_dd: float = 2.0,
) -> str:
    """分指数差异表。仅列 |Δ Net CAGR| ≥ threshold_cagr 或 |Δ MaxDD| ≥ threshold_dd 的指数。"""
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


def render_filter_hit_table(hits: List[Dict]) -> str:
    """Filter 命中统计表。仅 v9.3-bear 类策略才有数据。"""
    if not hits:
        return "（无 Filter 命中数据）"
    lines = [
        "| 指数 | 总 BUY 候选 | 被 suppress | suppress 率 | 若执行的事后 60D 收益均值 |",
        "|---|---|---|---|---|",
    ]
    for h in hits:
        hindsight = h.get("hindsight_60d_avg_return")
        hs = _fmt_pct(hindsight, signed=True) if hindsight is not None else "N/A"
        lines.append(
            f"| {h['name']}({h['code']}) "
            f"| {h['buy_candidates']} "
            f"| {h['suppressed']} "
            f"| {h['suppress_rate']:.1f}% "
            f"| {hs} |"
        )
    return "\n".join(lines)


def write_compare_report(
    results_by_strategy: Dict[str, tuple],
    windows: List[int],
    output_dir: Path,
) -> Path:
    """对比报告主入口。被 run.py 调用。

    results_by_strategy: { strategy_name: (strat, registry, index_data, full_results, window_results) }
    """
    names = list(results_by_strategy.keys())
    if len(names) != 2:
        raise ValueError(f"compare expects 2 strategies, got {names}")
    a_name, b_name = names

    _, _, _, _, a_windows = results_by_strategy[a_name]
    _, registry, _, b_full, b_windows = results_by_strategy[b_name]

    portfolio_md = render_portfolio_table([(a_name, a_windows), (b_name, b_windows)])

    diffs = []
    a_full = results_by_strategy[a_name][3]
    for meta in registry:
        a_r = a_full.get(meta.code)
        b_r = b_full.get(meta.code)
        if not a_r or not b_r:
            continue
        a0, b0 = a_r[0], b_r[0]
        diffs.append({
            "code": meta.code,
            "name": meta.name,
            "delta_net_cagr": (b0.annualized_return - a0.annualized_return),
            "delta_max_dd": (b0.max_drawdown - a0.max_drawdown),
        })
    diff_md = render_per_index_diff_table(diffs)

    # Filter 命中统计需要 BearTrendFilter 在引擎里采集 metadata，本次先空表占位（Task 13 决定是否补全）
    hits: List[Dict] = []
    hits_md = render_filter_hit_table(hits)

    today = date.today().isoformat()
    out = output_dir / f"{today}-compare-{a_name}-vs-{b_name}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    md = "\n\n".join([
        f"# 策略对比报告：{a_name} vs {b_name}",
        f"> 生成日：{today}",
        "## 一、组合层对比",
        portfolio_md,
        "## 二、分指数差异（|ΔCAGR|≥1pp 或 |ΔMaxDD|≥2pp）",
        diff_md,
        "## 三、Filter 命中统计",
        hits_md,
    ])
    out.write_text(md, encoding="utf-8")
    return out
```

- [ ] **Step 4: 跑测试确认通过**

```bash
pytest scripts/backtest/test_compare_report.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/backtest/compare_report.py scripts/backtest/test_compare_report.py
git commit -m "[backtest] 新增 compare_report（组合层/分指数差异/Filter 命中）"
```

---

## Task 12: v9-baseline 回归门槛验证（硬条件）

**Files:**
- 无新增；只跑 + 对比

- [ ] **Step 1: 备份当前 v9-manual-result.md 作为 baseline 快照**

```bash
cp agents/results/v9-manual-result.md /tmp/v9-manual-result-baseline.md
```

- [ ] **Step 2: 跑 v9-baseline 通过新框架**

```bash
python -m scripts.backtest.run --strategy v9-baseline --universe v9 --windows 3,5,8,10 2>&1 | tee /tmp/v9-baseline-new.log
```
Expected: 退出码 0，每个时间窗输出 `总 CAGR ...% / MDD ...%`。

- [ ] **Step 3: 提取四个时间窗的 CAGR / MaxDD 数值并与 baseline 对比**

从 `/tmp/v9-baseline-new.log` 抓取：

```bash
grep "总 CAGR" /tmp/v9-baseline-new.log
```

从 baseline `agents/results/v9-manual-result.md` 第三章「多窗口组合回测总览」表格提取相同数值。

人工对比：每行（3/5/8/10 年）的 CAGR 和 MaxDD 差异 < 0.01 个百分点。

如果差异 ≥ 0.01pp，**禁止进入 Task 13**。回退检查 `engine.run_with_strategy` 是否：
- 评估起点与旧 `run_strategy` 一致（`_compute_evaluation_start`）
- BUCKET_CAPITAL 一致（10000）
- D/W/M 三 cycle 都跑（默认 cycles=("D","W","M")）
- weekly_set / monthly_set 判断是否在某根日 K 线上触发对应 cycle 一致

修复后回到 Step 2 重跑。

- [ ] **Step 4: 通过则记录验收日志**

把对比结果写入临时文件供 Task 14 文档化：

```bash
cat > /tmp/regression-result.txt <<'EOF'
v9-baseline 回归门槛验证（new framework vs v9-manual-result.md）：
3 年: ΔCAGR=...pp ΔMaxDD=...pp
5 年: ΔCAGR=...pp ΔMaxDD=...pp
8 年: ΔCAGR=...pp ΔMaxDD=...pp
10 年: ΔCAGR=...pp ΔMaxDD=...pp
通过门槛（< 0.01pp）：YES
EOF
```

- [ ] **Step 5: 此 task 不产生 commit（仅验证）**

无文件改动，跳过 commit。

---

## Task 13: 跑 v9.3-bear + 生成对比报告

**Files:**
- Output: `agents/results/{today}-compare-v9-baseline-vs-v9.3-bear.md`

- [ ] **Step 1: 跑对比命令**

```bash
python -m scripts.backtest.run --compare v9-baseline,v9.3-bear --universe v9 --windows 3,5,8,10
```
Expected: 退出码 0；脚本结束时 `agents/results/2026-MM-DD-compare-v9-baseline-vs-v9.3-bear.md` 已生成。

- [ ] **Step 2: 检查对比报告生成成功**

```bash
ls -la agents/results/*-compare-v9-baseline-vs-v9.3-bear.md
head -50 agents/results/*-compare-v9-baseline-vs-v9.3-bear.md
```
Expected: 文件存在，前 50 行含三个章节标题（组合层 / 分指数差异 / Filter 命中）。

- [ ] **Step 3: 人工 sanity check 报告内容**

打开报告，验证：
- 一、组合层：四个时间窗都有 v9-baseline / v9.3-bear / Δ 三行
- 二、分指数：列出至少 1 个或显式说明「无显著差异指数」
- 三、Filter 命中：占位说明（本任务范围内不做反事实统计）

如果某项缺失或乱码，回退检查 `compare_report.write_compare_report` 与 `run.py:--compare` 分支。

- [ ] **Step 4: Commit 报告**

```bash
git add agents/results/*-compare-v9-baseline-vs-v9.3-bear.md
git commit -m "[backtest] 产出 v9-baseline vs v9.3-bear 对比报告"
```

---

## Task 14: 更新 backtest CLAUDE.md

**Files:**
- Modify: `scripts/backtest/CLAUDE.md`

- [ ] **Step 1: 在 CLAUDE.md「核心策略」段后追加新框架说明**

打开 `scripts/backtest/CLAUDE.md`，在第 19 行（"## 核心策略" 段最后）之后插入新段：

```markdown
## 组件化策略框架（V10）

新策略走 `scripts/backtest/strategy/` 模块：

- `protocol.py`：`Decider` / `Filter` / `Strategy` / `FilterContext`
- `registry.py`：`@register("name")` 装饰器
- `builtin.py`：`MA20CrossDecider` + `BearTrendFilter` + 注册 `v9-baseline` 与 `v9.3-bear`

跑新策略：

```bash
python -m scripts.backtest.run --list                              # 列出已注册策略
python -m scripts.backtest.run --strategy v9-baseline --universe v9
python -m scripts.backtest.run --compare v9-baseline,v9.3-bear --universe v9
```

旧入口（`run_v5/v6/v6_friction/v8/v9/v9_detail/windows`）保留作历史复现专用，新策略不再走老链路。

新策略加法：
1. 在 `strategy/builtin.py` 写 `Decider` 或新 `Filter`（也可放新文件）
2. 用 `@register("strategy-name")` 装饰返回 `Strategy(...)` 的工厂
3. 加 `test_strategy_*.py` 单测覆盖关键边界
4. `python -m scripts.backtest.run --strategy strategy-name --universe v9` 即可跑
```

- [ ] **Step 2: 在「文件结构」表格底部追加新模块**

找到现有「文件结构」表（第 ~37 行起），在表的末尾追加：

```markdown
| `indicators.py` | 共用指标：MA / 重采样 / splice / is_bear |
| `strategy/protocol.py` | Decider / Filter / Strategy / FilterContext |
| `strategy/registry.py` | 策略注册表 |
| `strategy/builtin.py` | MA20CrossDecider / BearTrendFilter / v9-baseline / v9.3-bear |
| `run.py` | 统一 CLI（--list / --strategy / --compare） |
| `compare_report.py` | 三张表对比报告生成器 |
```

- [ ] **Step 3: 在「迭代史」表底部追加 V10**

```markdown
| **V10** | 组件化策略框架（Decider+FilterChain）+ v9.3-bear 加月线 C>MA5 与双空头过滤 | 见 `agents/results/{date}-compare-v9-baseline-vs-v9.3-bear.md` |
```

- [ ] **Step 4: Commit**

```bash
git add scripts/backtest/CLAUDE.md
git commit -m "[backtest] CLAUDE.md 增补 V10 组件化策略框架使用方式"
```

---

## Task 15: 范围检查（生产隔离不变量）

**Files:**
- 无；纯检查

- [ ] **Step 1: 确认 scripts/quant/ 与 docs/ 没有任何改动**

```bash
git diff --name-only main... | grep -E '^(scripts/quant/|scripts/main\.py|docs/)' || echo "OK: 生产 + 前端干净"
```
Expected: `OK: 生产 + 前端干净`

如果命中任何文件，停下来检查——它意味着违反了 spec §1 的范围约束。回退：

```bash
git checkout main -- <被命中的文件>
```

并在重新提交前重新跑 Task 12 的回归验证。

- [ ] **Step 2: 跑全部新增 pytest 套件最后一遍**

```bash
pytest scripts/backtest/test_indicators.py scripts/backtest/test_strategy_registry.py scripts/backtest/test_strategy_builtin.py scripts/backtest/test_strategy_engine.py scripts/backtest/test_compare_report.py -v
```
Expected: 全部 passed。

- [ ] **Step 3: 跑 quant 现有测试，确认未被本次改动连带破坏**

```bash
pytest scripts/quant/tests/ -v
```
Expected: 与 main 分支一致（路径修复 Task 之外的本次 plan 不该影响 quant）。

- [ ] **Step 4: 不做 commit；标记 plan 完成**

无文件改动，无 commit。在 PR 描述里链接到 `agents/plans/2026-05-10-quant-strategy-framework-design.md` 与本 plan。

---

## 全流程一次性烟测脚本（开发期可复用）

```bash
# 全部新增 pytest 一次跑通
pytest scripts/backtest/test_indicators.py \
       scripts/backtest/test_strategy_registry.py \
       scripts/backtest/test_strategy_builtin.py \
       scripts/backtest/test_strategy_engine.py \
       scripts/backtest/test_compare_report.py -v

# 老 manual test
python -m scripts.backtest.test_signal_manual

# CLI 烟测
python -m scripts.backtest.run --list
python -m scripts.backtest.run --strategy v9-baseline --universe v9 --windows 3
python -m scripts.backtest.run --compare v9-baseline,v9.3-bear --universe v9 --windows 3
```

---

## Spec 覆盖度自查

| Spec 章节 | Plan 覆盖 |
|---|---|
| §2 v9 universe（14 指数） | Task 10 `_load_universe("v9")` 调 `build_v9_registry` |
| §3.1 `is_bear` 数学 | Task 1 实现 + 6 个单测 |
| §3.2 month_close_spliced | Task 9 `_build_filter_context` 通过「截 daily 到 today + resample_monthly」保证当月 close=当日 close（不需独立 splice 函数） |
| §3.3 月线 MA5 | Task 9 `_build_filter_context` 用 `compute_ma(window=5)` |
| §4 BearTrendFilter | Task 7 实现 + 12 单测 |
| §5 策略框架（Decider/Filter/Strategy/Registry） | Task 4 + Task 5 |
| §6.1 engine 改造 | Task 9 `run_with_strategy` |
| §6.2 兼容旧入口 | Task 3 `BucketGroup` rename + alias |
| §6.3 共用指标 | Task 1 + Task 2 |
| §7 CLI | Task 10 |
| §8.1 单策略明细 | （延后；本 plan 范围内仅产 §8.2 对比报告） |
| §8.2 对比报告 | Task 11 + Task 13 |
| §9.3 回归门槛 0.01pp | Task 12（硬门槛） |
| §10 测试范围 | 5 个 test_*.py 文件覆盖 |
| §11 不变量（不动 scripts/quant/） | Task 15 范围检查 |
| §12 风险 — month_close_spliced 不泄漏 | Task 1 `test_resample_monthly_on_partial_month_takes_today_close` + Task 9 `_build_filter_context` 用 `daily.loc[:today]` 重 resample（不读 data.monthly 预计算结果） |
| §13 不在范围 | 单策略明细报告未做（v9.3-bear-detail.md 由后续 plan 决定） |

**Spec §8.1「单策略明细」与本 plan 偏差说明**：spec 提到要为 `v9.3-bear` 单独产一份 `*-detail.md`，但本 plan 仅产对比报告。原因：明细报告的渲染逻辑与历史 `run_v9.py:render_v9_report` 高度相似，要复刻 7 个章节会让 plan 膨胀且重复 `run_v9.py` 已有代码。如果用户审稿时仍要求明细报告，我会在 spec 修正后补一个 Task 16，复用 `reporter.py` 的 `render_index_report` + 仿 `run_v9.py` 写 `render_strategy_detail_report`，预计 1 个新 task。
