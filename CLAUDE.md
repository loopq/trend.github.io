# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

全球指数趋势追踪系统 - 基于 GitHub Pages 的轻量化股票指数趋势追踪，每日自动汇总全球核心指数相对于 MA20 的趋势强度。

**核心特点**：完全无本地数据库，每次运行通过 AkShare/yfinance 动态获取数据并实时计算。

## 常用命令

```bash
# 激活虚拟环境
source venv/bin/activate

# 早间更新（前一天行情 + 归档）
python scripts/main.py --mode morning

# 调试模式
python scripts/main.py --mode morning --debug

# 强制运行（跳过休市检查 + 数据新鲜度检查）
python scripts/main.py --mode morning --force

# 逻辑测试（不请求数据，只打印日期判断）
python scripts/main.py --mode morning --mock-date 2026-01-17 --dry-run

# 本地预览
cd docs && python -m http.server 8000

# 本地测试 Analytics（使用假 ID）
python scripts/main.py --mode morning --enable-analytics --force

# 批量回填历史归档（从 API 获取历史数据重新生成归档页面）
python scripts/backfill_archive.py --days 30
python scripts/backfill_archive.py --start 2025-12-17 --end 2026-01-17

# 测试数据获取
python -c "
from scripts.data_fetcher import DataFetcher
fetcher = DataFetcher()
data = fetcher.fetch_index('000300', 'cs_index')
print(data.tail(5))
"
```

**注意**：`scripts/test_*.py` 是手动数据源测试脚本（直接 `python scripts/test_csindex.py` 运行），不是自动化测试套件，项目无 pytest/unittest。

## 架构

```
AkShare/yfinance API
        │
        ▼
DataFetcher (scripts/data_fetcher.py)
  - 多数据源获取：cs_index, sina_index, hk, us, spot_price, crypto
  - fetch_index() 返回日线 DataFrame（标准列：date, close, open, high, low, volume）
  - process_weekly_data() / process_monthly_data() 从日线重采样
  - 自动回退机制（中证失败→新浪）
  - 请求 800 天历史数据用于周/月线 MA20 计算
        │
        ▼
Calculator (scripts/calculator.py)
  - calculate_all_metrics() 是核心方法，返回指标字典（见下方数据契约）
  - MA20 状态判定：收盘价 >= MA20 → "YES"，否则 → "NO"
  - 偏离率 = (current_price / ma20 - 1) * 100，用于排名排序
  - 大周期状态：周线 MA20 + 月线 MA20 → "YES-YES" / "YES-NO" 等
  - 趋势拐点：昨日状态 ≠ 今日状态 → new_breakthrough / new_breakdown
  - 极强/极弱信号：连续 3 天最低价 > MA20（极强）或最高价 < MA20（极弱）
        │
        ▼
RankingStore (scripts/ranking_store.py)
  - 持久化排名历史到 scripts/ranking_history.json
  - 滑动窗口：仅保留 today + yesterday，每次运行 today → yesterday 轮转
        │
        ▼
Generator (scripts/generator.py)
  - Jinja2 模板渲染 + SVG sparkline 生成（最近20日趋势图）
  - 多空比例统计（仅 major_indices 参与计算）
  - 模板 → 输出映射：
    templates/index.html          → docs/index.html（首页）
    templates/archive_detail.html → docs/archive/YYYY-MM-DD.html（归档详情）
    templates/archive_list.html   → docs/archive/index.html（归档列表，扫描已有归档文件生成）
```

### calculate_all_metrics() 输出契约

这是贯穿整个系统的核心数据结构，从 Calculator 输出到 Generator 消费：

```python
{
    "current_price", "prev_close", "ma20",    # 价格数据
    "status",          # "YES" / "NO"（日线 MA20 上下）
    "change",          # 涨跌幅 %
    "deviation",       # 偏离率 %（排序依据）
    "change_date",     # 状态转变日期（回溯最多 250 天）
    "change_price",    # 转变日 MA20（区间涨幅基准）
    "interval_change", # 区间涨幅 %（从转变日 MA20 算起）
    "volume_ratio",    # 量比（当日量 / 前5日均量）
    "big_cycle_status",# "YES-YES" 等（周-月线 MA20）
    "status_change",   # "new_breakthrough" / "new_breakdown" / None
    "extreme_trend",   # "极强" / "极弱" / None
    "sparkline_prices",# 最近 20 日收盘价列表
    "error",           # 错误信息或 None
}
```

