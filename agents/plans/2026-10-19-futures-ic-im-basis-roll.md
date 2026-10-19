# 期指观察：IC/IM 贴水曲线 + 移仓点统计（需求 4659）

> 日期：2026-10-19 · 范围：新子系统 `scripts/futures/` + `templates/futures.html` + 站点入口 + `update.yml` 一个步骤 + `Generator.render` 原子写 + `main.py` 输出行情日
> 需求来源：无 PRD 文档；需求 4659 原文仅一句（见下），范围由本会话 grill-me 澄清确定（§0），用户已确认共同理解。
> 前置：`agents/plans/2026-10-19-site-refactor-futures-entry-slot.md`（入口槽 / `Generator.render` / `SITE_DIRS` 已预留并上线）
> 流程：grill-me（已确认）→ 本 plan → `/plan-review-codex`（gpt-6-astra）→ TDD 实施 → 本地起服务交用户验收 → 用户同意后才 commit；不 push。
> Review 记录：`agents/reviews/2026-10-19-futures-ic-im-basis-roll-review.md`

需求原文：「大屁股，这个 agent 能写一个跟踪 IC/IM 价差曲线并分析移仓点的程序？我已经写了，并且已经在运行了，逐日观察，我自己换仓的时候，我会提醒你们的。」入口：trend.loopq.cn 右上角「期指观察」。

## 0. 已确认决策（grill-me）

| # | 决策 |
|---|---|
| 1 | 「价差」= **同品种**贴水与跨期价差（IC、IM 各自看）；「移仓」= 换月。不做 IC↔IM 跨品种 |
| 2 | 立场：**多头吃贴水**（远月相对近月贴水越深，移仓越划算） |
| 3 | 贴水口径：**单月贴水（点/月）=（现货 − 期货收盘）÷ 剩余自然日 × 30**；表格另附年化 % |
| 4 | 曲线：每品种一张图，**次月 / 当季 / 下季 3 条**（§9：当月不展示），图例可开关，**默认只显示次月 + 下季** |
| 5 | 图表：**ECharts，vendor 本地**；横轴日期、左轴点数；**默认近 3 个月，可缩放拖回 2022-07** |
| 6 | 回测 = 统计，不做收益模拟：① 各角色单月贴水的**历史分位**；② **移仓时点**：每次月度到期前第 1–20 交易日，当月 → 次月 / 当季 / 下季三路径的跨期单月价差 |
| 7 | 样本窗口：**2022-07-22（IM 上市）起**，两品种同窗口 |
| 8 | 数据：**每日全量重算、无状态**（与主站一致） |
| 9 | 调度：**并入 `update.yml`**，主站生成后独立步骤，`continue-on-error`，与主站同次部署 |
| 10 | 页面顶部每品种一行**客观提示**（事实陈述，不下指令） |
| 11 | 不做：通知、个人换仓记录、按日归档、盘中数据、IF/IH、收益回测 |

## 1. 已实测事实（AkShare 1.18.55，2026-10-19）

| 事实 | 依据 |
|---|---|
| `ak.futures_zh_daily_sina(symbol="IC2611")` 返回单合约全生命周期日线（date/open/high/low/close/volume/hold/settle）；**过期合约可取**；**未上市合约抛 ValueError** | 实测 |
| 2022-07-22 ~ 2026-10-16：IC、IM 各 54 个合约、**1025 个交易日每日恰好 4 个合约**、合约存续期内**零缺日**、期货日期集合 == 现货日期集合、无空/零收盘 | 实测（`/tmp/futures-probe/raw.pkl`） |
| **跨源**：抽 12 个交易日（含 2022-07-22、普通月/季月到期日、最新日）共 96 个「日 × 合约」，新浪收盘 == `get_cffex_daily` 官方收盘 **96/96**；持仓量仅在**到期日的到期合约**不同（官方交割后记 0，新浪为交割前持仓） | 实测 |
| **到期规则**：54 个已到期合约的末根日期 == 「到期月第三个周五，遇非交易日顺延」**54/54**（日历取新浪） | 实测 |
| **挂牌规则**：102 个到期事件，到期日 `E` 当日在市合约 == `[c0, c0 的下一个月, 其后两个季月]` **102/102** | 实测 |
| 单合约取数 ~0.17s，全量 ~108 合约 ~20s | 实测 |
| `ak.futures_contract_info_cffex(date)` 给出当日挂牌合约的官方最后交易日 | 实测 |
| `ak.tool_trade_date_hist_sina()` 交易日历 1990-12-19 ~ **2026-12-31** | 实测 |
| AkShare 的 `futures_zh_daily_sina` / `futures_contract_info_cffex` 内部 `requests.get` **无 timeout** | 源码（review H2） |
| 过去一年主力（持仓最大）**241/241 天是季月合约**，每季在季月到期前约一周换月 | 实测（支撑「4 条线全画」） |
| ECharts 6.1.0 `dist/echarts.common.min.js` 715KB（gzip 240KB），含 line / legend / tooltip / dataZoom，Apache-2.0 | `npm pack echarts@6.1.0`（npm 校验 integrity） |

