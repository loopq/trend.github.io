# 全球指数趋势追踪系统 - 实现文档

## 1. 项目背景

### 1.1 目标

构建一个基于 GitHub Pages 的轻量化静态网站，每日自动汇总全球核心指数与行业板块相对于 MA20（20日均线）的趋势强度，支持：

- **历史数据归档**：早间 08:30 生成前一天快照

### 1.2 技术栈

| 组件 | 技术选型 |
|------|----------|
| 数据源 | AkShare |
| 计算引擎 | Python 3.11 + Pandas |
| 模板引擎 | Jinja2 |
| 自动化 | GitHub Actions |
| 部署 | GitHub Pages |

### 1.3 设计原则

**完全无本地存储** - 每次运行时通过 AkShare 获取历史数据并实时计算，不维护任何数据文件。

---

## 2. 核心实现思路

### 2.1 数据获取策略

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  AkShare    │ --> │ DataFetcher │ --> │ Calculator  │
│  各市场接口  │     │  标准化输出  │     │  MA20/状态  │
└─────────────┘     └─────────────┘     └─────────────┘
                                              │
                                              ▼
                                        ┌─────────────┐
                                        │  Generator  │
                                        │  HTML输出   │
                                        └─────────────┘
```

### 2.2 MA20 计算规则

| 模式 | 计算方式 |
|------|----------|
| 16:00 盘后 | `(今日收盘价 + 前19个交易日收盘价) / 20` |

### 2.3 状态转变时间算法

```python
# 伪代码
1. 获取当前状态 S_today (YES: 现价 >= MA20, NO: 现价 < MA20)
2. 从昨日开始回溯，逐日计算历史状态
3. 找到第一个与 S_today 不一致的日期 D_diff
4. 返回 D_diff 的后一个交易日作为"状态转变时间"
5. 若回溯 250 天未找到，显示"未查询到"
```

### 2.4 大周期状态

新增字段：**周-月线状态**

- 格式：`YES-NO`（周线状态-月线状态）
- 计算：当前价格 vs 周线/月线 MA20
- 周线 MA20：当前周 + 前19周收盘价平均
- 月线 MA20：当前月 + 前19月收盘价平均

---

## 3. 数据源对接记录

### 3.1 最终接口方案

| 数据类型 | AkShare 接口 | 代码示例 | 备注 |
|---------|-------------|---------|------|
| A股指数 | `index_zh_a_hist` | 000905, 000688 | 使用中证指数官方代码 |
| 港股指数 | `stock_hk_index_daily_em` | HSI, HSCEI, HSTECH | 东财港股指数 |
| 美股指数 | `index_us_stock_sina` | .INX, .NDX | 新浪美股指数 |
| 贵金属 | `futures_foreign_hist` | XAU, XAG | 伦敦金银现货 |
| 行业板块 | `stock_board_industry_hist_em` | 半导体, 光伏设备 | 使用板块名称 |

### 3.2 代码映射

**A股指数（中证官方代码）**：
```yaml
- 科创50: "000688"
- 中证500: "000905"
- 中证1000: "000852"
- 沪深300: "000300"
- 创业板指: "399006"
```

**贵金属（伦敦金银）**：
```yaml
- 黄金现价: "XAU"  # 伦敦金
- 白银现价: "XAG"  # 伦敦银
```

---

## 4. 问题解决记录

### 4.1 周末/休市处理

**问题**：周末运行脚本时，所有指数显示"休市"

**解决**：添加 `--force` 参数跳过休市检查

```bash
python scripts/main.py --mode final_term --force
```

### 4.2 贵金属价格数据不准确

**问题**：使用 COMEX 期货数据，价格与伦敦金银现货不一致

**原因**：用户需要的是伦敦金银现货价格（美元计价）

**解决**：改用 `futures_foreign_hist` 获取伦敦金银数据

```python
# XAU = 伦敦金, XAG = 伦敦银
df = ak.futures_foreign_hist(symbol="XAU")
```

### 4.3 接口弃用警告

**问题**：`FutureWarning: 'M' is deprecated`

**解决**：
```python
# 修改前
df = daily_df.resample("M").agg({...})

# 修改后
df = daily_df.resample("ME").agg({...})
```

### 4.4 行业板块数据获取失败

**问题**：使用 BK 代码无法获取数据

**解决**：使用板块名称而非代码

```python
# 修改前
ak.stock_board_industry_hist_em(symbol="BK0447")

# 修改后
ak.stock_board_industry_hist_em(symbol="半导体")
```

### 4.5 港股指数接口变更

**问题**：`stock_hk_index_daily_em` 返回数据列名不一致

**解决**：添加列名自动映射逻辑

```python
col_mapping = {}
for col in df.columns:
    if "date" in col.lower() or "日期" in str(col):
        col_mapping[col] = "date"
    elif "close" in col.lower() or "收盘" in str(col):
        col_mapping[col] = "close"
```

### 4.6 Tooltip 显示被截断

**问题**：大周期状态列的 Tooltip 被表格截断

**解决**：调整 CSS 定位，使用向上箭头样式

```css
.tooltip-text {
    position: absolute;
    bottom: -30px;  /* 显示在下方 */
    z-index: 1000;
}
```

---

## 5. 目录结构

```
trend/
├── scripts/
│   ├── config.yaml      # 配置文件（指数列表、时间设置）
│   ├── main.py          # 主脚本入口
│   ├── data_fetcher.py  # 数据获取模块
│   ├── calculator.py    # 计算模块（MA20、状态、偏离率）
│   └── generator.py     # HTML 生成模块
├── templates/
│   ├── index.html       # 首页模板
│   ├── archive_list.html    # 归档列表模板
│   └── archive_detail.html  # 归档详情模板
├── docs/                # GitHub Pages 根目录
│   ├── index.html       # 生成的首页
│   ├── archive/         # 历史归档
│   └── css/style.css    # 样式文件
└── requirements.txt     # Python 依赖
```

---

## 6. 配置说明

### config.yaml 关键配置

```yaml
# 时间配置（北京时间）
schedule:
  update_time: "16:00" # 盘后更新

# 回溯天数
lookback_days: 250

# 主要指数
major_indices:
  - code: "000905"
    name: "中证500"
    source: "cs_index"

# 行业板块
sector_indices:
  - code: "931152"
    name: "半导体"
    source: "cs_index"
```

### source 类型说明

| source             | 用途 | 接口 |
|--------------------|------|------|
| `cs_index`         | A股官方指数 | `index_zh_a_hist` |
| `hk`               | 港股指数 | `stock_hk_index_daily_em` |
| `us`               | 美股指数 | `index_us_stock_sina` |
| `spot_price`       | 贵金属 | `futures_foreign_hist` |
| `eastmoney_sector` | 行业板块 | `stock_board_industry_hist_em` |
