# Plan Review: Scripts Python 代码优化计划
**Plan File**: docs/agents/scripts-code-cleanup.md
**Reviewer**: Codex

---
## Round 1 — 2026-04-10
### Overall Assessment
这个计划有明确的重构切分和一定的风险意识，但“功能完全不变”的证明链条明显不足，多个关键步骤存在行为变更却被标成低风险。当前文档更像“重构意图说明”，还达不到可安全执行的工程计划标准。建议先补齐可重复验证、兼容性边界和回退策略，再进入实施。
**Rating**: 5/10

### Issues
#### Issue 1 (Critical): 回归验证依赖实时外部数据，无法证明“功能完全不变”
**Location**: `TDD 策略` 基准快照与每步验证（L26-L39, L57-L66）
当前基准和对比都基于实时 AkShare/yfinance 返回。即使代码不变，数据也会随时间、接口波动、补数据而变化，`diff` 结果不具可重复性；反过来，真实行为变更也可能被实时噪声掩盖。
**Suggestion**: 引入“固定输入回放”验证：先把每个指数的原始 DataFrame 序列化到本地快照（如 parquet/json），重构前后都用同一批快照计算，再对关键字段做结构化比对（status/deviation/big_cycle/status_change/extreme_trend/rank）。

#### Issue 2 (Critical): 步骤 5 实际改变容错语义，却未给出变更影响评估
**Location**: `步骤 5：理顺 _fetch_cs_index 异常处理`（L421-L455）
计划移除 `_fetch_cs_index` 的重试并声明“更快更可靠”，这不是纯重构，而是策略变更：遇到中证瞬时抖动会更早切到新浪，可能导致数据源一致性与历史可比性变化。
**Suggestion**: 把该步骤拆成“行为变更提案”，补充对比实验（同一时段多次拉取成功率、延迟、字段一致性），并新增开关（例如 `prefer_cs_retry=True`）保证可回滚到旧策略。

#### Issue 3 (High): 步骤 4 的验证方法无法覆盖 monkey-patch 是否生效
**Location**: `步骤 4 验证`（L369-L387）
验证示例里 `prepare_request` 只构建请求对象，不会走 `Session.request` 发送路径，无法证明 UA 注入逻辑是否仍然生效。该验证会产生“假阳性通过”。
**Suggestion**: 使用可控桩验证：mock `Session.request` 的下游调用并断言最终 `headers['User-Agent']` 存在；同时分别覆盖 `requests.get`、`requests.request`、`Session().request` 三条调用链。

#### Issue 4 (High): 步骤 6a 引入隐式前置条件，可能破坏公开方法兼容性
**Location**: `步骤 6a`（L493-L506）
计划删除 `detect_status_change/find_status_change_date/detect_extreme_trend` 内部排序，并要求调用方保证已排序。这改变了函数自身的容错语义；这些方法是公开实例方法，外部直调将出现行为漂移。
**Suggestion**: 二选一：
1. 保留内部排序（安全优先）；
2. 将其改为私有方法并仅由 `calculate_all_metrics` 调用，同时在 PR 中明确“API 收敛”并加调用扫描。

#### Issue 5 (High): 直接删除手工数据源脚本，削弱故障诊断能力
**Location**: `步骤 1：删除废弃测试脚本`（L78-L93）
这些脚本虽然不是自动化测试，但在项目文档中被明确作为“手动数据源测试脚本”使用。直接删除会降低线上异常时快速定位数据源问题的能力。
**Suggestion**: 不要直接删除，改为迁移到 `scripts/manual_checks/` 并统一入口（如 `python scripts/manual_checks/run_source_check.py --source cs_index`），在文档中标记“非 CI，仅运维排障”。

#### Issue 6 (High): 把共享函数塞进 `scripts/__init__.py`，模块边界设计不合理
**Location**: `步骤 8a`（L732-L747）
将 `load_config` 放进包入口会让 `__init__` 承担工具职责，后续容易演变为“杂物入口”，增加隐式依赖和导入副作用风险。
**Suggestion**: 新建 `scripts/config_loader.py`（或 `scripts/common/config.py`）承载 `load_config`，`main.py/backfill_archive.py` 显式 `from scripts.config_loader import load_config`。

