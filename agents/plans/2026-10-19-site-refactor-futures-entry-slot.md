# 主站重构：模板去重 + 期指观察入口预留 + quant 入口下线

> 日期：2026-10-19 · 范围：主站链路（`scripts/main.py` / `templates/` / `docs/css/style.css`）+ workflows 中 quant 入口 + 主站发布流程
> 原则：重构部分行为保持；既有 bug（B1/B2/B4/B5）与可见变化（D3）各自独立一步，先写失败测试再修（TDD）。
> 执行方式：用户不介入，仅最终验收（本地 + 线上）。本 plan 经 `/plan-review-codex`（gpt-6-astra）review 后执行。
> Review 记录：`agents/reviews/2026-10-19-site-refactor-futures-entry-slot-review.md`

## 0. 已确认决策

| # | 决策 |
|---|---|
| B1 | 「强度变化」改为从行情推导前一日排名，删 `ranking_store.py` + `ranking_history.json` |
| B2 | 修「周月状态」MA20 双计当前价，周/月线由 Calculator 从日线内部重采样 |
| D3 | 归档页补「量比」列，与首页同一份列定义 |
| Q | quant 已停用：移除其**定时/自动入口**；quant 代码、`docs/quant/` 前端、数据、各级 CLAUDE.md 全部保留 |
| T | 新增主站测试套件：单元（TDD）+ 功能（端到端渲染后逐格校验） |
| 硬约束 | 主站定时任务（`update.yml` 的 `repository_dispatch: morning`、`keepalive.yml`）**不动** |

## 1. 目标 / 非目标

| | 内容 |
|---|---|
| 目标 1 | 代码简洁：模板 606 → ~220 行，消除 4 份表格副本、2 份列说明 |
| 目标 2 | 零破坏：URL、视觉（除已确认的可见变化）、`DataFetcher.fetch_index` 接口不变 |
| 目标 3 | 为「期指观察」（需求 4659：IC/IM 价差曲线 + 移仓点）预留：页头右上角入口槽、新页面复用 base 布局与 `Generator.render`、数据源分发表一行注册 |
| 目标 4 | 测试证明展示数据正确：页面上每个数值单元格 = 独立 oracle 计算值 |
| 非目标 | 不实现期指观察本体，不加入口链接；不保证 quant 跑通（已停用） |

## 2. 现状诊断

| 位置 | 问题 |
|---|---|
| `templates/index.html`(303) + `archive_detail.html`(256) | 两张表的 `<tr>` 主体复制 4 份；head/GA/弹窗 JS 复制 2 份。差异仅在 css 路径、副标题、导航、量比列、弹窗格式、页脚 |
| 同上 | 列说明两份且格式不一：首页 `help-list`，归档页 `help-table`（CSS 中不存在 → 归档页弹窗一直无样式） |
| `templates/index.html:83` | 错误行 `colspan="10"`，实际剩余 11 列（14 − 3） |
| `generator.py:_render_page` | 只能渲染指数页；css 相对路径写死在各模板；新页面无法复用 |
| `generator.py:282` | 自读 `datetime.now()` 推归档日期，与 `main.py:299` 的 `record_date` 各算一遍；`--mock-date` 下不一致 |
| `main.py:67` | `process_indices(force)` 参数未使用 |
| `main.py:258-271` | A 股数据日期检查重复请求一次 000300（前面已拉过 800 天） |
| `main.py:220-236` | GA 配置 17 行 if/elif；`analytics_enabled` 与 `ga_measurement_id` 冗余 |
| `main.py` 整体 | 业务流程与 argparse/sys.exit/GITHUB_OUTPUT 糊在 `main()` 里，不可注入 fetcher/输出目录 → 无法做功能测试 |
| `main.py` vs `backfill_archive.py` | 「单指数 df → 页面行」逻辑写了两份；backfill 预加载后又写一份永不命中的惰性缓存 |
| `data_fetcher.py:185-199` | `fetch_index` 6 路 if/elif 分发 |
| `docs/css/style.css` | `.status-closed`、`.header .date`（含移动端）无人使用（模板 + 305 个归档页均无引用） |
| `scripts/config.yaml:2-3` | `schedule.update_time` 无代码读取 |
| 仓库根 | `2026-05-06-233319-local-command-caveat...txt` 是误提交的 Claude Code 会话导出 |

