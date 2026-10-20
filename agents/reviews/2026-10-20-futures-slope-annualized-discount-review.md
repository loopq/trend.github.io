# Plan Review: 2026-10-20-futures-slope-annualized-discount

**Plan File**: /Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-20-futures-slope-annualized-discount.md
**Reviewer**: Codex

---

## Round 1 — 2026-10-20

### Overall Assessment

复用已校验的合约日线、在纯计算层增加序列与摘要、独立注入模板的方向合理；本人从本地行情快照独立复算，计划中的当前值、分位和半年最低值均吻合，但页面读数方向冲突及原图金样验收缺口尚未闭合，发现 2 项 High，无 Critical。此前没有本计划的评审文件，本轮问题均为新增、状态 Open；本次由 Codex 亲自读取文件、复算和运行测试，未调用 skill、子代理或 Claude Code。计划没有 PRD 双链接或飞书 URL，且声明需求来自截图，因此记录 **PRD validation skipped — no local copy**：可以核对计划自述及现有代码，不能宣称已验证原始截图需求的完整覆盖、扩展范围或原始数据/API/埋点字段。

# Plan Review Result

## Decision

REQUEST_CHANGES

## Score

6 / 10

原图对照验收所需的独立预期值属于缺失的关键上下文，按评分规则最高 6 分；并非计算方案方向错误。

## Blockers

- **H1 · High · Open — 全局贴水方向说明与新增斜率符号相反。** 计划定位：[§2 定义，第 36 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-20-futures-slope-annualized-discount.md:36)、[§3 模板改动，第 47 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-20-futures-slope-annualized-discount.md:47)、[§4.4 保留现有内容，第 60 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-20-futures-slope-annualized-discount.md:60)。现有 [模板第 24 行](/Users/loopq/dev/git/loopq/trend.github.io/templates/futures.html:24) 在导航和所有模块之前无条件声明“数值越大表示贴水越深”；按计划新增模块后，这条全页说明仍然覆盖负值斜率，而斜率应是 −12% 比 −8% 更深。仅在新模块下方再写一条相反说明，不能消除同页自相矛盾，读者仍可能反向理解主要指标。**改进：**在 §3 明确修改这条共享说明，改为中性说明，或明确限定正向读数仅适用于现有基差/跨期价差模块；新模块同时写明“斜率越小、越负，远月相对当季贴水越深；分位越低越深”。共享说明位于两个旧 section 之外，修改它不需要改变旧模块 HTML、计算或图表。增加页面断言，防止全局再次出现没有适用范围的正向读数指引。

- **H2 · High · Open — 原图对照验收缺少独立预期值，盘中归因未证实。** 计划定位：[需求来源，第 4 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-20-futures-slope-annualized-discount.md:4)、[§1 口径反推，第 16–25 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-20-futures-slope-annualized-discount.md:16)、[§3 页面说明，第 47 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-20-futures-slope-annualized-discount.md:47)、[§4.2 原图验收，第 58 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-20-futures-slope-annualized-discount.md:58)。计划要求七日 × 两品种逐点等于“原文 14 个数”，但没有原图附件位置、原文链接或这 14 个预期值；文档只记录了最新两点的作者值。找到的 [官方行情缓存](/private/tmp/futures-slope/cffex.pkl) 与 [生产输入快照](/private/tmp/futures-slope/data-1019.pkl) 只有行情，不能作为“作者原图数字”的独立证据；两个计算器对同一行情算出相同结果，也不能证明匹配原图。最新两点存在差异且文章发表于当晚，并不能排除其他原因，因此 §4.2 将其直接标成“盘中取数”超出了现有证据。**改进：**在计划中登记可读取的截图/原文来源，并列出八日 × 两品种的作者原值、采用口径对应的合约与收盘计算值，固定为独立金样；预期值不能由待测公式现场生成。将差异原因写成“未确认，可能为盘中取值”，除非补充实际取数时点证据。若确实无法取得原图，应明确调整“复现作者原图”的验收承诺，改为已明确的收盘口径验收，不再声称验证了 14/16 命中。这一阻断针对 §4.2 无法独立执行的验收条件，而非要求补办一份形式上的飞书 PRD。

