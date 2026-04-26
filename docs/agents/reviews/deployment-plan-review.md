# Plan Review: 量化信号系统 - 部署上线 plan
**Plan File**: docs/agents/quant/deployment-plan.md
**Reviewer**: Codex
---
## Round 1 — 2026-04-25

### Overall Assessment
这版 v2.0 有明确的工程目标（mode 合并、mock 隔离、防覆盖），方向对，但当前文档仍存在多处“可运行但不稳”的上线级风险：调度单点、跨 workflow 耦合、并发写保护未闭环、安全边界过宽、与 MVP 基线文档不一致。按当前文本直接上线，出现“当天漏跑/错跑 + 难复盘”的概率偏高。

### Rating /10
**5.8 / 10**

### Issues
1. **[Critical] 14:48 仅保留 1 个外部 cron，形成真实单点故障**
Location: `§一.3` `L78-L104`，`§六` `L670`
Problem: 文档把 3 cron 合并成 1 cron，但兜底仅是“人工手动触发”。这不是容灾，只是人工补救。若 cron-job.org 或其 PAT 失效，系统会静默漏跑，且无法自动发现。
Suggestion: 增加自动兜底链路：`github schedule` 作为二级触发 + `signal` 模式内“当日已跑哨兵检查”保证幂等；再加 14:50 heartbeat 监控（未产出 signals 即报警）。

2. **[Critical] morning-reconcile 强耦合 update.yml 成功状态，导致 quant 可能跨日失真**
Location: `§二点五 update.yml 钩子` `L287-L299`，`§六故障处理` `L674`
Problem: `if: success()` + `continue-on-error: true` 的组合意味着：主链路失败时 quant 不执行；quant 自身失败也不会阻断后续。结果是次日 `yesterday_policy` 可能陈旧，14:48 误判风险上升。
Suggestion: 让 `morning-reconcile` 具备独立调度与可追溯 SLA；至少在 `mode=signal` 前加“昨日 reconcile 已完成”前置检查，不满足则 fail-fast 并报警。

3. **[High] 5 mode 缺少互斥矩阵与状态机约束，存在竞态写风险**
Location: `§二点五 5种mode` `L216-L225`，`§八.C P0-1` `L798`
Problem: 文档定义了 5 mode，但未定义哪些 mode 可并发、哪些必须互斥。`init` 与 `signal`、`deploy` 与 `signal` 同时触发时，状态与发布可能互相覆盖。
Suggestion: 在 plan 明确 mode 互斥矩阵，并在 workflow 加全局 concurrency key（例如 `quant-state-main`），对 `init/signal/morning-reconcile/deploy` 统一串行。

4. **[High] gh-pages 同步存在并发冲突 + 发布范围定义不一致**
Location: `§二部署链路` `L156-L163`，`§二 gh-pages 同步实施` `L170-L186`，`§八A` `L755`
Problem: 文本说“同步 docs/data/quant”，但示例 `publish_dir: ./docs` 实际会发布整个 docs。与此同时，`update.yml` 与 `quant.yml` 都能触发 gh-pages 写入，未定义统一发布锁。
Suggestion: 统一成单一发布入口（可复用一个 deploy workflow），并设置 gh-pages 专用 concurrency group；文档明确“只发 quant 数据”还是“全站 docs 增量发”，避免语义漂移。

5. **[High] mock-test 隔离面定义不足，仍有污染主分支的残余风险**
Location: `§二点五 mock-test` `L226-L266`，`§三 Step8 验证` `L379-L389`，`§五` `L648`
Problem: 目前只强调 `QUANT_DATA_ROOT`、NoOpNotifier、dry_run。缺少“运行后工作区必须零 diff”的硬校验，也没有说明 git 凭据隔离与 secrets 使用边界。
Suggestion: 在 mock-test workflow 末尾强制执行 `git status --porcelain` 断言为空；增加“禁 push、禁 deploy、禁真实 webhook”的硬门；把隔离校验写入验收标准。

