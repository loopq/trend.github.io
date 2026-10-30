# 全球指数趋势 + 量化信号

GitHub Pages 静态站；每日 AkShare/yfinance 取数算 MA20，无本地 DB。

## 子系统
- `scripts/futures/`：期指观察（IC / IM 贴水曲线与移仓统计），每日全量重算，失败保留线上旧页。
- `scripts/main.py`：主链路（每日趋势页面），plan 在 `agents/plans/`。
- `scripts/quant/`：量化信号（13 指数 × 36 bucket），plan 见 `agents/plans/mvp-plan.md`。**已停用**（2026-10-19）：定时入口 `quant.yml` 与 `update.yml` 中的 morning-reconcile 已移除；代码、`docs/quant/` 前端与数据保留，`backtest.yml` 仍调用 `scripts/quant/build_quant_backtest.py`。
- `scripts/backtest/`：离线回测，详见 `scripts/backtest/CLAUDE.md`。

## 命令

```bash
source venv/bin/activate
python -m scripts.futures --out /tmp/futures-site [--as-of YYYY-MM-DD]   # 期指本地生成；生产传主站 record_date
python scripts/main.py --mode morning [--debug|--force|--mock-date YYYY-MM-DD --dry-run]
python -m pytest scripts/tests scripts/backtest -q   # 主站 + 回测测试门禁（CI: trend-test.yml）
cd docs && python -m http.server 8000   # 本地预览
```

## 发布（gh-pages 两个写入方，均 keep_files，永不删除线上文件）
- `update.yml`：生成前 `site_publish restore` 从 gh-pages 恢复归档，生成后只发布主站文件（`scripts/site_publish.py` 的 `SITE_FILES` / `SITE_DIRS`）。
- `archive/deviation.json`：首页偏离率历史（2016 起增量状态），随 `site_publish restore` 恢复、随 `archive/` 发布；缺列自动回填。
- `backtest.yml`：只发布 `quant/`、`data/`。
- main 上的 `docs/index.html`、`docs/archive/` 是历史快照，不是部署源的全部；本地跑 `main.py` 产生的改动不要提交（pre-commit hook 会拦）。

## 新增页面（如期指观察）
- 模板 `templates/xxx.html` `extends "base.html"`；`Generator.render("xxx.html", "futures/index.html", ...)` 自动注入相对根路径 `root` 与 GA。
- 右上角站点入口：`templates/base.html` 的 `site_nav` block 加 `<a href="{{ root }}futures/">期指观察</a>`。
- 新目录登记到 `site_publish.SITE_DIRS`，否则不会发布。

## 文档目录约定
- `agents/plans/`：plan 文档（设计、迁移、事故响应）。
- `agents/reviews/`：plan / code review。
- `agents/results/`：回测产物报告。
- 新文件命名：`年-月-日-模块-描述.md`；旧文件保留原名。

## 规范
- 不主动 `git commit` / `push`。
- 优先编辑现有文件，不擅自新建；仅改必要代码，避免全文件格式化。
- review-loop 产物落根 `/reviews/`（已 .gitignore），按需归档至 `agents/reviews/`。