#### Issue 7 (Medium): “跨文件重复消除”范围不完整，遗漏 backfill 中同类逻辑
**Location**: `步骤 8：消除跨文件重复`（L710-L799）
计划处理了 `main.py` 的 rank_change 双循环，但 `backfill_archive.py` 里也有几乎同构的 major/sector rank_change 逻辑，未纳入统一策略。
**Suggestion**: 增加 8c：抽取通用函数（例如 `apply_rank_changes(results, get_prev_rank)`）并在 `main.py` 与 `backfill_archive.py` 共用，避免下一次再次分叉。

#### Issue 8 (Medium): 最终验证覆盖面不足，无法发现归档页与排名持久化回归
**Location**: `最终验证`（L68-L74）
最终只比较 `docs/index.html`，没有验证 `docs/archive/YYYY-MM-DD.html`、`docs/archive/index.html` 和 `scripts/ranking_history.json` 的结构一致性，回归盲区很大。
**Suggestion**: 增加结构化对比：
- 归档详情页：关键表格行数、关键字段渲染存在性；
- 归档列表页：月份分组和文件数量；
- ranking_history：today/yesterday 键结构与 rank 集合一致。

#### Issue 9 (Medium): 日志改造缺少 backfill 路径验证，风险评估偏乐观
**Location**: `步骤 2d` 与该步骤验证（L172-L210, L232-L240）
计划删除多个模块级 `basicConfig`，但验证只做 import/py_compile，没有覆盖 `backfill_archive.py` 实际运行日志格式和级别是否符合预期。
**Suggestion**: 在步骤 2 验证补一条：`python scripts/backfill_archive.py --days 1`，并断言日志格式/级别正确（至少检查时间戳和 INFO 输出存在）。

#### Issue 10 (Medium): 步骤 3 的一致性验证过于粗糙，无法保证 OHLC 聚合等价
**Location**: `步骤 3 验证`（L306-L318）
当前只打印行数和末日期，无法证明 open/high/low/close 聚合结果与重构前完全一致，也没有覆盖空数据/异常输入。
**Suggestion**: 增加对比脚本：同一输入下逐列比对 weekly/monthly DataFrame（含列名、dtype、每列 hash 或 `assert_frame_equal`），并补充空 df、缺列 df 的负例验证。

#### Issue 11 (Low): 总览指标口径不清且与仓库现状不一致
**Location**: `总览`（L10-L19）
文档称“8 个 .py（含 3 个废弃 test 脚本）”，但当前 `scripts/` 实际还有 `__init__.py`、`ranking_store.py` 等，口径不清会误导评审对工作量和收益的判断。
**Suggestion**: 明确统计口径（例如“仅统计核心执行脚本，不含包文件与存储模块”），并附一条自动统计命令保证数字可复现。

#### Issue 12 (Suggestion): “失败立即回退”缺少可执行机制
**Location**: `执行顺序与检查点`（L871）
当前只有原则，没有操作化手段。多步重构若连续进行，失败时很难精确回退到某一步。
**Suggestion**: 为每步增加固定检查点策略（如“每步单独 commit 或 patch 文件”），并给出回退命令模板（例如 `git restore -SW <files>` 针对该步影响文件）。

### Positive Aspects
- 计划按步骤拆分较细，便于分批落地和分批验证。
- 大部分改动优先保证公开接口不变，重构意图整体是克制的。
- 对重复逻辑和日志配置问题有较准确的问题识别，方向基本正确。

### Summary
Top 3 key issues: 1) 回归验证不可重复，当前证据链无法支撑“功能完全不变”；2) `_fetch_cs_index` 重试策略被改写为行为变更却未量化评估；3) 若删除手工数据源脚本会损失排障能力且未给替代方案。
**Consensus Status**: NEEDS_REVISION