## 2. 数据结构与输入契约

一个品种只有三张输入表，全部派生量都是它们的纯函数：

```
calendar : DatetimeIndex                        # 新浪交易日历（历史 + 当年未来），交易日的唯一定义
spot     : date, close                          # 现货指数（000905 / 000852），date ⊆ calendar
bars     : date, contract, close, oi            # 合约日线
expiry   : {contract: 最后交易日}                # 规则推导（见下），对官方 / 末根做校验
```

**交易日只由 `calendar` 定义**，行情记录缺行不能改变交易日（review H3）。

**到期日**：`rule_expiry(contract)` = 到期月第三个周五，若非交易日则顺延到 `calendar` 中下一交易日。`calendar` 未覆盖该月时（如 2027 季月）用 `futures_contract_info_cffex(T)` 官方值。校验：已到期合约末根 == `rule_expiry`；在市合约若规则可算则须 == 官方值。

**移仓目标**（挂牌规则，review H1）：`targets(c0) = [c0 下一个月, 其后第一个季月, 其后第二个季月]` → 路径槽位「→次月 / →当季 / →下季」。纯月份算术，历史事件与今日提示**共用同一定义**；校验：每个历史事件 `E` 当日在市合约 == `[c0] + targets(c0)`。

**角色**（当日表与曲线）：当日在市合约按 `expiry` 升序 → `当月 / 次月 / 当季 / 下季`。

**运行时输入契约**（任一不满足 → `FuturesDataError`，页面不更新；review H3）：

1. `T` = **本次主站实际采用的行情日**，生产经 `--as-of` 传入（主站 `run()` 写 GITHUB_OUTPUT `record_date`，review R2-H1），期指不再自行选择；仅本地手动运行省略 `--as-of` 时取沪深300 最新 K 线日（与 `_a_share_date` 同语义）。`T` 须为合法日期且 `T ∈ calendar`；现货与 `T` 日在市 4 个合约都必须有 `T` 日 K 线，数据源已有 `T` 之后的 K 线一律截掉（与主站同一天）。
2. `spot`：日期唯一；`[START, T]` 内日期集合 == `calendar ∩ [START, T]`；收盘有限且 > 0。
3. `bars`：`(contract, date)` 唯一；收盘有限且 > 0；**`calendar ∩ [START, T]` 的每一天恰好 4 个合约**（按日历遍历，而非按数据中出现的日期）。
4. 每个合约在 `[首根, min(末根, T)]` 内的日期 == 该区间的 `calendar`（存续期内零缺行）。
5. 到期日与挂牌规则校验（上文）。
6. 在市合约（`futures_contract_info_cffex(T)`）== `T` 当日 bars 中的 4 个合约。

不复用 `DataFetcher._standardize_dataframe` 处理期货（它会静默删行）；现货经 `fetch_index` 取得后再按第 2 条校验，静默删行会被日期集合比对捕获。

## 3. 指标定义（页面上每个数字的唯一来源）

常量：`START = 2022-07-22`，`WINDOW = 20`，`ROLES = [当月, 次月, 当季, 下季]`，`PATHS = [→次月, →当季, →下季]`。

