# scripts/backtest/ — MA20 趋势策略回测模块

> 完全独立的离线回测系统，**不参与生产链路**（生产指标计算用 `scripts/calculator.py`）。
>
> 所有产出在 `docs/agents/backtest/`。

## 设计原则

1. **不污染生产**：从不修改 `scripts/main.py` / `scripts/data_fetcher.py` 等核心文件。新增数据源（如 THS 行业、日经225）通过 `data_loader.py` 内本地分支处理
2. **数据终点固定**：`DATA_END_DATE = 2026-04-24`（见 `data_loader.py`），缓存永久有效
3. **缓存优先**：所有数据走 `cache.py`（pickle，stdlib），首次拉取后命中 ≤ 10ms
4. **不预设门槛**：先看分布再定阈值（V5/V6 的 σ ≥ 28% 是基于 90 行业实测中位数后选的）

## 核心策略

**"干净 K 线方向状态机"**：
- 干净-上：`low > MA20`（K 线整根在 MA20 上方）
- 干净-下：`high < MA20`
- 触碰：`low ≤ MA20 ≤ high`（哑元，方向状态不变）
- 方向翻转 → 交易：UP→BUY（仅当空仓），DOWN→SELL（仅当持仓）
- 三个独立时间维度：D（日）/ W（周）/ M（月）

## 文件结构

| 文件 | 职责 |
|---|---|
| `cache.py` | 本地 pickle 缓存（`source_code_enddate.pkl`） |
| `data_loader.py` | 拉数据 + 重采样 D/W/M + 计算 MA20，集成 cache |
| `signal.py` | `classify_bar` 纯函数 + `DirectionState` 状态机 |
| `strategies.py` | D / W / M 单周期 Bucket 配置 |
| `engine.py` | 主循环：tick 驱动、资金记账、指标计算（CAGR/回撤/胜率） |
| `reporter.py` | 纯渲染：Markdown + Calmar 权重分配（V4.1） |
| `window_engine.py` | 多窗口（3/5/8/10 年）组合聚合 |
| `index_registry.py` | V4 精选 20 指数注册表（手工维护） |
| `v5_registry.py` | V5 同花顺一级行业注册表（动态从 AkShare 拉） |
| `v5_screener.py` | 单行业 21 项指标计算（σ/alpha/Calmar 等） |
| `test_signal_manual.py` | 状态机 9 个边界用例手动测试 |
| `run_backtest.py` | V4.1 CLI（`config.yaml` 全量 27 指数） |
| `run_windows.py` | V4.2 CLI（多窗口，剔除 BTC） |
| `run_v5.py` | V5 CLI（90 个 THS 行业 → 4 排行榜 + 精选 Top 20） |
| `run_v6.py` | V6 CLI（精选 20 行业 × 多窗口） |
| `run_v6_friction.py` | V6 + 万一免五磨损扣减 |

## 迭代史（V1-V6）

| 版本 | 核心动作 | 关键发现 |
|---|---|---|
| **V1** | 三策略各 1/3，27 指数（config.yaml）| 大盘宽基策略效果差（B&H 大幅跑赢）|
| **V2** | D/W/M 拆成单周期独立策略 | 中证500 D 策略 +115%（10年） |
| **V2.2** | 扩到 27 个完整覆盖 | 强周期+成长板块 D 策略大胜，宽基拖后腿 |
| **V3** | 中证全量 α 过滤 373 → 跑通 151 | 70% 指数策略跑赢 B&H，但 D 仅占 50%（被宽基稀释）|
| **V4** | 精选 20 指数（宽基+板块+港股+海外）| 仍含 7 个宽基稀释，CAGR 6-9% |
| **V4.1** | Calmar 权重在 D/W/M 间分配 | 内部分配优化 |
| **V4.2** | 多窗口（3/5/8/10 年）+ 剔除 BTC | 真实 CAGR 仅 4-7%（扣磨损后），性价比低 |
| **认知拐点** | "策略是高波动板块的放大器，不是宽基的引擎" |  |
| **V5** | 转向 THS 一级行业 90 个全量筛选 | D 在 81% 行业最强，避开宽基 |
| **V5 Tiny** | 硬门槛筛选精选 20 个甜点行业 | σ ≥ 28% + alpha ≥ +50% + Calmar ≥ 0.25 |
| **V6** | 20 行业 × 多窗口 + Calmar 权重 | **CAGR 12-19%（vs V4.2 6-9%，翻倍）** |
| **V6 + 磨损** | 万一免五账户扣减成本 | **净 CAGR 18-19%** 仍 > V4.2 翻倍 |

## 关键产出文件

```
docs/agents/backtest/
├── conclusion.md        # V4.2 多窗口结论（剔除 BTC，16 指数）
├── v5-result.md         # V5 90 行业 4 维排行榜
├── v5-summary.md        # V5 运行清单 + 失败清单 + 全数据表
├── v5-tiny-result.md    # V5 精选 20 行业（用户最终选定池）
├── v6-sector-result.md  # V6 20 行业多窗口（毛 CAGR）
└── v6-friction-result.md # V6 + 万一免五磨损（净 CAGR）

docs/agents/v5-plan.md   # V5 实施计划（517 行详细规划）
docs/agents/ma20-backtest-plan.md # V1-V4 早期 plan + 4 轮 codex review
```

## 怎么跑

```bash
source venv/bin/activate

# V1-V4 系列（保留向后兼容）
python -m scripts.backtest.run_backtest      # V4.1 全量
python -m scripts.backtest.run_windows       # V4.2 多窗口

# V5/V6 系列（推荐使用）
python -m scripts.backtest.run_v5            # 90 行业筛选
python -m scripts.backtest.run_v6            # 精选 20 行业 × 多窗口
python -m scripts.backtest.run_v6_friction   # 加万一免五扣减
```

**首次跑** ~5 分钟（数据拉取），**之后** ~10 秒（缓存命中）。

如需更新到新数据终点：改 `data_loader.py` 的 `DATA_END_DATE`，删 `.cache/` 目录，重跑。

## 当前最优配置（V6 净 CAGR 18-19%）

20 个 THS 一级行业（v5-tiny-result.md），每行业 $10k，按 Calmar 权重在 D/W/M 间分配：

- 新能源链 6：光伏设备/风电设备/电池/电网设备/电机/其他电源设备
- 金属资源 3：能源金属/小金属/工业金属
- 医疗 2：医疗服务/医疗器械
- 军工 2：军工电子/军工装备
- 机械 2：通用设备/自动化设备
- 大消费 1：白酒
- 通信 1：通信设备
- 汽车 1：汽车整车
- 公用 1：电力（强制纳入，σ 偏低但策略适用）
- 环保 1：环保设备

D 策略主导（16/20 = 80%），M 策略 3 个，W 策略 0 个。

## 与生产链路关系

| 维度 | 生产 (`scripts/main.py` 等) | 回测 (`scripts/backtest/`) |
|---|---|---|
| 信号 | 收盘价 vs MA20（YES/NO，敏感）| 干净 K 线方向状态（过滤震荡）|
| 数据 | 实时 800 天 | 缓存 17 年（终点 2026-04-24）|
| 用途 | 每日推送趋势状态 | 离线回测策略性能 |
| 修改 | 严禁回测代码影响 | 自由迭代 |