> `.tooltip-*` 看似死代码，但 251 个旧归档页（2025-01-21 ~ 2026-01-30）在用 —— **保留**并加注释。

## 3. 既有 bug

### B1 「强度变化」一直对比 2026-02-01 的排名 🔴

- `RankingStore` 在 CI 里更新 `scripts/ranking_history.json`，但 `update.yml` 从不 commit。`apply_rank_changes` 在 `update_today` 之前执行，读的是仓库快照里的 `yesterday` 字段 = **2026-02-01**。线上比特币 +10、上证50 +7 即此。
- 修法：`calculate_all_metrics` 增加 `prev_deviation`（`closes[-2]` 相对 `mean(closes[-21:-1])` 的偏离率；不足 21 根为 None）。`apply_rank_changes(results)` 在「无 error 且 prev_deviation 非 None」的项内排序得前一日名次，`rank_change = prev_rank - rank`，其余项为 None。删 `RankingStore` 与 json。backfill 同用此函数，删 `prev_*_ranks` 追踪。
- **并列规则（review M1）**：今日、昨日排序统一用 `(−偏离率, 配置序号)`。`process_indices` 给每行写 `order`（配置中的位置）；`sort_by_deviation` 与 `apply_rank_changes` 都按此二元键排序 —— 与现有稳定排序（并列保留配置顺序）等价，且昨日排序不继承今日顺序。
- 已知语义差：各指数按「自身上一根 K 线」比较；休市不同步的市场（BTC 周末、港美股假日）与「上次发布页」略有出入。可接受。

### B2 「周月状态」MA20 把当前价算了两次 🟡

- 主链路：`_period_ma20_status` 中重采样最后一根周/月 K 已是进行中周期（close = 当前价），又 `+ [current_price]` → 窗口 `w-18..w-1, 当前, 当前`。合成数据实测确认。
- 回填链路同样不可靠（review H2 纠正了我先前「回填正确」的判断）：`_resample_data` 先 `tail(20)` 再按未来周期 label 截断，常只剩 19 根，被 `<20` 门槛判为 `-`；且回填只拉 `days=400`，月线约 15 根，不足 20。
- 修法：
  1. Calculator 从传入日线内部重采样（`W-SUN` / `ME`，聚合同现状），状态 = `close[-1] >= mean(close[-20:])`，**不足 20 根为 `-`**（降级规则）。删「追加当前价」特例；`calculate_all_metrics` 删 `weekly_df/monthly_df/current_price` 参数（`current_price` 尾盘模式无调用方）。
  2. `DataFetcher.process_weekly/monthly_data`、`get_latest_date` 无外部调用方（已 grep quant/backtest），移除。
  3. 取数窗口统一：`scripts/__init__.py` 定义 `HISTORY_DAYS = 800`，main 使用；backfill 取 `HISTORY_DAYS + (today − 最早目标日).days`，保证任一回填截至日拥有与当日主链路同等的预热历史（≥ 20 根月线、250 日状态回溯）。`fetch_index` 签名不变。
- 结果：会改变部分临界指数的周月状态显示。主链路与回填的一致性范围见 B3。

### B3 行情截至日语义（review R2-H2，明确契约，不改行为）

- **主链路保持现状**：每个指数用取数时刻的最新可得 K 线计算，不按 `record_date` 截断。理由：改为截断会改变 BTC / 黄金 / 白银的线上展示（08:00 运行时已有 T 之后的行情），超出已确认的 B1/B2/D3 范围。
- **回填保持现状**：按目标日 T 截断（`date <= T`）后计算。
- **一致性承诺按依赖范围分两类（review R3-H1）**：
  - **个体指标**（只依赖本指数自身行情）：状态、涨幅、现价、MA20、偏离率、量比、状态转变时间、区间涨幅、走势、周月状态、极强/极弱。同一 T、本指数有效输入相同（生产中 A 股 / 港股 / 美股在北京时间 08:00 最新 K 线 = T）且历史足够时，主链路与回填相等。
  - **组内指标**（依赖整组行情）：趋势强度、强度变化、多空比例。不要求跨路径相等 —— 同组的 BTC / XAU / XAG 在主链路多一根 T+1 K 线，就可能改变其他指数的名次。两条路径各自对「本路径完整分组输入」的独立 oracle 断言；只有整组成员、配置顺序、相关行情输入全部可比时，才断言跨路径一致。
  - 不为对齐而分市场排名、复制另一路径排名或改变截断规则。
  - 24 小时市场（BTC、XAU、XAG）的个体指标同样按设计不一致：主链路 = 全量 oracle，回填 = 截至 T 的 oracle。