## Required Changes

- 关闭 H1：把共享说明的修改纳入模板范围与页面测试，保持原 IC/IM 两节及其计算结果不变。
- 关闭 H2：补齐可追溯的原图金样及差异记录，或明确修订验收目标；区分已验证的收盘计算结果和未证实的作者取数时点。
- 达到 8+ 不需要重构取数、引入新依赖或改变公式；需要让口径说明与验收依据一致，并保留计划已有的独立 oracle、严格 JSON、全量回归及浏览器验收路径。

## Missing Context

- 缺少原始截图及其中 14 个历史预期值，影响 H2。计划自述以外的需求完整性和范围授权无法独立核对；不据此认定新增分位/半年最低值必然属于越界，也不虚构未提供的 API 或埋点要求。
- 已读取 [项目规范](/Users/loopq/dev/git/loopq/trend.github.io/.claude/CLAUDE.md)、前置计划、分析/取数/CLI/模板、Generator 及现有期指测试。项目规范未给出名为 Code Quality Hard Limits 的额外数值阈值，不能凭空追加行数或文件规模限制。现有 `_history` 已有角色排序，`_rank` 已实现含等号的取整分位，可以复用；无需新建通用分析框架。
- 已核验本地快照每品种 1026 日的末两档合约相隔三个合约月份；[中金所合约文本](https://www.cffex.com.cn/u/cms/www/202207/18190308vxpv.pdf) 也明确 IM 合约月份为当月、下月及随后两个季月。独立计算得到 IC 当前 −9.6990374%、全样本/近一年分位 8%/31%、半年最低 −10.8090439%（2026-09-11）；IM 当前 −10.2761164%、分位 25%/62%、半年最低 −12.6608434%（2026-07-01），与计划一致。八日 × 两品种的缓存官方收盘与本地 bars 计算也一致；这些核验没有验证作者截图。
- 实际运行 `venv/bin/python -m pytest scripts/tests/test_futures_analysis.py scripts/tests/test_futures_data.py scripts/tests/test_futures_page.py -q`：**56 passed，1 failed**。唯一失败在 [端口超时测试第 101 行](/Users/loopq/dev/git/loopq/trend.github.io/scripts/tests/test_futures_data.py:101)，原因是当前沙箱禁止 `socket.bind`（`PermissionError: Operation not permitted`），并非发现超时实现不正确。本轮未运行主站与回测全量测试，也未实现或浏览器验收新模块。

## Risk Assessment

- logic: 公式、分母、百分数倍率及两个统计窗口定义清楚，离线复算未见错误。角色必须取每日到期排序的第 3/4 档，不能改成最近两个季月，也不能误用现有“今日提示”的移仓目标。
- state: 低风险。每日纯函数重算，无新增持久状态；现有 CLI 异常处理与 Generator 原子替换可继续保证失败保留旧页面。
- data: 输入层已保证完整日期、每日四合约、收盘有限且大于零，因此无需为正常生产路径增加缺价填零或静默删日逻辑。主要未闭合风险是 H2 的原图证据及不确定归因，不是已复算的数值。
- UI: 高风险集中在 H1 的方向冲突。新图还应沿用时间轴、resize、表格横向滚动和现有图表的无障碍描述，清楚区分百分比斜率与旧模块点数口径。
- regression: 增量边界总体合理，旧模块数据结构无需改变。现有 [assert_page 第 19 行](/Users/loopq/dev/git/loopq/trend.github.io/scripts/tests/test_futures_page.py:19) 依赖“第一个 JSON script”，加入第二份数据时应按 `#futures-data` 与 `#slope-data` 分别取值；旧 section 的逐字节比较应使用同一份输入与固定上下文，避免两次实时取数造成无关差异。

## Test Requirements

- unit: 保留计划已有的手算、含等号分位、并列最低值及窗口边界测试；手算覆盖负值、零价差和正值，计算保持全精度，仅展示时舍入。用明确合约代码覆盖角色切换：例如 IC 在 2026-10-16 的当季/下季为 IC2612/IC2703，2026-10-19 为 IC2703/IC2706；覆盖年末跨年、日历月偏移及样本尚不足一年/半年的合法历史截至日。核验只使用 `[START, T]`，输入 bars 不被修改。
- integration: 两份 JSON 各按 ID 严格解析，序列、合约 tooltip 数组和摘要逐项对照独立 oracle，拒绝 NaN/Infinity；H2 金样必须来自独立登记的原图数据。以同一份冻结输入比较改动前后的 `#IC`、`#IM` 与旧 `futures-data`，保留旧表格、提示、图表及失败保留页面断言；补 H1 的说明范围断言。实施后运行计划要求的 `pytest scripts/tests scripts/backtest`，端口测试需在允许绑定本地端口的环境执行。
- manual: 三张图均可用；新图默认近一年且可拖回样本起点，IC/IM 数值与各自合约 tooltip 对齐，移动端无页面级横向溢出；在新模块与旧模块之间阅读时不会把“更负”误解为“更浅”。核对新图的无障碍描述与小表可读性，再执行本地真实数据 oracle 和既有线上验收扩展。

## Final Verdict

暂不建议执行；先消除全页读数方向冲突并闭合原图金样验收，计算与模块划分可以保留。

---

## Round 2 — 2026-10-20

### Overall Assessment

修订已解决第 1 轮两个 High 阻断：统一正值读数后同步调整了分位方向、半年极值及原图对照方式，截图与逐点金样也已补齐，方案可以实施。本轮由 Codex 亲自重读计划、前轮评审及相关源码，实际查看两张原图并独立复算，未调用 skill、子代理或 Claude Code；未发现新的 Critical、High 或 Medium，仅有一处不阻断实施的标题残留。计划仍没有飞书 PRD 双链接，记录 **PRD validation skipped — no local copy**，但本轮已直接核对存档的原图和原文说明，不再存在上一轮的截图证据缺口。

# Plan Review Result

## Decision

APPROVE

## Score

9 / 10

## Blockers

- 无未关闭的阻断项。
- **R1-H1 · High · Closed（计划层面）**：[§2 第 49–53 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-20-futures-slope-annualized-discount.md:49) 明确将输出改为 `(当季收盘 − 下季收盘) × 400 / 当季收盘`，分位越高越深，半年最深改取最大值；[§3 第 61、65 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-20-futures-slope-annualized-discount.md:61) 同步规定说明文案和页面断言。此方案与现有全局说明同向，不必修改旧模块；原图反号关系也已明示，关闭原来的全页读数冲突。剩余标题措辞单列为下方 L1。
- **R1-H2 · High · Closed（计划层面）**：已实际查看 [作者图表](/Users/loopq/dev/git/loopq/trend.github.io/agents/results/2026-10-20-futures-slope-author-chart.png) 与 [作者文章截图](/Users/loopq/dev/git/loopq/trend.github.io/agents/results/2026-10-20-futures-slope-author-article.png)，八日 × 两品种的 16 个标注值与 [§1 金样表第 18–27 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-20-futures-slope-annualized-discount.md:18) 一致。正文确实采用正值表述、图表采用负值绘制；[§4.2 第 72 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-20-futures-slope-annualized-discount.md:72) 要求对输出取负后比较固定原值，并将最新两点的差异原因标为“未确认”，不再把盘中取值当成已证实事实。

## Required Changes

- 无达到 8+ 所必需的阻断性改动。
- **L1 · Low · Open — 模块标题的减法顺序仍与正值公式相反。** 位置：[文档标题第 1 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-20-futures-slope-annualized-discount.md:1)、[§3 模块标题第 61 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-20-futures-slope-annualized-discount.md:61)。标题仍写“年化贴水（下季 − 当季 斜率口径）”，而 §2 的实际计算已改为当季减下季；只看标题会得到相反的减法顺序。**改进建议：**在实施时改为“IM / IC 年化贴水（当季 − 下季）”，或“IM / IC 季月间年化贴水”，在说明中保留“原图以相反符号绘制”。计算定义、全局方向和验收方式均已明确，因此此项为文案修正，不要求重新设计或暂停实施。

## Missing Context

- 没有阻断当前计划实施的缺失上下文。原图包含日期、IC/IM 曲线、百分数标注和公式，原文说明也已读取；现有输入表和 CLI 足以承接实现，原文没有额外 API 或埋点字段需要映射。分位、半年最深及全样本回看属于计划明确列出的扩展，不应在交付说明中称为作者原图已有功能。
- 本轮从现有 [行情快照](/private/tmp/futures-slope/data-1019.pkl) 重新按正值公式计算，未使用待实现的 slope 函数：IC 当前 9.6990374%，全样本/近一年分位为 92%/69%，半年最大 10.8090439%（2026-09-11）；IM 当前 10.2761164%，分位为 75%/38%，半年最大 12.6608434%（2026-07-01），均与 §1 一致。近一年样本数为 242，含等号计数分别为 168 和 92；这些分位是重新统计的结果，并非简单用 100 减去旧版已舍入分位。八个抽样日还与 [官方行情缓存](/private/tmp/futures-slope/cffex.pkl) 交叉核对，反号后前七日 14 点吻合截图，末日两点仍为计划明确记录的差异。
- 已复核项目 CLAUDE.md、输入校验、角色分配、`_rank`、CLI、模板、oracle 和原子写路径，未发现新增的 Code Quality Hard Limits 数值条款。本轮没有重跑未改动的测试；第 1 轮的 56 passed 与端口绑定受沙箱限制的 1 failed 仍是既有基线，不能当作新模块的验证结果，实施后的全量测试和浏览器验收仍须执行。

## Risk Assessment

- logic: 低风险。反号后的当前值、含等号分位和半年最大值相互一致；第 3/4 档角色与“最近两个季月”及今日提示目标已经明确区分，避免选错合约。
- state: 低风险。没有新增持久状态，分析失败可沿用 CLI 非零退出及 Generator 原子替换，保留原页面。
- data: 现有完整性校验覆盖日期集合、每日四合约、重复键及有限正收盘，新增公式可复用其前置条件。原图金样已独立固定，最新日差异公开保留，不要求修改计算结果去迎合原图。
- UI: 正值口径与现有页面一致，原图的反号关系已说明；仅 L1 标题仍有轻微歧义。实施时沿用现有时间轴、resize、表格滚动与无障碍描述即可。
- regression: §3 已补上按 JSON ID 定位及同一份冻结输入下的旧 section/旧 JSON 比较，解决上一轮提及的标签顺序依赖和取数漂移。仍应保持旧图表初始化、取数与 workflow 的范围约束。

## Test Requirements

- unit: 按 §3 覆盖正/零/负价差、四档角色切换、跨年、含等号分位、窗口开闭边界、短样本、半年最大值并列取最早及输入不变。正值分位须直接计数，不能从负值分位取补数；原图符号转换仅用于对照验收。
- integration: 新序列和摘要由独立 oracle 重算，两份 JSON 分别按 ID 严格解析；前七日取负后与截图固定金样比较，最新日只记录差异。用同一份输入保留旧两节 HTML、旧 JSON、旧图表和失败保留页面断言；完成计划要求的主站与回测全量测试，端口超时测试在允许本地 bind 的环境执行。
- manual: 新图及原有两图均可用，默认窗口为近一年且可回看至样本起点，tooltip 中日期、数值和合约对应正确；检查全局说明、标题、公式及坐标轴方向一致，移动端无页面级横向溢出，并完成真实数据 oracle 与计划中的上线检查。

## Final Verdict

可以按修订计划实施；顺手统一标题中的减法顺序，随后按既定测试与验收路径完成验证。
