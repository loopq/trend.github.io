# Plan Review: Quant 定时器单路化清理 Plan
**Plan File**: /Users/loopq/dev/git/loopq/trend.github.io/docs/agents/quant/cron-cleanup-single-source.md
**Reviewer**: Codex

---
## Round 1 — 2026-04-27
### Overall Assessment
这个 plan 的方向（去掉 GitHub schedule + heartbeat，收敛为单路）是清晰的，但关键风控假设和运行时语义还没闭环。尤其是 `today.done` 与 `update.yml` 触发条件组合后，在周一/节假日会出现系统性误报，且“软告警”对 cron-job 整体故障并不生效。按当前文本直接执行，存在可预见的运维噪音和误判风险。
**Rating**: 5.8/10

### Issues
#### Issue 1 (Critical): `today.done` 语义与 update 触发门控冲突，周一会稳定误报
**Location**: 行 74（触发矩阵“前置检查 today.done”），行 197（将 warning 作为缓解）
当前计划要求 signal 前置检查 `morning-reconcile-{today}.done`。但 `update.yml` 的 morning-reconcile step 受 `steps.run_script.outputs.should_deploy == 'true'` 门控，而 `scripts/main.py` 在“昨天非交易日”时会直接 `should_deploy=false`。这意味着周一 08:00（昨天是周日）不会跑 morning-reconcile，14:48 前置检查却要求 `today.done`，会形成常态 warning（不是异常）。
**Suggestion**: 在 plan 中明确修订前置检查语义为“最近一次有效 morning-reconcile 对应的交易日”，或把 morning-reconcile 从 `should_deploy` 门控中解耦（至少在交易日强制跑）。

#### Issue 2 (High): 节假日边界未闭环，五一期间存在误告警/伪通过窗口
**Location**: §4.3（行 196-199），§5.3（行 243-248）
计划没有处理“weekday 但非交易日”的完整路径。当前主链路 `scripts/main.py` 的交易日判定是 `weekday < 5`，不识别法定假日；而 morning-reconcile 本身只跳周末不跳节假日。五一等跨节场景会产生“写了 done 但语义不对”或“应跳过却发 warning”的混乱。
**Suggestion**: 在 plan 增加硬约束：morning-reconcile 与 signal 前置检查都必须基于同一交易日历（非交易日直接 skip 且不写/不要求 done），并补一条五一实测用例。

#### Issue 3 (High): “cron-job.org 整体故障”与“软告警”逻辑不相容
**Location**: 行 196（风险：cron-job.org 整体不可用）
计划写的是“14:55 看飞书无消息时手动 dispatch”。但软告警在 quant.yml 内部 step；当 cron-job 根本没触发时，quant.yml 不会启动，软告警根本不会发。也就是说缓解措施并非自动机制，而是纯人工巡检。
**Suggestion**: 在 plan 明确这是“人工 SOP”而非“软告警”，并新增一条可执行机制：外部监控/第二通道提醒（哪怕是 cron-job 自带失败通知）。

#### Issue 4 (High): morning-reconcile 失败“可见性”被高估
**Location**: 行 197（“14:48 前置检查会发飞书 warning，用户能看到”）
这个判断依赖多个前提：signal 当日确实触发、`SKIP_SIGNAL` 非 true、`FEISHU_WEBHOOK_URL` 存在且可用。workflow 中 `curl ... || true` 本身会吞告警发送失败。计划把它当作可靠缓解，风险评估过于乐观。
**Suggestion**: 在 plan 中把该项降级为“best effort”，并追加强制可见机制（`GITHUB_STEP_SUMMARY` 明确写入 + run 级别 annotation + 日常巡检点）。

#### Issue 5 (Medium): `check_readiness.py` 删除 `schedule:` 关键字检查后没有反向断言
**Location**: 行 148-156（3.3）
计划把 `schedule:` 从 keyword 列表删掉是对的，但没有补“禁止出现 schedule”断言。未来误加 `schedule` 时 readiness 不会报警，回归风险上升。
**Suggestion**: 在 plan 补一条：`assert "schedule:" not in quant.yml`（或等价检查），并在输出里明确 FAIL 原因。

#### Issue 6 (Medium): `check_readiness.py` 移除 heartbeat 必检后，未加“必须不存在”检查
**Location**: 行 138-146（3.3）
从 `must_exist` 删除 `quant-heartbeat.yml` 后，脚本不再约束它的存在性。若未来文件被误恢复，readiness 仍可能 PASS。
**Suggestion**: 在 plan 增加 `must_not_exist = ["quant-heartbeat.yml"]` 检查，保证“单路化”可被自动验证。

#### Issue 7 (Medium): 线上验证命令不可直接复制执行
**Location**: 行 229（`gh run watch <run-id>`）
`<run-id>` 占位符未给出获取命令，无法直接 copy/paste。按你的要求这属于可执行性缺口。
**Suggestion**: 改为可直接执行的两行：先 `gh run list --workflow quant.yml --limit 1` 取 ID，再 `gh run watch <ID>`。

