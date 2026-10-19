# Plan Review: 2026-10-19-site-refactor-futures-entry-slot

**Plan File**: /Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md
**Reviewer**: Codex

---

## Round 1 — 2026-10-19

### Overall Assessment
模板去重、移除失效排名存储、按截至日的日线计算周月指标，方向合理，但计划尚未闭合保留回测功能的发布边界、回填历史长度和共享处理函数的错误路径，不能直接执行。首次评审，无历史问题需要追踪；本轮发现 4 项 High、2 项 Medium，无 Critical，证据来自本人读取代码、检查本地 Git 历史及离线复现，未调用 skill、子代理或 Claude Code。计划没有 PRD 双链接，也没有单独的飞书 URL，仓库内未找到需求 4659 的原文，因此记为 **PRD validation skipped — no local copy**；只能核对计划自述范围，不能宣称已验证原始需求的完整性、数据/API 或埋点字段一致性。

# Plan Review Result

## Decision
REQUEST_CHANGES

## Score
6 / 10

## Blockers

- **H1 · High · 主站部署仍会覆盖保留的在线回测产物。**
  **计划位置：** [§3 B4，第 66–67 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:66)、[§4.5，第 140–141 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:140)。
  **问题与证据：** 主站继续发布整个 `docs`，只恢复 `archive`，同时删除原步骤中部署前的 `git pull --rebase`；保留的在线回测会更新并单独发布同名回测报告和索引。对应代码为 [update 的 pull 与 publish_dir](/Users/loopq/dev/git/loopq/trend.github.io/.github/workflows/update.yml:94)、[backtest 的独立 concurrency](/Users/loopq/dev/git/loopq/trend.github.io/.github/workflows/backtest.yml:28)、[backtest 的提交和发布](/Users/loopq/dev/git/loopq/trend.github.io/.github/workflows/backtest.yml:102)。实际可发生的顺序是：主站 checkout → 回测发布新版报告及 index.json → 主站用旧 checkout 发布，在线回测结果被旧内容覆盖。`keep_files: true` 只跳过清空目录，同名文件仍强制复制；已核对 [Action v4 的 copyDirContents / setRepo 源码](https://github.com/peaceiris/actions-gh-pages/blob/v4/src/git-utils.ts)，并用临时目录复现“归档保留、同名报告和索引回退”。两个 workflow 也没有共同的发布串行约束。当前本地两分支的 quant 内容相同，并不能排除上述运行时交错。
  **改进建议：** 明确发布目录归属，主站使用不包含 quant 前端及数据副本的 staging 目录，配合 keep_files 保留这些目录，并协调两个 workflow 的 gh-pages 写入，避免并发 push 失败。不要直接把 quant 加入该 Action 的 exclude_assets：其实现会删除目标目录中的匹配文件。补“旧主站 checkout 晚于新回测产物部署”的集成演练，要求报告和索引内容不回退。

- **H2 · High · 回填历史不足，B2 无法保证主站与归档的周月指标一致。**
  **计划位置：** [§3 B2，第 59–60 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:59)、[§4.4 backfill，第 130 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:130)、[§5.1，第 152 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:152)。
  **问题与证据：** 计划只统一计算函数，未修改取数范围。主流程 [请求 days=800](/Users/loopq/dev/git/loopq/trend.github.io/scripts/main.py:93)，回填 [交易日样本请求](/Users/loopq/dev/git/loopq/trend.github.io/scripts/backfill_archive.py:147) 和 [预加载请求](/Users/loopq/dev/git/loopq/trend.github.io/scripts/backfill_archive.py:165) 都只有 days=400；中证源把 days 转成距今 `days + 30` 个日历日的起点，见 [DataFetcher._fetch_cs_index](/Users/loopq/dev/git/loopq/trend.github.io/scripts/data_fetcher.py:280)。以 2026-10-16 截止的连续工作日合成行情离线验证，400 天请求范围仅有 15 根月线，800 天范围有 28 根；按计划新公式，前者为 `-`，后者可为 `YES`。更早的回填日期还会继续损失预热数据。此外，“backfill 路径反而正确”不成立：现有取数先 tail(20)，再按未来周期标签截断，常只剩 19 根，随后被 Calculator 的 `<20` 门槛判为缺失，见 [重采样截尾](/Users/loopq/dev/git/loopq/trend.github.io/scripts/data_fetcher.py:369)、[回填截断](/Users/loopq/dev/git/loopq/trend.github.io/scripts/backfill_archive.py:100)、[周期门槛](/Users/loopq/dev/git/loopq/trend.github.io/scripts/calculator.py:144)。
  **改进建议：** 将回填取数窗口纳入 B2，按最早目标日期向前保留至少 20 个有效月周期及日线 lookback 所需预热，同时保留 fetch_index 的公共签名。测试必须经过真实的 main/backfill 取数适配器，用能按 days 截断的桩验证相同截至日的结果，而不只是给两个 Calculator 调用同一份足量 df；为源数据确实不足的情况明确 `-` 的降级规则。

- **H3 · High · 共享处理函数可能把短历史错误升级为整批失败。**
  **计划位置：** [§4.4 共享 process_indices，第 126–130 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:126)、[§5.2 异常夹具与失败率，第 159–164 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:159)。
  **问题与证据：** 现有 [Calculator.calculate_all_metrics](/Users/loopq/dev/git/loopq/trend.github.io/scripts/calculator.py:251) 对不足 20 根的数据返回 `error="数据不足"`、`deviation=None`；主流程随后在 [第 122 行](/Users/loopq/dev/git/loopq/trend.github.io/scripts/main.py:122) 用 f-string `:.2f` 格式化 deviation，日志级别不是 DEBUG 时也会先求值并抛 TypeError。本人用 19 根日线离线调用，main.process_indices 确实抛出 `unsupported format string passed to NoneType.__format__`，现有 [backfill.process_indices_at_date](/Users/loopq/dev/git/loopq/trend.github.io/scripts/backfill_archive.py:104) 则正常返回“数据不足”行。按主流程直接抽取共享函数，会把这个故障引入此前能容错的回填路径，并绕过计划要求的失败率判断；只用 fetcher 返回 None 的“异常指数”夹具发现不了它。
  **改进建议：** 在共享函数的契约中明确：Calculator 返回 error 的结果仍进入错误行和失败率统计，不格式化缺失数值；消除这处不安全日志求值，无需吞掉任意异常。补 0/19/20/21 根数据、单个短历史且失败率不超限的渲染测试，以及短历史占比超限的停止写入测试，并验证 backfill 同样保留错误行。

- **H4 · High · B4 缺少可复现的恢复清单和连续部署验证。**
  **计划位置：** [§3 B4，第 66–69 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:66)、[§5 CI 触发路径，第 146 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:146)、[§5.4 workflow 验证，第 174 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:174)、[§7 第 8 步](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:191)。
  **问题与证据：** 这是已发生的历史页面丢失修复，但计划只给“121 个”和单次解压命令，没有逐文件版本选择、恢复后验收或第二次部署检查；新 CI 路径也不包含 update.yml，仅修改恢复流程时不会触发。本人以本地 `origin/gh-pages=5dedf2f5c47324088a6e5acb39acbcf3e8892086` 核对：相对 main 缺少的历史日期页共 121 个，其中 117 个工作日、4 个周末；117 个工作日中 2026-10-16 已在 gh-pages 当前树，实际还不在线的工作日是 116 个，且包括 B4 标题范围外的 2026-02-02、2026-02-16。Git 将日更识别为重命名，例如 `5dedf2f` 是 `R075 2026-10-15.html → 2026-10-16.html`；直接按默认 rename 检测执行 `git log --diff-filter=AM` 只会找出 5 个 main 缺失候选，关闭 rename 检测才得到 121 个。没有恢复算法和清单，执行者容易漏页；“YAML 可解析、tar 能解开”也不能证明第二天仍保留归档和完整索引。
  **改进建议：** 在实施前生成按日期列出的恢复清单，记录所选 commit/blob、当前是否存在、恢复或排除原因，显式处理 rename，限定只补缺失文件并确定多版本选择规则。固定部署前 gh-pages SHA 供恢复失败时回退。增加临时仓库/目录的两次连续部署、重复执行、恢复来源缺失或提取失败测试：原有与恢复页面内容保持，索引覆盖所有保留日期，失败时不进入部署；将相关 workflow 自身纳入 CI 触发。无需在本轮实际部署或 push。

## Required Changes

- **H1：** 收窄主站发布输入并协调 gh-pages 写入；通过“回测先发布、旧主站后发布”场景验证在线回测产物不会回退。
- **H2：** 补回填历史预热策略，修正“原 backfill 正确”的诊断；验证正常取数路径下同一截至日的周月状态一致。
- **H3：** 为共享行构建函数定义 Calculator 错误结果的处理契约，补足短历史与失败率的组合测试，保留原回填的容错能力。
- **H4：** 提供可复现恢复清单、版本选择与失败回退办法，补连续部署和幂等性测试，并覆盖 workflow 改动的 CI 触发。
- **M1 · Medium · 前一日偏离率并列时，重算排名会继承今日顺序。**
  **计划位置：** [§3 B1，第 54 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:54)、[§5.1 test_ranking，第 153 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:153)。
  **问题与证据：** [Calculator.sort_by_deviation](/Users/loopq/dev/git/loopq/trend.github.io/scripts/calculator.py:328) 使用稳定排序，今日相同偏离率时保留配置顺序；传给 apply_rank_changes 的 results 已按今日排序。若配置顺序 A、B，昨日偏离率都为 0，今日 B 高于 A，则再次仅按 prev_deviation 排序会得到昨日 B、A，算出两者变化都是 0。离线复现与此一致；按原配置稳定排序的昨日实际是 A、B，变化应为 B:+1、A:-1。
  **改进建议：** 两天都使用同一确定性并列规则。为保持现有排名行为，优先保留配置序号作第二排序键，不要在昨日排序时继承今日顺序。加入昨日并列、今日并列、两日均并列，以及恰好 20 根数据无 prev_deviation 的用例。
- **M2 · Medium · D3 的执行时点与共享模板方案冲突。**
  **计划位置：** [§4.1 共享 COLUMNS，第 82–96 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:82)、[§5.3 金样允许差异，第 168 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:168)、[§7 第 3、7 步](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:186)。
  **问题与证据：** 现有 [首页表头](/Users/loopq/dev/git/loopq/trend.github.io/templates/index.html:60) 为 14 列，现有 [归档表头](/Users/loopq/dev/git/loopq/trend.github.io/templates/archive_detail.html:60) 为 13 列。第 3 步直接共用同一份 COLUMNS 和行 macro 就已经实施 D3，第 7 步不可能再按承诺先红后绿补列；若金样从一开始就放行 D3，则第 3 步的纯重构门禁也失去这一行为保护。
  **改进建议：** 把 D3 的红测试和归档补列移到共享模板之前，再统一已一致的两页；或者明确第 3 步包含独立的 D3 红绿子步骤。各阶段分别维护允许差异，不能提前放行后续阶段的 B1/B2/D3 变化，也不必为了步骤顺序制造临时模板开关。

完成 H1–H4 和 M1–M2，并补齐相应可运行验证路径后，才具备 8+ 的可执行性；本轮不要求扩展实现期指观察本体。

## Missing Context

- 未提供需求 4659 原文或本地 PRD。当前仅审查“入口预留、不加链接、不实现期指功能”的计划自述，不据此要求增加 CFFEX 接口或业务页面。
- 已读取 [.claude/CLAUDE.md](/Users/loopq/dev/git/loopq/trend.github.io/.claude/CLAUDE.md:1) 和 [backtest/CLAUDE.md](/Users/loopq/dev/git/loopq/trend.github.io/scripts/backtest/CLAUDE.md:1)，未发现名为 Code Quality Hard Limits 的条款；本轮按实际存在的最小改动、兼容性和不主动提交规则评估，不虚构行数限制。
- B4 还需上述恢复清单及发布前后的目录内容校验结果。本轮历史证据来自本地 remote-tracking ref，未 fetch 或据此宣称已验证当前线上 HTTP 状态；实施恢复时需重新固定实际使用的远端 SHA。
- 已完成排名并列、400/800 天月周期差异、19 根日线异常、文件覆盖语义的离线复现，检查了 121 个候选最后可用版本的日期标题和拟删除 CSS 引用，未发现标题日期不符或对应 CSS 引用。未运行完整项目测试套件，也没有把“审计划”冒充“实现已通过测试”。

## Risk Assessment

- logic: 高。B1 缺并列规则；B2 只统一公式、未统一输入所需历史，无法达到承诺的一致性。
- state: 高。update 与保留的 backtest 各自持有检出快照并写同一发布分支，keep_files 不解决同名文件覆盖和并发发布问题。
- data: 高。历史恢复涉及 121 个候选和 Git rename，需要文件级来源及连续部署验证；短历史错误也不能导致整批中止。
- UI: 中。共享布局和空导航槽合理，旧 tooltip 已明确保留；D3 必须调整执行顺序，并校验新旧归档、弹窗和移动端。未发现必须增加新 UI 框架的理由。
- regression: 高。风险集中在取数/计算/渲染边界和发布流程；仅有数值 oracle 与 YAML 解析不足以覆盖。未发现本次需要另行设计认证或支付机制的问题。

## Test Requirements

- unit: 保留计划的计算与渲染测试；增加 0/19/20/21 根日线、19/20 个周月周期、未完成周期、B1 双日并列及无上一日指标。分发表测试除路由和签名外，应守住现有缓存副本、网络错误返回 None 与非预期异常传播的行为；GA 和渲染继续保留 autoescape。
- integration: 经过真正 main/backfill 适配器执行按 days 截断的离线取数，比较相同截至日；验证单个短历史错误不超阈值时仍能生成错误行，超阈值时不写页面，force、过期数据和 GITHUB_OUTPUT/退出码保持原有契约。增加 H1 的交错发布，以及 H4 的恢复失败、两次部署、幂等性、归档内容与索引完整性检查；新增测试工作流须覆盖自身及 update.yml 等相关配置改动。
- manual: 按原计划检查桌面与手机、首页/新旧归档、弹窗开关和 Escape、导航与 CSS 相对路径；在允许发布后抽查恢复清单中的缺失日期，并核对在线回测报告和索引未回退。部署前记录 gh-pages SHA，首次发布及下一次正常更新后各核对一次归档集合；实际 push 仍由用户执行。量化非阻塞测试与必须全绿的主站/backtest 测试应明确区分，避免 §5.4 和 §6 的“全量绿”口径冲突。

## Final Verdict
方向可保留，但当前计划不能直接执行；先补齐发布归属、回填预热、共享错误处理和归档恢复验证，再进入实施。

---

## Round 2 — 2026-10-19

### Overall Assessment

本轮修订已补齐大部分上一轮要求，模板与 Python 拆分方向合理，恢复算法和测试路径也明显更具体，但发布竞争只处理了一个方向，主站与回填的行情截至日仍未统一，尚不能按当前承诺直接执行。本人独立读取计划、Round 1、相关代码及金样夹具，核验本地 Git 历史、进行离线复现，并运行现有回测测试（97 passed）；本轮仅列 2 项 High，无 Critical，也不追加凑数的低等级问题，未调用任何 skill、子代理或 Claude Code。计划仍无 PRD 双链接或飞书原文 URL，本地也无需求 4659 副本，因此记为 **PRD validation skipped — no local copy**，仅能核对计划已明确的重构与入口预留范围，不能宣称完成原始 PRD 的需求、数据/API 或埋点字段校验。

# Plan Review Result

## Decision

REQUEST_CHANGES

## Score

7 / 10

## Blockers

- **R2-H1 · High · 发布重试只覆盖主站，反向并发仍会使在线回测部署失败。**
  **计划位置：** [§3 B4，第 76–77 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:76)、[§4.5 保留 backtest.yml，第 162 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:162)、[§5.3，第 193–198 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:193)。
  **问题与证据：** staging 排除 quant/data，确实解决了上一轮的同名文件覆盖；但计划只给 update 增加重试，保留的 [backtest 部署步骤](/Users/loopq/dev/git/loopq/trend.github.io/.github/workflows/backtest.yml:140) 仍只执行一次发布。其 [第 102–125 行重试](/Users/loopq/dev/git/loopq/trend.github.io/.github/workflows/backtest.yml:102) 处理的是 main 分支，不能重试后面的 gh-pages 部署。两个 workflow 的 concurrency group 不同；如果双方发布 Action 都已克隆同一 gh-pages HEAD，主站先成功，回测后 push 就会被拒绝。Action v3/v4 的发布源码都只进行一次普通 push，未内置重新克隆重试，见官方 [v3 git-utils.ts](https://github.com/peaceiris/actions-gh-pages/blob/v3/src/git-utils.ts#L203-L208)、[v4 git-utils.ts](https://github.com/peaceiris/actions-gh-pages/blob/v4/src/git-utils.ts#L215-L220)。这时报告虽已提交 main，却未上线；主站 staging 又不再包含 quant，不会替它补发，前端会进入 [workflow 失败状态](/Users/loopq/dev/git/loopq/trend.github.io/docs/quant/lib/backtest-viewer.js:390)。§5.3 的覆盖拷贝测试仅证明文件归属，无法覆盖这条失败路径；这是上一轮 H1 的剩余部分，不是要求重启已停用的 quant 信号任务。
  **改进建议：** 保留目录归属设计，为两个 gh-pages 写入方都明确有界重试：失败后从最新发布分支重新构造各自的发布提交，重试耗尽必须使任务失败，禁止 force push。若用首次步骤 `continue-on-error`，明确用该步骤的 `outcome` 判定是否重试，最终失败不能发送成功通知；现有 [邮件条件](/Users/loopq/dev/git/loopq/trend.github.io/.github/workflows/update.yml:115) 只有 `should_deploy`，需要与最终部署结果闭合。补两个发布方分别先成功的竞争用例、首次失败后成功、重试耗尽，以及 `should_deploy=false` 不部署；将改动后的 backtest.yml 也纳入 §5 的 CI 路径过滤。无需引入会取消排队任务的共享 concurrency group。

- **R2-H2 · High · 主站缺少行情截至日契约，“与回填逐格一致”及金样门禁互相冲突。**
  **计划位置：** [§3 B2，第 64–67 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:64)、[§4.2–4.4，第 134、146–147 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:134)、[§5.2，第 184–188 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:184)、[§5.4，第 202–209 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:202)。
  **问题与证据：** 延长历史解决的是输入起点，不会限制输入终点。计划仍定义 main 传网络拉取、backfill 传按日截断，只把 record_date 传给 Generator；现有 [main.process_indices](/Users/loopq/dev/git/loopq/trend.github.io/scripts/main.py:93) 将最新整份 df 送入 Calculator，而 [simulate_data_at_date](/Users/loopq/dev/git/loopq/trend.github.io/scripts/backfill_archive.py:47) 明确裁到目标日。[crypto 取数](/Users/loopq/dev/git/loopq/trend.github.io/scripts/data_fetcher.py:261) 也没有目标日参数。真实金样已经暴露矛盾：[common.py 第 5–6 行](/tmp/trend-refactor/harness/common.py:5) 冻结在 2026-10-17、记录日期为 10-16，但 [load_snap 第 19–20 行](/tmp/trend-refactor/harness/common.py:19) 只 tail、不截日期，[BTC 快照](/tmp/trend-refactor/snap/BTC.csv) 含 10-17 和 10-19 的行情。本人离线调用真实 main/backfill 适配器，BTC 现价分别为 82377.6015625 / 81500.8046875，MA20 为 83351.35546875 / 83561.402734375，涨幅与量比也不同；在仅替换为计划 B2 周月公式的审查用 Calculator 中，这些差异依然存在。另用跨月合成数据验证：截至 9 月 30 日所有价格为 100，10 月 1 日为 50，则修正后的 B2 仍因是否包含未来一根而分别输出 `YES-YES` / `NO-NO`。因此不能靠增加 800 天窗口或冻结渲染时间兑现逐格一致，也不能通过修改桩让其隐式只返回 T 日数据来证明生产路径正确。
  **改进建议：** 在 plan 中明确选择并落实行情时间语义。若坚持“同一截至日 T 逐格一致”，两个适配器应在指标计算前统一按 T 裁剪，并明确日期/时区口径；主流程的生产取数仍保留原有 fetch_index 签名。把由此改变的现价、MA20、排名等作为独立行为修复列出、先红后绿，不能塞进“B2 仅周月状态变化”的白名单。当前金样可保留用于纯结构回归，但必须另建无未来行情的截至日基准，并记录两个基准用途；若本轮选择保持主站“最新行情”行为，则应收窄 §3/§5 的一致性承诺，明确仅对有效输入截至日相同的情形成立，并给 BTC 等差异单独验收。两种选择都需要写清楚后再实施，不能留给执行者临场改变业务语义。

## Required Changes

- **R2-H1：** 补齐两个发布方的失败恢复和最终状态门禁；验证两个竞争顺序，不能仅用文件覆盖模拟代替发布竞争测试。
- **R2-H2：** 明确主站与回填的行情截至日，协调生产适配器、金样输入、允许差异与功能测试，消除相互冲突的验收要求。

**上一轮问题状态（均指计划层面，不代表代码已实现）：**

| Round 1 问题 | 状态 | 本轮依据 |
|---|---|---|
| H1 发布覆盖 / 并发写入 | 部分解决 | 第 72–76 行 staging 隔离解决文件回退；第 77 行只有主站重试，剩余问题见 R2-H1。 |
| H2 回填预热不足 | 已解决原问题 | 第 62–66 行纠正旧诊断，增加 800 天及历史日期偏移，并明确不足 20 周期降级；第 184 行要求适配器级测试。新发现的终点问题另见 R2-H2，不否定预热修订。 |
| H3 短历史导致整批崩溃 | 已解决 | B5 第 86–89 行规定错误行和失败率契约；第 175、183、187 行补短历史边界、渲染及超阈值测试。 |
| H4 恢复清单 / 连续部署 | 已解决 | 第 78–84 行给出固定 SHA、逐树寻 blob、过滤、哈希和标题校验；第 167、191–198、221 行补 workflow 触发、连续部署、失败和线上复核。本人复核 116 个候选的标题及 CSS 引用，未发现新问题。 |
| M1 排名并列 | 已解决 | 第 56 行明确两日共用配置序号作第二排序键，第 176 行包含原复现用例。 |
| M2 D3 执行时点 | 已解决 | 第 93、228–229 行将补列红绿步骤移到共享模板之前，第 202–209 行按阶段限制差异。 |

上述两项 High 闭合后即可达到 8+；不要求扩展期指业务、增加框架或顺带修复无关的旧问题。

## Missing Context

- 需求 4659 原文缺失，无法验证其全部需求及字段；本计划已明确只做入口预留，因此不据此要求实现 IC/IM 接口、价差曲线或移仓点。缺失 PRD 不替代本轮两个有代码证据的阻断理由。
- 已读取项目 [.claude/CLAUDE.md](/Users/loopq/dev/git/loopq/trend.github.io/.claude/CLAUDE.md:1) 和 [backtest/CLAUDE.md](/Users/loopq/dev/git/loopq/trend.github.io/scripts/backtest/CLAUDE.md:1)，没有发现名为 Code Quality Hard Limits 的额外条款；按实际存在的兼容性、最小改动和不主动提交规则审查。
- 本轮历史核验固定于本地 `origin/gh-pages=5dedf2f5c47324088a6e5acb39acbcf3e8892086`：121 个 main 缺失候选，116 个出现在沪深 300 快照交易日中，排除日期与新计划一致；其中 10-16 已在当前 gh-pages 树，尚不在该树的候选为 115 个。116 个选中 blob 的标题日期、CSS 路径均符合恢复方案；没有 fetch、部署或核实线上 HTTP 状态，实施时仍须刷新并记录实际 SHA。
- 现有回测套件使用本地 venv 执行 `python -m pytest scripts/backtest/ -q -p no:cacheprovider`，结果为 **97 passed in 0.83s**。本轮的行情差异复现纯离线；未运行线上发布竞争，也没有把新计划尚未编写的测试记为通过。

## Risk Assessment

- logic: 高。历史窗口起点已补足，但输入截至日未统一；新旧公式无法弥补不同日期的行情输入，连现价和排名都可能不同。
- state: 高。目录归属已清晰，发布分支仍有两个独立写入方，仅一方具备拟议重试，另一方可能提交成功却部署失败。
- data: 中。恢复已有明确来源、选择和校验规则，未发现遗漏交易日；需按固定 SHA 落实清单与失败停止，不能把本地 remote-tracking ref 当作实时线上证据。
- UI: 低。D3、空导航槽、旧 tooltip、相对路径和归档弹窗已有明确验收路径；没有发现需要追加框架或扩大页面范围的理由。
- regression: 中。现有回测 97 项通过且门禁口径已明确；主要剩余风险是错误日期的金样被当作业务正确性依据，以及发布测试只验证拷贝未验证失败状态。本轮无新增认证、支付或删除数据设计需要单列。

## Test Requirements

- unit: 保留计划的计算、并列排序、0/19/20/21 根日线、19/20 周月周期和错误行测试。对截至日裁剪覆盖恰好 T、T+1、跨周/月以及有时区日期，断言输入不被修改；若选择保留主站最新行情语义，则为例外范围建立明确断言，不能伪称所有页面逐格一致。
- integration: main/backfill 必须接收到含 T 之后数据的同一原始夹具，再由真实适配器落实各自契约；用跨月价格突变验证 B2，使用当前 BTC 快照复现并处置金样差异。取数桩应区分中证的日历窗口和新浪的 tail 行数语义，不能统一简化成一种窗口。发布测试补主站先成功、回测先成功、失败后重试成功、重试耗尽、跳过发布与通知条件；同时保留计划已有的连续两次部署、幂等、恢复失败、归档索引完整性和 quant 文件内容不回退测试。
- manual: 按 §6 完成桌面与移动端、新旧归档和在线回测入口验收；首次发布与下一次定时更新后核对恢复清单和回测报告。线上动作在用户 push 后进行，本轮只追加审查，不提交或发布代码。

## Final Verdict

方案已接近可执行，但必须先闭合双向发布失败恢复及行情截至日契约；当前维持 REQUEST_CHANGES，7 / 10。

---

## Round 3 — 2026-10-19

### Overall Assessment

双向部署重试、最终成功通知和“主站用最新行情、回填按目标日截断”的选择已经明确，上一轮的大部分阻断已解决，但新的逐行一致性断言遗漏了组内排名的跨指数依赖，执行顺序也有一处无法按承诺变绿。本轮由本人独立读取修订计划、前两轮记录、实际代码及金样，完成真实适配器和合成数据的离线复现，发现 1 项 High、1 项 Medium，无 Critical；未调用任何 skill、子代理或 Claude Code。计划仍无 PRD 双链接或飞书 URL，也无本地需求 4659 副本，记为 **PRD validation skipped — no local copy**，不能声称核验了原始 PRD 的需求、API、数据及埋点字段，仅审核已明确的重构与入口预留范围。

# Plan Review Result

## Decision

REQUEST_CHANGES

## Score

7 / 10

## Blockers

- **R3-H1 · High · “单指数行情相同则整行一致”不成立，排名和强度变化依赖整组行情。**
  **计划位置：** [§3 B3，第 73 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:73)、[§5.2，第 194–198 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:194)，同时涉及 [B1 排名规则，第 55–56 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:55)。
  **问题与证据：** B3 明确保留两条路径的不同时间语义，这是合理的兼容性选择；但它进一步承诺“某指数最新 K 线 = T，该行逐格一致”，§5.2 又将其写成验收断言。实际 [配置中的 major_indices](/Users/loopq/dev/git/loopq/trend.github.io/scripts/config.yaml:11) 把 BTC、黄金、白银与 A/H/美股指数放在同一组，[Calculator.sort_by_deviation](/Users/loopq/dev/git/loopq/trend.github.io/scripts/calculator.py:328) 对整组排序，[main 的排名处理](/Users/loopq/dev/git/loopq/trend.github.io/scripts/main.py:301) 也以整组为单位。因此，另一指数多一根 T+1 行情，就可能改变本指数的当前名次和前一日名次；本指数自己的价格完全相同，排名列仍会不同。
  **离线复现：** 使用现有真实 main/backfill 适配器和 [金样快照目录](/tmp/trend-refactor/snap)，T=2026-10-16，最新行情确实停在 T 的国企指数在主站/回填分别排名 **2 / 1**，上证 50 分别排名 **6 / 5**，两者自身现价相同。按计划 B1 公式离线推导后，上证 50 的强度变化分别为 **+1 / +2**，纳指 100 虽两边都是第 8，其强度变化仍为 **−3 / −2**；排名来自现有排序调用，强度变化是审查脚本对计划公式的模拟，并非声称 B1 已实现。更小的合成用例也复现：A 的 21 根行情为 20 根 100 加 T 日 101；BTC 为 20 根 100、T 日 90、T+1 日 120。两条路径中 A 输入完全一样，但主站 A 为第 2、变化 −1，回填 A 为第 1、变化 0；[多空比例](/Users/loopq/dev/git/loopq/trend.github.io/scripts/generator.py:57) 也从 100% 变为 50%。这不是主站应改成截断的问题，而是新的测试要求与保留的正确分组计算无法同时满足；挑选不会跨越名次的 BTC 夹具只会掩盖矛盾。
  **改进建议：** 保留已选定的主站/回填时间语义，将一致性约束分为两类：同一指数有效输入相同且历史足够时，比较其现价、MA20、偏离率、量比、状态等自身指标；趋势强度、强度变化和多空比例分别按各自路径的完整分组输入计算独立 oracle，不要求跨路径相等。只有整组的有效成员、配置顺序及相关行情输入都可比时，才断言整组排序及排名变化一致。修改第 73、198 行，并加入上述“只有 BTC 增加 T+1、A 排名变化”的反例；不要为通过错误断言而分市场排名、复制另一条路径的排名或改变线上截断规则。

## Required Changes

- **R3-H1：** 修正 B3 与功能测试的比较粒度，明确个体指标和组内指标的依赖范围；保留分组排序行为及两套时间语义。该项闭合后，不再存在行情一致性方面的执行阻断。
- **R3-M1 · Medium · 第 9 步的 workflow 绿灯依赖第 10 步才执行的 quant 删除。**
  **计划位置：** [§5.3，第 210–212 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:210)、[§7，第 247–248 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:247)。
  **问题与证据：** 第 9 步要求 workflow 结构断言先红、修改两个发布流程后转绿；该测试却同时要求 update 无 quant 步骤、quant.yml 不存在。实际 [quant.yml](/Users/loopq/dev/git/loopq/trend.github.io/.github/workflows/quant.yml:1) 仍存在，[update 的 quant 步骤](/Users/loopq/dev/git/loopq/trend.github.io/.github/workflows/update.yml:75) 也仍存在，而按执行队列第 10 步才做 quant 入口下线。即使第 9 步发布逻辑全部正确，也无法满足这组完整断言。
  **改进建议：** 最小改法是将 quant workflow 删除及 update 中三个 quant 步骤删除并入第 9 步，在结构断言转绿前完成，第 10 步只更新 CLAUDE.md 和交付说明；或者第 9 步仅加入发布结构测试，第 10 步再加入并跑通入口删除测试。明确选定顺序，不要通过临时跳过既定断言来宣称该阶段全绿。

**历史问题状态（计划层面，不等于实现已验证）：**

| 历史问题 | 本轮状态 | 依据 |
|---|---|---|
| R2-H1 / R1-H1 发布覆盖与双向竞争 | 设计阻断已解决 | 第 79–86 行明确独立 staging、两个发布方均重试、用 outcome 判断、最终失败传递及成功邮件条件；第 172、177、210–211 行补 backtest 修改范围、CI 触发和结构检查。运行时竞争未实测，作为明确的剩余验收风险记录。 |
| R2-H2 截至日语义与金样用途 | 部分解决 | 第 71–74 行已选择保持原行为并区分回归金样与正确性 oracle，第 194、198 行增加 T+1 和跨月夹具；逐行一致性承诺仍遗漏整组依赖，见 R3-H1。 |
| R1-H2 回填预热 | 保持已解决 | 第 62–66 行保留扩展取数窗口及不足 20 周期降级，第 194 行细分中证日历窗口与其他源的行数截取。 |
| R1-H3 短历史崩溃 | 保持已解决 | 第 96–99、185、193、197 行保留错误行、失败率与短历史验证。 |
| R1-H4 历史恢复 | 保持已解决 | 第 88–94、203–208、235 行保留来源清单、校验、连续部署、失败停止及上线后复核；未发现新增恢复阻断。 |
| R1-M1 排名并列 | 保持已解决 | 第 56、186 行保留统一配置序号和并列用例；本轮不要求改变这一规则。 |
| R1-M2 D3 顺序 | 保持已解决 | 第 103、242–243 行仍先完成归档补列再共享模板；R3-M1 是新加 workflow 测试的独立顺序问题。 |

完成 R3-H1 并对齐 R3-M1 的执行顺序即可达到 8+，无需扩展期指功能或重写排名算法。

## Missing Context

- 未找到本地 PRD，也没有可解析的 PRD 双链接；“期指观察仅预留、不实现本体”的范围足以审查本轮结构方案，但不能据此推断需求 4659 的原始字段或完整范围。
- 已复核项目 [.claude/CLAUDE.md](/Users/loopq/dev/git/loopq/trend.github.io/.claude/CLAUDE.md:1)；前轮已读取的 [backtest/CLAUDE.md](/Users/loopq/dev/git/loopq/trend.github.io/scripts/backtest/CLAUDE.md:1) 仍在，本轮未见新增 Code Quality Hard Limits 条款或代码修改。没有缺少完成这次重构所必需的源码上下文。
- 本轮核对了 GitHub 官方的 [outcome / conclusion 语义](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#steps-context) 与 [隐式 success() 条件](https://docs.github.com/en/actions/reference/workflows-and-actions/expressions#status-check-functions)：首次失败配合 continue-on-error 后仍可按 outcome 重试，第二次不容错的失败会阻止后续普通成功步骤。该依据支持新重试设计，不能代替实施后对实际 YAML 的检查或线上运行记录。
- 本轮未重复执行未变更的全量回测套件；Round 2 的 97 passed 仅作为已有基线。本轮新证据是 16 个主要指数快照的真实适配器对照，以及两指数合成反例；未运行未实现的主站测试，也未执行 fetch、commit、push 或部署。

## Risk Assessment

- logic: 高。剩余阻断是将依赖整组行情的排名误当成单指数属性，导致 B1 正确实现与 B3 验收不能同时成立；自身指标和时间语义已经清楚。
- state: 中。双向有界重试与最终失败状态已闭合，连续竞争仍可能耗尽重试，但会明确失败，不再被当作成功；实际 workflow 和上线行为尚待实施验收。
- data: 中。历史恢复的来源、范围、校验及回退 SHA 已明确；保持原方案的文件级校验与连续部署检查即可，没有本轮新增的数据删除风险。
- UI: 低。共享模板、空入口槽、归档量比和旧 tooltip 的边界清楚；注意排名和多空比例应展示各自路径的正确结果，不能为了页面一致而篡改数值。
- regression: 中。测试范围已较完整，当前主要问题是错误的等值断言和 workflow 分阶段门禁错位。金样现在仅承担同输入的结构/行为回归，职责合理。

## Test Requirements

- unit: 保留 B1 并列和缺失前日指标测试；增加“A 输入不变、同组 BTC 多一根 T+1 导致 A 当前排名或前一日排名变化”的用例，验证 rank 与 rank_change 均按本组输入生成。用全部输入相同的对照组验证稳定性。
- integration: 通过真实 main/backfill 适配器渲染混合市场夹具，对自身指标做限定范围的跨路径比较，对整组排名、强度变化和多空比例分别对各自独立 oracle；保留已有跨月周/月状态用例。按修订后的第 9/10 步分别验证发布结构及 quant 入口删除，保留恢复失败、连续部署、幂等与非所属目录不回退测试。
- manual: 按 §6 完成桌面/移动端、归档恢复、回测入口及首次和下一次定时发布验收；有部署失败记录时核对第二次 Action 的执行和通知结果。结构断言不能证明所有线上竞争都会恢复，实施报告应如实保留这一限制；无需为计划评审强行触发线上发布。

## Final Verdict

保留现有实现方向，先修正跨指数排名的一致性断言并对齐 workflow 测试执行顺序，再实施；本轮 REQUEST_CHANGES，7 / 10。

---

## Round 4 — 2026-10-19

### Overall Assessment

最新计划已解决前三轮发现的设计与执行阻断：个体指标和组内指标的比较边界正确，quant 下线与 workflow 结构测试在同一步闭合，发布归属、失败处理、历史恢复及分阶段验证均可执行。本人独立重读最新计划和审查记录，复核相关调用方、分组排序、多空统计、回填截断及 workflow，未发现新的 Critical、High 或值得要求修订的其他问题；本轮未调用任何 skill、子代理或 Claude Code。计划仍无 PRD 双链接、飞书 URL 或本地需求 4659 副本，因此保留 **PRD validation skipped — no local copy**，本次批准限于计划明确的重构与入口预留范围，不代表已验证原始 PRD 的完整需求、API、数据及埋点字段。

# Plan Review Result

## Decision

APPROVE

## Score

9 / 10

## Blockers

- 无。未发现尚未解决的计划执行阻断；此前的问题均已在方案和验证要求中闭合。

## Required Changes

- 无必须追加的计划修改，当前已达到 8+。按既定步骤实施并完成 §5–§6 验证即可；批准计划不等于确认尚未编写的实现或测试已通过。

**历史问题解决状态：**

| 问题 | 状态 | 最新计划中的依据及核验结论 |
|---|---|---|
| R3-H1 逐行一致性忽略跨指数依赖 | 已解决 | [B3 第 73–77 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:73) 按个体/组内依赖分类；[第 190、202–207 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:190) 加入 BTC 多一根行情的反例、各自分组 oracle 和全组输入相同的对照。与实际 [分组排序](/Users/loopq/dev/git/loopq/trend.github.io/scripts/calculator.py:318)、[多空统计](/Users/loopq/dev/git/loopq/trend.github.io/scripts/generator.py:57) 的依赖一致，未再要求错误的整行等值。 |
| R3-M1 workflow 测试与 quant 删除顺序冲突 | 已解决 | [第 257–258 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:257) 将 quant workflow 删除、update 中三个入口删除及发布改造合并到第 9 步，在结构测试转绿前完成；第 10 步仅处理说明文档，不再存在前后依赖倒置。 |
| R2-H2 行情截至日与金样用途冲突 | 已解决 | [第 71–78 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:71) 保留主站最新行情与回填截至 T 的现有行为，限定跨路径比较范围，金样仅用于同输入回归；[第 198–209 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:198) 用各自 oracle 验证业务计算，没有以统一页面数值为由扩大行为修改范围。 |
| R1-H1 / R2-H1 发布覆盖与单向重试 | 已解决设计阻断 | [第 83–91 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:83) 保留独立 staging、keep_files、双向有界重试、最终失败传递和成功邮件条件；[第 181、219–222 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:181) 覆盖两个 workflow 的 CI 触发及结构断言。运行时竞争仍须按计划如实记录验收限制。 |
| R1-H2 回填预热不足 | 保持已解决 | [第 62–66 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:62) 修正旧诊断，增加历史日期偏移及不足周期降级；第 198 行保留按 source 模拟取数窗口的适配器级测试。 |
| R1-H3 短历史导致整批失败 | 保持已解决 | [第 100–103 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:100) 明确错误行与失败率契约；第 189、197、201 行覆盖短历史边界、正常渲染及超阈值停止写入。 |
| R1-H4 历史恢复缺少可复现闭环 | 保持已解决 | [第 92–98 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:92) 保留固定 SHA、最新 blob 选择、交易日过滤、清单和哈希校验；[第 213–218、245 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:213) 覆盖连续部署、重复执行、失败停止及发布后复核。 |
| R1-M1 并列排名继承今日顺序 | 保持已解决 | [第 56、190 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:56) 保留两日共用配置序号的确定性规则及并列测试。 |
| R1-M2 D3 与共享模板执行顺序冲突 | 保持已解决 | [第 107、252–253 行](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-site-refactor-futures-entry-slot.md:107) 保留先补归档量比、再共享模板的步骤，阶段允许差异没有提前放行后续行为修改。 |

## Missing Context

- 没有阻断本次重构执行的缺失源码上下文。已读取的项目与 backtest 指令文件未提供额外的 Code Quality Hard Limits 条款；没有依据虚构新的行数或架构限制。
- 缺少需求 4659 原始 PRD，无法验证该需求的全部范围及字段；当前计划明确不实现期指本体，这不妨碍批准现有重构和空入口预留，也不构成未来期指实现的需求依据。
- 新增测试、实际实现和上线结果尚未产生，属于实施交付物。本轮未重复运行未变更的全量测试；Round 2 的 **97 passed** 是现有回测基线，Round 3 的排名反例是已有离线证据，均不冒充本轮新实现的通过结果。
- 归档历史核验仍沿用前轮固定的本地 gh-pages SHA 和 116 个候选的校验结果；实施时依计划重新取得实际来源 SHA、生成清单。本轮没有 fetch、提交、push 或部署，也未核实实时线上页面。

## Risk Assessment

- logic: 低。B1 排名集合、并列规则和 B2 周月窗口已明确；B3 正确区分自身行情与组内依赖，业务修复与纯重构有各自门禁。
- state: 中且边界明确。两个发布方各有目录归属与有界重试；持续竞争或网络故障仍可能耗尽重试，但任务会失败并抑制成功通知。结构测试与线上运行验证的区别已记录。
- data: 中且有保护措施。历史恢复涉及较多页面，但来源选择、缺失文件范围、内容校验、失败停止及部署前 SHA 已明确；执行时必须落实既定清单和连续部署检查。
- UI: 低。量比补列、归档弹窗、GA、空导航槽和旧 tooltip 的变更边界与浏览器验收路径清楚，没有发现新增不必要的框架或页面范围。
- regression: 低至中。共享函数和模板会影响主站与回填，但已有适配器级 oracle、短历史与失败率测试、分阶段金样及保留回测套件门禁；剩余风险在实施是否忠实落实，而非计划缺少关键路径。

## Test Requirements

- unit: 按 §5.1 落实 0/19/20/21 根日线、19/20 周月周期、进行中周期、双日并列、缺失前日指标、跨指数排名反例、fetcher 行为兼容、渲染路径和转义测试。
- integration: 按 §5.2 分别验证个体指标和整组 oracle，包括 BTC 型 T+1、全组输入相同对照、跨月突变、回填连续日期及失败率门禁；按 §5.3 验证归档恢复、重复和连续部署、非所属目录保留、双向重试结构与最终通知条件。第 9 步完成 quant 下线后再要求整组 workflow 断言全绿。
- manual: 按 §6 完成桌面与移动端、首页/新旧归档、弹窗、导航和保留回测入口验收；用户 push 后，在首次部署及下一次定时更新后核对归档集合和回测报告，记录实际部署状态及残余风险。

## Final Verdict

当前计划可以直接进入实施，APPROVE，9 / 10；按既定测试和发布后验收闭环交付，无需再增加设计步骤。
