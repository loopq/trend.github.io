# 共享前置 + B Faber GTAA 策略 — Design Spec

- 日期: 2026-05-10
- 范围: 仅 `scripts/backtest/`
- 不在范围: `scripts/quant/`（生产）、`scripts/main.py`、前端 `docs/`

## 0. 隔离保证（最高优先级）

**所有改动对 v9-baseline / v9.3-bear / V5-V9 历史入口零行为变更。**

具体：
- `Strategy` dataclass 加新字段必须有默认值且加在末尾，旧 `Strategy(name=..., decider=..., filters=...)` 调用不变
- `run.py:_run_one_strategy` 内 `aggregator == "cycle-calmar"` 分支保持现有逻辑一字不变
- `engine.run_with_strategy / run_strategy` 不动
- `compare_report` 在 N=2 输入下输出与现有等价
- 测试：跑完后 `pytest scripts/backtest/` 整套（含 v9-baseline / v9.3-bear 数值断言）必须 zero regression

## 1. 背景与目标

v9.3-bear 实测全输基础策略（v9 universe -1.3~-3.1pp、main-online -0.6~-2.0pp）—— BearTrendFilter "加过滤减信号" 方向反，少赚多于少赔。用户优先级：**收益第一、回撤次之**。

新方向：**加策略提收益**。规划三条路线（B → C → A 顺序）：
- B Faber GTAA（月线 MA10 趋势跟踪，最简单）
- C Donchian 200（突破策略）
- A Dual Momentum（横截面动量轮动）

本 spec 覆盖 **第一周期**：共享前置（universe + Strategy aggregator 字段 + equal-weight 流程 + 报告改造）+ B Faber GTAA 策略。

## 2. Universe：`combined-27`

合并 v9 universe（14 主题/行业）+ main-online universe（16 宽基/海外/商品），去重 3 个（创业板50/科创50/中证2000），共 **27 个唯一指数**。

| 类别 | 数量 | 代码 |
|---|---|---|
| A 股宽基 | 8 | 000300、000016、000905、000852、000688、000852、932000、399673、899050 |
| A 股主题 | 9 | 931151、399997、399989、931079、399808、931071、930721、399967、000819 |
| A 股行业 | 2 | 000813、399976 |
| 港股 | 3 | HSI、HSCEI、HSTECH |
| 美股 | 2 | NDX、SPX |
| 加密 | 1 | BTC |
| 商品 | 2 | XAU、XAG |

注册命名 `combined-27`，与现有 `v9` / `main-online` universe 并列存在。

## 3. 框架改动：Strategy aggregator 字段

`Strategy` dataclass 加最末位字段：

```python
@dataclass(frozen=True)
class Strategy:
    name: str
    decider: Decider
    filters: Tuple[Filter, ...] = field(default_factory=tuple)
    cycles: Tuple[str, ...] = ("D", "W", "M")
    aggregator: str = "cycle-calmar"   # 新字段，默认=现有行为
```

`aggregator` 三个合法值：
- `"cycle-calmar"`（默认）：现有 v9-baseline / v9.3-bear 用。每指数 D/W/M 三 cycle 拆开跑 → Calmar 权重切 → 多窗口聚合
- `"equal-weight"`：B Faber / C Donchian 用。单 cycle、每指数 1/N 资金、`Decider.decide()` 信号决定该指数 in/out
- `"cross-sectional-topk"`：A Dual Momentum 用。月度对所有指数排名 → 选 Top K 等权 → 月度 rebalance（**本 spec 不覆盖，留 A 周期**）

## 4. `run.py:_run_one_strategy` Dispatch

```python
def _run_one_strategy(strategy_name, universe_name, windows):
    strat = get_strategy(strategy_name)
    registry = _load_universe(universe_name)
    
    if strat.aggregator == "cycle-calmar":
        return _run_cycle_calmar(strat, registry, windows)   # 现有逻辑搬过来
    elif strat.aggregator == "equal-weight":
        return _run_equal_weight(strat, registry, windows)   # 新逻辑
    elif strat.aggregator == "cross-sectional-topk":
        raise NotImplementedError("Task A 周期实施")
    else:
        raise ValueError(f"unknown aggregator: {strat.aggregator!r}")
```

`_run_cycle_calmar` 是把现有 `_run_one_strategy` 函数体（已有的 cycle-split + Calmar 流程）原样剥离成的私有函数，**逻辑零改动**。`_run_equal_weight` 是新写的。

## 5. Equal-weight 流程

**模型**：N 个指数等权，单 cycle，每个指数独立按 Decider 信号 BUY/SELL；不用 Calmar 权重；每指数固定占 `INITIAL_CAPITAL / N` 资金。

