# Plan Review: 量化主页接入 Backtest 报告查看器
**Plan File**: docs/agents/quant/quant-backtest-viewer-plan.md
**Reviewer**: Codex
---
## Round 1 — 2026-04-26
### Overall Assessment
这个 v3 plan 比前两轮更聚焦，但仍有多处“写得漂亮、落地会翻车”的硬伤，尤其是同步语义和数据契约没有闭环。当前设计把关键正确性压在 regex 和人工流程上，和你强调的“消除特殊情况、数据隔离可验证”是冲突的。按当前文档直接实施，线上很容易出现陈旧报告与错误评价并存。
**Rating**: 4/10

### Issues
#### Issue 1 (Critical): 13 个报告的基线与真实源数据不一致
**Location**: §1.1 Round-3 范围（line 21），§2.1 数据流图（line 113），Step 2 期望（lines 570-575）
计划反复把范围写成 13 个，但当前仓库 `docs/agents/backtest/` 下匹配 `v9-\d{6}.md` 的单 code 文件实际是 14 个（多了 `v9-932000.md`）。这会直接导致验收清单、列表总数、脚本日志期望全部失真。
**Suggestion**: 明确“权威名单”机制：要么在脚本中维护 allowlist（严格 13），要么把验收基线改为自动按匹配数量；并增加启动时 assert（实际数量 vs 计划数量）失败即退出。

#### Issue 2 (Critical): sync 语义没有“删旧”，会长期保留孤儿文件
**Location**: `sync_files()`（lines 205-219），场景 3 描述（lines 662-665）
脚本只有 copy 没有 prune。源目录文件被删除后，展示目录旧文件不会自动清理，和文档“下次 sync 会同步删除”相矛盾，最终会把已下线报告继续对外展示。
**Suggestion**: 在 sync 阶段加入集合对账：`dst_expected` 之外的 `*.md` 自动删除（支持 `--no-prune` 开关）；并把删除动作写入日志和 dry-run 输出。

#### Issue 3 (High): enrich 解析过度依赖固定 regex，缺少失败保护
**Location**: `parse_metrics()`（lines 236-253），风险说明（lines 700-704）
关键指标表和 Calmar 权重表都靠硬编码 regex 抓取，任何列名改动、顺序调整、空行/对齐变化都可能静默失配，最后生成“0.00%/空权重”的伪正常综合评价。
**Suggestion**: 先做 fail-fast，再谈容错。每个文件必须校验 `CAGR/最大回撤/胜率/权重` 四组字段完整，不完整就报错并中止；中期应改为结构化源（例如回测生成 JSON 再渲染 md）。

#### Issue 4 (High): 权重列按固定下标读取，列漂移会读错数据
**Location**: `parse_metrics()`（lines 250-259）
当前直接取 `cells[4]` 解析百分比，默认“第 5 列一定是权重”。一旦报告模板插入新列或调整顺序，脚本会把错误列当权重，且不会报警。
**Suggestion**: 先解析表头映射再按列名取值（`权重`），不要按 magic index；并在缺列时抛异常。

#### Issue 5 (High): URL code 路由只描述了输入校验，没有定义直链防护
**Location**: viewer 逻辑说明（lines 524-535）
文档只写了“输入框先校验 code 在索引里”，但没有规定对 URL `?code=` 的严格校验。若实现直接拼 `fetch('backtest/' + code + '.md')`，会有路径探测/越权读取风险。
**Suggestion**: 明确路由契约：URL code 只能命中 `index.json.reports` 的 `file` 白名单；任何不在索引中的 code 直接 404，不做字符串拼路径。

#### Issue 6 (Medium): BTC 等非数字 code 的契约前后矛盾
**Location**: `V9_PATTERN`（line 198） vs 输入框行为（line 534）
脚本层允许 `[A-Z]+`（例如 BTC），但 viewer 规则写成“仅 6 位数字”。这不是小瑕疵，是数据契约冲突：后续加 BTC 会被后端同步、前端拒绝访问。
**Suggestion**: 统一 code 规范（例如 `^[0-9]{6}$|^[A-Z]{2,10}$`），并同步到脚本、viewer、验收 checklist 三处。

#### Issue 7 (Medium): 单脚本三合一把职责耦死，调试与回归都变重
**Location**: 设计决策（line 73），脚本职责（lines 163-167）
`sync + enrich + index` 强耦合在一个执行路径，看似省命令，实则降低可测性和可回归性。任何一步异常都阻断全流程，也不利于单步重跑排错。
**Suggestion**: 保留单入口，但拆成子命令：`sync`、`enrich`、`index`；默认 `all` 串联，出问题时可精准重跑单步。

