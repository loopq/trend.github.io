# V5 实施计划：从宽基组合转向同花顺一级行业板块筛选

> 目标：从 90 个同花顺一级行业板块中，筛选出"高波动 + 策略友好"的"甜点行业"组合，跑出比 V4.1（20 指数混合组合）显著更优的风险调整收益。
>
> 产出：缓存层 + THS 数据源 + V5 筛选引擎 + V5 结论 md。
>
> 状态：计划阶段，待批准后实施。

---

## 1. 背景与动机

### 1.1 V4.2 的真实画像（剔除 BTC 后）

| 窗口 | CAGR | 扣 2.5% 磨损后 |
|---|---|---|
| 3 年 | 9.41% | ~7% |
| 5 年 | 5.26% | ~3% |
| 8 年 | 7.83% | ~5% |
| 10 年 | 6.77% | ~4% |

性价比对小本金（20 万）实操不划算（详见 `docs/agents/backtest/v5.md` 第二三四章）。

### 1.2 V4 数据揭示的关键认知

> **策略是高波动板块的放大器，不是宽基的引擎。**

- 宽基（沪深300/中证500/上证50）：D 策略超额仅 +5%~+30%，扣磨损归零
- 高波动板块（白酒/医疗/光伏/新能车/有色/化工）：D 策略超额 **+100%~+200%**，扣磨损后仍显著正

### 1.3 为什么是同花顺一级行业

- **划分细致**：90 个一级行业（如半导体、白酒、电池、能源金属、新能源车），比中证 41 个行业更细
- **波动天然高**：行业指数 vs 宽基，方差更大，更适合趋势策略发力
- **数据覆盖完整**：测试拉取 2016-01-04 至 2026-04-24，2503 行日线 OHLC 完整
- **可投资性**：大部分主流行业都有 ETF/LOF 跟踪（半导体、白酒、新能车 等都有热门 ETF）

### 1.4 数据源限制识别

V3 全量 373 指数尝试时失败 222 个，原因主要是：
- 中证 API 对冷门 931xxx 主题指数返回空
- 反爬虫机制概率性拒绝请求

V5 的对策：
1. **缓存机制**（Part 2）：拉成功一次永久复用，失败的可手动重跑
2. **重试逻辑**：失败 ≠ 无数据，按用户原则——重试 3 次
3. **不静默剔除**：失败的行业单独列入失败清单，留给用户决策

---

## 2. 目标与非目标

### 2.1 做什么

- 加缓存层：终点固定 **2026-04-24** 收盘，缓存到本地，不重复请求
- 加 THS 行业数据源（`ths_industry`）
- 跑 90 个 THS 一级行业全量回测
- 筛选 + 排序 + 产出 V5 组合建议
- 与 V4.1 的 20 指数组合做对比

### 2.2 不做什么（YAGNI）

- 不做实时数据更新（终点 2026-04-24 是固定锚点）
- 不做更细的二级三级行业（YAGNI，先在一级层面验证策略有效性）
- 不做参数敏感性扫描（MA 周期、Calmar 公式等仍用 V4 参数）
- 不做交易成本仿真（仍假设零摩擦，磨损数字另估）
- 不改动生产链路（`scripts/main.py` 及生产指数生成）

---

## 3. 数据契约

### 3.1 数据终点（核心约束）

**所有数据拉取的 end_date 固定 = 2026-04-24（含当日收盘）**

理由：
- 当前是验证性回测，不需要每日更新
- 缓存永久有效（终点不变 → 缓存不需失效）
- 简化时间逻辑（避免"今天到底是几号"的歧义）

代码层面：
```python
DATA_END_DATE = pd.Timestamp("2026-04-24")
```

后续若想更新到新终点，只需改这个常量并清缓存。

### 3.2 THS 行业代码列表

通过 `ak.stock_board_industry_name_ths()` 动态获取，**不硬编码**（避免行业增减时维护成本）。

字段：`name`（如"半导体"）、`code`（如"881121"）

**关键实现点**：`ak.stock_board_industry_index_ths` 用 **name 作 symbol**，不是 code。要做映射。

### 3.3 数据范围

每个行业拉取 `2015-01-01` ~ `2026-04-24`：
- 2015 年起：满足 V4.1 的 ma20_ready_date 计算（月线 MA20 需 20 个月预热）
- 评估区间起点 = `2016-01-01`（与 V4.1 一致）
- 评估区间终点 = `2026-04-24`

### 3.4 数据格式（标准化后）

经 `data_loader._fetch_ths_industry` 后，统一返回：

```python
DataFrame 列：date(datetime), open, high, low, close, volume
排序：date 升序
索引：默认整数，非 date
```

