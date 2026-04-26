# MA20 趋势策略回测计划

> 目标：用历史数据验证"干净 K 线方向翻转"策略在中证500 上的 10 年收益表现，与指数 Buy & Hold 对比。
>
> 产出：独立回测模块 `scripts/backtest/` + 1 份 Markdown 回测报告。
>
> 状态：V2 修订（2026-04-24）—— 移除预热期和首日特例，改为 D/W/M 三个单周期独立策略。

---

## 1. 背景与动机（前因）

### 1.1 当前系统

本项目（`scripts/main.py` 生产链路）只做**实时状态展示**：每日早间获取前一交易日行情，计算各指数相对 MA20 的状态（YES/NO）、偏离率、大周期状态等，生成首页和归档页。**不做任何收益回测**。

核心判定在 `scripts/calculator.py:30-43`：

```python
def calculate_status(current_price, ma20):
    return "YES" if current_price >= ma20 else "NO"
```

这是纯 **close vs MA20** 的二元判定。每次翻转都是一次"闪烁"。

### 1.2 问题

用户在使用系统过程中产生了一个**策略假设**需要量化验证：

> 如果我按照 YES/NO 翻转信号来交易，过去 10 年能赚多少？

但直接用现有 YES/NO 会有两个严重缺陷：

1. **过度敏感**：close 在 MA20 附近小幅震荡时会反复触发假信号
2. **只看 close 忽略日内波动**：日内穿越 MA20 的 K 线和完全远离 MA20 的 K 线被同等对待

### 1.3 方法改进（策略核心）

用户提出的改进：**只信任"干净 K 线"的方向信号**。

- 一根 K 线如果**整根都在 MA20 上方**（`low > MA20`）→ 明确上升方向
- 一根 K 线如果**整根都在 MA20 下方**（`high < MA20`）→ 明确下跌方向
- 一根 K 线如果**穿越或触碰 MA20**（`low ≤ MA20 ≤ high`）→ 方向不明，忽略

**方向状态机**：记录最近一根干净 K 线的方向。方向翻转才触发交易，同方向延续则持有不动。

这个改进本质上是**用 K 线的 high/low 作为方向确认的过滤器**，大幅减少震荡期的假信号。

### 1.4 本次任务的边界

**做什么**：
- 实现回测引擎（纯离线，不接入生产链路）
- 在 3 个指数上跑 10 年历史
- 对比三种时间周期组合（日+周+月 / 周+月 / 仅周）
- 与指数 Buy & Hold 对比
- 输出 Markdown 报表

**不做什么**（YAGNI）：
- 不接入生产实时信号
- 不做组合回测（多指数共享资金池）
- 不做做空
- 不考虑交易成本（首版零摩擦）
- 不做参数优化（MA 周期、K 线粒度等全部固定）
- 不渲染图表（仅 Markdown 表格）

---

## 2. 策略定义（完整规范）

### 2.1 信号算法

对**任一时间维度**（日/周/月）的 K 线：

```python
def classify_bar(bar):
    """返回 'UP' / 'DOWN' / None"""
    if bar.low > bar.ma20:
        return "UP"
    if bar.high < bar.ma20:
        return "DOWN"
    return None  # 触碰，哑元
```

**边界约定**（严格）：
- 干净-上：`low > ma20`（严格大于）
- 干净-下：`high < ma20`（严格小于）
- 触碰：`low ≤ ma20 ≤ high`（含边界，`low == ma20` 或 `high == ma20` 也算触碰）

**边界示例**（防止实现者误解）：

| K 线 OHLC | MA20 | 判定 |
|-----------|------|------|
| L=100, H=105 | 99 | 干净-上（MA20 < L） |
| L=100, H=105 | 100 | 触碰（MA20 == L） |
| L=100, H=105 | 102 | 触碰（L < MA20 < H） |
| L=100, H=105 | 105 | 触碰（MA20 == H） |
| L=100, H=105 | 106 | 干净-下（MA20 > H） |

### 2.2 方向状态机