6. **[High] writer mergeFn 方案缺少幂等键，重试/重入会产生重复流水**
Location: `§三点五 mergeFn示例` `L507-L511`，`L529-L535`
Problem: `transactions.push(newTx)` 在网络超时或前端重复提交时无法去重。即使 parent-SHA 冲突解决了，也可能出现业务重复写（双记账）。
Suggestion: 引入 `operation_id`（信号ID+动作+客户端nonce）并在 merge 时去重；`signals/{date}.json` 的状态更新也做条件写（仅 pending 可转 confirmed/skipped）。

7. **[High] mergeFn 异常处理协议缺失，失败语义不可控**
Location: `§三点五 mergeFn示例` `L515-L520`，`L533-L535`
Problem: 示例默认 `find` 一定命中且结构合法，未定义 `mergeFn` 抛错/返回非法 JSON/目标信号不存在时如何处理。线上将出现“422 以外的失败不可归类”。
Suggestion: 定义 mergeFn 合同：输入 schema 校验、找不到目标即业务错误码、JSON 校验失败即拒绝提交；失败信息写入可观测日志并回传前端。

8. **[High] AkShare 实时数据“备用方案”仍停留在口头层，缺乏可执行降级策略**
Location: `§一.6` `L122-L135`，`§六故障处理` `L668`
Problem: 文档只写“可能切备用接口”，但没有定义：单指数缺失阈值、ETF 缺失是否允许部分信号、何时全量 fail、何时仅降级通知。
Suggestion: 写成策略矩阵：指数价缺失/ETF价缺失/多源分歧时的明确动作（跳过、降级、失败），并把阈值加入 workflow gate。

9. **[Medium] paper→real 切换步骤不具备数据迁移规范，账本会混叠**
Location: `§七切实盘动作` `L713-L721`
Problem: 只改 `paper_trading` 标记不足以隔离历史。paper 流水与 real 流水继续共存，后续统计与审计容易混淆。
Suggestion: 增加标准切换脚本：冻结窗口、归档 `transactions.paper=true`、生成切换快照（commit/tag）、再开启 real 模式。

10. **[Medium] 上线前操作复杂度过高，P0 14 项缺少“最小可上线路径”**
Location: `§三 Step2` `L316-L327`，`§八.C` `L794-L815`
Problem: 当前 P0 同时包含架构改造、数据源切换、安全配置、外部平台配置，认知负担大且易漏项。
Suggestion: 拆成 `P0-Core`（必须当天完成）和 `P0-Deferred`（可延后）；提供单命令 readiness 检查脚本输出 PASS/FAIL 清单。

11. **[High] PAT 双 token 方案可用但不够稳健，安全/运维成本偏高**
Location: `§一.2` `L56-L76`，`§一.3` `L92-L103`，`§三 Step6` `L367-L374`
Problem: 一个 PAT 在浏览器 localStorage，另一个 PAT 给第三方 cron，二者均为长期凭据，轮换与泄露治理未流程化。
Suggestion: 评估 GitHub App（短时安装令牌）或最少把 PAT 轮换、失效探测、权限审计写成月度 Runbook；明确 token 失效自动告警链路。

12. **[Medium] 与 `mvp-plan.md v1.5` 存在关键叙述冲突，影响变更基线可信度**
Location: `deployment-plan.md` `L7`、`L318-L325`、`L850-L863`；对照 `mvp-plan.md` `L63-L77`、`L1123-L1137`、`L1379-L1385`
Problem: v2.0 声称基于 v1.5 已实施并测试通过，但又列出大量“上线前必须代码改造”（多 workflow 合并、realtime auto、mergeFn 等）。与 v1.5“上线前只补外部配置、不改代码”冲突。
Suggestion: 回写一份“v1.5→v2.0 迁移附录”到 mvp-plan 或在 deployment-plan 增加兼容矩阵，明确哪些实现已完成、哪些仅设计未落地。