与现有 `data_loader.load_index` 输出兼容。

---

## 4. 架构变更

### 4.1 新增模块

```
scripts/backtest/
├── cache.py             # 新：本地 parquet 缓存层
├── v5_registry.py       # 新：90 个 THS 行业的 IndexMeta 列表
├── v5_screener.py       # 新：跑全量回测 + 筛选逻辑
└── run_v5.py            # 新：CLI 入口

docs/agents/backtest/
├── v5-result.md         # 新：V5 完整结果（90 行业排行 + 甜点 Top 20 + 对比 V4.1）
└── (其他文件不动)

scripts/backtest/.cache/  # 新：缓存目录（git ignore）
└── ths_industry_881121_20260424.parquet  # 例
```

### 4.2 修改模块

```
scripts/backtest/data_loader.py
  - 新增 source = "ths_industry" 分支
  - 列名映射：日期/开盘价/最高价/最低价/收盘价/成交量 → date/open/high/low/close/volume
  - 集成 cache 层

.gitignore
  - 新增：scripts/backtest/.cache/
```

### 4.3 不变模块

- `engine.py` / `reporter.py` / `strategies.py` / `signal.py` / `index_registry.py`：完全不动
- `run_backtest.py` / `run_windows.py`：不动（V4.1/V4.2 仍可独立运行）
- 生产链路（`scripts/main.py` 等）：不动

---

## 5. 缓存层设计（Part 1 详解）

### 5.1 缓存键（cache key）

```python
def cache_key(source: str, code: str, end_date: pd.Timestamp) -> str:
    return f"{source}_{code}_{end_date:%Y%m%d}"
# 例：ths_industry_881121_20260424
```

### 5.2 缓存协议

```python
# scripts/backtest/cache.py

CACHE_DIR = Path(__file__).parent / ".cache"

def cached_load(meta: IndexMeta, end_date: pd.Timestamp,
                fetcher: Callable[[], pd.DataFrame]) -> Optional[pd.DataFrame]:
    """如缓存存在直接返回，否则调 fetcher 并缓存。

    fetcher 是无参数的 lambda，封装好实际的 ak.* 调用。
    """
    key = cache_key(meta.source, meta.code, end_date)
    path = CACHE_DIR / f"{key}.parquet"
    if path.exists():
        return pd.read_parquet(path)

    df = fetcher()
    if df is None or df.empty:
        return None  # 不缓存空结果（保留下次重试机会）

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return df
```

### 5.3 缓存范围

- 缓存的是**标准化后的 DataFrame**（统一列名 date/open/high/low/close/volume）
- 不缓存重采样后的周/月（这部分本来就是纯计算，cache 没意义）
- 不缓存 BacktestResult（每次跑可能改算法）

### 5.4 失败重试策略

```python
@retry_on_network_error(max_retries=3, backoff_seconds=(2, 5))
def fetch_with_retry(...):
    ...
```

复用 `data_fetcher.py` 已有的 `retry_on_network_error` 装饰器（不修改它）。

---

## 6. THS 数据源实现（Part 2 详解）

### 6.1 在 data_loader.py 加分支

```python
# data_loader.py 修改点

def _fetch_ths_industry(name: str, end_date: pd.Timestamp) -> Optional[pd.DataFrame]:
    """从 AkShare 拉同花顺一级行业历史日线。"""
    import akshare as ak
    try:
        df = ak.stock_board_industry_index_ths(
            symbol=name,
            start_date="20150101",
            end_date=end_date.strftime("%Y%m%d"),
        )
    except Exception as e:
        logger.warning("THS industry fetch failed for %s: %s", name, e)
        return None
    if df is None or df.empty:
        return None
    df = df.rename(columns={
        "日期": "date",
        "开盘价": "open",
        "最高价": "high",
        "最低价": "low",
        "收盘价": "close",
        "成交量": "volume",
    })[["date", "open", "high", "low", "close", "volume"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def load_index(meta_or_code, source=None, name=""):
    # 集成 cache：
    if source == "ths_industry":
        daily_raw = cached_load(
            meta=...,
            end_date=DATA_END_DATE,
            fetcher=lambda: _fetch_ths_industry(name, DATA_END_DATE),
        )
    elif source == "global_sina":
        ...
    else:
        # 原有逻辑（cs_index/sina_index/hk/us/spot_price/crypto）
        ...
```

### 6.2 关键陷阱

- THS API 用 **name** 作 symbol，不是 code
- 个别行业名含特殊字符（如 "种植业与林业"），AkShare 可能编码出问题——需测试

---

## 7. V5 注册表（Part 3 详解）

