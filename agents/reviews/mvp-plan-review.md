# Plan Review: 量化信号系统 MVP — 产品需求与实施计划
**Plan File**: docs/agents/quant/mvp-plan.md
**Reviewer**: Codex

---

## Round 1 — 2026-04-25

### Overall Assessment
这版计划有明确目标和较完整模块拆分，但在“可执行闭环”上存在多个硬缺口：写入一致性、状态机完备性、触发时效 SLO、前端数据加载契约、以及安全边界假设都还不够严谨。以当前文档直接开工，极大概率在 Phase 4-6 出现反复返工。

### Rating /10
5.6 / 10

### Issues
1. Severity: Critical
Location: §5.3 L189-L193, §9.3 L633-L635, §10.4.5 L793-L796
Problem: 写路径是“前端双写 transactions/positions + 14:48 workflow 同时改 positions.policy_state”。这是典型多写者并发模型，且双文件更新非原子。任一 PUT 失败、重试或时序交错都会造成 `transactions.json` 与 `positions.json` 漂移。
Suggestion: 改为单写者模型。前端只写 `commands/*.json`（确认/跳过命令），由 Actions 消费并一次性生成单 commit 更新 `transactions + positions + signals`；或使用 Git Data API 一次 commit 打包多文件并带 parent SHA 乐观锁。

2. Severity: Critical
Location: §7.2 L387-L393, §8.3 L504-L510, §11.2 L892-L897
Problem: `status` 仅有 pending/confirmed/skipped，没有 `expired`、`cancelled`、`superseded`。若 W/M 信号当天未确认，后续周期切换时如何处理未决信号没有定义，状态机会悬空，容易丢单或重复处理。
Suggestion: 扩展信号状态机：`pending -> confirmed/skipped/expired/superseded`，加 `expires_at` 与跨日 reconcile job（每日开盘前或收盘后清理），并定义“超时默认行为”和审计日志。

3. Severity: Critical
Location: §1.2 L19-L20, §6.7 L285-L287, §8.1 L473-L474, §9.3 L631-L634
Problem: 策略语义使用 close vs MA20，但执行时点在 14:48 用实时价直接更新 `policy_state`。这在尾盘 12 分钟波动下会产生“盘中触发、收盘回撤”的假信号，尤其 W/M 周期更敏感。
Suggestion: 采用双阶段：14:48 仅发“预警信号（provisional）”，15:01 以后用收盘价确认并写 `policy_state`；若必须 14:48 下单，至少保留 `provisional/final` 字段并统计误触发率。

4. Severity: High
Location: §6.7 L287, §9.3 L622-L637, §11.2 L852-L853
Problem: “1-2 分钟完成 + 7 分钟决策窗口”是假设性结论，缺少 p95/p99 时延预算。GitHub runner 排队、AkShare抖动、飞书 webhook 抖动、以及“每信号 1 条卡片”都可能把到达时间推到 14:54 以后。
Suggestion: 给出明确 SLO：例如“飞书首条到达 p95 < 120s，最晚 < 300s”；在 workflow 内埋点并落地日报；消息改为“单卡汇总 + 明细链接”减少串行发送耗时。

5. Severity: High
Location: §10.2.3 L735-L736, §6.3 L263, §11.2 L893
Problem: 通知链路是核心价值，但文档把 webhook 失败定义为“log 错误但不阻塞主流程”。这会出现“信号生成成功但用户没收到”，与 MVP 目标冲突。
Suggestion: 通知失败应升级为硬失败（至少 fail workflow + 重试 + 飞书/邮件兜底）。最低要求：3 次指数退避重试 + dead-letter 文件 + 次级通道告警。

6. Severity: High
Location: §10.4.6 L800
Problem: 前端写了 `fetch signals/*.json`，浏览器无法直接对 GitHub Pages 静态目录做通配符拉取，这个读取契约不可实现。
Suggestion: 生成 `data/quant/signals/index.json`（按日期列出文件名和摘要），前端先拉索引再按需加载对应日期文件。

7. Severity: High
Location: §5.2.1 L173-L174, §6.11 L310, §10.4.3 L781-L782, §10.4.6 L807
Problem: 明确“不分页 + 全量 fetch transactions + 全量渲染”。初期能跑，但这是线性退化设计，数据增长后详情页首屏、移动端内存和带宽会持续恶化。
Suggestion: 按年月或指数分片存储（如 `transactions/2026-04.json` 或 `transactions/{code}.json`），默认只拉最近 N 天，详情页再懒加载历史。