`main.py` 的 `process_indices()` 额外附加 `rank`（偏离率排序序号）和 `rank_change`（较昨日排名变化）。

## 核心设计决策

### 部署门控（should_deploy）

`main.py` 通过 `_set_github_output("should_deploy", ...)` 控制 CI 是否触发 `peaceiris/actions-gh-pages` 部署。以下 3 个条件会阻止部署（`--force` 可跳过前两个）：

1. **昨天非交易日**：周六/周日运行时直接跳过（`is_trading_day(yesterday)`）
2. **A股数据过旧**：以沪深300（000300）作为哨兵，检查数据最新日期 < 上一个交易日则跳过
3. **失败率过高**：指数数据获取失败率 > 33% 时 `sys.exit(1)` 中止

### 数据源回退机制
- 中证指数 (`cs_index`) 失败时自动切换到新浪接口 (`sina_index`)，回退在 `DataFetcher._fetch_cs_index()` 中
- 美股指数有备用接口 `_fetch_us_index_alt()`（新浪全球指数）
- 所有数据源统一返回标准 DataFrame 格式（date, close, open, high, low, volume）
- 网络错误自动重试 2 次（`@retry_on_network_error` 装饰器，线性退避）

### 无持久化设计
- 每次运行重新从 API 获取全部数据（800天历史用于周/月线计算）
- 单次运行内使用 `_cache` 字典避免重复请求（不跨运行持久化）
- 唯一持久化文件：`scripts/ranking_history.json`（仅保留今日和昨日排名）

### 周月线重采样
- 周线通过日线数据重采样生成（`resample('W-SUN')`）
- 月线通过日线数据重采样生成（`resample('ME')`）
- `fetch_index()` 返回单个日线 DataFrame，周/月线通过 `process_weekly_data()` 和 `process_monthly_data()` 分别计算

### 请求伪装
- DataFetcher 在初始化时 monkey-patch `requests.Session.request`，为所有 HTTP 请求注入随机 User-Agent
- 线程安全（双重检查锁），整个进程只 patch 一次

## 数据源映射

| source | 用途 | AkShare 接口 |
|--------|------|--------------|
| `cs_index` | A股指数（主） | `stock_zh_index_hist_csindex` |
| `sina_index` | A股指数（回退/非中证） | `stock_zh_index_daily` |
| `hk` | 港股指数 | `stock_hk_index_daily_sina` |
| `us` | 美股指数 | `index_us_stock_sina`（备用 `index_global_from_sina`） |
| `spot_price` | 贵金属 | `futures_foreign_hist` |
| `crypto` | 加密货币 | yfinance |

### 新浪指数代码转换
`sina_index` 需要交易所前缀（sh/sz/bj），转换规则在 `SINA_EXCHANGE_CODES` 常量和 `_convert_to_sina_symbol()` 中。新增指数若使用 `sina_index` 源需确认前缀映射。

## 配置修改

修改 `scripts/config.yaml` 添加/删除指数：

```yaml
major_indices:
  - code: "000905"
    name: "中证500"
    source: "cs_index"

sector_indices:
  - code: "H30184"
    name: "半导体"
    source: "cs_index"
```

两个分组：`major_indices`（参与多空比例统计）和 `sector_indices`（仅展示）。

## GitHub Actions

### 触发方式
1. **手动触发**：Actions → Update Trend Data → Run workflow（可选 force）
2. **外部定时触发**：通过 `repository_dispatch` 事件（推荐 cron-job.org，避免 GitHub schedule 延迟问题）

### Workflows
- `update.yml`：核心工作流，获取数据 → 生成页面 → 部署到 gh-pages → 邮件通知
- `keepalive.yml`：每 45 天触发一次空提交，防止 GitHub 因 60 天无活动自动禁用 Actions

### 必需的 Secrets
- `GMAIL_USER` / `GMAIL_APP_PASSWORD`：邮件通知
- `GA_MEASUREMENT_ID`（可选）：Google Analytics