```python
def _run_equal_weight(strategy, registry, windows):
    """单 cycle + 等权聚合：
    
    - 假设 strategy.cycles 长度 = 1（如 ("M",) for Faber，("D",) for Donchian）
    - 每指数 INITIAL_CAPITAL / N 资金，单 cycle 跑 Decider
    - 信号：UP→BUY 满仓；DOWN→SELL 现金；else 维持
    - 多窗口聚合：N 年窗口内重跑（用 window_start 作为 min_evaluation_start）
    """
    if len(strategy.cycles) != 1:
        raise ValueError(f"equal-weight aggregator requires single cycle, got {strategy.cycles}")
    cycle = strategy.cycles[0]
    
    # 1. 加载所有指数 + 跑 full-history 单 cycle 得每指数 BacktestResult
    index_data = {}
    full_results = {}
    for meta in registry:
        data = load_index(meta.code, meta.source, meta.name)
        if data is None or data.daily.empty:
            continue
        index_data[meta.code] = data
        try:
            r = engine.run_with_strategy(
                data,
                strategy,                           # cycles=("M",) 时 engine 内只跑 M cycle
                min_evaluation_start=MIN_EVALUATION_START,
                index_category=meta.category,
            )
            # 注意：equal-weight 路径 **不** 走 compute_allocation，所以不需要 rewrite r.strategy_name。
            # r.strategy_name 保持 = strategy.name (= "faber-gtaa")，报告里直接显示策略名。
            full_results[meta.code] = [r]
        except ValueError as e:
            logger.warning("%s 回测失败：%s", meta.code, e)
    
    # 2. 多窗口聚合：等权（不用 Calmar）
    window_results = []
    for n in windows:
        wr = run_portfolio_window_equal_weight(index_data, full_results, n, AS_OF)
        logger.info("  %d 年 总 CAGR %.2f%% / MDD %.2f%%", n, wr.cagr, wr.max_drawdown)
        window_results.append(wr)
    
    return strategy, registry, index_data, full_results, window_results
```

**关键设计**：复用 `engine.run_with_strategy`，但 `strategy.cycles=(M,)` 让它内部只跑 M cycle，等价于现有 cycle-only 跑法。

新增 `window_engine.run_portfolio_window_equal_weight`：与 `run_portfolio_window` 同接口，但 `compute_allocation` 替换为"每指数等权 1/N"，不用 Calmar。

## 6. B Faber GTAA 策略

### 6.1 FaberMonthlyMaDecider

新 Decider，与 `MA20CrossDecider` 同 Protocol（`decide(*, cycle, bar, position_shares) -> Signal | None`），但逻辑：

```python
class FaberMonthlyMaDecider:
    """Faber 2007 月线 MA10 趋势跟踪。
    
    每根月线 K 线：
      close > MA{window} → 状态切 UP；UP 翻转 + 空仓 → BUY
      close ≤ MA{window} → 状态切 DOWN；DOWN 翻转 + 持仓 → SELL
      MA NaN → None（数据不足）
    
    与 MA20CrossDecider 区别：
    - 用 close 直接比，不用 low/high "干净 K 线"
    - 默认 MA 窗口 10（论文原值）
    - 仅跑 monthly cycle（用 strategy.cycles=("M",) 约束）
    """
    
    name = "faber-monthly-ma"
    
    def __init__(self, window: int = 10) -> None:
        self.window = window
        self._state_by_cycle: Dict[str, Optional[str]] = {}
    
    def decide(self, *, cycle, bar, position_shares):
        # bar 是月线 K，含 close 和 ma{window}
        # MA 必须在 indicators 入口处预算好（见 §6.3）
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
            return Signal(action=BUY, cycle=cycle, price=float(close),
                          bar_date=pd.Timestamp(bar.name) if bar.name is not None else pd.NaT)
        if new_dir == "DOWN" and position_shares > 0:
            return Signal(action=SELL, cycle=cycle, price=float(close),
                          bar_date=pd.Timestamp(bar.name) if bar.name is not None else pd.NaT)
        return None
```

**严格 ≠** `MA20CrossDecider` 的"干净 K 线"语义——Faber 不用 low/high，只用 close 比 MA。这是 Faber 原版规则。

### 6.2 注册

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

### 6.3 月线 MA10 数据准备

`data_loader._attach_ma20` 当前只算 MA20（默认）。Faber 需要 MA10。两条路：

**方案 A（推荐）**：让 `engine.run_with_strategy` 在入口处按需预算 MA。即：
- `Strategy.decider` 暴露 `required_indicators: list[(cycle, col_name, window)]` 接口（可选属性）
- engine 在跑前对 `data.weekly / monthly` 算缺失的 MA 列