8. Severity: High
Location: §6.4 L267-L271, §9.1 L576-L578, §10.4.4 L785-L789, §12 L913-L914
Problem: PAT 存 localStorage 且风险评估明显偏乐观。公开仓库 + 浏览器长期令牌意味着一旦 XSS/浏览器扩展泄露，攻击者可持续写仓库内容。
Suggestion: 至少做三件事：1) 改 `sessionStorage` 或短时内存令牌；2) 加严格 CSP/`integrity`；3) PAT 权限最小化并禁止 workflow 相关权限。中期建议改 GitHub App 或中转签名服务。

9. Severity: High
Location: §1.1 L14, §4.1 L74/L82, 附录A L970
Problem: 文档主叙事是“13 指数”，但 `v9-summary.md` 版本对比表写的是“V9.2（14 指数）”。基线不一致会直接影响回测复现和验收口径。
Suggestion: 在 plan 中加“基线快照锁定”：明确使用哪一版指数清单（13 或 14），并附配置文件 hash 与生成日期，验收按同一快照执行。

10. Severity: Medium
Location: CLAUDE.md L48, §10.0 L657, §10.4.3 L779
Problem: 仓库当前说明“无 pytest/unittest”，计划却引入 pytest + 前端 jest/vitest + 覆盖率门槛，但未给出 CI 工具链（Python/Node 版本、coverage 汇总、门禁脚本）。可达性不足。
Suggestion: 在 Phase 0 补“测试基建任务”：固定 Python/Node 版本、依赖锁、覆盖率收集方式、CI fail 条件；否则 90%/70% 只是口号。

11. Severity: Medium
Location: §6.12 L314, §11.2 L855
Problem: 一处写“paper 阶段所有信号默认 skipped”，另一处要求“用户≥3次成功确认成交写文件”。两者语义冲突：若默认自动 skipped，确认路径覆盖不足。
Suggestion: 区分两种 paper 模式：`auto_skip`（纯观测）与 `manual_mock_confirm`（走完整写入链路但打模拟标记）。验收要求绑定后者。

12. Severity: Medium
Location: §5.1 L126, §10.2.3 L733-L734
Problem: 飞书卡片 action 按钮跳转外站（GitHub Pages）通常依赖机器人卡片配置/域名白名单策略，文档未定义这一步，存在上线后按钮不可点风险。
Suggestion: 在 Phase 0 增加“飞书卡片域名放行与按钮联调”验收项，附最小可行 payload 与验证截图标准。

13. Severity: Medium
Location: §8.2 L489, §8.4 L513-L519
Problem: 关键一致性检查依赖 `assert`。生产中 `python -O` 会去掉 assert，且直接抛异常会让整批信号中断，不符合“单桶故障隔离”。
Suggestion: 用显式异常类型（如 `StateInvariantError`）+ bucket 级隔离处理：单 bucket 标红告警，其他 bucket 继续跑，并输出结构化错误报告。

14. Severity: Low
Location: §3.6 L64-L66, §5.0 L110-L114, §6.10 L302-L303
Problem: 文档直接暴露口令明文及其 MD5，弱保护可以接受，但当前写法等于“公开可复制口令”，对“防误入”效果也会快速衰减。
Suggestion: 至少改为环境化注入（build 时替换 hash）+ 定期轮换口令；若坚持纯前端，也应避免在 PRD 中出现明文口令。

### Positive Aspects
1. 目标边界清晰，MVP 范围与非范围区分明确（§4）。
2. 双状态模型（actual/policy）方向正确，能表达“策略状态”和“真实持仓”分离（§8.1）。
3. 针对资金门槛与执行现实选择半自动方案，实用主义取向正确（§6.2）。
4. 对交易日、周末、月末触发做了显式规则化，便于后续测试落地（§1.4、§9.3）。

### Summary（Top 3）
1. 必须先修“并发写 + 非原子双写”问题，否则账本必然漂移。
2. 必须补全“未确认信号跨日处理”状态机，否则 W/M 会出现悬空单。
3. 必须明确“14:48 预警 vs 收盘确认”机制，否则策略语义与执行口径不一致。

### Consensus Status
NEEDS_REVISION

---

## Round 2 — 2026-04-25

### Overall Assessment
v1.2 相比 Round 1 明显进步，关键缺口（原子提交、expired、provisional/final、SLO、索引读取）基本都有设计回应。问题在于文档内仍有多处“旧方案残留”和“新方案未闭环”，其中两处会直接影响账本正确性与信号可解释性。当前状态还不适合直接按文档全量实施。

### Rating /10
7.2 / 10

### Previous Round Tracking

