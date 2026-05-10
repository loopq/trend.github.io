# Quant 策略框架 + 空头过滤回测 — Design Spec

- 日期: 2026-05-10
- 范围: 仅 `scripts/backtest/`
- 不在范围: `scripts/quant/`（生产）任何文件、`scripts/main.py`、前端

---

## 1. 背景与目标

`scripts/backtest/` 当前把策略写死成 `d_strategy / w_strategy / m_strategy` 三个工厂，新策略要复制 `run_v9.py` 这套链路才能跑，且无法在同一次执行里横向对比。本次重构把"信号产生"与"过滤准入"解耦成可注册的组件，并落地一个新策略 `v9.3-bear`，验证以下规则在 v9 universe 上的效果：

> D / W 周期的 BUY 信号，必须同时满足：
> - 月线 C > 月线 MA5
> - 周线 MA60 不是空头趋势 **或** 月线 MA20 不是空头趋势
>
> M 周期的 BUY 不加过滤；任何 SELL 不加过滤。

生产代码本次不动。等回测验证策略后，另立 plan 把过滤器搬到 `scripts/quant/`。

## 2. 指数 Universe

回测固定使用 `v9-manual-result.md` 的 14 个指数（v9.2 整理后的最终清单）：

| 类别 | 代码 | 名称 |
|---|---|---|
| 主题 | 931151 | 光伏产业 |
| 主题 | 000819 | 有色金属 |
| 主题 | 399997 | 中证白酒 |
| 主题 | 399989 | 中证医疗 |
| 主题 | 931079 | 5G 通信 |
| 主题 | 399808 | 中证新能 |
| 主题 | 931071 | 人工智能 |
| 主题 | 930721 | CS 智汽车 |
| 主题 | 399967 | 中证军工 |
| 高波动宽基 | 399673 | 创业板 50 |
| 高波动宽基 | 000688 | 科创 50 |
| 高波动宽基 | 932000 | 中证 2000 |
| 行业 | 000813 | 细分化工 |
| 行业 | 399976 | CS 新能车 |

注：生产 `scripts/quant/config.yaml` 当前是 13 个（缺中证 2000），是否同步生产由本次回测结论决定，不在本 plan 内。

## 3. 数学口径

### 3.1 空头趋势判定

```python
def is_bear(ma_series: pd.Series, *, N: int, eps: float) -> bool:
    """
    最新 MA 与 N 周期前的 MA 比较。drop_rate = (ma[t-N] - ma[t]) / ma[t-N]
    drop_rate > eps  → 空头
    drop_rate ≤ eps  → 非空头（含放平和上升）
    数据不足（< N+1 个非空 MA 值）→ 视为非空头（冷启动不误杀）
    """
```

均针对**同周期序列**：周线 MA60 看周线 K 线序列上的 MA60；月线 MA20 看月线 K 线序列上的 MA20。

默认参数：

| 序列 | N | ε |
|---|---|---|
| 周线 MA60 | 4（≈1 月） | 0.5% |
| 月线 MA20 | 3（≈1 季） | 0.5% |

参数定义为 `BearTrendFilter` 的构造参数，不写死。未来要扫参直接注册新策略名（如 `v9.3-bear-N5-eps003`），不改框架。

### 3.2 月线 C 取数（`month_close_spliced`）

当月未走完时：把"当前回测日的日 K close"拼到月线序列末尾作为该月 close；月末该值与真实月 close 一致。这避免使用未来的"完结月 close"造成未来函数泄漏。生产 `scripts/quant/signal_engine.py` 已有同口径实现可参考。

### 3.3 月线 MA5

月线 K 线序列上的 5 周期均线（5 个月平均）。`compute_ma(monthly_series, window=5)`。

## 4. 过滤器规格

```python
class BearTrendFilter:
    def __init__(
        self,
        scope: tuple[str, ...] = ("D", "W"),
        weekly_bear_N: int = 4,
        weekly_bear_eps: float = 0.005,
        monthly_bear_N: int = 3,
        monthly_bear_eps: float = 0.005,
    ): ...

    def allow(self, signal: Signal, ctx: FilterContext) -> bool:
        if signal.action != "BUY":              return True
        if signal.cycle not in self.scope:      return True
        cond_close = ctx.month_close_spliced > ctx.month_ma5
        weekly_bear = is_bear(
            ctx.weekly_ma60_series,
            N=self.weekly_bear_N,
            eps=self.weekly_bear_eps,
        )
        monthly_bear = is_bear(
            ctx.monthly_ma20_series,
            N=self.monthly_bear_N,
            eps=self.monthly_bear_eps,
        )
        cond_trend = (not weekly_bear) or (not monthly_bear)
        return cond_close and cond_trend
```