**空值契约**（review M3）：正常缺失（`D < MIN_DAYS`、目标未上市、无样本）在分析层为 `None`；展示层显示「-」；图表 JSON 为 `null`。输出中不得出现 NaN / Infinity。

| 指标 | 定义 |
|---|---|
| 剩余天数 `D` | `(expiry − date).days`（自然日） |
| 贴水（点） | `spot − close`（正 = 贴水） |
| 单月贴水（点/月） | `贴水 / D × 30`（**当月不展示**，见 §9；展示角色 D ≥ 24，分母不会过小） |
| 年化贴水（%） | `贴水 / spot × 365 / D × 100` |
| 历史分位表 | 每品种 × 角色：`[START, T]` 内非空单月贴水的 P10/P25/P50/P75/P90（线性插值）+ 样本数 |
| 当前分位 | `T` 日该角色单月贴水 `x`；`x` 为 `None` → `None`；否则 `count(样本 ≤ x) / count(样本) × 100` 取整 |

**移仓时点统计**（每品种）：

- 事件：每个已到期合约 `c0`，到期日 `E ∈ (START, T]`。
- 第 N 日：`t_N` = `calendar` 中 `E` 往前第 N 个交易日（N = 1..20，`(t_N, E]` 恰含 N 个交易日）；`t_N < START` 不计。
- 跨期单月价差：`v(N, 路径) = (close_c0(t_N) − close_目标(t_N)) / (expiry_目标 − E).days × 30`，目标 = `targets(c0)` 的对应槽位；目标在 `t_N` 未上市 → `None`。多头卖近买远，同一事件内两次移仓的收益差恰为价差差，故 `v` 越大越划算。
- 汇总（每 N × 路径），**样本 = 配对集合 P(N) = {事件 | v(N) 与 v(1) 均非空}**（review M1）：`较第1日 = mean(v(N) − v(1))`，`胜率 = count(v(N) > v(1)) / |P(N)| × 100`，`n = |P(N)|`；`n = 0` → 全部 `None`。N = 1 时较第1日 = 0、胜率不定义（显示「-」）。
- 不同 N 的事件集合可能不同（远期目标在较早的 N 尚未上市），页面注明。
- 最划算 N（每路径）：`n > 0` 的 N 中「较第1日」最大者，并列取较小 N。

**今日提示**（每品种一行，事实陈述）：

- `c0` = `T` 日在市且 `expiry > T` 的最近合约；目标 = `targets(c0)`（到期当日新次月尚未挂牌 → 该槽位为「未上市」，不重新编号）。
- `N_now` = `calendar` 中 `(T, expiry_c0]` 的交易日数。**日历未覆盖到 `expiry_c0`**（跨年且新年日历未发布）时：天数显示「约 N 个交易日（按工作日估计）」，**不输出窗口判断与同期分位**（review M2）。
- 三路径当前值 `v_now`（`T` 日，同 `v` 公式），最高者加粗。
- `N_now ≤ WINDOW` 且日历覆盖：附「同期（到期前第 N_now 日）历史分位」= `count(历史非空 v(N_now, 路径) ≤ v_now) / count × 100`，并注明样本数；`N_now > WINDOW`：提示「尚未进入统计窗口（≤20 个交易日）」。
- 附「历史上 →X 平均最划算：到期前第 k 个交易日（较第 1 日 +y 点/月，胜率 z%，n 次）」，X = 当前值最高的路径。

## 4. 实现

### 4.1 文件

