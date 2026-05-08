# 全球指数趋势 + 量化信号

GitHub Pages 静态站；每日 AkShare/yfinance 取数算 MA20，无本地 DB。

## 子系统
- `scripts/main.py`：主链路（每日趋势页面），plan 在 `agents/plans/`。
- `scripts/quant/`：量化信号（13 指数 × 36 bucket），plan 见 `agents/plans/mvp-plan.md`。
- `scripts/backtest/`：离线回测，详见 `scripts/backtest/CLAUDE.md`。

## 命令

```bash
source venv/bin/activate
python scripts/main.py --mode morning [--debug|--force|--mock-date YYYY-MM-DD --dry-run]
cd docs && python -m http.server 8000   # 本地预览
```

## 文档目录约定
- `agents/plans/`：plan 文档（设计、迁移、事故响应）。
- `agents/reviews/`：plan / code review。
- `agents/results/`：回测产物报告。
- 新文件命名：`年-月-日-模块-描述.md`；旧文件保留原名。

## 规范
- 不主动 `git commit` / `push`。
- 优先编辑现有文件，不擅自新建；仅改必要代码，避免全文件格式化。
- review-loop 产物落根 `/reviews/`（已 .gitignore），按需归档至 `agents/reviews/`。
