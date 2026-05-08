# Plan Review: 量化主页 Backtest 在线触发回测器
**Plan File**: docs/agents/quant/quant-backtest-runner-plan.md
**Reviewer**: Codex
---
## Round 1 — 2026-04-26
### Overall Assessment
v4 方向纠偏是对的：从纯 viewer 回到 runner+viewer，问题定义终于对齐用户真实目标。  
但这个 plan 现在仍然有几处结构性断点，尤其是 run 关联、部署闭环、安全边界，属于“能演示、但上线后会间歇性错或直接卡住”的状态。  
如果不先修这些关键点，线上体验会很不稳定，且安全风险被明显低估。

**Rating**: 3/10

### Issues
#### Issue 1 (Critical): `workflow_dispatch` 后无法可靠绑定本次 run，存在串单风险
**Location**: §4.6.2 L391-L415, §6.2 L634-L638  
plan 明确承认 dispatch 不返回 run_id，但实现是“取最新 run”近似匹配。这个假设在并发用户、同仓库其他触发、GitHub API 延迟可见时都会错绑。错绑后前端会轮询到别人的 run，出现“你点了 A，结果盯着 B 的状态”，最终跳错详情或误报成功/失败。  
**Suggestion**: 放弃“最新 run”策略，改成强关联：dispatch 输入携带 `request_id`（UUID），workflow `run-name` 包含该 request_id，前端只查询并匹配该 request_id 的 run；再加 created_at 下界和 actor 校验做双保险。

#### Issue 2 (Critical): 部署链路断裂，workflow 成功不等于站点可见
**Location**: §3.1 L81-L85, §4.5, §5 Phase 4 L617-L623  
plan 假设 `backtest.yml` push main 后会被 `update.yml/quant.yml` 自动部署，但现有 workflow 并没有 `on: push`。这意味着“run 成功 + commit 成功”后，gh-pages 可能仍是旧内容，前端立即跳详情时常见 404 或 index 无新 code。  
**Suggestion**: 在 `backtest.yml` 末尾显式触发 deploy（调用 `quant.yml mode=deploy` 或直接复用 quant-only publish step），并在前端成功态增加“等待 index 出现目标 code”的二阶段确认后再跳转。

#### Issue 3 (High): `name` 输入可注入 Markdown/HTML，叠加 PAT 存浏览器形成高危 XSS 窃 token 面
**Location**: §4.5 L286-L289, §4.6.2 L384-L387, §4.6.3 L472, §4.9 L516-L522  
`name` 只做非空校验，没有字符白名单；该值会进入回测 md 标题并最终被前端 markdown 渲染。若渲染链允许 HTML（当前 viewer 是直接 `marked.parse` 后 innerHTML），可形成持久化 XSS，直接读 localStorage 里的 PAT（且包含 actions:write + contents:write）。  
**Suggestion**: 双层防护：1) workflow 校验 `name` 长度与字符集（拒绝 `< > \n \r` 等）；2) 前端渲染启用严格 sanitize（DOMPurify 或 marked sanitizer），并禁止内联 HTML。

#### Issue 4 (High): 前端接口契约写错，按 plan 实现会直接运行时崩
**Location**: §4.6.2 L360/L381/L407/L431, §3.2 L110  
plan 调用 `QuantWriter.getPAT()`，但现有实现暴露的是 `QuantWriter.getPat()`；同时 `backtest.html` 当前并未引入 `writer.js`。这不是“优化项”，是上线即报错级别断点。  
**Suggestion**: 统一方法名为 `getPat`（或在 writer.js 增别名 `getPAT` 兼容），并在 `backtest.html` 明确加载 `lib/config.js + lib/writer.js`，把这个依赖写入文件改动清单与验收项。

#### Issue 5 (High): 并发写仓库存在实际竞态，concurrency 只按 code 分组不够
**Location**: §4.5 L261-L263, L305-L312, §6.4 L645-L648  
`backtest-${code}` 仅串行同 code，不串行不同 code。两个不同 code 并发跑时都会重建同一个 `index.json` 并 push，极易 1 个失败（non-fast-forward）或覆盖顺序抖动。plan 虽提“重试3次”，但给的 workflow 片段并未实现 rebase+retry。  
**Suggestion**: 两个层次选一个：1) 全局串行 `backtest-global`；2) 保留并行但 push 前 `git pull --rebase` + 重建 index + retry（带指数退避），并把重试逻辑写成可复用脚本，别留口头承诺。