| 文件 | 内容 |
|---|---|
| `scripts/futures/__init__.py` | 常量：`START`、`VARIETIES = {"IC": ("000905", "中证500"), "IM": ("000852", "中证1000")}`、`ROLES`、`PATHS`、`MIN_DAYS`、`WINDOW` |
| `scripts/futures/data.py` | I/O + 输入契约：`load_calendar`、`load_variety`、`FuturesDataError`；请求超时 |
| `scripts/futures/analysis.py` | 纯函数：`rule_expiry`、`targets`、`daily_table`、`percentile_table`、`roll_events`、`roll_stats`、`today_hint`、`chart_series`（输出均已是 `None` 而非 NaN） |
| `scripts/futures/__main__.py` | CLI `python -m scripts.futures [--out docs] [--as-of YYYY-MM-DD]`：取数 → 校验 → 分析 → `Generator.render("futures.html", "futures/index.html")`；任一步失败非零退出、正式页面不变 |
| `templates/futures.html` | `extends "base.html"`；覆写 `site_nav` 为「趋势首页」；每品种：提示行、图表、今日合约表、分位表、移仓时点表；数据以 `<script type="application/json">{{ data|tojson }}</script>` 内嵌 |
| `templates/base.html` | `site_nav` 默认内容 = `<a href="{{ root }}futures/">期指观察</a>`（所有主站页面生效） |
| `scripts/generator.py` | `render` 改为**原子写**：先写 `output_dir/.tmp/` 下的临时文件（同文件系统、**不属于 `SITE_DIRS`**，被强制终止留下的残片不会被 stage 发布；review M4 / R2-M1），再 `os.replace` 到正式路径；异常时删除临时文件。主站输出内容不变 |
| `scripts/main.py` | `run()` 确定 `record_date` 后写 GITHUB_OUTPUT `record_date=YYYY-MM-DD`（一行；review R2-H1） |
| `docs/futures/echarts.min.js` | vendor `echarts.common.min.js` 6.1.0（保留 Apache 许可头）；**提交到 main**，保证 `docs/futures/` 目录恒存在 |
| `.gitignore` | 加 `docs/futures/index.html`（CI 生成物，本地运行不得混入 main）与 `docs/.tmp/` |
| `scripts/site_publish.py` | `SITE_DIRS += ["futures"]` |
| `docs/css/style.css` | 追加期指页少量样式（图表容器高度、提示行、表格紧凑） |
| `.github/workflows/update.yml` | `Run update script` 之后、stage 之前加步骤（见 4.3） |
| `.github/workflows/trend-test.yml` | paths 加 `scripts/futures/**` |
| `.claude/CLAUDE.md` | 子系统与命令各加一行 |

`DataFetcher` 不改：现货复用 `fetch_index(code, "cs_index", days=…)`；期货合约日线形态（多合约 + 到期日）与指数不同，独立在 `scripts/futures/data.py`。

### 4.2 取数（`data.py`）

1. 进程内给 `requests.Session.request` 设默认超时 `(connect 10s, read 30s)`（仅期指 CLI 进程；主站进程不受影响）；每次请求最多 3 次尝试、间隔 1s/2s，耗尽 → `FuturesDataError`（review H2）。
2. `calendar` = `tool_trade_date_hist_sina`。
3. `T` = `--as-of`（生产）或沪深300 最新 K 线日（本地省略时），见 §2 契约 1。
4. 现货：`fetch_index(code, "cs_index", days=(今天 − START).days + 40)`，截取 `[START, T]`。
5. `active = futures_contract_info_cffex(T)` 过滤品种 → `{合约: 官方最后交易日}`。
6. 合约清单（确定性枚举，**不靠「拉不到就跳过」**）= `[2208, active 最早月份)` 的每个月份 ∪ `active`。
7. 每合约 `futures_zh_daily_sina`，截取 `date ≤ T`（不截 `START` 之前：末根校验需要完整生命周期；分析层按 `START` 过滤）。
8. 执行 §2 运行时输入契约 1–6。

### 4.3 workflow（`update.yml`）

```yaml
      - name: 生成期指观察页（失败 / 超时不影响主站部署）
        if: steps.run_script.outputs.should_deploy == 'true'
        continue-on-error: true
        timeout-minutes: 5
        run: python -m scripts.futures --out docs --as-of ${{ steps.run_script.outputs.record_date }}
        env:
          TZ: Asia/Shanghai
          GA_MEASUREMENT_ID: ${{ secrets.GA_MEASUREMENT_ID }}
```

行情日：`--as-of` 取主站本次 `record_date`，两页日期由构造保证一致。失败语义：CI checkout 中 `docs/futures/index.html` 不存在（gitignore），失败 / 超时 → 不生成 → stage 只带 `echarts.min.js` → keep_files 保留线上旧页（页面自带日期）。渲染为原子替换且临时文件在 `docs/.tmp/`（不在发布目录内），进程在写入中被终止也不会让半成品或残片进入发布树。主站部署、邮件门禁不受影响。非交易日 `should_deploy=false` 时整步跳过。