#### Issue 8 (Medium): viewer 的错误态/loading/a11y 设计过薄
**Location**: HTML 根节点与初始化（lines 512-516），错误处理（lines 537-540），Step 6 checklist（lines 613-620）
当前只定义“加载中...”和两类错误文案，没有 retry、无障碍语义、焦点管理、网络超时策略。密码 gate + 异步加载叠加后，用户很容易陷入“空白页但无可操作路径”。
**Suggestion**: 补充状态机规范：`loading / loaded / empty / error`；为状态文案加 `aria-live`，错误态提供“返回列表/重试”按钮，并把焦点移动到错误标题。

#### Issue 9 (Medium): pre-commit 与新目录的协作策略缺失
**Location**: Step 7 提交步骤（lines 622-628）
仓库已有 pre-commit hook 主要拦截 `docs/index.html` 与 `docs/archive/*`，本计划新增 `docs/quant/backtest/*` 大量生成文件，但没有任何“源变更必须重建产物”的钩子或 CI 校验，容易提交陈旧 index/md。
**Suggestion**: 加一个轻量校验脚本（或 CI job）：若 `docs/agents/backtest/v9-*.md` 有变更，则运行 build 并断言工作区无 diff，否则拒绝提交。

#### Issue 10 (High): 回滚预案与 keep_files 语义冲突，执行路径不可靠
**Location**: 回滚预案（lines 734-737），workflow 真值表（line 647）
你在回滚里写“删本地目录 + quant deploy 后 gh-pages 保留旧文件”，这实际上不是回滚，而是保持线上旧状态不变；后续还要依赖另一条 workflow 再做删除，操作链条长且容易误判。
**Suggestion**: 定义单步可验证回滚：`revert 功能 commit -> 触发 update.yml 全量同步` 作为唯一真路径；文档里删除“先 quant deploy 再说”的半回滚流程。

#### Issue 11 (Low): `index.json` 声称“无 null”但实现未强制
**Location**: schema 说明（line 464），`build_index()`（lines 390-391）
计划说全部必填，但 `category` 解析失败会是 `None`，照样写入 JSON。文档与实现契约不一致，会污染前端筛选逻辑。
**Suggestion**: 在构建阶段做必填校验，缺字段就报错退出，并在日志打印具体文件名。

#### Issue 12 (Suggestion): 百分号符号格式缺乏统一函数，存在后续双符号回归风险
**Location**: `build_summary()`（lines 335, 345）
当前 `alpha` 用手工 `sign + {:.2f}`，`CAGR` 用 `{:+.2f}`，今天看起来正确，但维护者很容易改出 `++1.23%` 这类双符号回归。你已经点名这个风险，计划却没防线。
**Suggestion**: 收敛成统一格式化函数（如 `fmt_pct(value, signed=True)`），并加 3 个黄金用例（正/负/零）做回归测试。

### Positive Aspects
- v3 明确提出开发目录与展示目录隔离，这个方向是对的。
- 把 URL 参数简化到 `?code=`，前端心智负担明显下降。
- 明确“不改 password gate、不引入后端 API”，范围控制比前两轮克制。

### Summary
Top 3 关键问题是：1) 报告数量基线错误（13 vs 14）会导致整套验收标准失效；2) sync 没有 prune，孤儿文件会长期挂在线上；3) enrich 解析缺少 fail-fast，极易生成“看似正常但数据错误”的综合评价。先修这三点，再谈 UI 细节和部署便利性。
**Consensus Status**: NEEDS_REVISION
---
## Round 2 — 2026-04-26
### Overall Assessment
v3.1 明显不是“改了文案糊弄”，多数 Round 1 的硬伤确实被实质性修复，尤其是 prune、fail-fast、白名单路由和回滚路径收口。问题在于，新引入的状态机与 check/预提交联动还不够闭环，存在“看起来有防线，实际可绕过”的缺口。整体质量较 Round 1 大幅提升，但还没到可无条件放行。
**Rating**: 6.5/10