#### Issue 6 (High): 单指数模式失败语义不闭环，可能“绿灯成功但没有报告”
**Location**: §4.2 L158-L169, §4.5 L305-L311, §6.3 L640-L643  
现有 `run_v9_detail.py` 批量逻辑对单个指数失败是 continue 风格。若迁移时沿用这套语义，可能出现“数据拉取失败→未生成 md→git no changes→workflow 仍 success”的假成功。前端会按 success 跳详情，结果找不到报告。  
**Suggestion**: 单跑模式必须 fail-fast：目标 code 无数据/无策略结果/未产出文件时直接 `exit(1)`；workflow 在 commit 前断言 `docs/quant/backtest/{code}.md` 存在且包含 `## 综合评价`。

#### Issue 7 (Medium): `region -> source` 过于粗糙，缺少 source-specific code 合法性约束
**Location**: §4.1 L123-L140, §4.5 L282-L283, §7 L672-L679  
目前仅校验 code 形态（6位数字或2-10大写字母），但不同 region 的可跑 code 范围差异很大（例如 crypto 现实上只支持少数符号；us/hk 也有接口侧 symbol 约束）。结果是大量“格式合法但业务必失败”的请求进入 CI。  
**Suggestion**: 增加分 region 校验策略：`cn` 限 6 位或已知前缀；`btc` 先白名单（如 BTC/ETH）再逐步放开；`us/hk` 至少做一次预探测 API 检查再入主流程。

#### Issue 8 (Medium): 旧数据迁移脚本是“全目录通杀”，后续重复执行会污染新报告
**Location**: §4.7 L490-L500, §5 Step 6 L569-L582  
`for f in docs/quant/backtest/*.md; sed ... -> cn` 会改目录下所有 md。当前也许只有 14 个旧文件，但只要后续有 `us/hk/btc` 新报告，再误执行一次就会被改成 `cn`，属于高概率运维误伤。  
**Suggestion**: 迁移只针对明确清单（14 个 code 白名单），并做一次性脚本（执行后写 marker 或直接删除脚本）；同时保留迁移前快照以便回滚比对。

#### Issue 9 (Medium): 删除 sync/MANIFEST 护栏后，缺少替代的数据完整性约束
**Location**: §4.3 L182-L199, §4.8 L505-L512  
v4 删除了 v3.3 的源/目标一致性验证与 pre-commit 同步闸门，但没有给出等价替代机制。结果是“任意 md 只要形状合法就能进 index”，会把误生成、半成品、污染文件直接发布。  
**Suggestion**: 保留轻量护栏而非全删：例如 `code` 唯一性、mtime 单调性、标题-code-文件名三方一致、关键表格字段完整、禁止重复 run 覆盖为更旧数据。

#### Issue 10 (Medium): PAT 安全模型降级，但 plan 只强调可用性未给安全补偿
**Location**: §1.3 L36, §4.9 L516-L522  
把 `actions:write` + `contents:write` PAT 长期放 localStorage，本质上把高权限长期密钥交给浏览器环境。对“静态站点 + 第三方脚本 + Markdown 渲染”来说，这个风险等级不低。plan 没有任何补偿控制（短期 token、最小权限拆分、过期提醒、CSP、token 使用审计）。  
**Suggestion**: 至少做三件事：1) settings 页明确风险并强制短过期（如 7-30 天）；2) token 权限拆分（触发回测与写仓尽量分离）；3) 增 CSP 与敏感操作二次确认。

#### Issue 11 (Medium): a11y/UX 方案不完整，长等待场景会让用户“失联”
**Location**: §4.6.3 L465-L483, §7 L682-L685  
plan 提到 aria-live，但 modal 方案没给焦点陷阱、初始焦点、关闭返回焦点、错误态朗读节奏。并且固定 5 分钟超时后直接报错，不区分“排队中”还是“真失败”，用户体验会频繁误报。  
**Suggestion**: 给出完整 a11y 合同：`role="dialog"` + `aria-modal` + focus trap + escape/取消路径 + 状态文本 `aria-live="polite"`；超时后改为“后台继续 + 可手动刷新状态”，不要直接判死。