### 4.4 页面

- 入口：所有主站新生成页面右上角「期指观察」（`{{ root }}futures/`）；期指页右上角「趋势首页」。已上线的旧归档页不回填（静态快照）。
- 每品种一节：标题「IC · 中证500」+ 现货收盘 → 提示行 → 图表（4 条单月贴水线；`legend.selected` 仅次月、下季为 true；`dataZoom` inside + slider，`startValue` = `T` − 3 个月；tooltip 显示合约代码与点数；`null` 处断开）→ 今日合约表（角色、合约、最后交易日、剩余天数、收盘、贴水、单月贴水、年化%、历史分位、持仓量）→ 分位表（角色 × P10..P90 + 样本数）→ 移仓时点表（N 行 × 三路径各「较第1日 / 胜率 / n」）。
- 持仓量口径注明「新浪日线；到期日为交割前持仓」。
- 页脚：数据来源（新浪期货、中金所、中证指数）+ 生成时间。
- 移动端：图表宽 100%，表格沿用 `.table-wrapper` 横向滚动。

## 5. 测试（TDD：先写失败测试，再实现）

| 文件 | 覆盖 |
|---|---|
| `scripts/tests/test_futures_analysis.py` | `rule_expiry`（普通月、节假日顺延、日历未覆盖 → None）；`targets`（普通月、季月、跨年）；角色按 expiry 排序、季月到期后插入新次月；贴水 / 单月 / 年化手算值；`D < 7` 与 `D = 0` 为 `None`；分位 = numpy、当前分位含等号、`x = None` → `None`；事件 `t_N` 按日历（含节假日）；目标未上市 → `None`；`t_N < START` 不计；配对集合下的较第1日 / 胜率 / n（两事件手算反例：`v(N)=[2, None]`、`v(1)=[1, 1]` → 胜率 100%、n=1）；`n=0` 全 `None`；最划算 N 并列取小、跳过 `n=0`；提示：普通日、**普通月到期日 / 季月到期日 / 到期次日**的 `c0` 与三槽位具体合约断言、窗口外文案、日历未覆盖时不输出同期分位；输出无 NaN |
| `scripts/tests/test_futures_data.py` | 合约枚举（跨年、季月）；**输入契约反例**：删现货一日、删期货整日、删单合约末根、删存续期中间一行、重复键、收盘 0 / NaN / Inf、`T` 不在日历、在市清单不一致、末根 ≠ 规则到期日 → 均 `FuturesDataError`；`--as-of` 非法格式 / 非交易日 → 失败；**主站 T=10-16 而数据源只到 10-15 → 失败；数据源已到 10-19 → 截到 10-16 生成**；任一合约取数失败（重试耗尽）→ `FuturesDataError`；**请求超时**：本地起一个接受连接但不响应的 socket，验证请求在超时后失败且总耗时有界（全部离线，monkeypatch `ak.*`） |
| `scripts/tests/futures_oracle.py` | **独立实现**（不 import `scripts.futures.analysis`）：纯 Python / numpy 从原始 `bars/spot/calendar/expiry` 重算页面每个单元格与图表序列 |
| `scripts/tests/test_futures_page.py` | 合成数据经 `__main__` 真实链路渲染 → bs4 解析 → 每个表格单元格、提示行数字、内嵌 JSON == oracle；**内嵌 JSON 用严格解析（`parse_constant` 拒绝 NaN/Infinity）**；临期曲线含 `null`；图例默认选中、dataZoom 起点；`root` 相对路径、echarts `src`、GA；**取数失败 / 分析异常 / 模板异常 / 写入中途异常**：非零退出，干净目录不产生正式页面，已有正式页面逐字节不变 |
| `scripts/tests/test_generator.py`（加） | `render` 写入中途抛错 → 目标文件保持旧内容、无残留临时文件；**子进程写入临时文件后被 SIGKILL** → 正式文件不变，随后真实 `site_publish.stage` 的发布树不含任何临时文件 |
| `scripts/tests/test_main_flow.py` / `test_pages.py`（改） | GITHUB_OUTPUT 断言加 `record_date`（部署时 = 行情日；`should_deploy=false` 时不输出） |
| `scripts/tests/test_pages.py`（改） | `test_site_nav_slot_present_and_empty` → 入口存在且 href 正确：首页 `futures/`、归档详情 / 列表 `../futures/` |
| `scripts/tests/test_site_publish.py`（改） | seed 加 `docs/futures/echarts.min.js`、gh-pages 加旧 `futures/index.html`；stage 树含 `futures/`；**期指生成失败**时部署后线上旧 `futures/index.html` 逐字节保留、主站归档照常更新 |
| `scripts/tests/test_workflows.py`（改） | 期指步骤位于 `run_script` 与 stage 之间、`continue-on-error: true`、`timeout-minutes` ≤ 5、`should_deploy` 门禁、`--as-of ${{ steps.run_script.outputs.record_date }}`；trend-test paths 含 `scripts/futures/**` |