13. **[Low] 文档内部仍有旧引用与术语残留，增加执行歧义**
Location: `§六日常监控` `L659`，`§八B URL` `L791`，`§八.C` `L807`
Problem: 一处写“看三个 workflow”，一处仍链接 `quant-signal.yml`，但 P0 又要求删除旧 workflow。执行者容易按旧入口操作。
Suggestion: 全文统一术语与链接，给出“新入口映射表”（旧 workflow → quant.yml mode）。

### Positive Aspects
- 把 `lost-update` 明确为一等风险并给出可实现的 mergeFn 方向（`L472-L538`），这是正确方向。
- 明确区分真值层(main)与展示层(gh-pages)（`L399-L420`），有利于后续审计与回滚。
- 对 mock 隔离有明确工程意图（`L226-L266`），不是口头承诺。
- 切实盘前设置了量化验收门槛（`L697-L708`），有“先验证再冒风险”的纪律。

### Summary（Top 3）
1. 先解决“调度与耦合”：去掉单点 cron + 去耦 morning-reconcile。
2. 再解决“并发与幂等”：mode 互斥矩阵 + mergeFn 幂等键。
3. 最后补“文档基线一致性”：v2.0 与 mvp v1.5 的变更关系必须回写统一。

### Consensus Status
**NEEDS_REVISION**
---
## Round 2 — 2026-04-26

### Overall Assessment
v2.1 相比 v2.0 明显收敛，Round 1 的核心风险（单点触发、跨日耦合、merge 幂等、切实盘迁移、文档基线冲突）大部分已被系统性修复。当前剩余问题主要集中在“新加防护的可执行细节一致性”而不是方向性错误，已接近可上线评审标准。

### Rating /10
**8.3 / 10**

### Previous Round Tracking

| # | Round 1 Issue | Status | Evidence (v2.1) | 评审结论 |
|---|---|---|---|---|
| C-1 | 单 cron 单点故障 | Resolved | `L96-L159`, `L111-L127`, `L129-L157` | 已补主备双路（cron + schedule）和 14:55 heartbeat 哨兵。 |
| C-2 | morning-reconcile 耦合 update.yml | Resolved | `L339`, `L367`, `L890` | 已有 signal 启动前置 fail-fast + 手动补跑路径。 |
| H-3 | 5 mode 互斥缺失 | Resolved | `L344-L363`, `L365-L367` | 已补全局 concurrency、互斥矩阵、init 特殊保护、幂等检查。 |
| H-4 | gh-pages 并发与范围不清 | Partially Resolved | `L290-L304`, `L344-L351`, `L1199-L1201` | 已补并发思路与 publish 语义，但跨 workflow（含 update.yml）的并发锁描述仍不完整。 |
| H-5 | mock-test 隔离不足 | Partially Resolved | `L369-L420`, `L421-L428` | 4 道硬门已加，但关键隔离能力仍依赖待实施项，且存在凭据绕过细节（见新问题 N-1）。 |
| H-6 | mergeFn 缺幂等键 | Resolved | `L667-L723` | 已加 operation_id、状态条件写、调用示例完整。 |
| H-7 | mergeFn 异常协议缺失 | Resolved | `L651-L665`, `L743-L752` | MergeResult 协议与前端错误处理已定义。 |
| H-8 | AkShare 备用方案口头化 | Resolved | `L198-L215`, `L229-L235` | 已落为缺失阈值/主备源/分歧处理矩阵与代码骨架。 |
| M-9 | paper→real 切换混叠 | Resolved | `L932-L970`, `L976-L983` | 已有标准 migrate 脚本、tag、渐进 Runbook。 |
| M-10 | P0 复杂度过高 | Partially Resolved | `L1072-L1117`, `L1135-L1157` | 已拆 P0-Core/P0-Deferred + readiness；但 Core 项数量上升，执行负担仍偏高。 |
| H-11 | PAT 双 token 运维风险 | Partially Resolved | `L161-L178` | 已补月度轮换 Runbook；GitHub App 路线显式拒绝（可接受但保留长期风险）。 |
| M-12 | 与 mvp-plan 基线冲突 | Resolved | `L22-L37` | 兼容矩阵已明确“已实施 vs 上线前待改”。 |
| L-13 | 旧入口/术语残留 | Partially Resolved | `L1044-L1070` vs `L1228-L1230` | 主体已统一并补映射表，但文末仍残留 v2.0 旧表述。 |