---
## Round 2 — 2026-04-10
### Overall Assessment
新版计划明显吸收了不少 Round 1 反馈，验证设计和步骤拆分都更完整了，质量较第一版有实质提升。问题在于仍有几个高优先级缺口没有闭环：手工排障脚本被直接删除、步骤 5 缺少“失败场景”的验证证据、以及把通用能力继续堆进 `scripts/__init__.py`。当前版本已经接近可执行，但还不够稳。
**Rating**: 6.5/10

### Previous Round Tracking
| # | Issue | Status | Notes |
|---|-------|--------|-------|
| 1 | 回归验证依赖实时外部数据，无法证明功能不变 | Partially Resolved | 已引入快照回放与指标对比，但仍混用实时日志 diff，且覆盖面仍有限。 |
| 2 | 步骤 5 改变容错语义未评估 | Partially Resolved | 增加了“codify existing behavior”说明，但缺少针对 csindex 失败场景的可验证证据。 |
| 3 | 步骤 4 验证无法覆盖 patch 生效 | Partially Resolved | 增加了 mock 验证，但仍存在吞异常与可能假通过的问题。 |
| 4 | 步骤 6a 可能破坏公开方法兼容性 | Resolved | 已改为私有方法并补了调用扫描，兼容性风险显著下降。 |
| 5 | 删除手工数据源脚本削弱排障能力 | Unresolved | 仍是直接删除，没有迁移到 manual checks 或替代入口。 |
| 6 | 把共享函数放进 `scripts/__init__.py` 边界不合理 | Unresolved | 仍使用 `__init__.py`，且新增 `apply_rank_changes`，边界进一步模糊。 |
| 7 | 跨文件重复消除遗漏 backfill | Resolved | 已新增 8c，覆盖 backfill 同类逻辑。 |
| 8 | 最终验证覆盖面不足 | Partially Resolved | 新增归档与 ranking 检查，但仍偏结构层，内容等价性不足。 |
| 9 | logging 改造缺少 backfill 验证 | Resolved | 已补充 `backfill_archive.py --days 1` 验证路径。 |
| 10 | 步骤 3 验证过粗 | Resolved | 已使用固定快照 + `assert_frame_equal`，并补边界用例。 |
| 11 | 总览口径不清且数字不准 | Unresolved | 加了口径说明，但文件总数仍与当前仓库不一致。 |
| 12 | 回退机制不可执行 | Partially Resolved | 已新增 commit/revert 流程，但仍包含高风险/不推荐命令与流程冲突。 |

### Issues (new or unresolved)
#### Issue 13 (High): 步骤 1 仍然直接删除手工排障脚本，缺少可替代诊断路径
**Location**: `步骤 1：删除废弃测试脚本`（L138-L162）
计划继续把 `scripts/test_*.py` 直接删除，但这些脚本在当前项目语境里承担“数据源故障快速探测”的运维价值。删除后，数据源异常时会缺少低成本现场确认工具。
**Suggestion**: 改为“迁移而非删除”：保留到 `scripts/manual_checks/`，统一入口并标注非 CI 用途；至少保留 `cs_index/sina_index` 两个最常用探针脚本。

#### Issue 14 (High): 共享工具持续堆入 `scripts/__init__.py`，模块职责继续恶化
**Location**: `步骤 8a`（L821-L838）与 `步骤 8c`（L912-L938）
`load_config` 和 `apply_rank_changes` 都被放进包入口文件，`__init__.py` 从“包声明”演变成“工具集聚点”，后续可维护性会持续下降。
**Suggestion**: 拆分为显式模块：`scripts/config_loader.py` 与 `scripts/rank_utils.py`，业务脚本按需导入，`__init__.py` 保持最小化。

#### Issue 15 (High): 步骤 5 仍未验证“csindex 失败 -> fallback”关键路径
**Location**: `步骤 5 验证`（L545-L557）
当前验证是“拉一次 cs_index + 拉一次 sina_index”，这不等于验证 fallback 逻辑；没有证明在 csindex 失败时会按预期走到 sina 分支。
**Suggestion**: 增加强制失败用例：mock `ak.stock_zh_index_hist_csindex` 抛出 `RequestException`，断言 `_fetch_sina_index` 被调用且返回结果被透传。