真实数据验证（一次性，结果记入 §8）：

1. 跨源校验（§1 已完成 96/96，实施后用生产代码路径复跑一次）。
2. 真实数据生成页面 → oracle 逐格比对全部相等；内嵌 JSON 严格解析。
3. 真实页面抽查：普通交易日、普通月到期日、季月到期日、到期次日的角色 / 槽位（用历史日期作 `T` 离线复算）。
4. 主站回归：`pytest scripts/tests scripts/backtest` 全绿；golden harness 对比首页 / 归档页，差异仅入口链接。
5. 本地 `http.server` + 浏览器：两张图渲染、默认 2 条线、默认近 3 个月、拖回 2022、临期断线、移动端宽度；截图给用户。

## 6. 验收标准

- 本地：上述全部通过；用户看过本地页面并同意后才 commit（身份 `loopq <apolozh0808@gmail.com>`），**不 push**。
- 线上（用户 push 之后）：首页右上角入口可达；`/futures/` 日期 = 首页行情日；echarts 加载。线上验收脚本 `/tmp/trend-refactor/acceptance/check_live.py`（仓库外）同步修改：**原「site-nav 为空」断言替换为「入口存在且 href 正确」**，并增加期指页检查项。

## 7. 风险

| 风险 | 处理 |
|---|---|
| 新浪单源，任一合约失败 → 当日期指页不更新 | 严格失败优于残缺数据；线上保留前一版，页面自带日期 |
| 取数挂起拖住主站部署 | 请求级超时 + 有界重试 + 步骤 `timeout-minutes: 5`，超时后 `continue-on-error` 放行 stage/deploy |
| `stage` 对 `futures/` 缺失敏感 | `echarts.min.js` 提交在 `docs/futures/`，目录恒存在；测试覆盖生成失败场景 |
| 半成品页面被发布 | 原子写；测试覆盖写入中途失败 |
| 跨年日历未发布 | 提示天数标「约」，隐藏窗口判断与同期分位 |
| 页面体积（4 年 × 8 序列内嵌 + echarts 240KB gzip） | 内嵌 JSON 约 150KB，可接受；不做按日归档 |

## 8. 执行记录（2026-10-19）

- Review：3 轮（gpt-6-astra）R1 6/10 → R2 7/10 → **R3 APPROVE 9/10**；R1 H1–H3、M1–M4 与 R2 H1、M1 全部关闭。
- 实施：由 `cxd-third`（codex，gpt-6-astra）按本 plan TDD 实施；调度方逐文件审查后修正两处：
  1. `Generator.render` 原子写由 `tempfile.NamedTemporaryFile`（产物权限 0600）改为 `.tmp/{pid}-{name}` + `open`，权限恢复遵循 umask（0644），少一个依赖；相应两条中断测试改为注入模块级 `open`。
  2. 图表配色：默认显示的次月 / 下季改为对比最强的红 / 绿；时间轴 `axisLabel.hideOverlap` 解决窄屏标签重叠。