#### Issue 8 (Low): 验证期望写死具体日期，超出当天就失效
**Location**: 行 234（期望 `morning-reconcile-2026-04-27.done`）
这是一次性日期，过了当天会误导执行人判断失败。
**Suggestion**: 统一改成动态日期表达（例如 `${TODAY}`）并在命令前定义 `TODAY=$(TZ=Asia/Shanghai date +%F)`。

#### Issue 9 (High): 文档延后同步（YAGNI）会在事故期制造 runbook 冲突
**Location**: 行 295（“文档同步下次小 commit 单独清理”）
当前 `deployment-plan.md` 大量内容仍要求“GitHub schedule 备路 + quant-heartbeat 哨兵”。如果代码先改、文档后改，运维人员会按旧 runbook 执行，等于引入新的人为故障面。考虑 deadline 紧迫，这不是可以安全延后的项。
**Suggestion**: 把文档同步提升为本次最小范围内必须完成：至少在 `deployment-plan.md` 顶部加“已废弃”与跳转声明，并更新触发链章节。

#### Issue 10 (Medium): 回滚剧本不完整，忽略外部系统状态
**Location**: 行 257-258（“git revert <this-commit> 即可”）
仅 revert 代码不足以恢复真实运行态：外部 cron-job 配置、heartbeat workflow、readiness 断言与手动 SOP 不会自动回到一致状态。
**Suggestion**: 补全回滚脚本为“代码 + 外部配置”双清单，并定义回滚后验收命令（至少 1 次 mock-test + 1 次 signal 手动触发）。

#### Issue 11 (Suggestion): “pytest 86+6 不涉及 schedule/heartbeat”应在 plan 里给出可复验命令
**Location**: 行 179（影响评估）
结论本身大概率成立，但当前 plan 没给证据链。你要求的是“工程完整性”，这类断言应可复验。
**Suggestion**: 在验证步骤新增 grep 断言，例如：`rg -n "schedule|heartbeat|quant-heartbeat|cron" scripts/quant/tests .github/workflows/quant-test.yml scripts -g "test_*.py"`，并记录“NO_MATCH”预期。

#### Issue 12 (High): Linus 三问第 3 问回答与后文风险表自相矛盾
**Location**: 行 34（“不会破坏什么”），行 174-177（风险 0），行 192-199（又承认单点风险）
前面给“不会破坏”，后面又承认 `cron-job.org` 单点和 `continue-on-error` 吞错影响，这是逻辑冲突。评审和执行时会误导风险判断。
**Suggestion**: 重写三问第 3 问为“会破坏冗余容灾能力，但属用户显式接受的权衡”，并把风险表从 0 改成可量化的残余风险与应对时限。

### Positive Aspects
- 删除清单清晰，变更范围收敛在 `quant.yml` / `quant-heartbeat.yml` / `check_readiness.py`，实施成本低。
- 行号级修改指令大部分与当前文件吻合，执行者不需要二次猜测。
- 提前给了回滚方向和 deadline 约束，具备上线窗口意识。

### Summary
Top 3 关键问题：
1. `today.done` 与 `update.yml should_deploy` 组合在周一/节假日会出现系统性误报，前置检查语义需重定。
2. “软告警”无法覆盖 cron-job 整体故障，当前缓解实质上是人工巡检，不是机制保障。
3. 文档延后同步会和现有 deployment runbook 冲突，deadline 前必须做最小同步。

**Consensus Status**: NEEDS_REVISION

---
## Round 2 — 2026-04-27
### Overall Assessment
v2 相比 Round 1 有明显进步：风险表、反向断言、文档最小同步、可复制命令和回滚路径都补齐了，整体从“方向正确但执行不稳”提升到“可落地且风险透明”。Issue 1/2 没在本 plan 内修复，但已显式降级为 R4/R5 并挂到 incident Phase 2，作为短期过渡可以接受。剩余问题主要是执行细节的小缺口，不再是架构性阻塞。
**Rating**: 8.4/10