- **金样的用途**：`/tmp/trend-refactor/before/` 只做改动前后同输入的回归比对（快照中 BTC/XAU/XAG 含 10-17 / 10-19 的 K 线，正是主链路的生产语义），不作为业务正确性依据；业务正确性由 §5.2 的 oracle 功能测试证明。

### B4 线上 2026-04-27 ~ 2026-10-15 的归档全部 404 🔴

- 根因：`update.yml` 部署用 peaceiris 默认 `keep_files: false`，每次以 main 的 `docs/` 整体替换 gh-pages；main 上归档只到 2026-04-24 → 每天新归档在下一次部署时被抹掉，归档列表也只有「main 上的 + 当天」。
- **发布归属（review H1）**：主站只发布自己拥有的文件，不再发布整个 `docs/`：
  - 新模块 `scripts/site_publish.py`（两个函数 + CLI）：
    - `restore_archives(ref, docs_dir)`：`git archive <ref> archive` → 解包到 `docs/archive/`，ref 不存在或解包失败即非零退出（宁可不部署也不抹数据）。
    - `stage(docs_dir, out_dir)`：只拷 `index.html`、`css/`、`archive/`、`CNAME` 到 staging 目录。
  - `update.yml`：checkout（已 `fetch-depth: 0`）后先 `restore_archives origin/gh-pages`，跑 `main.py`，再 `stage` 到 `/tmp/site-publish`，peaceiris 以 `publish_dir: /tmp/site-publish` + `keep_files: true` 发布 —— 永不删除、永不触碰 `quant/`、`data/`（归 `backtest.yml` 所有，它本就 quant-only + `keep_files: true` 发布）。删除 `exclude_assets`（staging 已不含；peaceiris 的 exclude 会删除目标端匹配文件，不能用于保护）。
  - **双向有界重试（review R2-H1）**：两个写入方（`update.yml` 主站、`backtest.yml` 回测）并发 push gh-pages 时，后者普通 push 被拒、不覆盖任何内容。两个 workflow 的 gh-pages 发布都改为「首次步骤 `id: deploy` + `continue-on-error: true` → `sleep` → 第二次步骤 `if: steps.deploy.outcome == 'failure'`」。peaceiris 每次执行都在新临时目录重新 clone 最新 gh-pages，所以重试会在最新 HEAD 上重建提交。第二次失败即 job 失败；全程不用 `force_orphan` / force push。
  - `update.yml` 的成功邮件条件改为 `should_deploy == 'true' && (steps.deploy.outcome == 'success' || steps.deploy_retry.outcome == 'success')`；重试耗尽时 job 失败，邮件步骤因隐式 `success()` 被跳过。
  - 不合并 concurrency group（GitHub 会取消同组排队中的 run，可能吞掉每日更新）。
  - 真实并发竞争只能在 CI 中发生；本地以 workflow 结构断言（§5.3）守护重试与条件闭合，残余风险写入交付说明。