**方案 B**（保守）：在 `data_loader.py:_attach_ma_full` 改成同时算 MA10 / MA20 / MA60 等所有可能用到的窗口
- 缺点：浪费、随策略增多无限膨胀

**选 A**：`FaberMonthlyMaDecider` 暴露 `required_indicators = (("M", "ma10", 10),)`。`engine.run_with_strategy` 在主循环外预算所需 MA 列附在 `data.monthly` 上。

代码：
```python
# protocol.py: Decider Protocol 加默认值
@runtime_checkable
class Decider(Protocol):
    name: str
    required_indicators: Tuple[Tuple[str, str, int], ...] = ()  # (cycle, col_name, window) 列表，默认空 = 不需额外指标
    def decide(self, *, cycle, bar, position_shares) -> Optional[Signal]: ...

# engine.py 新增 helper
def _ensure_indicators(data: IndexData, requirements) -> None:
    """按 decider.required_indicators 在 data.{daily,weekly,monthly} 上加 MA 列。"""
    for cycle, col_name, window in requirements:
        target_df = {"D": data.daily, "W": data.weekly, "M": data.monthly}[cycle]
        if col_name in target_df.columns:
            continue
        target_df[col_name] = compute_ma(target_df["close"], window=window)
```

`run_with_strategy` 入口处调一次：
```python
_ensure_indicators(data, getattr(strategy.decider, "required_indicators", ()))
```

`getattr(..., default=())` 保证旧 Decider（`MA20CrossDecider` / `BearTrendFilter`）即使没暴露这个属性也能 work——向后兼容。Protocol 默认 `()` 也保证显式实现的新类不报错。

`MA20CrossDecider` 默认 `required_indicators = ()` —— 它依赖的 `ma20` 列已由 `data_loader._attach_ma20` 预算好，不需要在 engine 入口再算。**走旧路径行为零变化。**

## 7. 报告改造：N 策略对比

`compare_report.py` 改 `render_portfolio_table` 接受 `Sequence[Tuple[str, list[WindowResult]]]`，长度 ≥ 2：

```python
def render_portfolio_table(strategies: Sequence[Tuple[str, list]]) -> str:
    """N 策略对比，每窗口 N+1 行（N 策略 + Δ 第 i 个 vs 第一个）。"""
    if len(strategies) < 2:
        raise ValueError("portfolio table requires ≥ 2 strategies")
    base_name, base_windows = strategies[0]
    n_windows = len(base_windows)
    for name, win in strategies[1:]:
        if len(win) != n_windows:
            raise ValueError(f"strategy {name} has {len(win)} windows, expected {n_windows}")
    
    lines = ["| 时间窗 | 策略 | 总 CAGR | 最大回撤 | 总收益 |", "|---|---|---|---|---|"]
    for w_idx in range(n_windows):
        years = base_windows[w_idx].window_years
        lines.append(f"| {years} 年 | {base_name} | {_fmt_pct(base_windows[w_idx].cagr)} | {_fmt_pct(base_windows[w_idx].max_drawdown)} | {_fmt_pct(base_windows[w_idx].total_return, signed=True)} |")
        for name, windows in strategies[1:]:
            wr = windows[w_idx]
            lines.append(f"| {years} 年 | {name} | {_fmt_pct(wr.cagr)} | {_fmt_pct(wr.max_drawdown)} | {_fmt_pct(wr.total_return, signed=True)} |")
            lines.append(f"| {years} 年 | Δ ({name} − {base_name}) | {_fmt_pct(wr.cagr - base_windows[w_idx].cagr, signed=True)} | {_fmt_pct(wr.max_drawdown - base_windows[w_idx].max_drawdown, signed=True)} | {_fmt_pct(wr.total_return - base_windows[w_idx].total_return, signed=True)} |")
    return "\n".join(lines)
```

`render_per_index_diff_table` 同理改成接受 N 策略，每个非 base 策略输出一份子表。

`write_compare_report` 入口改：

```python
def write_compare_report(results_by_strategy: Dict[str, tuple], windows, output_dir) -> Path:
    names = list(results_by_strategy.keys())
    if len(names) < 2:
        raise ValueError(f"compare expects ≥ 2 strategies")
    # 第一个策略作为对照基线
    ...
```

CLI `--compare A,B,C,D` 接受任意多策略名（用逗号分隔），按顺序传入，第一个作为基线。

报告文件命名：`{date}-compare-{base}-vs-{rest_joined_by_dash}.md`。如 `2026-05-10-compare-v9-baseline-vs-v9.3-bear-faber-gtaa.md`。

## 8. 验收标准

### 8.1 隔离不变量（最关键）