### Previous Round Tracking
| # | Issue | Status | Notes |
|---|-------|--------|-------|
| 1 | today.done 与 update 门控冲突 | PARTIALLY_RESOLVED | 已在 §4.3 作为 R4 明确，并挂 incident Phase 2；本 plan 不修。短期可接受（已透明化且不阻塞信号），但属于技术债。 |
| 2 | 节假日边界未闭环 | PARTIALLY_RESOLVED | 已在 §4.3 R5 标注并指向 incident Phase 2 + §6.5 五一用例；本 plan 不修。短期可接受，但必须按 incident Phase 2 落地。 |
| 3 | cron 整体故障与软告警不相容 | PARTIALLY_RESOLVED | 已改成人工 SOP 叙述，并补“cron 失败邮件”第二通道；但该动作放在 Phase 2（可延后），上线当下不一定生效。 |
| 4 | morning-reconcile 失败可见性被高估 | RESOLVED | §4.3 R2 已降级为 best-effort，风险表达与机制能力匹配。 |
| 5 | check_readiness 缺 schedule 反向断言 | RESOLVED | §3.3 明确新增“quant.yml 不含 schedule:”反向断言。 |
| 6 | check_readiness 缺 heartbeat must_not_exist | RESOLVED | §3.3 新增 `must_not_exist = ["quant-heartbeat.yml"]`。 |
| 7 | `gh run watch <run-id>` 不可直接执行 | PARTIALLY_RESOLVED | §5.2 已改成可执行取 ID + watch；但 §六回滚表仍残留 `gh run watch <id>` 占位符。 |
| 8 | 验证写死日期 | RESOLVED | §5.2/§5.3 改为 `${TODAY}` / `${TOMORROW}` 动态。 |
| 9 | 文档延后同步会冲突 | RESOLVED | §3.4 + §七 1.4 已提升为 Phase 1 必做最小同步。 |
| 10 | 回滚剧本不完整 | PARTIALLY_RESOLVED | §六已大幅补全，但仍有 `<id>` 占位符，且“第二通道邮件”不在回滚验收硬门内。 |
| 11 | pytest 断言缺可复验命令 | RESOLVED | §5.1 已补反向 grep 验证步骤。 |
| 12 | Linus 三问与风险表矛盾 | RESOLVED | §1.2 与 §4.1 已统一改为“容灾降级是显式代价 + 残余风险量化”。 |

### New Issues This Round
#### Issue A (Medium): R1/R3 的关键缓解被放在“可延后”Phase 2，导致上线当下无第二通道保障
**Location**: §4.3 R1/R3（行 235-237）、§七 Phase 2.6（行 359）、§八（行 377）
计划把“cron-job 失败邮件通知”定义为 R1/R3 的主要缓解，但执行清单中它属于“Phase 2（可延后）”。这会导致刚合并后的关键窗口里仍是单通道。
**Suggestion**: 将“启用 cron-job 失败邮件通知”前移到 Phase 1 必做，或在验收标准中明确“未启用第二通道时，R1/R3 仍为高风险运行态”。

#### Issue B (Low): 本地验证命令里的 `! grep ...` 在交互式 zsh 可复制性差
**Location**: §5.1 步骤 3（行 263-265）
`! grep ...` 在交互式 zsh 可能触发历史展开，复制执行不稳定。
**Suggestion**: 改成显式 if 结构，例如：`if grep -rn ...; then echo FAIL; else echo OK; fi`，避免 shell 方言差异。

### Positive Aspects
- v2 把 Round 1 的核心批评点都“显式化”了：风险可见、范围可见、责任归属可见。
- `check_readiness` 的正反向断言思路正确，防回归能力明显增强。
- 文档最小同步被拉回当前提交，避免代码与 runbook 脱节。

### Summary
v2 已从 `NEEDS_REVISION` 提升到可合并候选状态。剩余是两类小问题：
1. 部分缓解措施（第二告警通道）不应继续放在“可延后”阶段。
2. 少量命令可执行性细节（`<id>` 占位符、zsh 兼容）还需打磨。

**Consensus Status**: MOSTLY_GOOD

---
## Round 3 — 2026-04-27
### Overall Assessment
v3 把 Round 2 的执行性细节补齐了：命令占位符清零、zsh 兼容修复、回滚验收与第二通道验收可执行化。对 Round 2 Issue A，虽然受 cron-job.org 当前无法登录的外部约束，未能物理前移 2.6，但已在风险表与执行清单中把“高风险运行态”明确化并提高优先级，这满足了评审要求的“风险透明 + 可操作”。
**Rating**: 9.1/10

### Round 2 Issue Tracking
| # | Issue | Status | Notes |
|---|-------|--------|-------|
| A | 第二通道告警放在 Phase 2 可延后 | RESOLVED | v3 未强行前移（有外部阻断），但已在 §4.3 R1/R3 明确“高风险运行态”时长与条件，并在 §七把 2.6 标 🚨、加 2.7 验收，风险表达与执行优先级到位。 |
| B | `! grep` 在交互式 zsh 不稳 | RESOLVED | §5.1 步骤 3 已改为 if/else 显式结构，copy/paste 稳定。 |

### Round 1 Carry-over
| # | Issue | Status | Notes |
|---|-------|--------|-------|
| 1 | today.done 与 update 门控冲突（R4） | PARTIALLY_RESOLVED | 仍为已知残余风险，已在本 plan 明确归档到 incident Phase 2（calendar 一致化）并透明告知，不再是“隐性风险”。 |
| 2 | 节假日边界未闭环（R5） | PARTIALLY_RESOLVED | 同上，保留为 Phase 2 必修项；本 plan 范围内已做到风险披露与责任归属清晰。 |

### New Issues This Round
无。

### Summary
v3 已把 Round 2 指出的可执行性问题全部处理，并把无法立即消除的外部受限风险做了充分显式化与优先级管理。剩余 1/2 为有意延期且有明确承接计划的技术债，不构成当前清理计划的合并阻塞。

**Consensus Status**: APPROVED