#### Issue 16 (Medium): 步骤 4 的 mock 验证仍可能假通过
**Location**: `步骤 4 验证`（L455-L467）
示例中 `try/except: pass` 会吞掉真实网络错误；且仅在 `mock_req.called` 时断言 headers。若调用未命中或被异常短路，脚本可能不报错但实际未验证到 UA 注入。
**Suggestion**: 去掉裸 `except`，改成显式断言调用次数与 headers；网络请求部分使用本地 stub/monkeypatch，避免外网不稳定影响结论。

#### Issue 17 (Medium): 最终 HTML 对比命令与“允许时间戳差异”描述不一致
**Location**: `最终验证`（L118-L121）
文档写“允许时间戳差异”，但命令是直接 `diff` 整个文件，时间戳变动会直接失败，执行层面自相矛盾。
**Suggestion**: 改为结构化比对（如先剔除 `update_time` 行再 diff），或用解析脚本仅比较关键数据区块。

#### Issue 18 (Medium): 固定快照覆盖范围不足，遗漏 `spot_price/crypto` 与错误路径
**Location**: `基准快照`（L41-L42）与 `最终验证`（L109-L115）
快照仅覆盖 `cs_index/sina_index/hk/us` 四类，未覆盖 `spot_price`、`crypto`，也没有任何失败场景/空数据场景的端到端回归。
**Suggestion**: 至少补两类样本（如 `XAU`、`BTC`）和一个错误路径样本（无效 code），并纳入指标与容错验证。

#### Issue 19 (Low): 文件数量统计仍与口径声明不一致
**Location**: `总览`（L10-L15）
声明“统计 scripts 下所有 .py（含 __init__.py）”，但表格写“9 个 .py（6 核心 + 3 test）”，未体现 `ranking_store.py`，数字仍不自洽。
**Suggestion**: 用自动统计结果直接回填表格，或明确排除项并在口径声明中写清楚。

#### Issue 20 (Suggestion): 回退章节仍包含不建议命令与流程冲突
**Location**: `回退机制`（L1015-L1029）
“每步完成后单独 commit”在部分团队流程下并不总是可执行；且 `git checkout -- <files>` 可读性差、已被 `git restore` 取代。
**Suggestion**: 改为“可选 checkpoint commit”，并统一回退命令为 `git restore --worktree --staged <files>`；同时补充“不要求自动提交”的流程说明。

### Positive Aspects
- 计划已显著增强可重复验证能力，尤其是快照回放与 `assert_frame_equal` 的引入。
- Round 1 的多项关键反馈被有效吸收（6a 私有化、8c 补齐、backfill logging 验证）。
- 执行顺序、风险分级与检查点比第一版更清晰，落地可操作性提升明显。

### Summary
Top 3 remaining concerns: 1) 手工排障脚本仍计划直接删除且无替代；2) 步骤 5 缺少对 fallback 关键路径的强验证；3) `scripts/__init__.py` 继续承担过多工具职责，模块边界仍不健康。
**Consensus Status**: NEEDS_REVISION

---
## Round 3 — 2026-04-10
### Overall Assessment
这版计划已经接近可执行状态：Round 1/2 的大多数问题都被系统性吸收，验证链路和回退机制比前两轮明显更扎实。并且你要求的“设计性接受”条目（测试脚本删除、`__init__.py` 聚合）现在有明确书面决策，可以公平地按决策关闭。剩余主要风险集中在步骤 4 的验证脚本本身，以及 parquet 依赖前置条件未写明。
**Rating**: 8/10