每个时间维度独立维护一个状态机：

```python
state = None  # 初始无方向
on each bar close:
    new_dir = classify_bar(bar)
    if new_dir is None:
        continue  # 触碰 → 状态不变
    if new_dir == state:
        continue  # 同方向 → 持有
    
    # 方向翻转（含首次从 None 初始化）
    old = state
    state = new_dir
    
    if old is None:
        if new_dir == "UP":
            trigger_buy()
        # 首次就 DOWN → 不做空（保持现金）
    else:
        if new_dir == "UP":
            trigger_buy()
        else:
            trigger_sell()
```

**为什么这样设计**：
- 只做多（用户选项 X）：DOWN 只平仓不做空，匹配 A 股散户实际能力
- 首次 UP 直接买入：符合"空仓新手等第一个明确上升信号"的真实直觉，**与交易软件图表上看到的开仓点对齐**
- 触碰不影响状态：避免震荡区间频繁被"重置"状态
- **V2 修订**：移除了原 §2.2.1 预热期和 §2.2.2 首日特例。原因：预热+首日特例会在 `evaluation_start` 当天基于"历史遗留的 UP 状态"立即追高买入，这与交易软件的直觉（只在看得见的翻转点开仓）不符。现在回测从 MA20 就绪日开始，state=None 起步，第一根干净 K 线才触发信号。

### 2.2.1 显式前置条件（V2 新增）

用户明确约束：

1. **BUY 前置条件**：该桶当前必须空仓（`bucket.shares == 0`）
2. **SELL 前置条件**：该桶必须有过一次 BUY 且目前仍持仓（`bucket.shares > 0`）

代码必须显式检查这两个条件，任何一个不满足就不交易（不是静默忽略，而是记录到日志便于调试）。

### 2.3 MA20 的时间维度

每个时间维度的 MA20 都是**该维度收盘价的 20 期移动平均**，**不是跨维度共享**：

| 维度 | MA20 计算 | K 线 OHLC |
|------|-----------|-----------|
| 日线 | 20 个日收盘价平均 | 当日 OHLC |
| 周线 | 20 个周收盘价平均 | 周内 O=周一开，H=最高，L=最低，C=周五收 |
| 月线 | 20 个月收盘价平均 | 月内 O=月初开，H=最高，L=最低，C=月末收 |

**为什么**：这是技术分析的标准做法，和现有 `calculator.py::_period_ma20_status` 的逻辑保持一致，不引入新概念。

### 2.4 信号触发时机

| 维度 | 触发频率 | 触发日 |
|------|----------|--------|
| 日线 | 每个交易日 | 当日收盘 |
| 周线 | 每周一次 | 该周最后一个交易日收盘（通常周五） |
| 月线 | 每月一次 | 该月最后一个交易日收盘 |

月末最后一个交易日可能**同时触发**日/周/月三个信号，每个桶独立处理，无冲突。

### 2.5 时序合同（避免 look-ahead bias）

回测的**事件时间线必须严格单向**：

```
T 日 15:00 收盘
  ├─ [Step 1] 使用 T 日及之前所有数据计算 MA20、clean_dir
  ├─ [Step 2] 根据新的 clean_dir 更新方向状态
  ├─ [Step 3] 若方向翻转 → 生成交易指令
  ├─ [Step 4] 在 T 日收盘价上执行成交（假设尾盘集合竞价能力）
  └─ [Step 5] 按 T 日收盘价 mark-to-market 记录净值
```

**关键规则**：
- Step 1 的计算**不得使用 T 日之后的任何数据**（look-ahead bias）
- Step 4 的成交价 == 当日收盘价，这是用户选择的简化模型（选项 I）
- 假设前提：在 A 股实际交易中，相当于在 14:57-15:00 尾盘集合竞价阶段下单。这是个**乐观假设**（实际会有滑点），报告必须在开头显著位置声明该假设，避免读者误判

**禁止**：
- 不得用 T+1 的数据计算 T 日的指标
- 不得以"下一根 K 线的开盘价"执行（这是另一种口径，本次回测不采用）