### 7.1 v5_registry.py

```python
# scripts/backtest/v5_registry.py

from dataclasses import dataclass
import akshare as ak

@dataclass
class IndexMeta:
    code: str
    name: str
    source: str   # "ths_industry"
    category: str # 主题分类（自动从 name 推断或留空）

def build_v5_registry() -> List[IndexMeta]:
    df = ak.stock_board_industry_name_ths()
    return [
        IndexMeta(
            code=str(row["code"]),
            name=str(row["name"]),
            source="ths_industry",
            category="THS一级行业",
        )
        for _, row in df.iterrows()
    ]
```

### 7.2 预期样本规模

- 测试时 `stock_board_industry_name_ths()` 返回 90 个
- 全部尝试拉取，预期 80+ 成功
- 失败的进 `failed.md`

---

## 8. 筛选与评分（Part 3 详解）

### 8.1 每个行业要计算的指标

```python
@dataclass
class SectorMetrics:
    code: str
    name: str
    eval_start: pd.Timestamp     # MA20 就绪日（含 min=2016-01-01）
    eval_end: pd.Timestamp       # 数据终点 2026-04-24

    # 资产层面
    annual_volatility: float     # 年化波动率
    bh_total_return: float       # B&H 总收益
    bh_cagr: float               # B&H 年化
    bh_max_drawdown: float       # B&H 最大回撤

    # D / W / M 各自
    d_total_return: float
    d_cagr: float
    d_max_drawdown: float
    d_calmar: float
    d_alpha: float               # = d_total_return - bh_total_return

    w_total_return: float
    w_cagr: float
    w_alpha: float

    m_total_return: float
    m_cagr: float
    m_alpha: float

    # 综合
    best_strategy: str           # D/W/M 哪个最强
    best_alpha: float            # max(d_alpha, w_alpha, m_alpha)
    best_calmar: float           # 最强策略的 Calmar
```

### 8.2 排行榜（不预设门槛，先看分布）

输出 v5-result.md 时按以下维度排序：

1. **波动率榜**：`annual_volatility` 降序（看分布）
2. **策略 alpha 榜**：`best_alpha` 降序
3. **风险调整榜**：`best_calmar` 降序
4. **综合甜点榜**：`best_alpha × annual_volatility / 100` 降序（高波动 × 高 alpha）

### 8.3 候选门槛建议（看分布后再定）

V5 plan 阶段**不锁死门槛**，等数据出来再定。预期门槛参考：

- σ > 30%
- best_alpha > +50%
- best_calmar > 0.5

但具体数值看实际分布——如果 90 个行业 σ 中位数 35%，那就用 30% 门槛；如果中位数 20%，那就 25%。

---

## 9. V5 结果输出（Part 4 详解）

### 9.1 v5-result.md 结构

```markdown
# V5 同花顺一级行业回测结果

> 评估区间：2016-01-01 ~ 2026-04-24（数据终点固定）
> 样本：同花顺一级行业 90 个

## 一、数据采集情况
- 总数：90
- 成功：N
- 失败：M（失败清单见末尾）

## 二、波动率分布
- σ 分布直方图（文字描述：min/p25/median/p75/max）

## 三、波动率排行（Top 30）
| 排名 | 行业 | 代码 | σ | B&H总收益 | D总收益 | D alpha |

## 四、策略 alpha 排行（Top 30）
| 排名 | 行业 | σ | D总收益 | B&H总收益 | D alpha | D Calmar |

## 五、综合甜点榜（高波动 + 高 alpha 双优 Top 20）
| 排名 | 行业 | σ | 最强策略 | best alpha | best Calmar | 推荐权重 |

## 六、推荐 V5 组合（精选 10-15 个甜点行业）
- 按相关性聚类（行业内只保留一个代表）
- 给出每个的 Calmar 权重 + 总仓位

## 七、与 V4.1 对比
- V4.1（20 指数）：CAGR 9.41%（3 年）
- V5（精选行业）：CAGR ?

## 八、失败行业清单
| 代码 | 名称 | 失败原因 |

## 九、附录：90 行业全表（按代码排序）
完整数据
```

### 9.2 命名

- **文件名**：`v5-result.md`（不污染现有 `summary.md`、`conclusion.md`、`v5.md`）
- 与 `v5.md`（V5 方向反思文档）配套：
  - `v5.md` 是"为什么要做 V5"
  - `v5-result.md` 是"V5 跑出来什么"

---

## 10. 实现步骤（按依赖顺序）

### Step 1：缓存层（独立可测）
- 创建 `scripts/backtest/cache.py`
- 单元测试（手工验证）：写 → 读 → 验证 DataFrame 一致