| # | Issue 简述 | Status | Notes |
|---|---|---|---|
| 1 | 多写者并发 + 非原子双写 | Partially Resolved | 已引入 Git Data API 单 commit（§3.7/§6.12），但文档仍残留 Contents API 叙述，且同日重跑覆盖风险未处理。 |
| 2 | pending 跨日悬空 | Partially Resolved | 已新增 `expired` + 09:00 reconcile（§6.13/§8.5），但未定义同日重跑/重复生成时的状态合并策略。 |
| 3 | 14:48 实时价污染策略语义 | Partially Resolved | 有 provisional/close-confirm（§3.8/§8.6），但 `policy_state` 仍在 14:48 落盘且 close-confirm 不回写，核心口径仍可能漂移。 |
| 4 | 时延预算不可验证 | Resolved | 已给三档 SLO + 埋点（§6.15/§9.3/§11.2）。 |
| 5 | 通知失败未硬失败 | Partially Resolved | 决策层已改硬失败（§6.16），但 TDD 仍保留“log 不阻塞”旧条目（§10.2.3）。 |
| 6 | `signals/*.json` 通配符不可实现 | Partially Resolved | 新增 `signals/index.json`（§7.4），但详情页数据源描述仍写 `signals/*.json`（§10.4.6）。 |
| 7 | 全量加载线性退化 | Partially Resolved | 保留不分页但新增 5000 阈值告警（§10.4.3/§12）。 |
| 8 | PAT localStorage 安全边界薄弱 | Partially Resolved | 权限收敛有改进（§10.0/§12），但核心风险模型仍乐观，未引入更强隔离。 |
| 9 | 13/14 指数基线不一致 | Partially Resolved | 已锁定 13 指数（§6.17），但附录仍有 3 个 ETF `待补`，基线快照未真正封版。 |
| 10 | 覆盖率目标与工具链可达性 | Partially Resolved | 已加 `quant-test.yml` 与 pytest-cov（§10.0/§10.5.4），但阈值与目标不一致，前端 CI 方案仍冲突。 |
| 11 | paper trading 语义冲突 | Resolved | 已拆分 6.A auto_skip 与 6.B manual_mock_confirm（§10/§11.2）。 |
| 12 | 飞书外链按钮联调缺失 | Resolved | Phase 0 已加入联调验收（§10.0）。 |
| 13 | assert 生产不可依赖 | Partially Resolved | 主干已改 `StateInvariantError`（§8.2/§8.4），但测试计划仍残留 assert 表述（§1.2/§1.3）。 |
| 14 | 密码明文/MD5 暴露 | Partially Resolved | 加了季度轮换（§3.6/§12），但文档明文与 hash 仍公开。 |

### Issues

1. Severity: Critical  
Location: §8.1 L580-L583, §7.1 L410, §8.6 L699-L704  
Problem: `policy_state` 在 14:48 由 provisional 信号落盘，但 close-confirm 仅写 `confirmed_by_close`，不修正 `policy_state`。次日若以 `policy_state` 作为 yesterday_policy，将引入错误状态转移。  
Suggestion: close-confirm 对 `confirmed_by_close=false` 的 bucket 必须回写最终 `policy_state`（或显式声明次日一律由收盘 cache 重算 yesterday_policy，禁止读 positions.policy_state）。

2. Severity: Critical  
Location: §7.2 L449-L456, §9.3 L821-L823, §5.9 L257-L260, §10.5.1 L1045-L1048  
Problem: 当日 `run_signal` 重跑（手动 dispatch 或重试）会重写 `signals/YYYY-MM-DD.json`，可能覆盖用户已确认/已跳过状态与成交字段。  
Suggestion: 增加“同日幂等合并规则”：重跑只允许新增或更新 `provisional/confirmed_by_close` 与价格快照，必须保留已有 `status/actual_*`；写入前做 per-signal merge。

3. Severity: High  
Location: §4.1 L93, §6.4 L282, §10.4.5 L1000  
Problem: 新旧写入方案并存。前文仍写“GitHub Contents API 直接写状态文件”，后文改为 Git Data API 原子提交，实施时会出现双实现分叉。  
Suggestion: 全文统一为单一写入抽象（`writer.py/writer.js`），删除 Contents API 表述并加“禁止绕过 writer”的约束。

4. Severity: High  
Location: §6.16 L359-L362, §10.2.3 L942-L944  
Problem: 通知语义冲突：决策层要求“失败硬失败”，TDD 仍写“log 错误但不阻塞”。这会把错误行为测试成“正确”。  
Suggestion: 统一成“3 次退避后抛异常并 fail workflow”，并把旧 throttle/非阻塞用例替换为重试与失败路径断言。