---

## 3. 资金与交易规则

### 3.1 本金与分配（V2 方案：单周期独立策略）

| 策略 | 桶配置 | 初始资金 |
|------|-------|---------|
| **D**（仅日线） | 1 个日线桶 | $10,000 |
| **W**（仅周线） | 1 个周线桶 | $10,000 |
| **M**（仅月线） | 1 个月线桶 | $10,000 |

**为什么拆成单周期**：
- 用户目标是**观察每个时间周期独立的交易表现**，混合策略（DWM/WM）会掩盖单周期的信号质量
- 每个策略用相同的 $10k 本金，可直接对比单周期收益
- 每个策略内部只有一个桶，交易日志清晰可核对

### 3.2 交易规则

- **只做多**：BUY 时用全部桶内现金换份额；SELL 时卖光份额回现金
- **空仓起步**：`evaluation_start` 当天所有桶 shares=0, cash=capital
- **成交价**：信号触发的 K 线**收盘价**（假设有尾盘成交能力）
- **零摩擦**：无佣金、无印花税、无滑点
- **份额支持小数**：无整手/整股约束（回测常规简化）
- **显式前置条件（V2 新增，见 §2.2.1）**：
  - BUY：`bucket.shares == 0` 才允许
  - SELL：`bucket.shares > 0` 才允许（即桶内有过一次 BUY 且未平仓）

### 3.3 桶级状态机示例

```
初始：  cash=10000, shares=0
UP 信号 @ close=100:  shares=100, cash=0
持有中...
DOWN 信号 @ close=120:  cash=12000, shares=0（赚了 $2000）
持有现金...
UP 信号 @ close=110:  shares=109.09, cash=0
```

每个桶独立，互不影响。

---

## 4. 回测范围

### 4.1 指数列表

| 名称 | 代码 | 数据源 | 备注 |
|------|------|--------|------|
| 中证500 | `000905` | cs_index | major_indices 已有 |

**V2 变更**：仅保留中证500 做单点验证。V1 曾包含沪深300 和创业板50，本轮移除以聚焦信号正确性。若验证通过可再扩展。

**样本选择偏差声明**（必须写入报告头部）：

本回测仅覆盖 1 个 A 股宽基指数，样本极小，结论**不可外推**。当前目的是验证信号和交易逻辑的正确性，不是验证策略的普适性。

### 4.2 时间窗口（V2 简化：无预热期）

#### 4.2.1 关键日期定义

| 变量 | 定义 |
|------|------|
| `fetch_start` | 数据拉取起点 |
| `ma20_ready_date` | 各周期 MA20 首个非空值日期（按周期不同） |
| `evaluation_start` | 评估起算日：`max(D/W/M 的 ma20_ready_date)`，即所有周期的 MA20 都就绪 |
| `evaluation_end` | 评估终点：数据最后一天 |

#### 4.2.2 计算规则（V2 修订）

1. 回测请求数据长度：`days=6200`（约 17 年）
2. 每个周期的 MA20 在连续 20 根 K 线之后产生首个非空值
3. **没有预热期**：state 起始为 `None`，评估区间内第一根干净 K 线才初始化状态并触发信号
4. `evaluation_start` = max(D/W/M 的 `ma20_ready_date`)（通常由月线主导，月线 MA20 ≈ 数据开始后 20 个月）
5. 若某指数历史数据不足，`fetch_start` = 最早可得日期，`evaluation_start` 相应后延
6. **三个策略和 B&H 基准共用同一个 `evaluation_start`**（保证可比性）

**V2 变更说明**：移除了 V1 的 60 月预热期和 §2.2.2 首日特例。原因是这些机制会导致 `evaluation_start` 当天基于"历史遗留的 UP 状态"立即追高买入，与交易软件图表上看到的开仓点（真实的方向翻转）不一致。

#### 4.2.3 数据拉取实现约束（不触碰生产链路）