### 新发现 Issues

1. **[High] mock-test “硬门 #1”存在凭据绕过窗口，当前定义并非真正硬隔离**
Location: `§二点五 mock-test` `L381-L383`
Problem: 文档声明“`GITHUB_TOKEN=''` 任何 push 必失败”，但若 `actions/checkout` 保留默认凭据，git remote 里仍可能保留可用认证信息。仅清空 env 不能保证绝对不可 push。
Suggestion: 在 plan 的 workflow 样例中明确 `actions/checkout@v4` 使用 `persist-credentials: false`，并追加一步 `git remote set-url origin https://github.com/...`（无 token）+ `git push` 预检应失败。

2. **[Medium] 互斥矩阵与 concurrency 配置语义不一致**
Location: `§二点五` `L344-L351` + `L357-L361`
Problem: 顶层 `concurrency.group: quant-state-main` 会串行所有 mode；但矩阵又写 mock-test“可并行”。两者不能同时成立。
Suggestion: 二选一：
1. 保持全串行并把矩阵改成一致。
2. 使用动态 group（mock-test 独立 group，写主分支 mode 走 `quant-state-main`）。

3. **[Medium] 主备幂等检查条件过窄，低信号日可能触发不必要备路执行**
Location: `§一.3` `L127`，`§二点五` `L365`
Problem: 当前以“今日文件存在 + 含 pending”判定已跑。若当日无 pending（例如无信号或已全部处理），备路可能仍执行，导致重复数据拉取和额外噪声。
Suggestion: 改为“当日 run 完成标记”判定（例如 heartbeat 中写 `mode=signal,date,status=done`），而不是依赖业务状态字段。

4. **[Low] 文档尾部仍残留 v2.0 旧结论与旧编号，影响执行一致性**
Location: `L1228-L1230`
Problem: 末尾仍写“review-ready v2.0”“按 P0-1~P0-10 实施”，与 v2.1 的 P0-Core/C-1~C-20 不一致。
Suggestion: 统一改为 v2.1 版本表述与新编号，避免落地人员按旧清单执行。

### Positive Aspects
- 对 Round 1 的关键风险给出了结构化补强，不是“文字应付”，尤其是 C-1/C-2/H-6/H-7/M-9。
- `v1.5 → v2.0 兼容矩阵`（`L22-L37`）显著提升了文档可追溯性。
- `P0-Core + readiness`（`L1072-L1157`）让上线前 gate 有了可自动化执行的方向。
- 故障处理章节补充了新机制对应的异常路径（`L893-L898`），可运维性提升明显。

### Summary（Top 3）
1. Round 1 的主风险基本收敛，v2.1 已从“方向正确但不稳”提升到“基本可上线”。
2. 剩余主要问题是“防护声明与执行细节的一致性”，不是架构方向错误。
3. 先修复 N-1/N-2/N-4 这三条，再跑一次文档一致性检查，可进入 APPROVED 候选。

### Consensus Status
**MOSTLY_GOOD**
---
## Round 3 — 2026-04-26

### Overall Assessment
v2.1.1 对 Round 2 的 4 条新问题完成了实质修复：mock-test 凭据绕过、动态 concurrency、无信号日幂等判定三项都已闭环，整体方案可执行性与抗误操作能力继续提升。当前剩余问题属于文档一致性层面的轻微残留，不构成上线阻塞。

### Rating /10
**9.0 / 10**

### Previous Round Tracking