### Previous Round Tracking
| # | Issue | Status | Notes |
|---|-------|--------|-------|
| 1 | 回归验证依赖实时外部数据，无法证明功能不变 | Resolved | 已引入固定快照 + 基准/结果逐字段对比。 |
| 2 | 步骤 5 改变容错语义未评估 | Resolved | 已补“codify existing behavior”说明，并新增强制 fallback 验证。 |
| 3 | 步骤 4 验证无法覆盖 patch 生效 | Unresolved | 验证写法仍有逻辑错误（见 Round 3 Issue 21）。 |
| 4 | 步骤 6a 可能破坏公开方法兼容性 | Resolved | 已私有化并给出调用扫描证据。 |
| 5 | 删除手工数据源脚本削弱排障能力 | Resolved (by design decision) | 已明确“与项目负责人确认，直接删除”的设计决策及理由。 |
| 6 | 把共享函数放进 `scripts/__init__.py` 边界不合理 | Resolved (by design decision) | 已明确小项目阶段接受该方案，并给出后续拆分阈值。 |
| 7 | 跨文件重复消除遗漏 backfill | Resolved | 已新增 8c 并统一主脚本/回填脚本逻辑。 |
| 8 | 最终验证覆盖面不足 | Resolved | 已补归档与 ranking 结构验证，覆盖面明显提升。 |
| 9 | logging 改造缺少 backfill 验证 | Resolved | 已补 backfill 日志路径验证。 |
| 10 | 步骤 3 验证过粗 | Resolved | 已使用 `assert_frame_equal` + 边界输入验证。 |
| 11 | 总览口径不清且数字不准 | Resolved | 数字与口径已更新为 10 个 `.py`。 |
| 12 | 回退机制不可执行 | Resolved | 已给出按步 commit + `git restore`/`git revert` 流程。 |
| 13 | 直接删手工脚本缺少替代路径 | Resolved (by design decision) | 与 Issue 5 同源，已明确按设计接受。 |
| 14 | `__init__.py` 职责恶化 | Resolved (by design decision) | 与 Issue 6 同源，已明确按设计接受并设拆分条件。 |
| 15 | 步骤 5 未验证 csindex 失败 fallback | Resolved | 已加入 mock csindex 失败并断言 fallback 成功。 |
| 16 | 步骤 4 mock 验证仍可能假通过 | Unresolved | 问题形态变化但本质未闭环（见 Round 3 Issue 21）。 |
| 17 | HTML 对比与“允许时间差异”矛盾 | Resolved | 已改为过滤时间戳后再 diff。 |
| 18 | 快照覆盖不足（缺 spot/crypto/错误路径） | Resolved | 已补 `XAU` 与 `BTC`；错误路径在步骤 5 强制 fallback 中覆盖。 |
| 19 | 文件统计与口径不一致 | Resolved | 当前表格与口径一致。 |
| 20 | 回退章节命令不建议/流程冲突 | Resolved | 已移除 `git checkout --`，改用 `git restore`。 |

### Issues (new or still unresolved)
#### Issue 21 (High): 步骤 4 的 UA 注入验证脚本会拦截错层，无法证明目标行为
**Location**: `步骤 4 验证`（L450-L474）
当前写法 `patch.object(requests.sessions.Session, 'request', interceptor)` 会直接替换掉被测的 `patched_request`，导致测试路径不再经过“UA 注入逻辑”本体。换句话说，这段测试并没有验证你要验证的东西，且很可能因为 `headers` 为空而失败或误判。
**Suggestion**: 不要 patch `Session.request` 本身。改为 patch `requests.sessions.Session.send`（或 adapter 层）来捕获最终 `PreparedRequest.headers`，断言 `User-Agent` 存在；并保留一次不依赖外网的纯单元路径。

#### Issue 22 (Medium): 计划强依赖 parquet，但未声明引擎前置条件
**Location**: `基准快照/最终验证/步骤3验证` 中多处 `to_parquet/read_parquet`（L44, L58, L110, L379-L383）
当前文档默认可直接使用 parquet，但未声明需要 `pyarrow` 或 `fastparquet`。在缺省环境下这些命令会直接失败，导致整个验证流程不可执行。
**Suggestion**: 在计划开头增加“环境前置条件”段落，明确安装命令（如 `pip install pyarrow`）；或提供 CSV/PKL 兜底方案，避免被可选依赖卡死。

### Positive Aspects
- 新版计划对反馈吸收很快，且能把“争议点”转化为明确设计决策记录。
- 验证链路从“运行看看”升级到“固定输入 + 结构化断言”，工程质量明显提升。
- 回退机制和步骤边界已具备实操性，按步落地风险可控。