### Previous Round Tracking
| # | Issue (Round 1) | Status (RESOLVED/PARTIAL/NOT_RESOLVED) | Notes |
|---|---|---|---|
| 1 | 13 个报告基线与真实数据不一致 | PARTIAL | 已改成“≈14 + baseline assert”（`quant-backtest-viewer-plan.md:51-54,230-238`），但仍是下限校验，不是精确集合校验。 |
| 2 | sync 无删旧，孤儿文件残留 | RESOLVED | `sync_files(prune=True)` 已落地（`...:241-270`），且验收补了 prune 场景（`...:871-875`）。 |
| 3 | enrich regex 失配会静默产出伪结果 | RESOLVED | `MetricsParseError` + enrich 汇总失败后 `sys.exit(1)`（`...:309-334,432-463`）。 |
| 4 | 权重固定列下标（magic index） | RESOLVED | 改为 `parse_table_by_header()` + 列名查找“权重”（`...:281-345`）。 |
| 5 | URL 直链缺白名单防护 | RESOLVED | `CODE_RE` + `resolveReportFile()` 白名单后才 fetch（`...:716-746`）。 |
| 6 | BTC/非数字 code 契约冲突 | RESOLVED | 脚本与前端统一到 `^(\\d{6}|[A-Z]{2,10})$`（`...:193,716`）。 |
| 7 | 三合一脚本 SRP 过重 | RESOLVED | 已拆 `sync/enrich/index/all/check` 子命令（`...:146-166,558-596`）。 |
| 8 | viewer 状态/错误/a11y 过薄 | PARTIAL | 补了状态机/aria-live/retry（`...:680-683,697-777`），但状态数据写入与 timeout 仍有实现缺口（见 Round 2 新问题）。 |
| 9 | pre-commit 与新目录协作缺失 | PARTIAL | 新增 `build ... check` 提醒（`...:815-830`），但仅 warning 且 check 深度不足，仍可提交失同步产物。 |
| 10 | 回滚预案与 keep_files 语义冲突 | RESOLVED | 已收敛成 `revert + update.yml force` 单一路径（`...:1035-1054`）。 |
| 11 | index.json “无 null”无强约束 | RESOLVED | `build_index` 缺 category 直接 fail（`...:470-499`），schema 也改为必填（`...:645-649`）。 |
| 12 | 百分号格式可能双符号 | RESOLVED | `fmt_pct()` 统一输出 + 黄金测试（`...:203-213,607-621`）。 |

### New Issues (Round 2)
#### Issue 13 (Critical): 状态机 `setState` 丢弃 payload，错误态数据不会进入 state
**Location**: `quant-backtest-viewer-plan.md:706-710,740-756,763-770`
`loadDetail()` 调 `setState('error', {message, retryFn})`，但 `setState(next, data)` 完全没把 `data` 写回 `state.error`。随后 `renderError()` 直接访问 `state.error.message/retryFn`，按当前片段会触发空引用或渲染空错误态。
**Suggestion**: 明确状态写入契约：`setState(next, patch)` 至少要 `Object.assign(state, patch)`，并在 `next==='error'` 时强制校验 `state.error` 非空。

#### Issue 14 (High): `check` 只校验“有无文件”，不校验内容一致性
**Location**: `quant-backtest-viewer-plan.md:515-545,818-827`
`cmd_check` 只比较 code 集合和 index.json 存在性，无法发现“源 md 改了但展示 md 未重建”“index 中 metadata 过期”“enrich 丢失”等问题。也就是说它不能证明“同步”，只能证明“文件壳子在”。
**Suggestion**: `check` 至少增加一层内容校验：比对源/目标 hash（或 mtime+size+marker），并校验每个展示 md 含 `## 综合评价`，否则 exit 1。

#### Issue 15 (High): pre-commit 仅告警不阻断，数据失同步可直接进主干
**Location**: `quant-backtest-viewer-plan.md:818-830,1018-1019`
你在设计里明确写了“非 hard-fail，继续 commit 不会被阻止”。这和“展示目录受控、避免错误数据上线上”目标冲突：最关键校验点允许被无成本忽略。
**Suggestion**: 默认 hard-fail，提供显式逃生阀（如 `SKIP_BACKTEST_SYNC_CHECK=1 git commit ...`）。让绕过变成有意行为，而不是默认行为。

#### Issue 16 (Medium): 基线保护是“下限”不是“清单”，会吞入意外 v9 文件
**Location**: `quant-backtest-viewer-plan.md:53,198,230-238`
`assert_baseline` 只要求“数量 >= 14”。如果开发目录误入额外 `v9-*.md`（临时/脏文件），脚本会合法通过并对外发布，无法保护“受控范围”。
**Suggestion**: 引入 manifest（精确 code 列表）并做 exact match；或至少新增 `--strict-manifest` 默认开启，`--allow-extra` 作为显式降级。