`FilterContext` 由 engine 在每个回测点构建，包含截至当日的：
- `month_close_spliced: float`
- `month_ma5: float`
- `weekly_ma60_series: pd.Series`（足够长，至少 N+1 个非空值）
- `monthly_ma20_series: pd.Series`

## 5. 策略框架

### 5.1 协议

```python
# scripts/backtest/strategy/protocol.py
class Decider(Protocol):
    name: str
    def decide(self, state: BucketState, ohlc: OHLC, ind: Indicators) -> Signal | None: ...

class Filter(Protocol):
    name: str
    def allow(self, signal: Signal, ctx: FilterContext) -> bool: ...

@dataclass(frozen=True)
class Strategy:
    name: str
    decider: Decider
    filters: tuple[Filter, ...]
    cycles: tuple[str, ...] = ("D", "W", "M")
```

`Decider` 只产生原始信号，不知道有没有 Filter；`Filter` 只决定 allow / suppress，不知道决策逻辑。

### 5.2 注册表

```python
# scripts/backtest/strategy/registry.py
_STRATEGIES: dict[str, Callable[[], Strategy]] = {}

def register(name: str):
    def deco(factory):
        if name in _STRATEGIES:
            raise ValueError(f"strategy {name!r} already registered")
        _STRATEGIES[name] = factory
        return factory
    return deco

def get(name: str) -> Strategy: ...
def list_all() -> list[str]: ...
```

### 5.3 内置策略

```python
# scripts/backtest/strategy/builtin.py
@register("v9-baseline")
def _v9_baseline():
    return Strategy(
        name="v9-baseline",
        decider=MA20CrossDecider(),
        filters=(),
    )

@register("v9.3-bear")
def _v9_3_bear():
    return Strategy(
        name="v9.3-bear",
        decider=MA20CrossDecider(),
        filters=(BearTrendFilter(scope=("D", "W")),),
    )
```

`MA20CrossDecider` 是把现有 `engine.py` 内 MA20 交叉那段抽出来的纯类，不变更行为。

## 6. 回测引擎改造

### 6.1 目标

`engine.run_strategy()` 由"硬编码遍历 D/W/M 三个 factory"改为"接受 `Strategy` 对象，按 `strategy.cycles` 遍历，每根 K 线先走 `decider.decide()`，再过 `filters`，命中才记 trade"。

### 6.2 兼容旧入口

- `run_v9.py` 保留为 thin wrapper，内部调 `run --strategy v9-baseline --universe v9`
- `run_v5.py` / `run_v6.py` 保留原文件不动（不接入新框架，仅供历史复现）
- `v9_registry.py` 改名 `universe.py`，导出 `UNIVERSES = {"v9": [...]}`，保留旧符号 `build_v9_registry` 作为 alias 以免现有 import 报错

### 6.3 共用指标模块

新增 `scripts/backtest/indicators.py`：

- `compute_ma(series, window)`
- `resample_weekly(daily_df)` / `resample_monthly(daily_df)`
- `splice_realtime_close(monthly_df, today_close, today_date)`
- `is_bear(series, N, eps)`

`data_loader.py` 内重复实现的 MA20 / 重采样迁过来调 `indicators.py`。生产 `scripts/quant/signal_engine.py` 不变。

## 7. CLI

```bash
# 单策略复现历史 v9
python -m scripts.backtest.run --strategy v9-baseline --universe v9 --windows 3,5,8,10

# 跑新策略
python -m scripts.backtest.run --strategy v9.3-bear --universe v9 --windows 3,5,8,10

# 对比（顺序跑两个策略 + 自动出对比表）
python -m scripts.backtest.run --compare v9-baseline,v9.3-bear --universe v9 --windows 3,5,8,10

# 列出已注册策略
python -m scripts.backtest.run --list
```

`run.py` 是新增的统一入口，老的 `run_v9.py` 留作兼容。

## 8. 报告输出

### 8.1 单策略明细

- 路径：`agents/results/2026-MM-DD-{strategy}-detail.md`
- 格式沿用 `v9-manual-result.md`（每指数 σ / CAGR / D/W/M 权重 / 净值曲线 / 时间窗口）

### 8.2 对比报告