- 当前 `DataFetcher.fetch_index(code, source, days=N)` 接受 days 参数，`scripts/main.py` 调用时传 `days≈800`
- **回测代码调用时传 `days=6200`**（约 17 年），**不得修改 DataFetcher 的默认值**，**不得修改 `scripts/main.py` 的调用参数**
- 验收条目增加：生产链路行为不变（见 §10）

---

## 5. 架构

### 5.1 目录结构

```
scripts/backtest/
├── __init__.py
├── data_loader.py       # 只负责：拉取日线 + 重采样周/月 OHLC + 计算 MA20
├── signal.py            # 只负责：classify_bar + DirectionState 状态机
├── strategies.py        # 只负责：D / W / M 三种单周期 Bucket 配置
├── engine.py            # 只负责：事件调度 + 资金记账 + 净值曲线
├── reporter.py          # 只负责：自然年切片 + Markdown 渲染
├── test_signal_manual.py  # 手动测试脚本（效仿现有 scripts/test_csindex.py 风格）
└── run_backtest.py      # CLI 入口：python -m scripts.backtest.run_backtest

docs/agents/backtest/        # 内部评审文档（不发布到站点）
├── 000300.md
├── 000905.md
├── 399673.md
└── summary.md
```

**模块职责边界（严格单一职责，避免 DataLoader 与 Signal 重复实现）**：

| 模块 | 输入 | 输出 | 禁止 |
|------|------|------|------|
| DataLoader | 指数代码 | 标准化 OHLC + MA20 的 `DataFrame` | **不得**计算 clean_dir / 状态 / 信号 |
| Signal | Bar + 当前 state | 新 state + 动作（BUY/SELL/None） | **不得**访问历史数据或 MA20 之外的数据 |
| Engine | DataLoader 结果 + Strategy 配置 | `BacktestResult`（含所有计算好的指标） | **不得**重新判定方向 |
| Reporter | `BacktestResult` 列表 | Markdown 文件 | **不得**做任何数值计算，只做字符串格式化 |

**Engine / Reporter 边界明确**：Engine 负责按 §5.4 指标定义表计算所有数值（年度收益率、CAGR、最大回撤、胜率等），并写入 `BacktestResult`；Reporter 只读取 `BacktestResult`，调用 `f-string` 渲染 Markdown。这样保证指标口径只有一处实现。

**输出路径说明**：
- 报告归档在 `docs/agents/backtest/`（遵循项目 CLAUDE.md "文档放 docs/agents/" 规则）
- 这是内部评审/草拟产物，**不是**对外发布到 GitHub Pages 站点的内容
- 未来若要对外展示，另起任务从 `docs/agents/backtest/` 复制到 `docs/backtest/`

### 5.2 数据流

```
DataFetcher (复用现有 scripts/data_fetcher.py)
        │  调用端传 days=6200（约 17 年），不改默认值
        ▼
DataLoader（每个指数只拉一次、只重采样一次）
  - 日线：fetch_index() 返回
  - 周线：groupby(pd.PeriodIndex(date, freq='W-FRI'))，取组内 max(date)作为 bar_date
           agg = {open:first, high:max, low:min, close:last}
  - 月线：groupby(pd.PeriodIndex(date, freq='M'))，取组内 max(date)作为 bar_date
           agg 同上
  - 每个 DataFrame 只预计算 ma20 列
  - 不计算 clean_dir（Signal 模块职责）
        │
        ▼
Engine（共享 DataLoader 结果跑 3 个策略，节省 I/O）
  for strategy in [D, W, M]:
      for date in daily_trading_dates[evaluation_start:]:
          update_daily_state(daily_bars[date])  # 调用 Signal 模块
          if date == week_end: update_weekly_state(...)
          if date == month_end: update_monthly_state(...)
          equity[date] = mark_to_market(close[date])
      # 评估结束后，按 §5.4 计算所有指标（年度收益率、CAGR、回撤、胜率等）
      # 写入 BacktestResult.yearly_returns/annualized_return/max_drawdown/win_rate
        │
        ▼
Reporter（纯渲染，无任何数值计算）
  - 读取 BacktestResult 列表
  - 用 f-string 渲染 Markdown 表格
  - 写入 docs/agents/backtest/{code}.md
```