### Summary
目前只剩一个高优先级验证脚本问题和一个依赖声明问题，修完即可进入可执行状态。
**Consensus Status**: NEEDS_REVISION

---
## Round 4 — 2026-04-13
### Overall Assessment
这版计划整体质量已经很高，Round 3 的核心问题（Issue 21）确实按要求修复，验证链路继续收敛。与此同时，“Issue 22 全部改为 CSV”并未完全落地，步骤 3 的验证脚本仍残留 `read_parquet`。除这一处外，其余历史问题都维持已解决状态。
**Rating**: 9/10

### Previous Round Tracking
| # | Issue | Status | Notes |
|---|-------|--------|-------|
| 1 | 回归验证依赖实时外部数据，无法证明功能不变 | Resolved | 固定快照 + 基准对比机制已稳定存在。 |
| 2 | 步骤 5 改变容错语义未评估 | Resolved | 已有“codify existing behavior”说明与 fallback 测试。 |
| 3 | 步骤 4 验证无法覆盖 patch 生效 | Resolved | 已改为在 `Session.send` 层验证最终请求头。 |
| 4 | 步骤 6a 可能破坏公开方法兼容性 | Resolved | 私有化 + 调用扫描已覆盖。 |
| 5 | 删除手工数据源脚本削弱排障能力 | Resolved (by design decision) | 仍为明确接受的设计决策。 |
| 6 | 把共享函数放进 `scripts/__init__.py` 边界不合理 | Resolved (by design decision) | 仍为明确接受的设计决策。 |
| 7 | 跨文件重复消除遗漏 backfill | Resolved | 8c 已覆盖。 |
| 8 | 最终验证覆盖面不足 | Resolved | 归档与 ranking 验证已保留。 |
| 9 | logging 改造缺少 backfill 验证 | Resolved | backfill 验证步骤已保留。 |
| 10 | 步骤 3 验证过粗 | Resolved | 逐列断言与边界验证已纳入。 |
| 11 | 总览口径不清且数字不准 | Resolved | 当前数字与口径一致。 |
| 12 | 回退机制不可执行 | Resolved | 回退流程可执行。 |
| 13 | 直接删手工脚本缺少替代路径 | Resolved (by design decision) | 与 Issue 5 同源，按设计关闭。 |
| 14 | `__init__.py` 职责恶化 | Resolved (by design decision) | 与 Issue 6 同源，按设计关闭。 |
| 15 | 步骤 5 未验证 csindex 失败 fallback | Resolved | 强制 fallback 验证已存在。 |
| 16 | 步骤 4 mock 验证仍可能假通过 | Resolved | 通过 send 层拦截已规避原假通过路径。 |
| 17 | HTML 对比与“允许时间差异”矛盾 | Resolved | 已改过滤时间戳后比较。 |
| 18 | 快照覆盖不足（缺 spot/crypto/错误路径） | Resolved | `XAU/BTC` 已覆盖，错误路径亦覆盖。 |
| 19 | 文件统计与口径不一致 | Resolved | 统计口径与表格一致。 |
| 20 | 回退章节命令不建议/流程冲突 | Resolved | `git restore` 方案已替换旧命令。 |
| 21 | 步骤 4 验证拦截错层，无法证明目标行为 | Resolved | 已由 patch `Session.request` 改为 patch `Session.send`。 |
| 22 | parquet 依赖未声明 | Unresolved | 大部分改为 CSV，但步骤 3 验证仍残留 parquet 读法。 |

### Issues (new or still unresolved)
#### Issue 22 (Medium): CSV 迁移未完全完成，步骤 3 验证仍残留 parquet 读法
**Location**: `步骤 3 验证`（`docs/agents/scripts-code-cleanup.md` L379-L383）
计划宣称已将 parquet 全面替换为 CSV，但步骤 3 的示例仍使用 `pd.read_parquet('/tmp/trend_snapshots/...')`。这会与前文 CSV 快照路径不一致，执行时直接失败。
**Suggestion**: 将该段统一改为 `pd.read_csv(..., parse_dates=['date'])`，路径后缀改为 `.csv`，确保与基准快照/最终验证完全一致。