- `git diff db1dc13..HEAD -- scripts/quant/ scripts/main.py docs/` = 空
- `pytest scripts/backtest/test_*.py` 全部 PASS（含原 44 个测试 + 新增）
- `python -m scripts.backtest.run --strategy v9-baseline --universe v9 --windows 3,5,8,10` 数值与 `agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-v9universe.md` 第三章 v9-baseline 行**逐字一致**（即 v9-baseline 在新框架下数值零变化）
- `python -m scripts.backtest.run --compare v9-baseline,v9.3-bear --universe v9` 输出组合层数值与同份 v9universe 报告逐字一致
- `python -m scripts.backtest.run --compare v9-baseline,v9.3-bear --universe main-online` 输出组合层数值与 `agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-mainonline.md` 第三章逐字一致

### 8.2 新功能验收

- `python -m scripts.backtest.run --list` 含 `faber-gtaa` 一行
- `python -m scripts.backtest.run --strategy faber-gtaa --universe combined-27 --windows 3,5,8,10` 跑通，4 个窗口数据合理（CAGR ≥ 0、MaxDD ≤ 0）
- `python -m scripts.backtest.run --compare v9-baseline,v9.3-bear,faber-gtaa --universe combined-27 --windows 3,5,8,10` 出报告，组合层 N=3 行 + Δ 行齐全
- 报告写入 `agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-faber-gtaa.md`

### 8.3 单测（最少）

- `test_indicators.py` 新增：`compute_ma(window=10)` 边界（已被现有 compute_ma 测试覆盖，无需新写）
- `test_strategy_builtin.py` 新增：`TestFaberMonthlyMaDecider`（5-7 个边界用例）+ `test_faber_gtaa_registered`
- `test_strategy_engine.py` 新增：`test_run_equal_weight_*`（2-3 个集成测试）
- `test_compare_report.py` 修改：`render_portfolio_table` 现有 2 策略测试不变，加 1 个 N=3 策略测试

## 9. 测试范围

完整 pytest 套件：

```bash
pytest scripts/backtest/test_indicators.py \
       scripts/backtest/test_strategy_registry.py \
       scripts/backtest/test_strategy_builtin.py \
       scripts/backtest/test_strategy_engine.py \
       scripts/backtest/test_compare_report.py
```

预期数：现有 44 个 + 新增 ~12 个 = ~56 个，全 PASS。

## 10. 报告内容（B Faber 周期完成后）

报告文件：`agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-faber-gtaa.md`

需含：

1. **简介**：universe = combined-27，时间窗 3/5/8/10
2. **三策略组合层对比表**（baseline / bear / faber 三行 + Δ bear、Δ faber 两行 per 窗口）
3. **分指数差异表**：Δ faber − baseline，列 |ΔCAGR|≥1pp 或 |ΔMaxDD|≥2pp 的指数
4. **Filter 命中**：N/A（faber 无 filter）
5. **中文解读**：
   - 一句话结论（faber 是赢还是输）
   - 与 bear 对比（这次"提收益"路线 vs 之前"加 filter"路线效果对比）
   - 适合什么 universe 子集
   - 后续可调方向

## 11. 关键不变量

- `scripts/quant/` 任何文件本周期不修改
- `scripts/backtest/{indicators,strategies,signal,data_loader,engine,window_engine}.py` 在 cycle-calmar 路径上行为零变化
- `Strategy(name=..., decider=..., filters=..., cycles=...)` 旧调用形式仍 work（aggregator 默认 cycle-calmar）
- v9-baseline / v9.3-bear 在 v9 universe / main-online universe 上的数值与现有报告逐字一致

## 12. 风险与权衡

- **`Strategy.aggregator` 字段加在末尾 + 默认值** ：dataclass 兼容，但若未来重构有人改字段顺序会破坏。**对策**：所有 Strategy(...) 构造保持 keyword 形式，positional 严禁。
- **`required_indicators` 协议是非强制属性**（可选 attr）：Decider 不暴露则默认空 list。新 Decider 都该暴露。**对策**：在 Protocol 文档里说明，code review 把关。
- **`combined-27` universe 含数据源差异大的标的**（A 股 vs BTC vs XAG）：跨日历对齐问题、商品 5×24 vs A 股 5×4h 的微妙差异。**对策**：组合层用日 K 对齐（每个交易日各自独立汇总），跨指数日历差异由 daily.index 自然吸收。

## 13. 不在范围

- **C Donchian** 实施（下一周期）
- **A Dual Momentum + cross-sectional-topk aggregator**（下下周期）
- v9.3-bear 参数变体调优（已证明方向反，弃）
- 生产 `scripts/quant/` 任何修改
- 前端 `docs/` 任何修改