- **一次性恢复（review H4）**：
  - 固定来源：执行时 `git fetch` 后记录 `origin/gh-pages` SHA（当前 `5dedf2f`），写入清单头；用户部署前若需回退，以此 SHA 为准。
  - 算法（不依赖 rename 检测）：按 `git rev-list <SHA>` 由新到旧遍历，每个 commit `git ls-tree archive/` 列文件；每个日期取**第一次遇到的（最新的）blob**。候选 = 不在 main `docs/archive/` 的日期页。
  - 过滤：日期必须是 A 股交易日（以 000300 日线为准）。已核：候选 121 个 → 恢复 116 个（2026-02-02、2026-04-27 ~ 2026-10-16；其中 10-16 在 gh-pages 当前树，恢复无害），排除 5 个非交易日（01-17、01-31、02-16 春节、04-25、04-26）。窗口内每个交易日都有来源，无缺口。
  - 产出清单 `agents/results/2026-10-19-archive-recovery-manifest.md`：每行 日期 / commit / blob / 是否已在线 / 动作 / 原因。
  - 恢复后校验：每个文件 blob 哈希 = 清单；`<title>` 日期 = 文件名日期；main 上原有 305 个文件零改动。
  - pre-commit hook 会拦 `docs/archive/*.html`，用户提交时需 `--no-verify`（交付说明写明）。

### B5 数据不足的指数会让主链路整批崩溃 🔴（review H3 发现）

- `calculate_all_metrics` 对 < 20 根数据返回 `error="数据不足"`、`deviation=None`；`main.py:122` 的 f-string `:.2f` 即刻求值 → TypeError，整次更新失败。回填路径无此日志，能正常出错误行。
- 修法：共享 `process_indices` 契约 —— Calculator 返回 error 的结果原样成为错误行（与 fetch 失败同等），计入失败率；日志不格式化 None。不吞任意异常。

### D3 归档页补「量比」列

- 在模板统一**之前**先在现有 `archive_detail.html` 上红绿完成（review M2），统一后两页同一份 `COLUMNS`；只影响新生成的归档。

## 4. 方案

### 4.1 模板：base + trend + 列定义单一来源

```
templates/
├── base.html            # 新：doctype/head/GA/container/页头(含 site-nav 槽)/footer —— 所有页面共用
├── trend.html           # 新：多空仪表盘 + 两张指数表(macro) + 列说明弹窗，COLUMNS 单一来源
├── index.html           # 改：extends trend.html，只覆盖 副标题/导航/页脚 block
├── archive_detail.html  # 改：同上
└── archive_list.html    # 改：extends base.html
```

```jinja
{% set COLUMNS = [
  ("趋势强度", "按偏离率排序的排名，数字越小趋势越强。极强/极弱 = 连续3日未触碰MA20"),
  ("代码", "指数代码"),
  ...
] %}
<thead><tr>{% for name, _ in COLUMNS %}<th>{{ name }}</th>{% endfor %}</tr></thead>
...
<td class="status-error" colspan="{{ COLUMNS|length - 3 }}">{{ item.error }}</td>
```

- css / 链接前缀统一 `{{ root }}`（Generator 按输出路径深度推导）。autoescape 保持开启。
- 归档页弹窗改用 `help-list`（样式修复，仅新归档）。
- GA 块在 base，`archive_list` 也带 GA。

### 4.2 Generator：通用 render

```python
def render(self, template: str, out: str, **ctx) -> str:
    """渲染 template 到 output_dir/out；注入 root（相对站点根前缀）与 ga_id"""
    root = "../" * out.count("/")
    html = self.env.get_template(template).render(root=root, ga_id=self.ga_id, **ctx)
    ...
```

- 指数页 / 归档页 / 归档列表都走 `render`；期指观察将来 `render("futures.html", "futures/index.html", ...)`。
- `generate_all(major, sector, record_date, now)`：日期由调用方传入，单一来源（`now` 仅用于「更新时间」文本，便于测试固定）。
- 构造参数合并为 `ga_id`（None = 关闭）；内联两个单行 format 包装。

### 4.3 期指观察预留位（只留位，不加链接）

- `base.html` 页头加空槽 `<nav class="site-nav">{% block site_nav %}{% endblock %}</nav>`；CSS：`.header` 相对定位，`.site-nav` 桌面端右上角绝对定位，≤768px 回落为标题下方居中，`:empty` 隐藏 —— 当前视觉零变化。
- 将来接 4659：`scripts/futures/` 产数据 → `templates/futures.html` extends base → 槽里加一行 `<a href="{{ root }}futures/">期指观察</a>` → `update.yml` 加 `continue-on-error` step，`site_publish.stage` 加 `futures/` → 需要 CFFEX 合约日线时分发表加一行。