### Step 2：THS 数据源
- 修改 `scripts/backtest/data_loader.py` 加 `ths_industry` 分支
- 集成 cache 层
- 测试：拉一个行业（如"半导体"），验证缓存写入和复用

### Step 3：V5 注册表
- 创建 `scripts/backtest/v5_registry.py`
- 测试：能从 AkShare 拿到 90 个行业列表

### Step 4：批量拉数据 + 计算指标
- 创建 `scripts/backtest/v5_screener.py`
- 跑 90 个行业，构建 List[SectorMetrics]
- 失败重试 3 次，仍失败入 failed list

### Step 5：渲染 v5-result.md
- 4 个排行榜 + 综合甜点榜 + 失败清单
- 与 V4.1 数据对比段落

### Step 6：CLI 入口
- 创建 `scripts/backtest/run_v5.py`
- `python -m scripts.backtest.run_v5` 一键跑通

### Step 7：验证 + 提交
- 抽样 5 个行业核对开仓点（与之前方法一致）
- 生产链路 dry-run 验证不变
- 提交

---

## 11. 验证标准

### 11.1 数据正确性

- [ ] 拉到的某个行业 K 线（如半导体）与 AkShare 直接调用结果一致
- [ ] 缓存写入 → 读出 → 内容字节一致
- [ ] 同一行业第二次拉取走 cache 路径（zero AkShare call）

### 11.2 指标正确性

- [ ] 抽样 3 个行业的 D 策略首笔 BUY 满足"干净-上"定义（low > MA20）
- [ ] 抽样 3 个行业的 B&H 与独立计算结果一致
- [ ] σ（年化波动率）= 日 log 收益率标准差 × √252

### 11.3 工程

- [ ] 90 个行业全跑完后，**第二次**跑同样 90 个行业的总耗时 < 30 秒（全 cache 命中）
- [ ] 第一次拉取因网络/反爬失败的行业，重试机制能补救
- [ ] 生产链路 dry-run 输出与回测代码部署前**完全一致**

---

## 12. 风险与对策

| 风险 | 概率 | 对策 |
|---|---|---|
| THS API 反爬阻断部分请求 | 中 | 重试 3 次 + cache + 失败清单 |
| 行业名特殊字符（如"种植业与林业"）API 不支持 | 低 | 测试时挨个排查；失败的标注后跳过 |
| 缓存 parquet 兼容性（pyarrow 版本） | 低 | 失败回退到 pickle |
| 90 行业内有大量低波动（金融保险类） | 中 | 不预设门槛，按分布筛 |
| 行业相关性高导致组合实际分散度低 | 中 | V5 组合挑选时做相关性聚类，每簇保留 1 个 |

---

## 13. 决策汇总

| 决策点 | 选择 | 理由 |
|---|---|---|
| 数据范围 | THS 一级行业 90 个 | 用户指定，对标同花顺直观 |
| 数据终点 | **2026-04-24（固定）** | 用户要求，配合缓存 |
| 缓存机制 | 本地 parquet | 简单、跨平台、Python 原生友好 |
| 失败处理 | 重试 3 次 + 失败清单（不静默剔除）| 用户原则："失败 ≠ 无数据" |
| 算法 | V4.1 Calmar 权重 + D/W/M 三策略 | 不重新设计，复用现有 |
| 输出文件 | `v5-result.md`（新文件）| 不污染现有 md |
| 波动率门槛 | **不预设**，看分布定 | 避免过早优化 |
| V4.1 对比 | 写入 v5-result.md 第七章 | 验证 V5 是否真的更优 |

---

## 14. 成功标准

1. ✅ `scripts/backtest/.cache/` 内含 80+ 个 parquet 文件
2. ✅ `docs/agents/backtest/v5-result.md` 含 9 章完整内容
3. ✅ Top 20 甜点行业明显跑赢 V4.1 的 16 指数组合（CAGR 高 + 回撤可控）
4. ✅ 第二次运行总耗时 < 30 秒（全 cache）
5. ✅ 生产链路逐字节一致
6. ✅ 失败重跑机制可用：清掉某个 cache 文件，下次自动重拉

---

## 15. 后续扩展（不在 V5 计划内）

- V6：用 V5 选出的甜点行业 + V4.2 多窗口框架 → 新组合的 3/5/8/10 年表现
- V7：加入交易成本仿真（按真实佣金/印花税扣减）
- V8：参数敏感性分析（MA10/20/30/60 哪个对该行业最优）
- V9：每行业自适应选 D/W/M（而非固定 V4.1 的 Calmar 权重）
- V10：与同花顺二级行业（粒度更细）做对比