| Round 2 Issue | Status | Evidence (v2.1.1) | 评审结论 |
|---|---|---|---|
| N-1 mock-test 凭据绕过 | Resolved | `L390-L402`, `L444-L446`, `L1227` | 已补 `persist-credentials: false` + `unset extraheader` + 远端 URL 失效化，双保险成立。 |
| N-2 互斥矩阵与 concurrency 不一致 | Resolved | `L344-L353`, `L356-L364`, `L1228` | 已改动态 group，矩阵与 yml 语义一致。 |
| N-3 幂等检查过窄 | Resolved | `L368-L379`, `L373-L374`, `L1229` | 已改 `.runs/{mode}-{date}.done` 显式标记，无信号日也安全。 |
| N-4 文末残留 v2.0 / 编号旧式 | Partially Resolved | `L1230`, `L1267-L1269` | 已从 v2.0 与旧编号迁移到新体系，但文末仍写 `review-ready v2.1`，未完全对齐 `v2.1.1`。 |

### 新发现 Issues

1. **[Low] 文档版本号在局部仍未完全对齐到 v2.1.1**
Location: `L1267`
Problem: 文末写的是 `review-ready v2.1`，与文档头 `v2.1.1` 不一致。
Suggestion: 文末版本提示统一改为 `review-ready v2.1.1`。

2. **[Low] “硬门数量”表述仍有旧值残留（4 vs 5）**
Location: `L387`, `L1118`, `L1136`, `L1240`
Problem: 主体已升级为 5 道硬门，但若干段落仍写 4 道，容易造成验收时口径不一致。
Suggestion: 全文统一为 5 道硬门，并在 C-19 验收项同步改成“5 道硬门全部通过”。

3. **[Low] P0-Core C-1 对 concurrency 的描述仍是旧口径**
Location: `L1112` vs `L352`
Problem: C-1 写“顶层 concurrency `quant-state-main`”，但当前已是动态 group（mock-test 独立）。
Suggestion: 把 C-1 改为“动态 concurrency（mock-test=quant-mock-test，其余=quant-state-main）”。

### Positive Aspects
- Round 2 的 3 个技术阻塞项（N-1/N-2/N-3）均已落地为可执行机制，而非文字承诺。
- `.runs` 显式标记替代业务字段判定，幂等语义明显更健壮。
- mock-test 隔离从“策略”升级为“可被审计的硬门流程”，工程可控性提升。
- 文末编号体系已从旧 P0-* 基本迁移到 C-* / P1 / P2，执行路径更清晰。

### Summary
v2.1.1 已达到“可上线前最后清理”的状态，剩余均为低风险文档一致性问题。修完本轮 3 条 small issue 后可直接升级到 APPROVED。

### Consensus Status
**MOSTLY_GOOD**
---
## Round 4 — 2026-04-26

### Overall Assessment
v2.1.1 已完成 Round 3 的 3 条 Low 一致性修订，关键文案与执行口径已对齐：`review-ready v2.1.1`、`5 道硬门`、`动态 concurrency` 三处均有明确落点。未发现新的阻塞性问题，当前文档已达到发布前评审通过标准。

### Rating /10
**9.6 / 10**

### Round 3 Issues Tracking

| Round 3 Issue | Status | Evidence (v2.1.1) | 结论 |
|---|---|---|---|
| L-1 文末版本号未对齐 v2.1.1 | Resolved | `L1267` | 已明确改为 `review-ready v2.1.1`。 |
| L-2 4/5 道硬门表述不一致 | Resolved | `L387`, `L443`, `L1118`, `L1136`, `L1240` | 主体、清单、验收、变更日志均统一为 5 道硬门。 |
| L-3 C-1 仍写旧 concurrency 口径 | Resolved | `L352`, `L1112` | C-1 已改成动态 concurrency（mock-test=`quant-mock-test`，其余=`quant-state-main`）。 |

### Consensus Status
**APPROVED**