### Positive Aspects
- Issue 21 的修复方向正确，验证层级终于对齐了被测逻辑。
- 大多数历史问题已经稳定关闭，计划结构和可执行性明显成熟。
- 设计性取舍（Issues 5/6/13/14）已被文档化，评审语义清晰。

### Summary
当前仅剩 1 个中等级别的文档一致性问题（Issue 22）待清理；修复后可进入 `APPROVED`。
**Consensus Status**: MOSTLY_GOOD

---
## Round 5 — 2026-04-13
### Overall Assessment
本轮更新把 Round 4 的最后遗留项（Issue 22）完整清理，计划文本在验证链路上已前后一致。至此，1-22 的问题都具备明确闭环（含设计性接受项），且没有发现新的实质风险。该计划已达到可执行、可验证、可回退的标准。
**Rating**: 10/10

### Previous Round Tracking
| # | Issue | Status | Notes |
|---|-------|--------|-------|
| 1 | 回归验证依赖实时外部数据，无法证明功能不变 | Resolved | 固定快照与对比机制稳定。 |
| 2 | 步骤 5 改变容错语义未评估 | Resolved | 行为解释与验证链路完整。 |
| 3 | 步骤 4 验证无法覆盖 patch 生效 | Resolved | 已在 send 层验证最终请求头。 |
| 4 | 步骤 6a 可能破坏公开方法兼容性 | Resolved | 私有化与调用扫描闭环。 |
| 5 | 删除手工数据源脚本削弱排障能力 | Resolved (by design decision) | 设计决策明确且有理由。 |
| 6 | 把共享函数放进 `scripts/__init__.py` 边界不合理 | Resolved (by design decision) | 设计决策明确且有拆分阈值。 |
| 7 | 跨文件重复消除遗漏 backfill | Resolved | 已通过 8c 覆盖。 |
| 8 | 最终验证覆盖面不足 | Resolved | 归档与 ranking 验证已覆盖。 |
| 9 | logging 改造缺少 backfill 验证 | Resolved | backfill 验证保留。 |
| 10 | 步骤 3 验证过粗 | Resolved | 逐列断言与边界用例保留。 |
| 11 | 总览口径不清且数字不准 | Resolved | 口径与数字一致。 |
| 12 | 回退机制不可执行 | Resolved | 回退流程明确可执行。 |
| 13 | 直接删手工脚本缺少替代路径 | Resolved (by design decision) | 与 Issue 5 同源，按设计关闭。 |
| 14 | `__init__.py` 职责恶化 | Resolved (by design decision) | 与 Issue 6 同源，按设计关闭。 |
| 15 | 步骤 5 未验证 csindex 失败 fallback | Resolved | 强制 fallback 验证存在。 |
| 16 | 步骤 4 mock 验证仍可能假通过 | Resolved | 验证层级已修正。 |
| 17 | HTML 对比与“允许时间差异”矛盾 | Resolved | 时间戳过滤后对比。 |
| 18 | 快照覆盖不足（缺 spot/crypto/错误路径） | Resolved | 覆盖项已补齐。 |
| 19 | 文件统计与口径不一致 | Resolved | 统计一致。 |
| 20 | 回退章节命令不建议/流程冲突 | Resolved | 命令已更新为推荐写法。 |
| 21 | 步骤 4 验证拦截错层，无法证明目标行为 | Resolved | 已改为 patch `Session.send`。 |
| 22 | parquet 依赖未声明 | Resolved | 已统一为 CSV，`parquet` 零命中。 |

### Issues (new or still unresolved)
无。

### Positive Aspects
- 迭代节奏健康：每轮问题都能被精确吸收并形成文档证据。
- 验证策略从“可跑”升级到“可重复、可断言、可定位”。
- 争议点以“设计决策”方式显式记录，避免后续评审语义漂移。

### Summary
**Consensus Status**: APPROVED