#### Issue 17 (High): schema 声明 `file == {code}.md`，但实现未做一致性校验
**Location**: `quant-backtest-viewer-plan.md:645-649,481-493`
`build_index` 里的 `code` 来自 markdown 标题，`file` 来自文件名，二者若被手工改坏可以不一致。此时白名单按 `code` 走，fetch 按 `file` 走，行为会出现隐蔽错配。
**Suggestion**: 在 `build_index` 增加强校验：`if f.name != f"{code}.md": failures.append(...)`，直接 fail-fast。

#### Issue 18 (Medium): 文档宣称“网络超时 10s”，但示例代码没有 timeout 机制
**Location**: `quant-backtest-viewer-plan.md:746-757,797`
错误表写了“网络超时（10s）”，但 `fetch(...)` 片段没有 `AbortController` 或超时包装。网络挂起时可能长期停留在 loading，不会进入 error/retry。
**Suggestion**: 明确实现 `fetchWithTimeout(url, 10000)`，并在超时分支 `setState('error', ...)`，把文档承诺和代码行为对齐。

### Positive Aspects
- Round 1 的核心架构缺陷（prune、fail-fast、白名单、回滚路径）都做了实质性补强，不是纯文字修辞。
- 子命令拆分让调试和单步重跑比 v3 清晰很多，执行层可操作性明显提升。
- `fmt_pct` + 黄金用例是正确的“把易回归点变成可测试契约”的做法。

### Summary
闭合度结论：12 条旧 issue 中，`RESOLVED=8`、`PARTIAL=4`、`NOT_RESOLVED=0`，修复质量整体合格但未闭环。新问题里最关键的是 `Issue 13/14/15`：状态机 payload 丢失、check 只验壳不验内容、pre-commit 默认放行。这三条不补，线上仍会出现“看似有保护，实际可带错数据发布”。
**Consensus Status**: NEEDS_REVISION

---
## Round 3 — 2026-04-26
### Overall Assessment
v3.2 的修复质量明显再上一个台阶，Round 2 提出的 6 个问题里 5 个闭合得比较硬，尤其是 `setState` payload 契约、`fetchWithTimeout` 和 pre-commit hard-fail。Round 1 的 3 个历史 PARTIAL（1/8/9）也基本补齐。剩余阻塞点集中在 `check` 的严格性与文档契约一致性，属于“最后 10%”但会直接影响防错能力。
**Rating**: 8/10

### Previous Round Tracking
| # | Issue | Round 1 Status | Round 2 Status | Round 3 Status |
|---|---|---|---|---|
| 1 | 报告数量基线与真实源数据不一致 | NOT_RESOLVED | PARTIAL | RESOLVED |
| 2 | sync 无删旧，孤儿文件残留 | NOT_RESOLVED | RESOLVED | RESOLVED |
| 3 | enrich regex 失配静默产出伪结果 | NOT_RESOLVED | RESOLVED | RESOLVED |
| 4 | 权重固定列下标（magic index） | NOT_RESOLVED | RESOLVED | RESOLVED |
| 5 | URL 直链缺白名单防护 | NOT_RESOLVED | RESOLVED | RESOLVED |
| 6 | BTC/非数字 code 契约冲突 | NOT_RESOLVED | RESOLVED | RESOLVED |
| 7 | 三合一脚本 SRP 过重 | NOT_RESOLVED | RESOLVED | RESOLVED |
| 8 | viewer 状态/错误/a11y 过薄 | NOT_RESOLVED | PARTIAL | RESOLVED |
| 9 | pre-commit 与新目录协作缺失 | NOT_RESOLVED | PARTIAL | RESOLVED |
| 10 | 回滚预案与 keep_files 语义冲突 | NOT_RESOLVED | RESOLVED | RESOLVED |
| 11 | index.json “无 null”无强约束 | NOT_RESOLVED | RESOLVED | RESOLVED |
| 12 | 百分号格式可能双符号 | NOT_RESOLVED | RESOLVED | RESOLVED |
| 13 | setState 丢弃 payload（错误态数据丢失） | N/A | NOT_RESOLVED | RESOLVED |
| 14 | check 仅验文件存在，不验内容同步 | N/A | NOT_RESOLVED | RESOLVED |
| 15 | pre-commit 仅告警不阻断 | N/A | NOT_RESOLVED | RESOLVED |
| 16 | baseline 下限校验会吞入意外 v9 文件 | N/A | NOT_RESOLVED | PARTIAL |
| 17 | file 与标题 code 未做一致性校验 | N/A | NOT_RESOLVED | RESOLVED |
| 18 | 文档承诺 timeout 但代码无超时机制 | N/A | NOT_RESOLVED | RESOLVED |