### 4.4 Python 结构

| 文件 | 改动 |
|---|---|
| `scripts/__init__.py` | 共享：`load_config`、`HISTORY_DAYS`、`process_indices(indices, get_df, calculator)`（`get_df(cfg) -> df|None`；main 传网络拉取、backfill 传按日截断；写 `order`；B5 错误契约）、`apply_rank_changes(results)`（B1） |
| `main.py` | `main()` 只管 argparse / 日志 / dry-run / `GITHUB_OUTPUT` / 退出码；业务抽为 `run(config, check_date, fetcher, generator, force, now) -> bool(should_deploy)`，失败率超限抛异常由 `main()` 转 `sys.exit(1)`。删 `force` 死参数；GA 收成 `_ga_id(args)`；A 股日期检查读结果里的 `latest_date`，去掉重复请求。CLI 参数、`should_deploy` 输出、退出码契约不变 |
| `calculator.py` | B1 `prev_deviation`；B2 内部重采样；结果加 `latest_date`；`sort_by_deviation` 用 `(−偏离率, order)` |
| `data_fetcher.py` | if/elif → `{source: method}` 分发表；缓存副本、网络错误返回 None、非预期异常上抛三种行为不变；删 B2 迁走的方法；`fetch_index` 签名不变（quant `run_signal`、backtest `data_loader` 依赖） |
| `backfill_archive.py` | 改用 `process_indices` + `apply_rank_changes`；B2 取数窗口；删双重缓存 |
| `site_publish.py` | 新：B4 的 `restore_archives` / `stage` |
| `config.yaml` | 删 `schedule.update_time` |
| `style.css` | 删 `.status-closed`、`.header .date`×2；加 `.site-nav`；`.tooltip-*` 加「旧归档在用」注释 |
| 仓库根 | 删误提交的会话导出 txt |

### 4.5 quant 入口下线（代码保留）

| 入口 | 处理 |
|---|---|
| `.github/workflows/quant.yml`（cron-job.org `repository_dispatch: quant-trigger` 的 signal / morning-reconcile / deploy / init / mock-test） | 删除文件。外部 cron-job.org 的 quant 任务需用户自行停用（不停也只是空派发，无害） |
| `update.yml` 内 quant 步骤（git identity、morning-reconcile、push main） | 删除这 3 步；concurrency group `quant-state-main` 改名 `trend-update` |
| 保留 | `scripts/quant/**`（`backtest.yml` 仍调用 `scripts/quant/build_quant_backtest.py`）、`docs/quant/**`（backtest viewer 在此）、`docs/data/quant/**`、`quant-test.yml`（仅 PR 触发、无定时）、`backtest.yml`（仅加 gh-pages 发布重试，见 B4）、`keepalive.yml` |
| CLAUDE.md | 项目 `.claude/CLAUDE.md` 标注 quant「已停用：入口已移除，代码保留」，补主站测试命令与发布归属；`scripts/backtest/CLAUDE.md` 不动 |

## 5. 测试（TDD + 功能）

位置 `scripts/tests/`（与 `scripts/quant/tests/` 同构），纯离线，不触网。新增 `.github/workflows/trend-test.yml`：push / PR 触及 `scripts/*.py`、`scripts/tests/**`、`templates/**`、`docs/css/**`、`.github/workflows/update.yml`、`.github/workflows/backtest.yml`、`.github/workflows/trend-test.yml`、`requirements*.txt` 时跑 `scripts/tests/` + `scripts/backtest/`。

**门禁口径**：`scripts/tests/` 与 `scripts/backtest/` 必须全绿；`scripts/quant/tests/` 仅尽力跑、结果记录、不阻塞（已停用）。

### 5.1 单元测试（先红后绿）

