# Plan Review: 2026-10-19-futures-ic-im-basis-roll

**Plan File**: /Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-futures-ic-im-basis-roll.md
**Reviewer**: Codex

---

## Round 1 — 2026-10-19

### Overall Assessment
三张输入表、纯函数分析与独立生成步骤的方向合理，能够复用现有站点结构，但当前计划存在到期日路径错配、取数阻塞主站部署、输入完整性校验不足三个 High 问题，不能直接实施。本人独立读取计划、相关源码、项目规范及原始探测快照，并进行了离线复算和故障注入；未调用 skill、子代理或 Claude Code，本评审文件此前不存在，所有问题均为本轮新增、状态 Open，未发现 Critical 问题。计划没有 PRD 双链接、飞书 URL 或本地需求 4659 副本，故记录 **PRD validation skipped — no local copy**：以下只验证计划内部一致性、现有代码及可取得的数据证据，不宣称已经核对原始需求的完整范围、API 或埋点字段。

# Plan Review Result

## Decision
REQUEST_CHANGES

## Score
6 / 10

## Blockers

- **H1 · High · Open — 到期日顺延导致移仓路径缺位或错配。**

  **计划位置：** [§3，L67–80](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-futures-ic-im-basis-roll.md:67)，尤其是历史目标固定在事件到期日、今日 `c0` 排除当日到期合约、随后仍计算“三路径”这三条规则。

  **证据与影响：** 原始快照中，2026-09-18 的 IC 合约为 `2609 / 2610 / 2612 / 2703`，顺延后的 `c0=2610` 后面只剩 `2612 / 2703`；该 `c0` 真正到期日 2026-10-16 的三条目标却是 `2611 / 2612 / 2703`，且 `2611` 首根行情为 2026-09-21。IM 完全相同。若把剩余两项紧凑编号，`2612` 会被拿去和历史“次月”比较；若沿用当日旧角色，也不能普遍成立，例如 2026-10-16 顺延到 `2611` 后，`2612` 应成为下一事件的次月，而非当日表格的当季。无条件索引三个目标则直接失败。这是正常月度换月场景，当前最新日 2026-10-16 本身就只有两个可用目标；新月份合约在交割后的下一交易日开始交易也符合[中金所交易细则](https://www.cffex.com.cn/u/cms/www/202207/182020307zry.pdf)。

  **修改建议：** 历史统计与今日提示共用由事件 `c0 / E` 确定的目标身份和路径槽位，未上市目标保持空位，不能通过过滤后重新编号改变路径；或者明确到期当日暂不输出下一事件的移仓比较，下一交易日恢复。补普通月、季月到期日及下一交易日的具体合约映射断言，不能只测“c0 已顺延”。

- **H2 · High · Open — 无超时的期指取数会阻塞主站部署。**

  **计划位置：** [§4.2，L109；§4.3，L116–126](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-futures-ic-im-basis-roll.md:109)，声称重试两次、`continue-on-error` 即可保证“失败不影响主站部署”。

  **证据与影响：** 当前安装的 AkShare 在 [futures_zh_daily_sina，L669](/Users/loopq/dev/git/loopq/trend.github.io/venv/lib/python3.11/site-packages/akshare/futures/futures_zh_sina.py:669) 和 [futures_contract_info_cffex，L28](/Users/loopq/dev/git/loopq/trend.github.io/venv/lib/python3.11/site-packages/akshare/futures_derivative/futures_contract_info_cffex.py:28) 均直接调用没有 `timeout` 的 `requests.get`；现有 [DataFetcher 请求补丁](/Users/loopq/dev/git/loopq/trend.github.io/scripts/data_fetcher.py:116) 只补 User-Agent，[重试器](/Users/loopq/dev/git/loopq/trend.github.io/scripts/data_fetcher.py:72) 也只能在请求抛异常之后重试。新增步骤位于 [stage/deploy 之前](/Users/loopq/dev/git/loopq/trend.github.io/.github/workflows/update.yml:75)，慢连接不退出时后续部署一直不能开始。`continue-on-error` 处理步骤失败，不提供执行时间上限，参见 [GitHub 官方语义](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idstepscontinue-on-error)。

  **修改建议：** 给期指步骤明确的短总预算，例如 `timeout-minutes: 5`，并明确本地 CLI 的请求连接/读取超时及有限重试行为；总预算到达后必须允许主站继续 stage/deploy。补网络一直不返回、重试耗尽、步骤超时后的部署门禁验证，不能只测试立即抛错。

- **H3 · High · Open — 把行情缺行当成日历，会静默改写统计样本。**

  **计划位置：** [§2，L43–50](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-futures-ic-im-basis-roll.md:43)、[§4.2，L106–112](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-futures-ic-im-basis-roll.md:106)、§5 L140。生产校验仅明确了最新日期一致、全局 `max(bars.date)==T` 和每日四合约；§1 的完整性只是一次探测事实。

  **证据与影响：** 复用的 [DataFetcher._standardize_dataframe，L148–162](/Users/loopq/dev/git/loopq/trend.github.io/scripts/data_fetcher.py:148) 会将非法收盘转换成 NaN 并删行，既不保证现货日期完整，也不拒绝零值、无穷值或重复日期。离线从现货快照删除 2026-10-15 后，最新日依然是 2026-10-16，期货每日依然四合约，所有上述检查仍成立，但以 `spot.date` 作日历时，该事件的 `t_1` 从 10-15 错变为 10-14。类似地，合约首部被截断可能被误认为尚未上市，尾部被截断可能污染推断出的 expiry；原始收盘 NaN 也可能被当成正常缺样本。结果是看似成功的新页面包含错误分位、事件日期或样本数，而非计划承诺的失败保留旧页。

  **修改建议：** 在 futures 输入边界明确验证唯一键、有效日期、有限正收盘、完整样本起止范围、现货/期货日期对齐及在市各合约截至 T 的覆盖；以已取得的交易日历校验历史日期，不能由缺失的价格记录决定交易日是否存在。对合约存续期内缺行与确实未上市作区分，expiry 不能未经核验就信任最后一根。生产 T 还应对齐本次主站行情日，兑现 §6 的日期一致要求。补删现货一日、删整日期货、删单合约末根、重复键、零/NaN/Infinity、历史窗口截短的离线失败测试。

## Required Changes

- **先关闭 H1–H3：** 明确事件路径身份，给网络和生成步骤加总时限，将探测阶段的数据完整性假设变成运行时输入契约；上述规则及反例测试进入计划后，才具备达到 8+ 的基础。

- **M1 · Medium · Open — 样本数不能固定写在表头，胜率必须明确配对掩码。**

  **计划位置：** [§3，L69–72](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-futures-ic-im-basis-roll.md:69)、[§4.4，L131](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-futures-ic-im-basis-roll.md:131)。公式按每个 N 和路径定义 n，页面却要求“n 写在表头”。

  **证据与影响：** 按计划规则复算快照中截至 2026-10-16 的 51 个已到期事件，IC、IM 的 N=1 三路径样本数都是 `51 / 51 / 51`，N=20 则是 `28 / 51 / 38`，差异来自目标尚未上市，绝非异常数据。一个表头 n 无法表达这些数字。胜率公式还应明确沿用差值的有效配对集合；直接计算 pandas 的 `mean(vN > v1)` 会把 NaN 比较结果当成 False，例如 `[2, NaN] > [1, 1]` 得 50%，有效配对胜率实际是 100%。

  **修改建议：** 每个 N×路径单元展示有效 n，明确均值样本与差值/胜率配对样本的关系；若不同则分别展示。胜率显式过滤两端非空，n=0 输出无样本，选最大 N 时不参与。保留不同 N 覆盖不同事件群体的说明，测试以上真实样本数和两事件手算反例。

- **M2 · Medium · Open — 估算交易日会改变历史分位，不仅影响提示天数。**

  **计划位置：** [§3，L77–79](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-futures-ic-im-basis-roll.md:77)、[§7，L166](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-futures-ic-im-basis-roll.md:166)。

  **证据与影响：** 同一个可能按工作日估算的 `N_now` 随后直接用于 `N_now <= 20` 门禁和历史 `v(N_now, 路径)` 的取样。跨年日历缺失时，多算的节假日不仅改变“约 N 天”，还可能选错历史分布，甚至把窗口内误判为窗口外；只给天数加“约”不能限定误差的实际传播。

  **修改建议：** 日历返回覆盖完整性；覆盖不全时可以展示约数，但隐藏依赖精确 N 的同期分位和精确窗口判断，并明确提示日历尚不完整。补跨年且缺失节假日日历的夹具，验证不会输出貌似精确的同期百分位。

- **M3 · Medium · Open — 指标空值到分位和图表 JSON 的契约缺失。**

  **计划位置：** [§3，L60–63](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-futures-ic-im-basis-roll.md:60)、[§4.1，L92](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-futures-ic-im-basis-roll.md:92)、§5 L142。

  **证据与影响：** `D < 7` 的空值是每个月必然出现的正常数据。按当前分位公式直接比较 NaN，`mean(样本 <= NaN)` 会得到 0%，不是无值。现有 [Generator 的 Jinja 环境](/Users/loopq/dev/git/loopq/trend.github.io/scripts/generator.py:31) 没有非有限值转换；实际调用 `{{ data|tojson }}` 渲染 `[NaN, 12.3]` 得到的仍是 `[NaN, 12.3]`，严格 JSON 解析失败。bs4 取文本或 Python 默认宽松 `json.loads` 不能证明浏览器可以解析，因此逐格 oracle 测试也可能全部通过而图表不能启动。

  **修改建议：** 明确 x 为空时当前分位也为空；正常指标缺失在展示 DTO 中统一转换为 Python `None` / JSON `null`，原始异常非有限价格按 H3 报错。补严格 JSON 解析及浏览器初始化验收，验证临期曲线正常断开、表格显示无值而非 0%，JSON 中没有 NaN/Infinity。

- **M4 · Medium · Open — 写入失败仍可能把残缺 HTML 发布上线。**

  **计划位置：** [§4.1，L91](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-futures-ic-im-basis-roll.md:91)、[§4.3，L126](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-futures-ic-im-basis-roll.md:126)、§5 L142–144，承诺“失败非零退出、不写页面”，但只测试取数失败。

  **证据与影响：** 实际 [Generator.render，L41–45](/Users/loopq/dev/git/loopq/trend.github.io/scripts/generator.py:41) 直接以 `w` 打开最终文件再写入。本人在临时目录注入“写入 30 字节后 OSError”，确认异常抛出后最终 HTML 仍存在且旧内容已丢失。[site_publish.stage，L38–45](/Users/loopq/dev/git/loopq/trend.github.io/scripts/site_publish.py:38) 会复制整个目录；`continue-on-error` 后这个半成品将被发布，`keep_files` 只保留缺席文件，不能保护被坏文件覆盖的旧页。增加超时后也必须考虑渲染写入期间进程被终止。

  **修改建议：** 在发布目录之外完成渲染，完整成功后通过同文件系统原子替换写入正式路径；失败不得让残缺新页面进入 stage，可直接复用现有 Generator 的可配置输出目录。补取数、分析、模板、写入失败及中断的集成测试，分别断言干净 checkout 不产生正式页面、已有正式页面内容不变、线上旧页不会被半成品覆盖。

## Missing Context

- 原始需求 4659 的本地副本及确认记录未提供，无法独立验证 §0 的决定是否覆盖原始需求、是否新增范围、API/字段/埋点是否一致；此事实已记录在本轮摘要，不单独据此判定方案方向错误。
- 已读取项目 [.claude/CLAUDE.md](/Users/loopq/dev/git/loopq/trend.github.io/.claude/CLAUDE.md) 和用户提供的规范，未发现单独列出的 Code Quality Hard Limits 数字阈值；不虚构行数限制。现有 Generator、模板入口、发布归属与测试入口均已核实。
- [原始快照](/private/tmp/futures-probe/raw.pkl) 可读，已核实两品种各 54 合约、1025 个日期、每日四合约及现货日期集合一致；本轮复算和故障注入不等于重新完成 §5 的 12 日跨源价格校验。官方 expiry、价格跨源结果及最终页面的浏览器验证仍应由实施阶段记录。
- §6 的 `check_live.py` 实际位于 [临时验收目录](/private/tmp/trend-refactor/acceptance/check_live.py:1)，不在仓库 scripts 下；其 L71–72 仍要求 site-nav 为空。修改计划时应写明实际复用位置及入口断言替换，避免仅“增加期指检查”后保留必败的旧断言。

## Risk Assessment

- logic: 高。到期日路径身份不统一会把当前合约和错误历史路径比较；估算 N、空值和未配对胜率可产生貌似精确的错误提示。
- state: 中。分析无状态不代表发布没有状态；现有最终文件直接写入与失败保留旧页的承诺不一致。
- data: 高。现有完整快照证明当前样本正常，不能替代每天运行时的完整性校验；价格记录不应自行定义交易日是否存在。
- UI: 中。错误 n、空值显示 0% 和非法 JSON 会误导读者或令图表无法初始化；已有表格和移动端方案本身可复用。
- regression: 高。无时限的新取数步骤位于主站部署之前，扩大了主站失败面；路径、GA、旧归档以及其他发布目录的既定回归测试应保留。

## Test Requirements

- unit: 在既有公式测试上加入 H1 的普通月/季月到期映射及未上市槽位；H3 的日期缺失、重复、窗口截短和非有限输入；M1 的逐 N 样本数、有效配对胜率和空集合；M2 的不完整未来日历；M3 的缺失当前分位与严格 JSON null。关键反例用手算期望值，不仅让独立 oracle 重复计划中的同一错误规则。
- integration: 通过真实 CLI、Generator、stage 与 keep_files 模拟，覆盖立即失败、持续阻塞达到预算、写入一半失败及已有旧页的情况；失败后主站仍进入发布，期指旧页逐字节不变。页面测试须严格解析内嵌 JSON；更新旧导航断言，保留跨源校验、主站 golden 对比和 `scripts/tests` / `scripts/backtest` 回归门禁。
- manual: 验证普通交易日、普通月到期日、季月到期日和下一交易日的实际合约标签与提示；在临期含 null 的真实页面验证两张图可加载、默认图例/时间范围、拖动及手机宽度。部署演练应验证超时仍更新主站、旧期指页保留且日期可见；§5 要求的跨源 12 日校验必须有记录。

## Final Verdict
暂不可执行；先修正三个 High 问题并补齐上述统计、空值与失败发布契约，再进入 TDD 实施。

---

## Round 2 — 2026-10-19

### Overall Assessment
修订计划已解决上一轮的路径身份、请求及步骤超时、配对样本、估算日历和空值输出问题，整体设计与现有站点结构兼容；仍有一个 High 和一个 Medium 问题，分别是本次行情日未跨步骤共享，以及强制终止后临时文件会进入发布目录。本人独立重读两轮材料和实际调用链，以原始快照复核合约映射，并通过现有主站生成链路、子进程强制终止及实际 stage 函数复现剩余问题，未调用 skill、子代理或 Claude Code。计划现已说明没有独立 PRD，并提供需求原文和 §0 澄清范围，按这些内容未发现无关范围扩张；保留 **PRD validation skipped — no local copy**，不将不存在的独立 PRD 作为阻断，也不宣称完成了外部原文的 API/埋点字段核验。

# Plan Review Result

## Decision
REQUEST_CHANGES

## Score
7 / 10

## Blockers

- **R2-H1 · High · Open（R1-H3 剩余项）— 独立重取行情日仍可发布与主站不同日期的数据。**

  **计划位置：** [§2 契约 1，L64](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-futures-ic-im-basis-roll.md:64)、[§4.2 步骤 3–7，L132–136](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-futures-ic-im-basis-roll.md:132)、§4.3 L146、§6 L186。计划将“再次按沪深 300 最新 K 线取 T”视为与主站一致，但并未传递或比较本次主站实际采用的日期。

  **实际代码与复现：** [main.run，L121–136](/Users/loopq/dev/git/loopq/trend.github.io/scripts/main.py:121) 用本进程取得的行情确定 `record_date`，[main.main，L229–230](/Users/loopq/dev/git/loopq/trend.github.io/scripts/main.py:229) 只输出 `should_deploy`。期指步骤启动另一进程、再次联网；[DataFetcher._fetch_cs_index，L278–304](/Users/loopq/dev/git/loopq/trend.github.io/scripts/data_fetcher.py:278) 还允许请求失败时切换到新浪，因此相同接口语义不能保证两次结果相同。本人通过现有 `main.run` 生成了行情日为 2026-10-16 的首页，再模拟期指重取沪深 300 仅返回截至 10-15：按计划将真实 IC/IM 快照截取到 10-15 后，现货日历集合、每日四合约、唯一键、合约存续期、历史末根到期日和历史事件目标校验全部仍通过。官方在市清单的校验同样只对第二次选定的 T 做自洽检查，没有任何条件比较主站日期。

  **影响：** 已生成的新首页可以配上前一天的期指页面，甚至把线上较新的期指页覆盖回旧日期；两次请求之间数据更新也会造成相反方向的不一致。把输入截到独立取得的 T 后，新增的完整性校验无法发现这种错误，违背 §6 的两页日期一致要求。

  **修改建议：** 将主站本次最终采用的 `record_date` 作为单一输入传给期指步骤，例如新增 workflow 输出并传入 `--as-of`，或读取本次已生成页面中明确的行情日；生产模式不再重新选择 T。期指验证现货和各在市合约确实覆盖该 T，否则保持旧页并失败退出。同步补文件改动范围及“主站 T=10-16，第二次数据为 10-15／10-19”的集成测试；独立本地 CLI 可以保留自动选 T，但应与生产入口区分。

## Required Changes

- 关闭 R2-H1，使本次行情日在主站与期指之间成为同一个值，而不只是使用同一个取数口径。

- **R2-M1 · Medium · Open（R1-M4 剩余项）— 同目录临时文件在强制终止后仍会被发布。**

  **计划位置：** [§4.1，L117、L120](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-futures-ic-im-basis-roll.md:117)、[§4.3，L152](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-futures-ic-im-basis-roll.md:152)、§5 L170–173。同目录临时文件加 `os.replace` 能保护正式文件，但不足以支持“进程在写入中被终止也不会留下半成品”“stage 只带 echarts.min.js”这两个发布承诺。

  **实际代码与复现：** [site_publish.stage，L44–45](/Users/loopq/dev/git/loopq/trend.github.io/scripts/site_publish.py:44) 使用无过滤的 `shutil.copytree`。本人在临时站点的 futures 目录中启动子进程，写入部分 HTML 到 `.index-*.tmp` 后执行强制终止，再按计划把 futures 加入 `SITE_DIRS` 并调用实际 stage：正式 `index.html` 确实没有出现，但发布目录包含 `.index-*.tmp` 和 `echarts.min.js`。异常路径的 `finally` 清理不能处理 SIGKILL；本仓库 `.gitignore` 不参与 `copytree`，也不能靠它过滤发布产物。正式旧页被保护这一点已解决，但临时半成品会进入发布树，并可能因 keep_files 长期残留。

  **修改建议：** 给原子写与 stage 约定明确的临时文件隔离方式：优先把临时文件放在同文件系统、但不属于 `SITE_DIRS` 的专用目录，再原子替换正式文件；也可让 stage 明确排除生成器专用的临时文件模式。补“子进程写入中被强制终止 → 实际 stage”的离线测试，断言正式文件不变且发布树不含临时文件；不只测试 Python 异常后能执行清理的情况。

上一轮状态追踪（Resolved 指计划层面的修订完成，尚不代表实现或测试已通过）：

| 上轮问题 | 本轮状态 | 核验依据 |
|---|---|---|
| R1-H1 到期日路径错配 | Resolved | §2 L58 的 `targets(c0)` 与 §3 L99 的固定槽位共用；对快照各 51 个事件复算，合计 102 个事件映射一致，9 月季月及 10 月普通月到期日的未上市目标均可保留正确槽位。 |
| R1-H2 取数阻塞主站 | Resolved | §4.2 L130 明确连接/读取超时及有限尝试，§4.3 L145 设置五分钟步骤预算，§5 L167、L173 覆盖超时行为与配置。 |
| R1-H3 数据完整性与行情日 | Partially resolved | §2 L54–71 已补独立日历、完整日期集合、唯一键、有效价格、到期及在市合约校验；跨步骤实际行情日仍未共享，见 R2-H1。 |
| R1-M1 样本数及胜率掩码 | Resolved | §3 L93–95 明确配对集合、空样本及 N=1 行为，§4.4 L157 每个 N×路径展示 n，§5 L166 有手算反例。 |
| R1-M2 估算日历污染分位 | Resolved | §3 L100 明确日历覆盖不全时隐藏窗口判断和同期分位，§5 L166 增加对应测试。 |
| R1-M3 空值与 JSON | Resolved | §3 L77、L86 规定 None/null 与缺失当前分位，§5 L169 使用拒绝 NaN/Infinity 的严格 JSON 解析。 |
| R1-M4 半成品发布 | Partially resolved | §4.1 L117 的原子替换解决正式目标截断；同目录临时文件在强制终止后仍会被整目录发布，见 R2-M1。 |

## Missing Context

- 没有阻碍继续修订的缺失源码上下文；剩余问题是已明确的接口和发布契约缺口。§6 已补线上检查脚本实际位置及旧空导航断言的替换，上一轮这一项已解决。
- 需求依据已补为计划 L9 的原文和 §0 的确认决定；不存在可读取的独立 PRD，因此本轮不继续要求补一个并不存在的文档。仅依据当前提供的需求内容，模块拆分、图表、统计和站点入口没有发现额外的无关功能。
- §1 新增的跨源 96/96 属于计划作者报告，本轮没有将其当成本人重新执行的联网结果；本轮独立验证了原始快照的 102 个事件目标映射及上述离线反例，实施阶段仍应按 §5 留存生产路径复跑结果。
- 已复核项目 CLAUDE.md；没有额外可据以判定违规的 Code Quality Hard Limits 数字条款。当前仍未实现 futures 子系统，本轮没有运行不存在的 futures 测试，也不宣称主站全量回归已通过。

## Risk Assessment

- logic: 中。路径、配对统计与空值规则已闭合；独立选择 T 仍可能让正确公式计算出错误行情日的页面。
- state: 中。原子替换保护正式旧页，但强制终止留下的临时文件尚未与发布目录隔离。
- data: 中。历史缺行、异常价格与到期推断已有明确校验；必须再绑定本次主站的实际行情日，避免把过旧日期作为合法截断点。
- UI: 低。缺失值、未上市槽位、样本量和不完整日历的展示均已明确，图表和移动端效果留待实现验收。
- regression: 中。新增步骤已有时限；共享 Generator 的原子写变更应维持原有输出内容、路径及 GA 行为，并增加强制终止后的发布树检查。

## Test Requirements

- unit: 保留修订计划现有反例；日期输入应验证合法格式及是否为交易日，生产入口须使用主站传入的目标日期。继续覆盖 targets 的普通月、季月和跨年，以及 None/null、配对胜率、逐 N 样本数。
- integration: 在真实主站生成后模拟第二次取数滞后或超前，断言期指严格使用本次主站 T，缺少该日行情时非零退出且保留旧页；对子进程在原子替换前执行强制终止，随后调用实际 stage，断言没有任何临时文件进入发布树。保留原有立即失败、写入异常、keep_files、导航和 GA 回归测试。
- manual: 按 §5 复跑跨源校验、真实页面 oracle 与浏览器验收；上线后分别验证成功更新时两页日期一致，以及期指失败/超时时主站继续部署、旧期指页面保留。无需为本轮审阅提前实现功能或声称这些检查已经通过。

## Final Verdict
仍需修改计划；补齐共享行情日和临时文件发布隔离这两个具体缺口后，可进入实施，无需重做整体设计。

---

## Round 3 — 2026-10-19

### Overall Assessment
本轮修订已闭合共享行情日和临时文件发布隔离两项剩余问题，前两轮问题全部在计划层面解决，未发现新的 Critical、High 或值得要求修订的其他问题。本人独立重读计划、历轮评审及相关源码，并验证了现有输出 helper、计划中的 workflow 日期传递和实际 stage 的临时目录隔离行为，未调用 skill、子代理或 Claude Code。计划明确没有独立 PRD，本轮依据 L9 所载需求原文及 §0 确认范围核对，未发现无关范围扩张；保留 **PRD validation skipped — no local copy**，不宣称核验了不存在的外部 PRD 或其 API/埋点字段。

# Plan Review Result

## Decision
APPROVE

## Score
9 / 10

## Blockers

- 无。

## Required Changes

- 无必须修订项；可以按当前计划进入实施。以下 Resolved 均表示计划已明确解决方案和验证路径，不表示尚未实施的代码已经通过测试。

| 历史问题 | 本轮状态 | 关闭依据 |
|---|---|---|
| R1-H1 到期日路径缺位或错配 | Resolved，保持关闭 | §2 L58 和 §3 L99 继续共用 `targets(c0)`，未上市目标保留槽位；§5 L167 覆盖普通月、季月到期及下一交易日的具体合约。前轮核验的 102 个事件映射规则未被改动。 |
| R1-H2 无超时取数阻塞主站 | Resolved，保持关闭 | §4.2 L131 的连接/读取超时和有限重试、§4.3 L146 的五分钟步骤预算均保留，失败放行与 should_deploy 门禁未改变。 |
| R1-H3 输入完整性；R2-H1 跨步骤行情日不一致 | Resolved，本轮关闭剩余项 | [§2 L64](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-futures-ic-im-basis-roll.md:64) 要求生产使用主站实际 T；[§4.1 L118](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-futures-ic-im-basis-roll.md:118) 明确主站输出 record_date；[§4.3 L147](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-futures-ic-im-basis-roll.md:147) 显式传入 `--as-of`。§5 L168、L172、L175 覆盖数据滞后/超前、输出字段及 workflow 接线；独立日历与完整性校验保持。 |
| R1-M1 样本数与胜率掩码 | Resolved，保持关闭 | §3 L93–95 继续使用有效配对集合并处理无样本和 N=1；§4.4 L158 每个 N×路径展示 n，§5 L167 保留手算反例。 |
| R1-M2 估算日历污染历史分位 | Resolved，保持关闭 | §3 L100 明确日历覆盖不足时不输出窗口判断及同期分位，§5 L167 有对应验证。 |
| R1-M3 空值与 JSON | Resolved，保持关闭 | §3 L77、L86 明确 None/null 和缺失当前分位；§5 L170 保留拒绝 NaN/Infinity 的严格 JSON 解析及临期断点检查。 |
| R1-M4 半成品覆盖；R2-M1 强制终止后的临时文件发布 | Resolved，本轮关闭剩余项 | [§4.1 L117](/Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-10-19-futures-ic-im-basis-roll.md:117) 将临时文件移至 `output_dir/.tmp/`，原子替换正式文件且临时目录不属于 SITE_DIRS；§4.3 L153 明确发布语义，§5 L171 增加 SIGKILL 后调用实际 stage 的测试。 |

本轮对两项新修订的独立核验：

- **行情日传递可接入现有结构。** [main.run 的 record_date](/Users/loopq/dev/git/loopq/trend.github.io/scripts/main.py:134) 已是首页和归档实际使用的日期，计划增加输出的位置位于正常跳过和失败率检查之后；既有 [_set_github_output](/Users/loopq/dev/git/loopq/trend.github.io/scripts/main.py:44) 可直接复用。本轮在临时输出文件中验证其能同时写入 `record_date=2026-10-16` 与 `should_deploy=true`，并解析计划 YAML，确认 `--as-of` 引用该步骤输出、原部署门禁和五分钟时限均存在；不需要再次联网决定生产 T。
- **临时目录确实被发布白名单排除。** [site_publish.stage](/Users/loopq/dev/git/loopq/trend.github.io/scripts/site_publish.py:38) 只复制 SITE_FILES 和 SITE_DIRS。本轮在临时站点留下 `.tmp/interrupted.tmp`，按计划加入 futures 发布目录后调用实际 stage，发布树仅含正式站点文件、旧期指页和 vendor，旧页内容保持不变且没有临时残片；这项隔离不依赖进程退出时能否执行清理。

## Missing Context

- 无阻塞实施的关键上下文缺失。当前需求依据就是计划中的原文和确认范围，不要求补造独立 PRD；新增主站日期输出与共享生成器原子写均为解决现有问题所需的最小接入改动。
- 已核对项目 CLAUDE.md、主站输出链路、Generator、stage、模板入口及相关测试调用方；没有额外的 Code Quality Hard Limits 数字条款可以据以提出问题。
- futures 子系统尚未实现；本轮的 helper 与发布目录验证是评审实验，不替代实施后的完整链路测试。计划作者报告的跨源 96/96 仍应按 §5 用最终生产路径复跑，本轮没有声称重新执行了联网校验、浏览器验收或全量回归。

## Risk Assessment

- logic: 低。事件目标、配对统计、空值和生产行情日已定义清楚；成功生成时使用同一 T，失败保留旧页及旧日期是明确的降级行为。
- state: 低。原子替换保护正式页面，发布白名单隔离临时残片；正常异常清理与强制终止均有验证路径。
- data: 中。全量重算仍依赖外部行情和日历服务，任一必需输入失败会暂停期指更新；运行时完整性校验、请求时限、步骤预算及旧页保留已明确控制影响。
- UI: 低。未上市槽位、无值、样本数、日历不足及图表默认行为均有规格和验收路径，实际布局仍需实施后浏览器检查。
- regression: 低。主站只增加日期输出，Generator 只改变文件写入方式；计划已列出受影响输出断言、页面回归、发布测试及 golden 对比，未发现与现有模块结构冲突。

## Test Requirements

- unit: 执行 §5 已列的输入契约、日期合法性、targets/expiry 边界、配对统计和 None/null 测试；保持主站成功时输出实际 record_date、正常跳过时不输出该字段的断言。
- integration: 执行数据源滞后时失败、超前时截到主站 T 的测试；验证写入中途异常和 SIGKILL 后旧页面不变、实际 stage 无临时文件。完成页面 oracle、严格 JSON、workflow 门禁、keep_files 及主站/回测回归测试。
- manual: 按 §5–6 完成跨源复跑、历史换月日期抽查、桌面及移动端图表验收；上线后分别检查成功更新的日期一致性与失败更新时旧期指页保留。均属于既定实施验收，不是新增的计划审批条件。

## Final Verdict
计划可执行；批准按当前方案进入 TDD 实施，并完成计划规定的回归与用户验收。