- 路径：`agents/results/2026-MM-DD-compare-{a}-vs-{b}.md`
- 表 1（组合层，14 指数总盘）

| 时间窗 | 策略 | 总 CAGR | 净 CAGR | 最大回撤 | Calmar | 胜率 | 换手率 | 平均持仓天数 |
|---|---|---|---|---|---|---|---|---|

每个时间窗（3/5/8/10）一组，三行：策略 A、策略 B、Δ。

- 表 2（分指数，仅列 |Δ Net CAGR| ≥ 1pp 或 |Δ MaxDD| ≥ 2pp 的指数）
- 表 3（Filter 命中统计，仅 v9.3-bear 有）

| 指数 | 总 BUY 候选 | 被 suppress | suppress 率 | 若执行的事后 60D 收益均值 |
|---|---|---|---|---|

最后一列是回测才能算的反事实——把被过滤掉的 BUY 信号假设执行，看 60 个交易日后的收益。如果均值显著为负，说明过滤器抓对了；接近 0 或为正则要警惕。

格式纯 Markdown，便于 git diff 跟踪。

## 9. 执行阶段

| # | 内容 | 验收 |
|---|---|---|
| 1 | `indicators.py` + 单测（`is_bear` / MA / 重采样 / splice） | pytest 通过；与 `data_loader.py` 在 v9 universe 上 MA20 数值逐点一致 |
| 2 | `strategy/{protocol,registry,builtin}.py` + `MA20CrossDecider` + `BearTrendFilter` + 单测 | filter 边界用例（D/W/M × BUY/SELL × 4 种空头组合 × 月线 C 与 MA5 大小关系）全覆盖 |
| 3 | `engine.py` 接受 `Strategy`；`run.py` 新增；`run_v9.py` 改 thin wrapper | **回归门槛**：`v9-baseline` 在 14 指数 4 窗口下，组合层 CAGR / Net CAGR / MaxDD 与 `v9-manual-result.md` 数值差异 < 0.01 个百分点 |
| 4 | 跑 `v9.3-bear`，生成明细 + 对比报告（含 Filter 命中统计） | 报告进 `agents/results/`，三张表完整 |
| 5 | `scripts/backtest/CLAUDE.md` 更新使用方式 | 文档明确"新策略走 `--strategy` / 旧 v5/v6 用旧脚本" |

阶段 3 的回归验证不通过，禁止进阶段 4。

## 10. 测试范围

- `tests/backtest/test_indicators.py`：`is_bear` 在跌透/放平/上升/数据不足/边界 ε 各场景；MA 与重采样的数值；splice 不引入未来数据
- `tests/backtest/test_strategy_protocol.py`：注册表去重、`get` 抛错、`list_all` 一致
- `tests/backtest/test_filter_bear_trend.py`：
  - SELL 永远 allow
  - M 周期 BUY 永远 allow（即使 D/W 在 scope 内）
  - D 周期 BUY × {月线C 是否大于 MA5} × {周空头/月空头/双空头/双非空头} 共 8 种组合
- `tests/backtest/test_engine_integration.py`：用 fixture 数据跑 `v9-baseline` 与 `v9.3-bear`，确认 Filter 真的过滤了至少 1 条 BUY

## 11. 关键不变量

- `scripts/quant/` 下任何文件本次不修改。CI / 提交前用 `git diff --name-only main... | grep -v '^scripts/quant/'` 检查
- 阶段 3 回归门槛是硬条件
- 旧 `run_v5.py` / `run_v6.py` 的 import 路径不破坏（v9 registry rename 时保留 alias）

## 12. 风险与权衡

- **`month_close_spliced` 的回测实现**：要把"如果回测日是 t，月线最后一根的 close = 当日日 K close"做对，不能图省事直接用月末 close（会泄漏未来）。这是阶段 1 的重点测试目标
- **MA20 双份实现导致的细微差异**：现行 `data_loader.py` 与生产 `signal_engine.py` 各算一份，可能存在 `min_periods` 之类的细微差异。本次只动 backtest 一侧，不强求两侧统一
- **Filter 命中统计的"反事实"列依赖 60D 前瞻**：回测末尾 60 天的样本算不出，要么截断、要么标 N/A，文档里说清楚

## 13. 不在范围

- 生产 `scripts/quant/` 任何修改
- 前端 `docs/` 任何修改
- 把 v5/v6 系列接入新框架
- 参数扫参网格（`v9.3-bear-N5-eps003` 这类变体留作后续策略各自注册）
- 自动对接 cron / 调度