#### Issue 12 (Medium): plan 自身改动清单不自洽，存在沉默破坏风险
**Location**: §3.2 L91-L114, §4.1 L122, §4.9 L520, §5 Step 1/Step 9-11  
文件清单写“新增2个文件、总改动21个”，但正文又要求新增 `scripts/backtest/region_dispatcher.py`、更新 `settings.html`/README 文案，还隐含前端脚本依赖调整。这种清单不闭合会导致实施遗漏，最后出现“看似按 plan 做完，实际关键文件没改”。  
**Suggestion**: 重写变更矩阵：按“必须改/可选改/迁移一次性脚本”分层列完整文件；每个文件绑定验收断言，避免口头项漏落地。

### Positive Aspects
- 方向纠偏到 runner+viewer 是正确的，目标和用户真实需求终于一致。  
- 对 `workflow_dispatch` 异步特性有显式识别，没有再假设同步返回结果。  
- 把失败场景（403、数据源失败、push 冲突）提前列出来了，说明作者知道真实世界会出错。  
- 保留旧 14 份报告并做兼容迁移，避免一次性硬切导致页面空窗。

### Summary
Top 3 关键问题：1) run 绑定策略不可靠（会串单），2) 部署闭环断裂（成功不等于可见），3) 安全面太薄（输入可注入 + 高权限 PAT 在浏览器）。

**Consensus Status**: NEEDS_REVISION

---
## Round 2 — 2026-04-26
### Overall Assessment / Rating
v4.1 相比 v4 已经从“结构性不可靠”提升到“可落地但仍有收口漏洞”，核心链路（dispatch 关联、直接 publish、XSS 基础防护）明显补强。  
但我做独立核对后，12 条里仍有多条仅部分闭合，且 v4.1 新增实现里出现了新的执行级缺陷（尤其 workflow push/校验脚本细节）。  
当前状态不适合直接 APPROVED。

**Rating**: 6.5/10

### Previous Round Tracking
| # | Issue | Round 1 Status | Round 2 Status |
|---|---|---|---|
| 1 | run 绑定不可靠 | OPEN | PARTIAL |
| 2 | 部署链路断裂 | OPEN | RESOLVED |
| 3 | name 注入/XSS 风险 | OPEN | RESOLVED |
| 4 | getPAT/getPat 契约错配 | OPEN | RESOLVED |
| 5 | 并发写仓竞态 | OPEN | PARTIAL |
| 6 | 单跑 silent success | OPEN | RESOLVED |
| 7 | region→source 校验不足 | OPEN | PARTIAL |
| 8 | 迁移脚本通杀全目录 | OPEN | RESOLVED |
| 9 | 删 sync 后护栏缺失 | OPEN | PARTIAL |
| 10 | PAT 安全补偿不足 | OPEN | PARTIAL |
| 11 | modal a11y 不完整 | OPEN | RESOLVED |
| 12 | 变更矩阵不完整 | OPEN | PARTIAL |

### New Issues
#### Issue N1 (High): push retry 3 次后仍可能“假成功”
**Location**: plan §4.5 L461-L479  
`for i in 1 2 3` 循环里如果三次 `git push` 都失败，脚本不会 `exit 1`，step 可能以成功结束，前端看到 workflow success 但 main 并未更新。  
**Suggestion**: 循环后加明确失败断言，例如 `pushed=false` 标记，三次失败后 `exit 1`。

#### Issue N2 (Medium): workflow name 长度校验 shell 写法错误，规则未真正生效
**Location**: plan §4.5 L431-L433  
`${#inputs[name]}` 不是这里应使用的变量写法，`name` 长度校验在当前脚本中不可靠，可能放过超长输入。  
**Suggestion**: 先赋值 `NAME="${{ inputs.name }}"`，再用 `if [ ${#NAME} -gt 30 ]; then ... fi`。

#### Issue N3 (Medium): request_id 查 run 仍有漏匹配/误匹配窗口
**Location**: plan §4.6.2 L659-L679  
`findRunByRequestId()` 只拉 `per_page=10` 且按 `indexOf(requestId)` 模糊匹配。仓库 run 密集时可能翻页漏掉；模糊匹配也可能在异常输入下误命中。  
**Suggestion**: 至少增加分页/时间窗过滤，并做精确匹配（例如 `run.name === "backtest:" + code + ":" + requestId`）。

