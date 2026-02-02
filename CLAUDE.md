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

# 强制运行（跳过休市检查）
python scripts/main.py --mode morning --force

# 逻辑测试（不请求数据）
python scripts/main.py --mode morning --mock-date 2026-01-17 --dry-run

# 本地预览
cd docs && python -m http.server 8000

# 测试数据获取
python -c "
from scripts.data_fetcher import DataFetcher
fetcher = DataFetcher()
data = fetcher.fetch_index('000300', 'cs_index')
print(data.tail(5))
"
```

## 架构

```
AkShare/yfinance API
        │
        ▼
DataFetcher (scripts/data_fetcher.py)
  - 多数据源获取：cs_index, sina_index, hk, us, spot_price, crypto
  - 周/月线重采样
  - 自动回退机制（中证失败→新浪）
        │
        ▼
Calculator (scripts/calculator.py)
  - MA20 计算与状态判定 (YES/NO)
  - 偏离率计算与排名
  - 状态转变时间检测（回溯250天）
  - 大周期状态（周-月线）
  - 极强/极弱信号检测
        │
        ▼
RankingStore (scripts/ranking_store.py)
  - 持久化排名历史到 ranking_history.json
  - 计算排名变化
        │
        ▼
Generator (scripts/generator.py)
  - Jinja2 模板渲染
  - 输出到 docs/ 目录
```

## 关键文件

| 文件 | 说明 |
|------|------|
| `scripts/main.py` | 主入口，流程控制 |
| `scripts/data_fetcher.py` | 多源数据获取 |
| `scripts/calculator.py` | 技术指标计算 |
| `scripts/generator.py` | HTML 页面生成 |
| `scripts/config.yaml` | 指数配置列表 |
| `scripts/ranking_history.json` | 排名历史记录 |
| `templates/` | Jinja2 模板 |
| `docs/` | GitHub Pages 输出目录 |
| `.github/workflows/update.yml` | CI/CD 自动更新 |

## 数据源映射

| source | 用途 | AkShare 接口 |
|--------|------|--------------|
| `cs_index` | A股指数 | `stock_zh_index_hist_csindex` |
| `sina_index` | 新浪指数（回退） | `index_zh_a_hist` |
| `hk` | 港股指数 | `stock_hk_index_daily_em` |
| `us` | 美股指数 | `index_us_stock_sina` |
| `spot_price` | 贵金属 | `futures_foreign_hist` |
| `crypto` | 加密货币 | yfinance |

## 运行模式

- **morning**（08:30）：更新前一天行情，生成归档快照

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