| 文件 | 覆盖 |
|---|---|
| `test_calculator.py` | 特征化现有行为（MA20、状态、涨幅、偏离率、量比、状态转变日 + 区间涨幅、拐点 🔼🔽、极强/极弱、排序）；0/19/20/21 根日线边界；**TDD**：`prev_deviation`（B1，20 根时为 None）、周/月 MA20 不双计、19/20 个周期边界、进行中周期（B2） |
| `test_ranking.py` | **TDD**：`apply_rank_changes` 由 `prev_deviation` 推导；昨日并列、今日并列、两日均并列（M1 用例：配置 A、B，昨日均 0、今日 B>A → B:+1、A:−1）；错误项 / 无 prev 项为 None；A 输入不变、同组 BTC 型多一根 T+1 → A 的 rank / rank_change 按本组输入变化（R3-H1） |
| `test_generator.py` | **TDD**：`render` 的 root 推导（`index.html`→`""`、`archive/x.html`/`futures/index.html`→`"../"`）、ga_id 开关、autoescape 保持、归档列表按月分组倒序 |
| `test_data_fetcher.py` | 分发表路由每个 source；未知 source → None；缓存命中返回副本（改返回值不污染缓存）；网络错误 → None；非预期异常上抛；`fetch_index(code, source, name=, days=)` 签名兼容 |
| `test_site_publish.py` | 见 5.3 |

### 5.2 功能测试（端到端，证明展示数据正确）

- 夹具：确定性合成 OHLCV，覆盖 —— 极强上涨、极弱下跌、今日突破 🔼、今日跌破 🔽、排名前后变化、fetch 失败指数、短历史（19 根）指数、周/月临界指数、偏离率并列。
- 桩 fetcher 按 source 模拟生产取数语义：`cs_index` = 距「今天」`days + 30` 个日历日起点再 `tail(days)` 行；其余 source = 全量再 `tail(days)` 行。夹具中 A 股类指数最新 K 线 = T，24 小时类指数（BTC 型）含 T+1 的 K 线。经真实 `main.run()` / backfill 适配器跑 → 产出 `index.html`、`archive/{date}.html`、`archive/index.html` 到 `tmp_path`。
- bs4 解析页面，**每一格**与测试内独立 oracle（纯 pandas 公式，不调 Calculator）比对：趋势强度/排序、状态、涨幅、现价、MA20、偏离率、量比、状态转变日、区间涨幅、强度变化、周月状态、极强/极弱标记、多空比例。
- 结构断言：两页均 14 列且表头 = 弹窗术语列表（D3）；错误行 colspan = 11 且显示「数据异常」/「数据不足」；归档页 css 为 `../css/style.css`；site-nav 存在且为空；GA 随 ga_id 出现/消失。
- 流程断言：昨日非交易日 → should_deploy=False 且不写文件；A 股数据过旧 → 跳过；`--force` 绕过两项检查；单个短历史 / fetch 失败且失败率 ≤ 1/3 → 正常出页含错误行；失败率 > 1/3 → 异常且不写页面（main 转 exit 1）；`GITHUB_OUTPUT` 写入 `should_deploy=true/false`。
- 主链路 vs 回填（B2/B3）：同一原始夹具、同一 T，`main.run(check_date=T+1)` 与 backfill(T) 的归档页 ——
  - 最新 K 线 = T 的指数：**个体指标**跨路径相等；
  - BTC 型指数：个体指标主链路 = 全量 oracle、回填 = 截至 T 的 oracle；
  - **组内指标**（趋势强度、强度变化、多空比例）：两条路径各自对本路径完整分组输入的 oracle 断言，不做跨路径等值；
  - 反例用例（review R3-H1）：A 的 21 根 = 20×100 + T 日 101；BTC 型 = 20×100、T 日 90、T+1 日 120。A 输入两路径完全相同，主链路 A 第 2 / 强度变化 −1、回填 A 第 1 / 0，多空比例 100% vs 50% —— 两边都等于各自 oracle；
  - 全组输入相同的对照组：组内指标跨路径相等。
- 跨月价格突变夹具（9 月末全 100、10 月 1 日 50）验证 B2 周月状态在两条路径下各自正确。
- backfill 连续 3 个交易日：强度变化与逐日 oracle 一致。

### 5.3 发布流程测试（`test_site_publish.py`，临时 git 仓库）