#### Issue N4 (Medium): 文档存在 v4/v4.1 混杂，执行口径会被带偏
**Location**: plan §6.2 L1172-L1177, §8 L1240, §9 L1251  
这些段落仍保留 v4 旧描述（“最近 1 分钟最新 run”“backtest-${code}”“21 文件”“sed 迁移”），与 v4.1 修复口径冲突。实施者按该段执行会回退到旧方案。  
**Suggestion**: 清理所有过时段落，保证 risk/对照/review 准备区与 v4.1 主方案一致。

### Positive Aspects
- 把 `request_id` 引入 dispatch 与 run-name，方向正确，已脱离“最新 run”硬猜。  
- backtest workflow 内直接 publish quant-only，修复了 Round 1 最严重的部署断链。  
- XSS 防护从单点变成了多层（输入校验 + DOMPurify + getPat 契约修正），工程上更稳。  
- 迁移脚本改为白名单 + 幂等，避免了旧版 sed 通杀误伤。

### Summary / Consensus Status
v4.1 已明显进步，但尚未达到“可无保留批准”的标准：主要剩余风险是 workflow 脚本细节会制造假成功，以及文档仍有旧口径残留。  
建议先修复 N1/N2/N4，再复审一次；这三项清掉后基本可进入 APPROVED。

**Consensus Status**: NEEDS_REVISION

---
## Round 3 — 2026-04-26
### Overall Assessment / Rating
v4.2 对 Round 2 的 4 条新增问题修复是实质性的，尤其是 push 失败硬退出、shell 长度校验、run 关联精确匹配，这些都把主链路稳定性抬上来了。  
但独立复核后，Round 1 里仍有部分中风险项未完全收口（region 约束、安全补偿、文档一致性），且 v4.2 新引入了 1 个时间基准相关的匹配风险。  
整体已接近可批，但还不满足“全闭合 APPROVED”。

**Rating**: 8.0/10

### Previous Tracking
| # | Issue | R1 | R2 | R3 |
|---|---|---|---|---|
| N1 | push retry 假成功 | N/A | OPEN | RESOLVED |
| N2 | shell 长度校验写法错误 | N/A | OPEN | RESOLVED |
| N3 | run 查找漏匹配/误匹配 | N/A | OPEN | PARTIAL |
| N4 | v4/v4.1 过时口径残留 | N/A | OPEN | RESOLVED |
| 1 | run 绑定不可靠 | OPEN | PARTIAL | PARTIAL |
| 5 | 并发写仓竞态 | OPEN | PARTIAL | RESOLVED |
| 7 | region→source 校验不足 | OPEN | PARTIAL | PARTIAL |
| 9 | 删 sync 后护栏缺失 | OPEN | PARTIAL | RESOLVED |
| 10 | PAT 安全补偿不足 | OPEN | PARTIAL | PARTIAL |
| 12 | 变更矩阵不完整 | OPEN | PARTIAL | PARTIAL |

### New Issues
#### Issue R3-N1 (Medium): run 匹配时间窗依赖客户端时钟，存在时钟漂移误判
**Location**: plan §4.6.2 L669-L688  
`earliestAllowed` 基于浏览器 `Date.now()` 计算（`dispatchedAt - 5000`）。若用户本机时钟明显快于 GitHub 服务器，`created_at >= earliestAllowed` 可能长期不成立，导致明明已触发却找不到 run。  
**Suggestion**: 时间窗基准改为服务端时间（例如 dispatch 后首次 `runs` 响应头 Date，或去掉 created_at 下界仅保留 `run.name` 精确匹配 + retry/pagination）。

### Positive Aspects
- N1 修复到位：`PUSHED=false` + 三次失败后 `exit 1`，彻底堵住“假成功”。  
- N2 修复到位：`env: NAME` 注入 + `${#NAME}`，shell 规则正确且可读。  
- N3 大幅提升：`===` 精确匹配、带 code、扩大 `per_page` 并加翻页，误绑概率显著下降。  
- N4 指定过时口径已清理，风险章节核心逻辑和 v4.2 主方案一致。

### Summary / Consensus Status
v4.2 已经完成了主要阻塞问题清理，当前剩余项以中风险收口为主，不是架构级阻塞。  
建议再补一轮小修（R3-N1 + Issue 7/10/12）即可进入 APPROVED。

**Consensus Status**: MOSTLY_GOOD