### New Issues (Round 3)
#### Issue 19 (High): `check` 的 L1 只校验缺失，不校验 extra，manifest 严格模式可被绕过
**Location**: `quant-backtest-viewer-plan.md:61,580,591-594`
文档把 manifest 定义为“严格相等”，但 `cmd_check` 的 L1 只检查 `missing_src`，没有检查 `extra_src`。结果是源目录新增 `v9-xxxxxx.md`（不在 manifest）时，`check` 仍可能通过，和“默认严格”目标冲突。
**Suggestion**: 在 `cmd_check` 增加 `extra_src = set(found.keys()) - MANIFEST`，默认失败；仅在显式开关（如 `--allow-extra`）下放行并打印强警告。

#### Issue 20 (Medium): L5 对 `index.json` 只校验 `total`，无法保证索引项与 manifest 一致
**Location**: `quant-backtest-viewer-plan.md:621-631,740-746`
当前 L5 只验证 `total == len(MANIFEST)`。若 `index.json` 保持 14 条但 code/file 被人为改坏，check 仍可能通过，和“白名单可信”目标不匹配。
**Suggestion**: L5 追加集合校验：`reports.code` 集合必须等于 `MANIFEST`，且每项 `file == {code}.md`，否则 fail。

#### Issue 21 (Medium): v3.2 文档仍保留多处过期描述，执行口径前后矛盾
**Location**: `quant-backtest-viewer-plan.md:139,176,1001-1002,1181-1183`
文档仍残留“pre-commit 非 hard-fail”“--baseline/assert_baseline”“pre-commit 仅警告不强制”等旧口径，与 v3.2 新设计冲突。对接下一位执行者时会直接造成误操作。
**Suggestion**: 做一次“契约清理”：删除所有 baseline/非 hard-fail 旧描述，统一到 manifest + hard-fail + escape hatch 的单一口径。

### Positive Aspects
- Round 2 的核心问题（13/15/17/18）修复是实打实落地，不是换措辞。
- `check` 从壳层校验升级到 L1-L5 分层，方向正确且可扩展。
- `setState(next, patch)` + 错误态 fail-safe 让状态机从“脆弱样例”变成了可维护契约。

### Summary
闭合结论：18 条历史 issue 中，Round 3 已实质解决绝大多数；Round 1 的 PARTIAL（1/8/9）已补齐，Round 2 的 13-18 中仅 Issue 16 仍为 PARTIAL。当前阻塞主要是 `check` 与 manifest/index 的严格性闭环（Issue 19/20）和文档口径一致性（Issue 21）。修完这三条，这个 plan 可以进入 APPROVED。
**Consensus Status**: NEEDS_REVISION
---
## Round 4 — 2026-04-26
### Overall Assessment
v3.3 的收尾质量总体扎实，Round 3 的两个功能性问题（Issue 19/20）都做成了实质闭环：`cmd_check` 已从“弱校验”升级为更严格的一致性守门。剩余问题主要是文档口径仍有少量历史残留，属于执行指引一致性问题，不是核心逻辑缺陷。
**Rating**: 9/10

### Previous Round Tracking
| # | Issue | Round 3 Status | Round 4 Status |
|---|---|---|---|
| 19 | `cmd_check` L1 未校验 extra_src（manifest 严格模式可绕过） | NOT_RESOLVED | RESOLVED |
| 20 | `cmd_check` L5 仅校验 total，未校验 code 集合与 file 一致性 | NOT_RESOLVED | RESOLVED |
| 21 | 文档仍有 baseline/非 hard-fail 旧措辞残留 | NOT_RESOLVED | PARTIAL |

### New Issues (Round 4)
NO_NEW_ISSUES。v3.3 主要是收紧 `cmd_check` 和文档清理，没有引入新的实现性阻塞缺陷。

### Positive Aspects
- `check` 的 L1 现在同时校验 `missing` 和 `extra`，与 manifest 严格模式一致。
- L5 已补上 `reports.code` 集合与 `file/code` 一致性校验，索引可信度明显提升。
- pre-commit hard-fail + escape hatch 的策略在本轮保持一致，守门策略没有被回退。

### Summary
本轮已完成关键收口：Issue 19/20 均闭合，系统级阻塞点已清除。Issue 21 仍有少量文档残留（例如仍可见旧的“assert_baseline/仅警告”措辞），建议再做一次文本口径清扫后即可彻底收官。
**Consensus Status**: MOSTLY_GOOD
