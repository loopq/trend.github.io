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

## 核心设计决策

### 数据源回退机制
- 中证指数 (`cs_index`) 失败时自动切换到新浪接口 (`sina_index`)
- 回退发生在 `DataFetcher.fetch_index()` 中（scripts/data_fetcher.py:113）
- 所有数据源统一返回标准 DataFrame 格式（date, close, open, high, low, volume）

### 无持久化设计
- 每次运行重新从 API 获取全部数据（250 天历史）
- 单次运行内使用 `_cache` 字典避免重复请求（不跨运行持久化）
- 唯一持久化文件：`ranking_history.json`（仅保留今日和昨日排名）

### 周月线重采样
- 周/月线通过日线数据重采样生成（`resample('W-FRI')` / `resample('M')`）
- 非直接 API 调用，确保时间对齐一致性
- 实现位置：`DataFetcher.fetch_index()` 返回三个 DataFrame

## 关键文件

| 文件 | 说明 | 关键细节 |
|------|------|----------|
| `scripts/main.py` | 主入口，流程控制 | 包含失败率保护机制（>33% 中止运行） |
| `scripts/data_fetcher.py` | 多源数据获取 | 包含数据源回退逻辑和单次运行缓存 |
| `scripts/calculator.py` | 技术指标计算 | 状态转变时间需要回溯逐日重算（最多250天） |
| `scripts/generator.py` | HTML 页面生成 | 生成首页、归档详情页、归档列表页 |
| `scripts/config.yaml` | 指数配置列表 | 修改此文件添加/删除指数 |
| `scripts/ranking_history.json` | 排名历史记录 | 仅保留今日和昨日，用于计算排名变化 |
| `templates/` | Jinja2 模板 | index.html, archive_detail.html, archive_list.html |
| `docs/` | GitHub Pages 输出目录 | 生成的静态页面和归档 |
| `.github/workflows/update.yml` | CI/CD 自动更新 | 支持手动和外部定时触发 |

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

## 关键算法说明

### 状态转变时间追溯
- 当前状态为 YES 时，向前回溯找到最近的 NO→YES 转变日
- 需要逐日重算 MA20 和状态判断，最多回溯 250 天
- 计算密集型操作，可能影响运行时间
- 实现位置：`Calculator.find_status_change_date()` (scripts/calculator.py:191)

### 失败率保护机制
- 统计所有指数的数据获取成功率
- 失败率 > 33% 时中止运行，避免生成错误页面
- 保护机制防止在数据源大规模故障时更新网站
- 实现位置：`main.py` 的 `process_indices()` (scripts/main.py:55)

## GitHub Actions 配置

### 必需的 Secrets
在仓库 Settings → Secrets and variables → Actions 中配置：
- `GMAIL_USER`：发送通知的 Gmail 邮箱
- `GMAIL_APP_PASSWORD`：Gmail 应用专用密码（非账户密码）
  - 获取方式：Google 账户 → 安全性 → 两步验证 → 应用专用密码

### 触发方式
1. **手动触发**：Actions → Update Trend Data → Run workflow
   - 可选择运行模式（morning）
   - 可选择是否强制运行（跳过休市检查）

2. **外部定时触发**：通过 `repository_dispatch` 事件
   ```bash
   curl -X POST \
     -H "Authorization: Bearer <PAT_TOKEN>" \
     -H "Accept: application/vnd.github.v3+json" \
     -d '{"event_type":"morning"}' \
     https://api.github.com/repos/<owner>/<repo>/dispatches
   ```
   - 推荐使用 [cron-job.org](https://cron-job.org) 进行精准定时触发
   - 避免 GitHub Actions `schedule` 触发器的延迟问题

### 工作流逻辑
1. 运行 `python scripts/main.py --mode morning`
2. 成功后使用 `peaceiris/actions-gh-pages` 部署到 `gh-pages` 分支
3. 使用 `dawidd6/action-send-mail` 发送邮件通知
4. 时区设置为 `Asia/Shanghai`