**重采样口径锁定（强制，不得替换实现）**：

- 周线分组键：`pd.PeriodIndex(df['date'], freq='W-FRI')`
  - 每个周期内的"bar_date" = 组内最大交易日（通常是周五，节假日则前推）
  - 适配 A 股周一到周五的交易日历和节假日
- 月线分组键：`pd.PeriodIndex(df['date'], freq='M')`
  - bar_date = 组内最大交易日（通常是月末最后交易日）
- **禁止**使用 `df.resample('W-SUN')` 或 `df.resample('ME')`——这些基于日历周/月，会在节假日错位

### 5.3 核心数据结构

```python
@dataclass
class Bar:
    date: date
    open: float
    high: float
    low: float
    close: float
    ma20: Optional[float]  # None if insufficient history
    clean_dir: Optional[str]  # "UP" / "DOWN" / None

@dataclass
class Bucket:
    timeframe: str  # "daily" / "weekly" / "monthly"
    capital: float  # 桶初始资金
    shares: float = 0.0
    cash: float = 0.0  # 初始 = capital
    state: Optional[str] = None  # 方向状态

@dataclass
class Trade:
    date: date
    timeframe: str
    action: str  # "BUY" / "SELL"
    price: float
    shares: float
    cash_change: float

@dataclass
class BacktestResult:
    index_code: str
    strategy_name: str  # "D" / "W" / "M"
    evaluation_start: date
    evaluation_end: date
    equity_curve: pd.Series  # indexed by date
    trades: List[Trade]
    yearly_returns: Dict[int, float]  # year → return %
    total_return: float
    annualized_return: float
    max_drawdown: float
    win_rate: float
    open_position_value: float  # 末日未平仓市值
```

### 5.4 指标数学定义表（强制口径，Engine 按此计算，Reporter 只渲染）

| 指标 | 公式 | 样本范围 | 四舍五入 | 说明 |
|------|------|----------|----------|------|
| 年度收益率 | `(equity[year_end] / equity[year_start] - 1) × 100%` | 每个自然年 | 2 位小数 | year_end/year_start 取该年实际首末交易日净值 |
| 总收益率 | `(equity[eval_end] / equity[eval_start] - 1) × 100%` | 评估区间 | 2 位小数 | — |
| 年化收益率 (CAGR) | `(equity[end]/equity[start]) ** (365.25/days) - 1` | 评估区间 | 2 位小数 | 按日历天数而非交易日 |
| 最大回撤 | `min((equity[t] / cummax(equity[0:t+1]) - 1) for t)` × 100% | 评估区间 | 2 位小数 | 基于日净值序列 |
| 交易次数 | `count(trades where action == 'SELL')` | 评估区间 | 整数 | 只数完整交易对，每个 BUY-SELL 计为一次 |
| 胜率 | `count(profitable closed pairs) / count(closed pairs) × 100%` | 评估区间 | 2 位小数 | "完整 BUY-SELL 对"才算；末笔未平仓不计 |
| 未实现盈亏 | `shares × close[end] - 最后一次 BUY 的 cost` | 每个桶 | 2 位小数 | 报告单独列出，不并入胜率 |

**末笔未平仓处理**：
- 评估终点 `equity[end]` 按 mark-to-market 计入（即用最后一天收盘价乘以持仓份额）
- 未平仓的 BUY 不参与胜率计算，但单独在报告中列明"未实现盈亏"
- 总收益率和年化收益率**包含**未实现盈亏（因为 equity 是 MTM 口径）

---

## 6. 输出规范

单指数 Markdown 报告：