5. Severity: High  
Location: §7.4 L497-L520, §10.4.6 L1019  
Problem: 已新增 `signals/index.json`，但详情页数据源仍写 `fetch signals/*.json`，实现契约仍自相矛盾。  
Suggestion: 明确详情页统一走 `index.json -> lazy load`，并抽公共 loader，禁止任何通配符路径假设。

6. Severity: High  
Location: §3.4 L54-L55, §9.2 L795-L806, §10.5.4 L1062  
Problem: 覆盖率目标写 90%/70%，CI 实际 `--cov-fail-under=85`。验收口径和门禁口径不一致。  
Suggestion: 将 CI 拆成分层阈值（核心逻辑 90、IO 70）或把文档目标统一到可执行阈值；避免“文档通过、CI不拦”假绿。

7. Severity: High  
Location: §10.0 L862, §10.5.4 L1063  
Problem: 前端测试声明“不引 npm/Node”，但 CI 要跑 headless chrome。当前文档没有无 Node 的可执行方案。  
Suggestion: 二选一：1) 接受最小 Node 依赖（Playwright/Puppeteer）；2) 改 Python 侧浏览器驱动方案并写清命令与依赖。

8. Severity: Medium  
Location: §3.7 L75, §8.5 L665-L678, §9.3 L837  
Problem: reconcile 代码示例在循环内 `commit_atomic`，与“单 commit 多文件”原则冲突，可能产生部分成功、部分失败的中间态。  
Suggestion: reconcile 先收集所有待改文件，再一次性 commit；失败整体回滚并告警。

9. Severity: Medium  
Location: §6.17 L364-L370, §10.0 L864, 附录A L1229-L1235  
Problem: 声称“基线快照锁定 13 指数”，但 3 个 ETF 仍 `待补`，这不是可复现实盘快照。  
Suggestion: 将“补齐 3 个 ETF”前置为 Phase 0 阻塞门（未补齐不得进入 Phase 1），并记录配置 hash。

10. Severity: Medium  
Location: §10.6 L1077-L1087, §6.15 L357, §11.2 L1144-L1156  
Problem: 周期定义不一致：Phase 6 标题写 14 个交易日，但 6.A+6.B 仅 5+5=10 天；SLO 通过标准仍引用“14 天 ≥13 天”。  
Suggestion: 统一为 10 天或把 6.A/6.B 扩展到 14 天，并同步修正所有验收阈值与统计样本数。

11. Severity: Medium  
Location: §4.4 L996, §12 L1192  
Problem: 文档要求 settings 页“校验 PAT 实际权限范围”，但未定义可用 API/头字段与校验算法，落地不可操作。  
Suggestion: 补充可执行校验路径（例如试探受限端点并判断 403 模式），若做不到就删除该承诺，避免伪安全。

12. Severity: Low  
Location: 文档头 L3, 变更日志 L1279  
Problem: 文档头版本仍是 `v1.0`，而正文声明已到 `v1.2`，配置管理信息不一致。  
Suggestion: 更新文档头版本与修订时间，确保评审和实现引用同一版本号。

### Positive Aspects
1. 原子提交、expired、close-confirm、SLO、索引读取这些高价值修订方向是正确的，且章节覆盖较完整。  
2. 引入 `StateInvariantError` + bucket 级隔离，明显提升了故障可控性。  
3. Paper trading 拆成 6.A/6.B 后，链路稳定性验证与用户交互验证终于解耦。  
4. Phase 0 新增飞书跳转联调、PAT 权限清单、测试基建，工程落地性比 v1.1 明显更强。

### Summary（Top 3）
1. 必须先修“provisional 写入后不回正 policy_state”，否则次日状态机会继续漂移。  
2. 必须定义“同日重跑合并规则”，否则手动重跑会覆盖用户已确认状态。  
3. 必须清理文档内新旧方案冲突（Contents API/通知语义/详情页数据源），否则实现会分叉。

### Consensus Status
NEEDS_REVISION

---

## Round 3 — 2026-04-25

### Overall Assessment
v1.3 已经把 Round 2 的关键技术风险基本收敛：`policy_state` 回正、同日幂等合并、writer 抽象硬约束、通知失败硬失败、索引化读取、分模块覆盖率门禁都已形成可执行方案。当前剩余问题主要是“文档内部一致性”和少量实现细节表达，不再是架构级阻塞。整体可进入实施，但建议先做一轮文档清洗，避免执行歧义。

### Rating /10
8.8 / 10

### Previous Round Tracking