- 构造仓库：`gh-pages` 含 `archive/{d1,d2}.html`、`quant/backtest/x.md`（新版）；main 检出的 `docs/` 含 `archive/d1.html`、`quant/backtest/x.md`（旧版）。
- `restore_archives` → `docs/archive` 含 d1、d2；生成 d3 → 归档列表含 d1–d3。
- `stage` → staging 只含 `index.html`、`css/`、`archive/`、`CNAME`，**不含 `quant/`、`data/`**。
- 模拟 keep_files 发布（staging 覆盖拷入 gh-pages 树）→ `quant/backtest/x.md` 仍为新版（H1 交错场景：回测先发布、旧主站后发布不回退）；d1–d3 保留。
- 第二次连续运行（d4）→ d1–d4 全在，列表完整；同日重复运行 → 结果幂等。
- ref 不存在 / 解包失败 → 非零退出，不进入后续步骤。
- **workflow 结构断言**（`test_workflows.py`，解析 YAML）：
  - `update.yml`：保留 `repository_dispatch: [morning]` 与 `workflow_dispatch`；无 quant 步骤；`restore` 在 `main.py` 之前；发布源为 staging、`keep_files: true`、无 `exclude_assets` / `force_orphan`；重试步骤条件 = 首次 `outcome == 'failure'` 且 `should_deploy == 'true'`；首次步骤 `continue-on-error`、重试步骤不带；邮件条件含最终部署成功；`should_deploy != 'true'` 时两次发布与邮件均不执行。
  - `backtest.yml`：gh-pages 发布同样的首次 + 重试结构，无 force；main 的 commit/push 段不变。
  - `quant.yml` 不存在；`keepalive.yml` 不变。

### 5.4 一次性金样对比（不进仓库，`/tmp/trend-refactor/`）

改动前已用当前代码 + 真实数据快照（27 指数）+ 冻结时间产出基线（`before/`）。每个阶段后同输入重跑，单元格级比对（按 表 × 指数代码 × 列 对齐）。**各阶段允许差异独立维护，不提前放行**：

| 阶段 | 允许差异 |
|---|---|
| D3 | 归档页新增「量比」列 |
| 模板统一 / Python 结构 | 无单元格差异（结构性：site-nav 空槽、归档弹窗、archive_list 的 GA、错误行 colspan） |
| B1 | 「强度变化」列 |
| B2 | 「周月状态」列 |

### 5.5 其他回归

- `python scripts/main.py --mock-date 2026-10-19 --dry-run` 输出不变。
- workflow：YAML 解析校验；`site_publish restore` 对真实 `origin/gh-pages` 演练到 `/tmp`，文件数 = gh-pages 当前 `archive/` 数。

## 6. 验收（执行者自行完成）

1. 门禁测试全绿（§5 口径）。
2. 真实数据跑一遍：复制 `docs/` 到 `/tmp/trend-site`，`restore_archives` + `run()` 输出到该目录（不污染仓库 `docs/`）。
3. `python -m http.server` 起服务，浏览器（桌面 1280 + 手机 390 宽）验：首页两表 14 列、数值与线上同日对照合理、列说明弹窗（点击 / 遮罩 / Escape 关闭）、新归档页弹窗有样式 + 量比列、归档列表含恢复日期、抽查恢复的归档页、旧归档页（tooltip 样式）、`/quant/` 仍可访问、site-nav 不可见、css 相对路径正确。截图留证。
4. 线上（用户 push 后）：首次发布及下一次定时更新后各核对一次归档集合与回测报告未回退（交付说明给出检查命令）。

## 7. 执行顺序

1. ✅ 金样基线（§5.4，已完成，改动前）
2. 测试骨架 + 特征化测试（对当前代码绿）
3. B5：红测试（19 根数据不崩）→ 修 → 绿
4. D3：红测试（归档 14 列含量比）→ 在现有归档模板补列 → 绿 → 金样（仅量比列差异）
5. Generator.render + 模板拆分 + 预留位 → 金样（零单元格差异）+ 测试
6. Python 结构（4.4，不含 B1/B2）→ 金样（零单元格差异）+ 测试
7. B1：红 → 实现 → 绿 → 金样（仅强度变化列）
8. B2：红 → 实现（含取数窗口）→ 绿 → 金样（仅周月状态列）
9. B4 + quant 入口下线（review R3-M1：同一步完成，workflow 结构断言才能整体转绿）：`site_publish` 红绿 → `test_workflows.py` 红 → 删 `quant.yml`、删 `update.yml` 的 3 个 quant 步骤并改 concurrency 名，改 `update.yml`（restore / staging / 重试 / 邮件条件）与 `backtest.yml`（发布重试）→ 绿 → 恢复清单 + 归档恢复 + 校验
10. CLAUDE.md 更新 + 交付说明
11. 全量测试 + 验收（§6）