```markdown
# {指数名} ({code}) 回测报告

## 回测口径声明（必读）

- **评估起算日** (`evaluation_start`)：YYYY-MM-DD（= max D/W/M 的 MA20 就绪日）
- **评估终止日** (`evaluation_end`)：YYYY-MM-DD
- **起始资金**：$10,000 / 策略（D / W / M 各 $10,000，不共享）
- **成交价假设**：信号日收盘价（模拟 A 股尾盘集合竞价能力；乐观假设，未扣滑点）
- **交易摩擦**：0（零佣金、零印花税、零滑点）
- **状态机起步**：state=None，第一根干净 K 线触发信号（无预热、无首日特例）
- **B&H 基准**：同一 `evaluation_start` 全仓建仓（$10,000）

## 年度收益率对比（单位 %）

| 年份 | D | W | M | 指数B&H |
|------|-----|-----|-----|-----|
| 2010 | ... | ... | ... | ... |
| ... |
| **总收益** | ... | ... | ... | ... |

## 关键指标

|  | D | W | M | B&H |
|---|---|---|---|---|
| 终值 ($) | ... | ... | ... | ... |
| 年化收益 CAGR (%) | ... | ... | ... | ... |
| 最大回撤 (%) | ... | ... | ... | ... |
| 交易次数（完整对） | ... | ... | ... | - |
| 胜率 (%) | ... | ... | ... | - |
| 未实现盈亏 ($) | ... | ... | ... | - |

## 完整交易日志

每个策略独立列表（按日期升序），字段：日期、动作 BUY/SELL、成交价、份额、桶内现金、对应 K 线 High/Low/MA20（便于核对信号）
```

---

## 7. 实现步骤

**测试承载方式**（与仓库约束对齐）：项目无 pytest/unittest 套件（见 CLAUDE.md 行 48）。本计划采用与 `scripts/test_csindex.py` 同风格的**手动脚本 + 固定 I/O 样例**验证。

### Step 1 — DataLoader
- 调用 `DataFetcher.fetch_index(code, source, days=6200)`（不改默认值）
- 按 §5.2 的 `groupby(PeriodIndex)` 口径实现周/月重采样
- 计算 MA20 列

### Step 2 — Signal 模块
- `classify_bar(bar)` 纯函数
- `DirectionState` 状态机（state=None 起步，无预热）
- **验证脚本** `test_signal_manual.py`：构造固定 K 线序列
  - 用例 A：首次 UP（state=None → UP，BUY）
  - 用例 B：首次 DOWN（state=None → DOWN，无动作）
  - 用例 C：UP → 同方向 UP（无动作）
  - 用例 D：UP → 触碰 → UP（整段无动作）
  - 用例 E：UP → 触碰 → DOWN（SELL）
  - 用例 F：DOWN → UP（BUY）
- 显式前置条件（§2.2.1）：BUY 需要 shares==0，SELL 需要 shares>0

### Step 3 — Engine
- 评估循环：从 `evaluation_start` 开始，state=None 起步，执行完整状态机 + 交易
- 单指数数据只拉取一次，3 个策略（D/W/M）共享 DataLoader 结果
- **评估结束后按 §5.4 计算所有指标**
- **验证**：手工检查第一笔 BUY 对应的 K 线 high/low 确实 > MA20，与交易软件开仓点一致

### Step 4 — Reporter
- **只做字符串格式化**，禁止做任何数值计算
- 读取 `BacktestResult` 列表，用 f-string 渲染 Markdown 模板（见 §6）
- 写入 `docs/agents/backtest/{code}.md` 和 `summary.md`
- **验证**：B&H 独立计算 `shares = 30000/close[evaluation_start]; equity[t] = shares * close[t]`，与 Engine 写入 `BacktestResult` 的 B&H 列逐年对拍（验证 Engine 的计算，不验证 Reporter）

### Step 5 — CLI + 批量运行
- `python -m scripts.backtest.run_backtest`
- 1 指数（000905）× 1 次拉取 + 3 策略（D/W/M）= 3 次策略模拟
- 生成 1 份 md（`000905.md`）到 `docs/agents/backtest/`

---

## 8. 验证与风险