| # | Issue 简述 | Status | Notes |
|---|---|---|---|
| 1 | close-confirm 未回正 policy_state | Resolved | §8.6 已明确回正并补无信号 bucket 同步更新。 |
| 2 | 同日重跑覆盖用户 status/actual_* | Resolved | §3.7.1 增加 per-signal merge，明确不可覆盖字段。 |
| 3 | Contents API/Git Data API 并存 | Resolved | 主体章节已统一 writer + Git Data API，并增加禁止绕过约束。 |
| 4 | notifier 语义冲突（硬失败 vs 非阻塞） | Resolved | §10.2.3 已改为重试后抛异常并触发 workflow fail。 |
| 5 | 详情页仍用 `signals/*.json` | Resolved | §10.4.6 改为 `signals/index.json + lazy load` + `data-loader.js`。 |
| 6 | 覆盖率门禁与目标不一致 | Resolved | §10.5.4 引入 `.coveragerc` + `check_per_module_coverage.py` 分层校验。 |
| 7 | 无 npm 前提下前端 CI 不可执行 | Resolved | 给出 Python + selenium + headless Chrome 方案。 |
| 8 | reconcile 循环内 commit 造成中间态 | Resolved | §8.5 已改循环外一次 commit。 |
| 9 | ETF 待补与基线锁定冲突 | Partially Resolved | 已加 Phase 0 阻塞门，但附录 A 仍保留 `待补` 占位，易让读者误判为已锁定完成。 |
| 10 | Paper trading 14 天/10 天口径冲突 | Resolved | 已统一为 10 个交易日（5+5）。 |
| 11 | PAT 权限“自动校验”不可实现 | Resolved | §10.4.4 改为有效性试探 + 用户自检指引。 |
| 12 | 文档头版本未更新 | Resolved | 文档头已更新到 v1.3。 |

### Issues

1. Severity: Medium  
Location: §6.18 L384-L387, §10 Phase 6 L1148-L1160  
Suggestion: §6.18 仍在描述“第一阶段所有信号默认 skipped”，与 6.A/6.B 双阶段定义不一致。建议把 §6.18 改写为“6.A auto_skip + 6.B manual_mock_confirm”摘要，避免策略语义误读。

2. Severity: Medium  
Location: §9.3 L882-L889, §8.6 L735-L740  
Suggestion: 15:30 时序图仍写“写 signals/{today}.json + index.json”，但 §8.6 实际还要写 `positions.json` 回正 policy_state。建议同步更新时序段，确保读图即得真实写入集合。

3. Severity: Medium  
Location: §10.4.4 L1041-L1044, §12 L1263  
Suggestion: §10.4.4 已明确“不做权限范围自动校验”，但风险表仍写“settings 页校验 PAT 实际权限范围”。建议风险表改为“仅提供配置指引 + 有效性试探”，保持单一事实源。

4. Severity: Medium  
Location: §8.2/§8.4 已改异常机制（L600-L650, L659-L667），但 §10 Phase 1 测试项 L934, L946  
Suggestion: 测试计划仍写“assert 抛错”。建议统一改为 `StateInvariantError` 断言，避免测试实现偏离设计。

5. Severity: Low  
Location: 附录 A L1300-L1307, L1313 与 §10 Phase 0 L906  
Suggestion: 当前附录仍是 `待补` 占位。若这是“预实施模板”，建议在附录标题标注“Pre-Phase0 Snapshot”；若作为执行版基线，应在进入 Phase 1 前补全并替换占位值。

6. Severity: Low  
Location: §8.6 L745  
Suggestion: 假信号率分母写为 `sum(provisional==False)` 容易歧义（close-confirm 后全部会置 false）。建议改成“当日参与 close-confirm 的信号数”或 `confirmed_by_close is not null`，统计口径更清晰。

### Positive Aspects
1. Round 2 的两个核心阻塞点（policy_state 真值回正、同日重跑覆盖）都已被实质性修复。  
2. writer 抽象 + 幂等 merge + 单 commit 约束已经形成明确工程护栏，设计质量显著提升。  
3. 覆盖率门禁从“口号”升级为可执行机制（整体阈值 + 分模块脚本校验）。  
4. 前端数据加载契约已统一为索引驱动，消除了通配符读取不可实现问题。  
5. 当前残留问题集中在文档一致性和表达清晰度，修复成本低、风险可控。

### Summary
Round 3 结论：计划已从“需结构性返工”收敛到“可实施、需小修文档一致性”。建议先清理 6 条残留后再冻结实施版，以减少执行歧义与返工。

### Consensus Status
MOSTLY_GOOD