不 commit，完成后交用户验收；交付说明列出：需 `--no-verify` 提交的归档、需停用的 cron-job.org quant 任务、部署前 gh-pages SHA、push 后两次线上核对方法。

## 8. 执行记录（2026-10-19，已完成，待用户验收）

- Review：4 轮（gpt-6-astra），R1 6/10 → R2 7/10 → R3 7/10 → R4 **APPROVE 9/10**。
- 测试：门禁 `scripts/tests` 73 + `scripts/backtest` 97 = **170 passed**；`scripts/quant/tests` 179 passed（不阻塞）。
- 金样（27 指数真实快照，改动前 vs 最终）：差异仅 D3 量比列、B1 强度变化 23 格、B2 周月状态 1 格（XAG 月线）；独立 oracle 对首页 / 归档页各 378/378 格一致。
- 真实联网验收：24 个 A/港/美指数个体指标与线上 2026-10-16 页面逐格相同；差异仅 BTC/XAU/XAG（线上生成后的新 K 线）、组内名次联动与 B1/B2。
- 与计划的偏差：
  1. backfill 改用共享 `process_indices` 从第 6 步移到第 8 步（与 B2 重采样耦合，保证第 6 步零行为变化）。
  2. 新增一处小修：`DataFetcher` 缓存未命中时返回了缓存对象本身（调用方修改会污染缓存），改为缓存副本 —— 由新增契约测试发现。
  3. `sort_by_deviation` 显式使用 `(−偏离率, order)`，与原稳定排序等价。
- 归档恢复：115 个写入 `docs/archive/`，清单 `agents/results/2026-10-19-archive-recovery-manifest.md`。
- 观察到的既有风险（未修，超出范围）：yfinance 被限流时内部抛 `TypeError`，`DataFetcher` 按原契约上抛，整次更新失败（旧代码同样如此）。

## 9. 追加（2026-10-19 午间，用户确认「清理并修根因」）：force 语义 + 非交易日页清理

**现象**：周一手动 `force` 运行 → `record_date = 昨天 = 10-18（周日）` → 首页标为 2026.10.18、生成 `archive/2026-10-18.html`；新流程 keep_files + restore 使其永久留存。另有 4 月遗留的周日页 `2026-04-12`（main 与 gh-pages 均有）。

**根因修复**：行情日改为「沪深300 最新 K 线日期」，取数失败时回退昨天。
- 正常运行（非 force）：过旧检查保证该日期 = 昨天，输出与现状完全一致。
- force 于周末 / 节假日：页面与归档落在最近交易日（如 10-16），不再产出非交易日页面。
- 实现：`_a_share_date()` 单一来源，供过旧检查与 `record_date` 共用。

**TDD**：`test_main_flow` 新增「周一 force → 归档为 2026-10-16.html、首页日期 2026.10.16」（红 → 绿）；`test_deploy_when_data_fresh` 收紧为断言归档文件名 = 行情日。

**清理顺序**（必须先清 gh-pages 再重跑，否则 restore 会把 10-18 带回来）：
1. main：修复 + 测试 + 删除 `docs/archive/2026-04-12.html` → push。
2. gh-pages：删除 `archive/2026-10-18.html`、`archive/2026-04-12.html`，以剩余归档重生成 `archive/index.html`（保留线上 GA ID）→ push。
3. 手动 `force` 运行 update.yml → 首页回到 2026.10.16，10-16 归档以新模板重生成。
4. 线上验收脚本期望全部通过（含「首页行情日为交易日」「归档无非交易日页」）。