### 8.1 正确性验证点

1. **MA20 值**与现有 `calculator.py` 在同一日期上逐日对拍
2. **干净 K 线判定**：随机抽取 10 个触碰日和 10 个干净日人工确认
3. **状态翻转**：在一段连续触碰区间中，方向状态不应变化
4. **净值单调性**：零交易日的净值变化 = 持仓 × 当日收盘价变化，应完全匹配指数变化
5. **B&H 对照**：使用**与策略相同的 `evaluation_start`**，独立计算 `shares = 10000/close[evaluation_start]; equity[t] = shares * close[t]`，与 Engine 写入 `BacktestResult` 的 B&H 字段一致
6. **生产链路不变**：回测代码落地前后，运行 `python scripts/main.py --mode morning --mock-date 2026-01-17 --dry-run` 输出完全相同（证明未改动生产行为）
7. **V2 新增**：手工检查第一笔 BUY 的 K 线（high/low）确实在当时的 MA20 上方，与交易软件开仓点一致

### 8.2 已识别风险

1. **数据缺口**：长周期拉取可能遇到数据源返回截断或失败。对策：拉取失败直接 abort，不静默填充
2. **周/月 K 线对齐**：已在 §5.2 锁定 `groupby(PeriodIndex)` 口径，不再有歧义
3. **月末识别**：通过 `PeriodIndex` 分组自动取实际最后交易日，节假日自动前推

---

## 9. 决策汇总（Brainstorm 阶段已锁定）

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 信号类型 | 干净 K 线方向状态机 | 用户提出，过滤震荡假信号 |
| 触碰定义 | `low ≤ MA20 ≤ high`（含边界） | 用户确认严格等号算触碰 |
| 首次 DOWN 是否做空 | 否，只做多（X） | 用户选项 X，匹配 A 股实际 |
| 初始仓位 | 空仓，cash=capital（P） | 用户选项 P，模拟新手起步 |
| 回测范围（V2） | 仅中证500 单指数 | 聚焦信号正确性验证 |
| 交易摩擦 | 零（A） | 首版验证策略本身，不掺成本噪音 |
| 成交价 | 信号日收盘价（I） | 回测标准简化 |
| 仓位分配（V2） | D/W/M 三策略，各 $10k 独立 | 观察每个时间周期独立表现 |
| 年度收益公式 | `(年末净值/年初净值 - 1)×100%` | 自然年切片 |
| 输出形式 | Markdown 表格 | 早期草拟，先不做图 |
| 预热期（V2） | 无 | 匹配交易软件开仓点直觉 |
| 前置条件（V2） | BUY 要求 shares==0；SELL 要求 shares>0 | 用户显式要求 |

---

## 10. 成功标准

本计划完成的判定条件：

1. ✅ 1 份中证500 报告 `docs/agents/backtest/000905.md`：年度收益率表、关键指标表、**完整**交易日志（不截断 20 笔）
2. ✅ 手动测试脚本 `scripts/backtest/test_signal_manual.py` 7 个用例通过（含 V2 前置条件验证）
3. ✅ B&H 基准独立计算对拍一致
4. ✅ 所有回测产物在 `docs/agents/backtest/`，源码在 `scripts/backtest/`
5. ✅ 生产链路行为不变：
   - 本任务**仅修改白名单内文件**：`scripts/backtest/**`、`docs/agents/backtest/**`、`docs/agents/ma20-backtest-plan.md`、`docs/agents/reviews/**`
   - **行为验收主证据**：dry-run 前后输出完全一致
6. ✅ 第一笔 BUY 对应的 K 线 Low 严格 > 该日 MA20（即"干净-上"定义），与交易软件开仓点一致

---

## 11. 后续可能扩展（不在本计划内）

- 加入交易成本（方案 B 或 C）
- 做空版本（非 A 股市场）
- 多指数组合回测
- 参数敏感性分析（MA 周期 10/20/30/60）
- 图表渲染（equity curve + drawdown chart）
- 与生产链路打通，实时产出信号