- 规模：`scripts/futures/` 374 行 + `templates/futures.html` 105 行；主站改动 14 文件 +160/−18（含测试）。
- 测试：`pytest scripts/tests scripts/backtest` **232 passed**。
- 主站回归：golden harness（快照数据 + 冻结时间）对比首页 / 归档详情 / 归档列表，差异**仅** `site-nav` 一行入口链接（`futures/`、`../futures/`）；文件权限 0644。
- 真实数据 oracle（生产 CLI 联网生成 vs 独立 oracle，oracle 输入为另行拉取的新浪快照 + 自推到期日）：
  | T | 场景 | 结果 |
  |---|---|---|
  | 2026-10-16 | 最新日 / 普通月到期日（IC2610） | 536 格 + 8200 曲线点 + 2 行提示全等 |
  | 2026-08-21 | 普通月到期日（→次月 IC2610 未上市，槽位不重排） | 全等 |
  | 2026-09-18 | 季月到期日（→次月 IC2611 未上市） | 全等 |
  | 2026-09-21 | 到期次日（IC2611 挂牌，三路径齐全） | 全等 |
  | 2026-10-09 | 窗口内（到期前第 5 日，跨国庆）同期分位 n=50 | 全等 |
- 跨源：§1 96/96；另核 2026-08-18 异常尖峰（IC 次月 149.6 点/月）：期货收盘 == 中金所官方、现货 == 新浪指数，为真实行情（次日现货 −4.8%）。
- 浏览器（本地 http.server）：两图渲染、默认仅次月 + 下季、默认 2026-07-16 ~ 10-16、可缩放至 2022-07-22、tooltip 含合约代码；390px 宽无横向溢出。
- 线上验收脚本 `/tmp/trend-refactor/acceptance/check_live.py`：入口断言替换 + 期指 7 项（含「线上表格 = 本地同日重算」），已对本地预览空跑通过。
- 未 commit / push：等用户看完本地成品同意后再 commit。

## 9. 修订：移除当月展示（2026-10-19，用户验收反馈）

**反馈**：当月过了交割日（第三个周五）显示负贴水，当月统计没有意义。

**事实**：角色按当日在市合约排序，交割日次日当月即自动轮到下一合约，不存在「过了交割日还挂着当月」；用户看到的是 **T = 交割日当天**（10-16 = IC2610 交割日）：当月剩余 0 天、收盘已收敛到交割结算价，贴水 −32.45。此外当月剩余天数 0–35 天，单月贴水被小分母放大：历史 P10 −12.8 / P90 99，分布宽到没有参考价值；对多头它是「移出」对象而非比较目标。

**改动**：
- 曲线、图例、今日合约表、历史分位表**不再展示当月**（`SHOWN_ROLES = 次月 / 当季 / 下季`）；角色仍按 4 个在市合约排序分配，数据契约（每日 4 合约）不变。
- 展示角色剩余天数 ≥ 24（次月在当月交割日当天距自身到期 ≥ 4 周，节假日顺延后仍 ≥ 24），`MIN_DAYS` 及其空值分支成为死代码，**删除**。
- **保留**：移仓时点统计（本就是「当月到期前 N 日 → 次月 / 当季 / 下季」）与今日提示（点名要移出的当月合约）。

**验证**：
- 真实数据：展示角色（次月）最小剩余天数 **24 天**（2026-02-24，春节顺延的 IC2602 交割日 → IC2603），与上文下限一致；`MIN_DAYS` 删除安全。
- `pytest scripts/tests scripts/backtest` **232 passed**（测试改为断言：交割日当天表格只含次月 / 当季 / 下季、剩余天数 ≥ 24、曲线无空值）。
- 真实数据 oracle：T = 2026-10-16（当月交割日）/ 09-18（季月交割日）/ 02-13（春节前）全部逐格相等（每品种少当月 17 格：今日表 10 + 分位表 7）。
- 浏览器：图例 3 项（默认次月 + 下季）、今日表 3 行、分位表 3 行。
- 顺带删除死代码：`MIN_DAYS`、空样本分支、图表 `connectNulls` 与 tooltip 空值分支（展示角色不再产生空值）。
