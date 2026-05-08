# Plan Review: Quant morning-reconcile + cache 实现

**Plan File**: docs/agents/quant/incident-2026-04-27-signal-failure.md
**Reviewer**: general-purpose subagent (Codex unavailable, fallback round)

---

## Round 1 — 2026-04-27

### Overall Assessment

Plan 的 Bug A 诊断准确、修复方案可落地；Bug C 诊断方向正确但实施细节存在严重架构错误（多处独立 `writer.commit_atomic` 已使"单 commit 原子提交"成为不可能事件，plan 未察觉）；**Bug B 诊断完全错误** —— 现有 `_check_yesterday_morning_reconcile_done` 语义其实是对的，plan 提议的 `today.done` 反而会破坏前置检查的真实意图。Phase 2 还遗漏并发竞态、push 失败传染、check_readiness 自检失败、`fetcher=None` 空指针、cache 同时进 main 和 gh-pages 的设计违规等多个具体风险点。

**Rating**: 4.5/10

### Issues

#### Issue 1 (Critical): Bug B 诊断错误，提议修复会反向破坏前置检查语义
**Location**: 第二章 §2.2 P0-Bug B；第四章 §1.3；第六章 §6.1 表格 "signal 前置检查" 行
plan 称 "D 日 09:05 morning 写 `morning-reconcile-{D}.done`，signal 找 `morning-reconcile-{D-1}.done` 永远找不到"。这是**误读**。`run_signal.py:40-47` 的语义其实是正确的："今日 14:48 signal 跑之前，前一个工作日的 09:05 morning 是否跑过？" —— 因为 morning 的语义是"D 日 09:05 处理（confirm）D-1 的 provisional 信号"，所以 `morning-reconcile-{D}.done` 这个文件的语义是"D 日 morning 已跑（已 confirm D-1 真值）"。Mon 14:48 signal 要确认"Fri 真值已被 confirm" → 找 `morning-reconcile-{Fri}.done`（Fri 09:05 morning 写的）—— 完全配对。`quant.yml:111-119` 同一个工作流的 yaml 端前置检查也是用 prev_workday，**两端是一致的**。本次 04-27 14:48 signal 找不到 04-24.done 的根因是 04-24 09:05 morning **根本没跑**（Bug A 静默吞错），而不是命名错位。

plan 提议改成 `today.done`：Mon 14:48 找 `morning-reconcile-Mon.done`（Mon 09:05 刚写的） —— 这只能告诉你"今天早上跑了"，**不能告诉你 Friday 的真值是否被处理过**（Friday 的真值是 Friday 早上 morning 处理的，不是 Mon 早上）。这是**语义倒退**，会让前置检查变成 trivially true 的废检查。

**Suggestion**: 删除 §1.3 整节。Bug B 不存在；只要修好 Bug A（git config），04-28 起 morning 自然跑起来，前置检查会正常通过。如果坚持要改，应改的是文件命名（`morning-reconcile-{processed_date}.done` 把 D-1 写在文件名里）而不是检查方向，但这属于 cosmetic refactor、不在事故修复范围。同时把 §6.1 "signal 前置检查 改前 永远找不到 yesterday.done → 始终警告" 这一行从破坏性评估表里删除，因为它建立在错误诊断上。

#### Issue 2 (Critical): "13 csv + positions + signals + done 一次原子 commit" 在现有架构下不可能实现
**Location**: 第四章 §2.2 关键决策段 "走 LocalWriter.commit_atomic（与现有 close-confirm + reconcile + done 标记合并到同一 commit）"；§6.3.2 期望 "commit 包含 13 个 cache/{code}.csv + done 文件 + positions.json"
现状：`cmd_morning_reconcile`（run_signal.py:160-209）当前已经是**三次独立 commit**：
1. `confirm_signals_with_close()`（close_confirm.py:130-139）内部自调 `writer.commit_atomic([signals_path, positions, index])`
2. `reconcile_pending_signals()`（reconcile.py:84）内部自调 `writer.commit_atomic([changes...])`
3. `cmd_morning_reconcile` 自己最后再 `writer.commit_atomic([done_file])`（run_signal.py:200）

也就是说 §3.7 "单 commit 多文件原子提交" 的硬约束在 morning-reconcile 链路上**已经被破坏了**，writer 抽象只保证"单次调用是一笔 commit"，并不能跨子函数合并。plan 只在 morning-reconcile 主函数里追加 cache changes 是**第 4 笔独立 commit**，远不止 plan 所说的"一次性原子提交"。

**Suggestion**: 必须在 §四引入额外子任务"重构 cmd_morning_reconcile 为单次 commit 收集模式"——把 close_confirm / reconcile / cache update / done 全部改成 **返回 `list[FileChange]`**（不再内部 commit），由 morning-reconcile 主函数末尾**一次** `writer.commit_atomic` 提交全部。或者明确放弃"单 commit"目标，把 §六的验证期望改成"4 笔有序 commit：close-confirm + reconcile + cache-update + done-mark"。任选其一，但 plan 当前的描述既不是前者也不是后者，而是**自相矛盾**。

#### Issue 3 (High): cache 文件被 update.yml 的 peaceiris 同步进 gh-pages，违反"cache 只进 main"设计
**Location**: 第四章 §1.1 update.yml 改动；ground rules "Cache files commit to main, NOT gh-pages"
update.yml 当前结构（line 76-84）：quant step 跑完 → 工作树有 `docs/data/quant/cache/*.csv` → 然后 `peaceiris/actions-gh-pages@v4 with publish_dir: ./docs` 把整个 docs（**包括 cache**）发布到 gh-pages。plan §1.1 又新增 `git push origin main`。结果：cache **同时被 push 到 main 和 gh-pages**。这违背 plan 自己说的 "cache 只 commit 进 main 不进 gh-pages"。

**Suggestion**: 三选一明确写进 plan：
1. update.yml 在 peaceiris 之前 `rm -rf /tmp/publish/data/quant/cache` 过滤 publish_dir（要先 cp 整个 docs 到 /tmp 再过滤）
2. peaceiris 用 `exclude_assets: 'data/quant/cache/*'` 选项（v4 支持）
3. 改 paths：cache 不放 docs/data/quant 而是放 `data/quant/cache`（不在 docs 下），需同步改 `paths.cache_dir` + 前端 fetch 路径——成本很大，估计要放弃这个方案

quant.yml 也有类似问题（line 247-256 同样 publish_dir 包含 cache）——plan 完全没提。

#### Issue 4 (High): morning-reconcile 在非交易日（周末/节假日）无 calendar gate，会写脏 done 文件
**Location**: 第四章 §1.5 / §6.3.1 验证步骤；scripts/quant/run_signal.py:160-209 `cmd_morning_reconcile`
`run_signal_generation`（signal_generator.py:148-156）有 `decide_buckets_to_run` 走 calendar；非交易日 → `skipped_non_trading_day=True` 提前 return。但 `cmd_morning_reconcile` **完全没有** calendar 检查，update.yml 也没传 `--calendar` 参数。如果某天 update.yml 在节假日（比如 2026-05-01 劳动节）被人工触发或 should_deploy 误判 true，morning-reconcile 会去找前一个 weekday（不一定是交易日）的 signals 文件、跑 close-confirm、写 `morning-reconcile-2026-05-01.done`。下一个交易日 signal 前置检查找 prev_workday=2026-05-01 → 找到这个伪 done 文件 → 跳过警告 → **silently skip 真正应该警告的场景**。

**Suggestion**: §1.x 新增一项："cmd_morning_reconcile 增加交易日 gate：如果 today 非交易日 → 直接 return 不写 done"。但 morning-reconcile 当前根本没传 `--calendar`，需要先改 `quant.yml:169-172` 与 `update.yml:69-72` 加上 `--calendar scripts/quant/tests/fixtures/trading_calendar_2026-04.json`，且 fixture 必须每月更新。或者：done 文件命名带上"被处理日"`morning-reconcile-{today}-confirms-{prev_workday}.done`，signal 端用更精确的语义检查。

#### Issue 5 (High): Phase 2 cache 增量循环对 `fetcher=None` 路径会 NoneType 崩
**Location**: 第四章 §2.2 cache 增量代码片段；scripts/quant/run_signal.py:176 `fetcher = _build_fetcher(args.realtime) if args.realtime != "skip" else None`
`cmd_morning_reconcile` 当前支持 `--realtime skip` 把 fetcher 设为 None（用于跳过 close-confirm）。plan §2.2 新增的 cache 循环里 `fetcher.fetch_history_daily(...)` 没有 None 防护，`--realtime skip` 模式下会立即 `AttributeError: 'NoneType' object has no attribute 'fetch_history_daily'`。

**Suggestion**: §2.2 代码片段在 `for spec in cfg.indices:` 之前加 `if fetcher is None: pass else:` 包一层，或者把 cache 拉取下沉到独立 `_update_cache(repo_root, cfg, today, fetcher)` 函数，在 fetcher is None 时跳过整个块。同时 plan 应明确"`--realtime skip` 模式下 cache 也不更新"的设计语义。

#### Issue 6 (High): check_readiness.py:153 grep 旧函数名，plan §1.3 重命名后会自检 FAIL
**Location**: 第七章执行清单 §1.3；scripts/quant/check_readiness.py:148-157
`check_readiness.py:153` 用字符串 grep 检查 `_check_yesterday_morning_reconcile_done` 是否存在。plan §1.3 提议重命名为 `_check_today_morning_reconcile_done`。重命名后这个静态自检会从 PASS 变 FAIL，影响后续 `python scripts/quant/check_readiness.py` 走 CI gate。plan §八 YAGNI 列出 "_check_yesterday_morning_reconcile_done 函数完整重命名（影响调用点）" 推迟，但这不是"调用点"问题，是**字符串 grep 自检**问题，YAGNI 不能覆盖。

**Suggestion**: 与 Issue 1 联动：既然 Bug B 不成立，§1.3 整节删除。如果坚持重命名，必须在 §1.3 同步加一项"更新 check_readiness.py:153 marker"。

#### Issue 7 (High): update.yml 与 quant.yml 之间无 concurrency group，多 push 竞态会导致状态分裂
**Location**: 第四章 §1.1 push step；.github/workflows/update.yml（无 concurrency block）；.github/workflows/quant.yml:33-35
quant.yml 的 morning-reconcile 由 `cron: '5 1 * * 1-5'`（09:05 SGT）触发；update.yml 的 morning step 由外部 cron-job.org 触发，**实际触发时间高度接近**（08:00 SGT 主路 + 备路）。两边都会 commit + push 到 main。quant.yml 有 `concurrency: quant-state-main`，update.yml **没有任何 concurrency**。结果：
- 两个 workflow 同时跑 → 各自从 main 拉 → 各自 commit → 第二个 push 因 non-fast-forward 失败
- 因为 plan §1.1 用 `git push origin main || true`，**push 失败被静默吞**，本地工作树的 commit 留在 runner 上、runner 销毁丢失 → cache 永远写不进 main

**Suggestion**: §1.1 push step 改成：
```bash
for i in 1 2 3; do
  git pull --rebase --autostash origin main && git push origin main && break
  sleep $((RANDOM % 10 + 5))
done
```
或：在 update.yml 顶层加 `concurrency: { group: quant-state-main, cancel-in-progress: false }`，与 quant.yml 同 group 互斥。**任何方案都不能保留 `|| true` 静默吞错**——这正是这次事故的根因模式。

#### Issue 8 (High): writer.py 硬约束被 quant.yml 内联 git commit 已经绕过；plan 仅删两处但漏一处
**Location**: 第四章 §1.2 "删除：line 149-150 + line 177-178"；scripts/quant/writer.py 顶部注释 "禁止任何代码绕过本抽象直接写状态文件"
quant.yml line 142-153 这一整块（写 `signal-{date}.done` 标记）是**自起炉灶的 mkdir + cat + git add + git commit + git push** —— 完全绕过 LocalWriter，违反 mvp-plan §3.7 / writer.py 顶部硬约束。plan §1.2 只关心"删除内联 git config"（line 149-150），**保留了 line 142-153 整段绕过 writer 的逻辑**。

**Suggestion**: §1.2 必须新增一项 "重写 quant.yml line 142-153：`signal-{date}.done` 写入合并进 `cmd_signal_for_one_day` 内部，由 `writer.commit_atomic([signals, index, positions, done])` 一笔提交"。这同时简化 cmd_signal_for_one_day:144-149 直接 `done_file.write_text(...)` 这一处也是绕过 writer 的违规。修完 quant 整条链路才真正符合"writer 是唯一写入路径"硬约束。

#### Issue 9 (Medium): 800 天冷启动无重试 / 无频控；13 个 cs_index 串行调用可能触发 csindex.com.cn 限流
**Location**: 第四章 §2.1 / §6.2 注 "60s+ 一次性成本"
plan §2.1 说"参考 `_fetch_cs_index` pattern（含网络重试）"，但 §2.2 给出的代码片段只是 `new_df = fetcher.fetch_history_daily(spec.index_code, days=days)` —— 没有 retry decorator、没有 backoff、没有 sleep 间隔。13 个指数串行 + 每个 800 天，cs_index 接口在过去事故中被观察到对短时间高频请求会返回 429 / 空 DF。一旦某个失败，没有 retry → cache 部分写入 → 下一日"看起来 cache 已存在" → `last+1~today` 增量逻辑只补几天 → **永久缺失 800 天里的某个区间**。

**Suggestion**: §2.1 实现要求加四条硬约束：
1. `fetch_history_daily` 必须带 `@retry_on_network_error(max_retries=2)`（复用主站装饰器，或 quant 子系统独立复制）
2. 13 个指数之间 `time.sleep(0.5)` 间隔（防限流）
3. 冷启动失败时**整体回滚**：先全部拉完临时存到 dict，全部成功才一次性 append 到 cache（否则保持 cache 空，下次再试）
4. 加超时：`days >= 200` 时单调用 timeout 30s

#### Issue 10 (Medium): plan §2.2 的 `if days <= 0: continue` 永不触发；增量门控逻辑错
**Location**: 第四章 §2.2 代码片段 "if days <= 0: continue # cache 已是今日，跳过"
代码：`days = 800 if last is None else (today - last.date()).days + 5`。`+5` 让 days 永远 ≥ 5（即使 `last == today` 时 `days = 5`）。`days <= 0` 不可能成立。注释"cache 已是今日，跳过"与代码不符。

**Suggestion**: 改为 `if last is not None and last.date() >= today: continue`，或把 `+5` 改成 `+1`、然后 `if days < 1: continue`。同时把意图注释清楚："`+5` 是为了节假日 / 数据延迟回灌缓冲"。

#### Issue 11 (Medium): plan 验证步骤未要求重跑 pytest，无法保证既有测试不破
**Location**: 第七章执行清单 §2.4 "加 pytest 单测"；§6.3 验证步骤
plan §2.4 只要求**新增**单测（`fetch_history_daily` mock + `merge_daily` 幂等），完全没要求**重跑现有 86 用例 + 6 集成测试**确保 Phase 1 的 git config / Phase 2 的 cache.append_daily 重构不破坏现有 `test_cache.py` / `test_writer.py` / `test_integration_replay.py`。`append_daily` 拆成 `merge_daily + write` 是**签名兼容性变更**，现有 test_cache.py 极可能依赖旧返回值/副作用。

**Suggestion**: §六增加一节 "6.4 回归测试": 列出必须通过的现有测试套件清单 + 命令 `pytest scripts/quant/tests/ -v` —— Phase 1 push 前一次、Phase 2 push 前一次。明确门：86 + 新增的不能少于现状，旧用例不许 skip / xfail。

#### Issue 12 (Medium): mock-test 5 道硬门隔离 vs Phase 1 全局 git config 的潜在冲突未被验证
**Location**: 第六章 §6.1 表格 "mock-test mode" 行 "git config 入 .git/config 不入工作区，硬门 #3 不破"
plan 断言 "git config 不入工作区"。这是**对的**（git config 写 .git/config 而非 worktree）。但 plan 没有验证 plan §1.2 的全局 git config step 与 quant.yml line 74-79 的 "硬门 #1：移除 git remote 凭据" step 顺序：当前 `Configure git identity` 如果加在 `Install dependencies` 之后（plan §1.2 写法），**它会跑在硬门 #1 之后**，无影响。但如果加在 checkout 之后、硬门 #1 之前，那么后续硬门 #1 会**保留** identity（unset 的是 extraheader），不破坏隔离。plan 没明确 step 顺序，存在歧义。

**Suggestion**: §1.2 明确指定 step 位置 —— "在 `Install dependencies` step 之后、所有 mode 分支之前（line ~91 之间）"。额外加一句 "mock-test 模式下 git identity 仍存在但工作树不允许有 diff（硬门 #3 兜底），无副作用"。同时把这个加进 mock-test 验证清单——跑一遍 mode=mock-test，硬门 #3 必须仍 PASS。

#### Issue 13 (Medium): Phase 2 cache 不依赖 `_fetch_cs_index` retry decorator，但 plan 要求"参考主站 pattern" 而 quant 已声明"不跨 import"
**Location**: 第四章 §2.1 "不跨 import——quant 子系统独立复制一份"；scripts/data_fetcher.py:60-90 retry/EXTRA_DAYS_BUFFER/NETWORK_ERRORS
plan 决策表 #2 "ak 历史接口：复用主站 pattern（csindex 主 + sina 备） + 不跨 import 保子系统独立"。但 retry decorator (`retry_on_network_error`)、EXTRA_DAYS_BUFFER 常量、NETWORK_ERRORS tuple、`_standardize_dataframe` 私有方法、`_convert_to_sina_symbol` 私有方法，**全是 main 子系统的实现细节**。子系统独立复制意味着这五块代码要在 quant/data_fetcher.py 重写或全文复制。plan §2.1 给出的接口签名只有 `fetch_history_daily(code, days)`，**完全不提复制成本和测试覆盖**。复制后两份代码漂移风险：主站 update 了 csindex 表头处理，quant 不知道。

**Suggestion**: §2.1 加一节"实现细节清单": 列出必须复制的 5 项（retry decorator、EXTRA_DAYS_BUFFER、NETWORK_ERRORS、列名 rename map、sina symbol 转换）+ 一条 "quant 子系统独立复制后不再追主站变更，主站如有 cs_index 接口失效需独立修复 quant 副本"。或者：plan 重新评估"不跨 import"是否真的必要——主站 fetcher 在 main.py 里通过 `monkey-patch requests.Session.request` 注 UA，quant 也跑在同进程吗？如果不是同进程（quant 是独立 `python -m scripts.quant.run_signal`），跨 import 一个纯函数（`_fetch_cs_index`）反而比复制 5 个 helper 更简单。

#### Issue 14 (Medium): plan §6.3.3 "04-28 自然链路观察" 假设 04-28 是交易日，但 plan 自己引用的 calendar fixture 显示 04-28 确实是交易日 —— 不过 fixture 只到 05-08，5/9 之后就盲区
**Location**: 第六章 §6.3.3；scripts/quant/tests/fixtures/trading_calendar_2026-04.json:1-11
fixture 涵盖 2026-03-30 至 2026-05-08，含五一假期（5/1, 5/2, 5/3 不在列表内 = 非交易日）。plan §6.3.3 验证 04-28 没问题；但 04-30 / 05-04 这种连续 4 天假期（5/1 ~ 5/3 + 5/4 是工作日吗？fixture 显示 05-04 是交易日，所以 5/1 ~ 5/3 仅 3 天假期）—— quant.yml 在 4 月 30 日 09:05 跑 morning-reconcile 处理 04-29 真值，但**5/1（周五）是节日 + 5/4（周一）是交易日**，5/4 09:05 morning 会找 prev_workday = 4/30（fixture 没列 5/1 但列了 4/30）—— 经过 weekday 跳周末 + 不跳节假日的 `_check_yesterday_morning_reconcile_done`，算出来的 prev_workday 可能不准。

更关键：**fixture 必须在五一前更新**，否则 5/8 之后 calendar 失效，signal 全部 skip。plan §八 YAGNI 没列这个长期负债。

**Suggestion**: §六加一节"6.5 节假日预案": 明确 5/1-5/3 跨节预演手动跑 `--mock-now 2026-05-04T14:48` 验证 prev_workday=2026-04-30 / done 文件正确。同时新增任务 "calendar fixture 季度更新 SOP" 进 plan §九（或单独追踪）。

#### Issue 15 (Medium): plan §1.1 push step `continue-on-error: true` 与 update.yml 故障隔离传染
**Location**: 第四章 §1.1 "continue-on-error: true # 故障隔离不影响主链路"
update.yml 的 quant step 设计上 "故障不影响主站趋势数据推送"（Issue 7 也提到）。但 plan §1.1 新增的 push step 也 `continue-on-error: true`：
- 场景 A：push 失败（网络 / 竞态）→ 静默 → cache 写不进 main，下一日重新冷启动 800 天 —— 浪费 60s + 上游限流风险
- 场景 B：peaceiris deploy step（line 76-84）紧跟其后，**仍会用工作树的 cache 文件发布到 gh-pages** → main 没 cache，gh-pages 有 cache，状态分裂

**Suggestion**: push step 改成"先 push，失败重试 3 次，仍失败则 fail step（不带 continue-on-error）；deploy step 改成 `if: success() && ...`"。让"主链路推送 trend 数据"和"quant cache push"合二为一：trend 数据本来也是 push 进 gh-pages，没必要要求"quant fail 不影响 trend"——因为 trend 的失败也会导致 deploy 跳过。如果坚持隔离，至少 push step 不能静默失败，否则违背"故障必须可见"原则。

#### Issue 16 (Low): plan 推断 "04-27 14:48 signal 跑 14 个指数 MA20 极可能全为 NaN" 但 config.yaml 只有 13 indices
**Location**: 第一章 §1.1 时间线 "14:48 signal 跑完 14 个指数"
config.yaml 现状 13 个 indices（光伏、有色、白酒、医疗、5G、新能、AI、智汽车、军工、创业板50、科创50、化工、新能车）—— plan 全文也称 "13 指数"。§1.1 这里 "14 个指数" 应是笔误。

**Suggestion**: §1.1 时间线改成 "13 个指数"。

#### Issue 17 (Low): plan §六验证步骤未给 `--mock-now` 期望失败语义
**Location**: 第六章 §6.3.2.2 "mode=signal --mock-now 2026-04-27T14:48"
04-27 是周一，但 04-27 fixture 含 04-27 trading day。问题：04-27 当时 quant.yml 已经写了 `signal-2026-04-27.done`（plan §1.3 实施前，那次 commit 失败 → done 没写 → OK）。但 phase 2 跑完后会**真的写** signal-2026-04-27.done。如果第二天 plan §6.3.3 "04-28 14:48 signal 自然触发" 之前手贱 mock 又跑了一次 04-27，就跳过；OK。但如果 plan §6.3.2.2 设置的是 `--mock-now 2026-04-27T14:48`，**positions.json 状态会被基于 04-27 收盘价改一次**，然后 04-28 自然链路又一次基于 04-28 改。状态机演进会有"04-27 验证轨迹"不一致主链路的风险。

**Suggestion**: §6.3.2.2 改为 mock 一个未来日（例如 `--mock-now 2026-04-28T14:48`，但 cache 当时只有到 04-24 的真历史，04-25 / 04-26 周末，04-27 = 实时拼接），或者用 dry-run / write-only 模式跑验证、不进 main，避免 positions.json 污染。

#### Issue 18 (Suggestion): plan 缺乏回滚预案
**Location**: 第六章 §6.1 / §6.2 通篇
plan 列出了"破坏性评估"和"行为变化预期改进"，但**没有回滚步骤**。Phase 2 上线后如果发现 cache 拉来的某个指数数据有偏差（比如 cs_index 接口返回了非交易日行 / 列名变化），如何**快速回退**？没有"删除 cache/{code}.csv 重新拉" 或 "git revert phase-2-commit + 触发一次 morning-reconcile" 的明确剧本。

**Suggestion**: §六新增 "6.6 回滚剧本":
- 单指数 cache 损坏：`rm docs/data/quant/cache/<code>.csv` + commit + 下次 morning-reconcile 自动冷启动
- 整体 Phase 2 回退：`git revert <phase2-commit-sha>` + `rm -rf docs/data/quant/cache/*.csv` + commit + push
- positions.json 污染：用 `cmd_init` 重置（plan §一已知 init 是干净 CASH 状态）

#### Issue 19 (Suggestion): plan 没有量化"什么时候算成功"的明确退出条件
**Location**: 第三章"终极目标"
plan 用图描述目标，但没列出可验证的指标。比如：
- Phase 1 成功 = `quant.yml mode=signal` 跑完不报 git error + `morning-reconcile-2026-04-27.done` 出现在 main
- Phase 2 成功 = 13 cache csv 都有 ≥ 600 行（800 天减节假日大约 600 trading days）+ signal 跑完 errors 列表为空 + positions.json 至少一个 bucket 进入 HOLD 态

**Suggestion**: §六新增 "6.7 验收标准 (acceptance criteria)" —— 用具体数字而非"期望 commit 成功" 这种含糊表达。让评审/用户能 yes/no 判断。

#### Issue 20 (Suggestion): "不补 04-27 done" 决策的副作用未充分讨论
**Location**: 第五章决策表 #4 "04-27 morning-reconcile.done — 不补"
plan 决策"04-28 早 8 点 update.yml 修复后自然跑 morning（写 04-28.done），前置检查 bug 修复后命名对齐，明天 14:48 signal 不警告"。但如果 Phase 1 在 04-28 早 8 点之前没合并到 main 怎么办？04-28 早 8 点 update.yml 跑的还是旧 yml → 又一次静默吞错 → 04-28 14:48 signal 又一次警告"04-27 morning-reconcile 未跑"。决策的隐含假设是"Phase 1 在 04-27 21:00 前 merge + push 到 main"，plan 没明说时间窗。

**Suggestion**: §五决策表 #4 备注加 deadline："Phase 1 必须 04-28 SGT 08:00 前合并到 main，否则 04-28 14:48 signal 仍会发出虚警"。或者：临时手动写 `morning-reconcile-2026-04-27.done` 兜底（即使 cache 仍空、policy_state 不更新，至少让 04-28 signal 通过前置检查不发飞书噪音警报）。

### Positive Aspects
- Bug A 诊断准确：`update.yml:66-72` 的 `continue-on-error: true` 静默吞错确实是事故根因，时间线与症状对得上
- Bug C 方向正确：cache 写入零实现是事实（grep 验证 `cache.py:50` 只有 `write_cache` 内部互调，无外部调用方）
- Phase 1 / Phase 2 分阶段实施的思路正确：先把基础设施（git config）跑通再加新功能，符合"小步可独立验证"工程原则
- 决策表把已确认决策点列清楚，避免后续反复（虽然有些决策依赖于错误诊断，见 Issue 1）
- "不补 04-27 done" 这种"不破坏已有 ranking-history 状态"的克制思路，符合 Linus "Never break userspace" 哲学（虽然时间窗未明，见 Issue 20）

### Summary

**Top 3 key issues**:
1. **Bug B 诊断错误** (Issue 1) —— `_check_yesterday_morning_reconcile_done` 现有语义其实正确，plan 提议的 `today.done` 反而破坏前置检查。整段 §1.3 应删除。
2. **"单 commit 原子提交" 在现有 cmd_morning_reconcile 架构下不可能** (Issue 2) —— close_confirm + reconcile 已经各自独立 commit；Phase 2 加 cache 是第 4 笔 commit。要么改成 FileChange 收集模式重构，要么放弃"单 commit"目标。
3. **cache 同时进 main 和 gh-pages** (Issue 3) + **多 push 竞态** (Issue 7) + **silent push 失败** (Issue 15) —— 三个 push 相关 issue 共同导致"plan 看似修了 Bug A，但其实仍可能像 Bug A 一样静默状态分裂"，是事故模式的 reincarnation。

**Consensus Status**: NEEDS_REVISION

---

## Round 2 — 2026-04-27

### Overall Assessment

Round 1 的 20 个 issue 中 17 个被认真处理（其中 Issue 1 被反驳，反驳论证经代码事实链复核成立——Round 1 那条诊断错的反而是我）；§2.3 引入的 FileChange 收集模式是真正的 "good taste" 重构，把事故修复升级为消除架构违规；剩余隐患主要在 peaceiris exclude_assets 默认值覆盖、quant.yml v3 和 update.yml v4 不对称、以及 §2.3 helper 签名细节。整体已达可实施门槛，但 Phase 2 push 前需要补两处微调。

**Rating**: 8/10

### Round 1 Issue Resolution Tracking

| # | Round 1 Issue | Status | Notes |
|---|---|---|---|
| 1 | Bug B 诊断错误（findreviewer 主张现有 yesterday.done 语义对） | **Rejected by plan §10.1（反驳成立，Round 1 错）** | 复核证据链：`signal_generator.py:185 yesterday_policy = bucket.policy_state` 读 positions.json 当前值；`bucket.policy_state` 在 D 日 14:48 之前最近一次写入由 D 日 09:05 morning-reconcile 内的 `confirm_signals_with_close()`（`close_confirm.py:113`）执行；该 morning 写出的 done 文件名是 `morning-reconcile-{D}.done`（`run_signal.py:163` 用 today）。Round 1 的论证错在"Fri 09:05 morning 处理 Fri 真值"——实际上 Fri 09:05 morning 处理的是 Thu 真值（`cmd_morning_reconcile` 算 yesterday=Thu，传给 close_confirm）。所以 D 14:48 signal 应该确认的是 D 09:05 morning（写 today.done）已跑，plan §10.1 表格逻辑正确。**接受反驳**。Round 1 Issue 1 撤回；plan §1.3 改 today.done 是对的修复方向。注意一个小坑：`confirm_signals_with_close` 里的 `quote = fetcher.fetch_indices()` 拿到的其实是 D 日早晨的实时价（不是 D-1 真实收盘）——这是另一个独立的语义偏差，但不在本次事故范围。 |
| 2 | morning-reconcile "单 commit 原子" 不可能 | **Resolved（§2.3 + §决策表 #5）** | §2.3 真的把 close_confirm / reconcile 改成返回 `tuple[dict, list[FileChange]]`；cmd_morning_reconcile 末尾唯一一次 `writer.commit_atomic(all_changes, ...)`。这是 Linus "consolidate the special case" 重构，不是表面妥协。注意：`reconcile.py:84` 当前确实在循环外一次性 commit（已经是 1 笔），改成"返 changes 不 commit"工作量极小。close_confirm.py:130 同理。**Phase 2 真的是 1 笔 commit**（cache + close-confirm + reconcile + done）。 |
| 3 | cache 同时进 main 和 gh-pages | **Partial** | update.yml 用 peaceiris@v4 `exclude_assets`（已通过 WebFetch 验证支持 glob，但默认值是 `.github`——plan 写 `'data/quant/cache/**'` 会**覆盖默认**导致 `.github` 不再被排除，需写成 `'.github,data/quant/cache/**'`）；plan §1.1 改动 4 注释里有 fallback 提到这个风险但未在最终 yml 里写正确值。quant.yml 路径用 cp + rm（§1.2 改动 4），这一侧是安全的。**新瑕疵见 New Issue 1。** |
| 4 | morning-reconcile 缺 calendar gate | **Resolved（§2.3 改动 3 + §2.4）** | cmd_morning_reconcile 加了 `cal = _load_calendar(...) if args.calendar else (lambda d: True)`；非交易日 `skipped_non_trading_day` 直接 return 不写 done。yml 端 §2.4 给 quant.yml + update.yml 都加了 `--calendar` 参数。但 `args.calendar` 当前 cmd_morning_reconcile argparse 还没声明，需要在 §2.5 补 `p_mr.add_argument("--calendar", default=None)` 否则会 AttributeError。**新瑕疵见 New Issue 2。** |
| 5 | `--realtime skip` 模式 fetcher=None NoneType 崩 | **Resolved** | §2.3 cache 增量逻辑显式 `fetcher = _build_fetcher(args.realtime) if args.realtime != "skip" else None`；`_update_cache_incremental` 第一行 `if fetcher is None: return [], {...}`；close-confirm 段 `if fetcher is not None and ...`；reconcile 段不依赖 fetcher——None 路径全部覆盖。 |
| 6 | check_readiness.py:153 marker 重命名后会失败 | **Resolved（§1.4 + 执行清单）** | §1.4 明确"`scripts/quant/check_readiness.py:153` marker 同步改名"；执行清单 1.4 也列了。 |
| 7 | update.yml 与 quant.yml 多 push 竞态 | **Resolved（§1.1 改动 1 + 决策 #6）** | update.yml 顶层加 `concurrency: { group: quant-state-main, cancel-in-progress: false }`，与 quant.yml 同 group；排队不并发。决策 #6 明确写在表里。 |
| 8 | quant.yml line 142-153 绕过 writer 未删 | **Resolved（§1.2 改动 3 + §1.4）** | §1.2 明确删 line 142-153 整段；done 由 cmd_signal_for_one_day 内部走 writer 提交（§1.4）。这真的让 yml 端零 git commit。注意：cmd_signal 端会变成 2 笔 commit（signals/positions/index 一笔 + done 一笔）——plan §八 YAGNI 把这个单 commit 化推迟到后续，明确说出来。**完整修了硬约束违规。** |
| 9 | 800 天冷启动无 retry / 限流 / 整体回滚 | **Resolved（§2.2 + §2.3 改动 4）** | §2.2 实现要求 7 条全列：retry decorator 复制清单、`time.sleep(0.5)` 限流、超时 30s、fail-soft 返回空 DF。§2.3 `_update_cache_incremental` 实现"全部成功才一次性 append"和"is_cold_start + failed > 0 → 整体回滚"。 |
| 10 | `if days <= 0: continue` 永不触发 | **Resolved** | §2.3 改动 4 的代码改成 `if last is not None and last.date() >= today: continue`，跳过条件正确。 |
| 11 | 验证步骤未要求重跑 pytest | **Resolved（§6.4）** | §6.4 新增"回归测试（push 前必跑）"，明确 Phase 1 / Phase 2 push 前 86 + 6 + 新增**全 PASS**，不允许 skip / xfail，覆盖率不下降。 |
| 12 | mock-test 与全局 git config 顺序歧义 | **Resolved（§1.2 改动 1 注解 + §6.3.1 验证 1）** | §1.2 明确"在 Install dependencies 之后、所有 mode 分支之前新增"；硬门 #1（line 74-79）在 Install deps 前已跑完——顺序明确。验证步骤 6.3.1.1 mock-test 重跑硬门 #3 必须 PASS。 |
| 13 | 不跨 import 复制清单不明 | **Resolved（§2.2 复制清单表 + drift 风险声明）** | §2.2 列出 5 项复制清单（retry decorator / EXTRA_DAYS_BUFFER / NETWORK_ERRORS / 列名 rename / sina symbol 转换），并明确"drift 风险接受——quant 复制后不再追主站变更"。决策 #2 也再次确认。复制清单的行号略有偏差（plan 写 line 294-295 是 inline rename，而主站还有 `_normalize_columns` line 127 + COLUMN_PATTERNS line 25-32），但意图清楚（中→英映射）。**复制清单可以更精确到函数名而不是行号——5/8 后行号会漂移。** |
| 14 | calendar fixture 5/8 后失效 | **Resolved（§九长期任务 + §6.5 跨节预演）** | §九列了 calendar fixture 月度更新 SOP；§6.5 新增"5/1-5/3 五一假期跨节预演"在 4-30 前手动跑 `--mock-now 2026-05-04T09:05:00+08:00`。 |
| 15 | push 失败 `\|\| true` 静默吞错 | **Resolved（§1.1 改动 3 + 决策 #7）** | update.yml push step 改成 3 次重试（pull --rebase --autostash + push），全失败 `exit 1` + warning/error annotation 可见。`continue-on-error: true` 仅保留主站隔离原则（quant fail 不阻塞 trend deploy），step 内部不再静默。决策 #7 明确"failure must be visible"。 |
| 16 | "14 个指数" 笔误 | **Resolved** | §一时间线现写"13 个指数 / 14 个 trigger_buckets"——保留 14 是因为按 D/W/M frequency 算（决策表里 36 bucket，每天选 D + W + M 子集）。新文案准确。 |
| 17 | mock-now 04-27 验证会污染 positions.json | **Resolved** | §6.3.2.2 改成 `--mock-now 2026-04-28T14:48 --writer-mode dry_run`，明确 dry_run 不入库。 |
| 18 | 缺回滚剧本 | **Resolved（§6.6）** | §6.6 列了 4 个故障的具体回滚步骤（单指数 cache 损坏 / 整体 Phase 2 回退 / positions.json 污染 / Phase 1 修复后 cache 仍空）。 |
| 19 | 缺量化退出条件 | **Resolved（§6.7）** | §6.7 验收标准：每行数 ≥ 600 / commit 数 = 1 / errors 列表为空 / 至少 1 bucket 不为 CASH——可量化、可 yes/no 判断。 |
| 20 | 不补 04-27 done 决策的时间窗未明 | **Resolved（决策表 #4 备注）** | 决策表 #4 加了 "Phase 1 必须 04-28 SGT 08:00 之前合并到 main——否则 04-28 14:48 signal 仍会发出虚警，需手写一个 morning-reconcile-2026-04-27.done 兜底"。 |

### New Issues (from revision)

#### New Issue 1 (Medium): peaceiris@v4 `exclude_assets` 覆盖默认值会让 `.github` 不再被排除
**Location**: §1.1 改动 4
plan 写：
```yaml
exclude_assets: 'data/quant/cache/**'
```
peaceiris@v4 的 `exclude_assets` 默认值是 `.github`（已通过官方 README 验证）。一旦 user 指定了自定义值，**默认值被完全覆盖**，`.github` 目录会被发布到 gh-pages——可能泄漏 workflow 配置 / 引发 GitHub Pages limit 警告。
**Suggestion**: 改成
```yaml
exclude_assets: '.github,data/quant/cache/**'
```
保留默认 `.github` 排除 + 新增 cache 排除。建议在 plan §1.1 改动 4 直接更新 yaml 片段，避免实施时遗漏。

#### New Issue 2 (Medium): cmd_morning_reconcile 的 argparse 缺 `--calendar` 声明
**Location**: §2.3 改动 3 + §2.4 yml 改动
§2.3 改动 3 主函数用 `args.calendar`：
```python
cal = _load_calendar(Path(args.calendar)) if args.calendar else (lambda d: True)
```
§2.4 yml 改动给 quant.yml + update.yml 都加 `--calendar` 参数。但 `run_signal.py:287-290` 里 `p_mr.add_subparser("morning-reconcile")` 当前**没有 `--calendar` 参数声明**：
```python
p_mr.add_argument("--mock-now", required=True)
p_mr.add_argument("--realtime", default="auto", ...)
p_mr.add_argument("--writer-mode", default="write_only")
```
传 `--calendar` 会触发 `argparse error: unrecognized arguments`。
**Suggestion**: §2.5 执行清单加一行 `p_mr.add_argument("--calendar", default=None, help="可选；若提供则跳过非交易日")`。同时把这一项写进 §2.3 改动 3 的代码片段（让"plan 自包含、agent 看 plan 就能写"）。

#### New Issue 3 (Low): quant.yml 用 peaceiris@v3 而 update.yml 用 v4，版本不对称
**Location**: `.github/workflows/quant.yml:249` (`peaceiris/actions-gh-pages@v3`) vs `update.yml:78` (`peaceiris/actions-gh-pages@v4`)
plan 没提到这个不对称。v3 的 `exclude_assets` 选项与 v4 略有差异（v3 也支持但 glob 行为细微不同）。quant.yml 的 cache 排除走 cp + rm 路径不依赖 `exclude_assets`，所以**实际不影响本次事故修复**，但留作未来一致性 issue。
**Suggestion**: §九长期任务加一行 "升级 quant.yml peaceiris@v3 → v4，与 update.yml 对齐"。本次不强制做。

#### New Issue 4 (Low): §2.3 改动 1 与 §2.3 改动 3 中 `confirm_signals_with_close` 的参数列表不一致
**Location**: §2.3 改动 1 vs §2.3 改动 3
改动 1 给 close_confirm 新签名：
```python
def confirm_signals_with_close(...) -> tuple[dict, list[FileChange]]:
```
但没列出参数。改动 3 调用：
```python
cc_summary, cc_changes = confirm_signals_with_close(
    cfg=cfg, today=yesterday, book=book, fetcher=fetcher,
    repo_root=repo_root,
)
```
注意：**少了 `writer=writer`**——现行 close_confirm.py:46 签名要 `writer: LocalWriter`。新签名不再 commit 所以不需要 writer 是对的，但 plan 没明确把"删除 writer 参数"写出来。`cmd_close_confirm` 调用点（run_signal.py:251-254）也需要同步改。
**Suggestion**: §2.3 改动 1 加一句"同时删除 writer 参数；调用方 cmd_close_confirm（run_signal.py:246-255）也需要同步：`writer = LocalWriter(...)` 后用 `result, changes = confirm_signals_with_close(...); writer.commit_atomic(changes, ...)`"。否则 cmd_close_confirm 子命令会 unused warning + signature mismatch。

#### New Issue 5 (Low): §2.3 改动 4 `_update_cache_incremental` 未导入 `time`
**Location**: §2.3 改动 4 helper 内
helper 用 `time.sleep(0.5)` 但 `run_signal.py` 顶部 import 区无 `import time`。
**Suggestion**: 写进 §2.3 改动 4 注解："若 helper 放在 run_signal.py，文件顶部需添加 `import time`；若放进单独 helper 模块（`scripts/quant/cache_updater.py`）则在新模块导入。**实际建议**：放进新模块更干净，避免 run_signal.py 越来越胖。

### Positive Aspects

- **§10.1 反驳论证扎实**：plan 不是简单 "I disagree"，而是给了完整时间线表格 + 代码事实链。Round 1 reviewer 错就要勇于撤回——Linus 说的 "技术批评针对问题不针对人"——plan 作者做对了。
- **§2.3 FileChange 收集模式重构**：把"3 笔独立 commit"消除成"1 笔单 commit"是 Linus "好品味" 的教科书例子——消除特殊情况而不是加 if。helper 函数从 commit-side-effect 转成 pure compute（返 list[FileChange]），调用方负责一次性提交，正是 Bad programmers worry about code, good programmers worry about data structures 的体现。
- **§6.4-6.7 完整闭环**：回归测试门槛 + 节假日预案 + 回滚剧本 + 量化验收标准全部补齐——之前 4.5/10 主要扣分项现在都修了。
- **决策表 #0-#7 全部明确**：每个争议点都有"选项 + 理由"对应，避免后续反复。决策 #6 共享 concurrency group 和 #7 push 失败可见性都是 "failure must be visible" 哲学的落地。
- **Phase 1 / Phase 2 分阶段 + 各自独立 acceptance**：Phase 1 修事故根因（git config + 命名 + 违规），Phase 2 加 cache 实现。两阶段独立可合并、独立可回滚——符合"小步可独立验证"工程原则。

### Summary

**Top 3 remaining concerns**（均为 implementation-detail 级别，非根因）：
1. **peaceiris exclude_assets 覆盖默认值**（New Issue 1）—— yaml 片段写错会让 `.github` 进 gh-pages，5 字符的修复但容易漏。
2. **cmd_morning_reconcile argparse 缺 `--calendar`**（New Issue 2）—— Phase 2 验证一跑就 unrecognized arguments，但属于 trivial fix。
3. **§2.3 helper 签名/import 细节**（New Issue 4 + 5）—— 不修也能跑，但 plan 自包含原则下应该补全。

**Consensus Status**: MOSTLY_GOOD（修完 New Issue 1+2 即可 push；3+4+5 是 polish）

---
## Round 3 — 2026-04-27

### Overall Assessment
Round 2 的确修掉了不少文本级漏洞，但还没达到“可安全实施”的状态：关键链路里仍有前置检查语义分裂、节假日前一交易日计算错误、以及 quant 主流程 push 静默失败复发风险。独立复核代码后，§10.1 的核心方向（signal 前置检查应对齐 D 日 morning）成立，但它依赖的“已确认 D-1 真值”前提在现实现里仍有数据语义漏洞。整体结论应回到需要修订。

**Rating**: 6/10

### Previous Rounds Tracking
| Round | Issue # | Status as of now | Notes |
|---|---|---|---|
| R1 | 1 (Bug B 诊断) | Confirmed rejected（但应补语义边界） | 代码链路显示 `signal_generator.py` 读的是当前 `bucket.policy_state`，而该值在 D 日 14:48 前最近写入点是 D 日 morning；因此“检查 today.done”方向正确。需要补一句：`close_confirm.py` 当前用的是 D 日早盘实时价，不等于严格 D-1 收盘真值。 |
| R2 | New 1 (peaceiris) | Resolved | plan §1.1 已写 `exclude_assets: '.github,data/quant/cache/**'`，修复了默认 `.github` 覆盖风险。 |
| R2 | New 2 (`--calendar` argparse) | Resolved | plan §2.4 已补 `p_mr.add_argument("--calendar", ...)`。 |
| R2 | New 3 (peaceiris v3/v4 不对称) | Partial | plan 放进 §九长期任务，未在本轮执行范围内统一。 |
| R2 | New 4 (close_confirm 签名不一致) | Resolved | plan §2.3 已明确“删 writer 参数 + 同步 cmd_close_confirm”。 |
| R2 | New 5 (`import time`) | Resolved | plan §2.3/§2.5 已补 `import time`。 |

### Issues (new from Round 3)
#### Issue 1 (Critical): 前置检查“today.done”只改了 Python，没改 quant.yml shell 前置检查
**Location**: §1.3、§1.2、§6.1
plan 把 `run_signal.py` 改成检查 `today.done`，但 `quant.yml` 里 signal 前置检查 step 仍在算 `PREV_WORKDAY` 并检查 `morning-reconcile-${PREV_WORKDAY}.done`。这会产生双重语义：Python 侧与 workflow 侧可能给出相反结论（误报/漏报都可能），且飞书告警仍基于旧逻辑。
**Suggestion**: 统一单一真相源。优先删除 shell 前置检查，改为调用 Python helper（或直接读取 `run_signal.py` 的统一检查结果）；至少把 workflow 也改为 `today.done`。

#### Issue 2 (High): “前一工作日”仍按 weekday 计算，节假日会确认错日期
**Location**: §2.3 改动 3（`while yesterday.weekday() >= 5`）、§6.5
plan 新增了“today 是否交易日”gate，但计算 close-confirm 目标日仍只跳周末、不跳法定节假日。五一跨节场景下会把 2026-05-01（休市）当作“前一工作日”，导致 close-confirm 查不到 signals 文件并跳过，实际应处理 2026-04-30。
**Suggestion**: 增加 `prev_trading_day(today, cal)`，用 calendar 回溯上一交易日；signal warning、morning close-confirm、验证脚本都走同一个 helper。

#### Issue 3 (High): quant.yml 主链路 push 仍是 `|| true`，静默失败模式未根治
**Location**: §1.2（未覆盖 quant.yml push step）
plan 修了 `update.yml` 的 push 可见性，但 `quant.yml` 的 morning push 仍是 `git push origin main || true`。这和事故模式同源：本地 commit 成功但远端未落库，runner 销毁后状态丢失，且 workflow 表面成功。
**Suggestion**: quant.yml 同步使用“pull --rebase + push 重试 + 失败可见”策略；禁止 `|| true` 吞错。

#### Issue 4 (High): §2.3 改签名遗漏 `cmd_reconcile` 调用点，落地会直接 TypeError
**Location**: §2.3 改动 2、§2.5
plan 明确要把 `reconcile_pending_signals` 改为返回 `tuple[dict, list[FileChange]]` 且删除 `writer` 参数，但执行清单只要求同步 `cmd_close_confirm`，没覆盖 `cmd_reconcile` 子命令。实施后 `cmd_reconcile` 仍按旧签名调用会直接崩。
**Suggestion**: 在 §2.5 明确增加 `cmd_reconcile` 调整项，并补对应 CLI 回归测试。

#### Issue 5 (Medium): refactor 后若无变更仍调用 `commit_atomic` 会触发 WriterError
**Location**: §2.3 改动 1/2 + §2.5(d)
`LocalWriter.commit_atomic` 对空 changes 直接抛 `WriterError("no changes to commit")`。close-confirm/reconcile 在“无 signals/无 pending”场景下是合法无变更；plan 里 `cmd_close_confirm`/`cmd_reconcile` 的新调用模式未写 `if changes:` 防护。
**Suggestion**: 明确“仅当 `changes` 非空才 commit”，空变更返回 summary 并正常退出。

#### Issue 6 (Medium): 冷启动部分失败后仍写 morning done，会把失败伪装成通过
**Location**: §2.3 改动 3/4、§6.2、§6.3.2
`_update_cache_incremental` 在冷启动部分失败时返回 rollback summary，但主流程仍继续并写 `morning-reconcile-{D}.done`。后续 signal 只看 done 存在就认为前置满足，实际 cache 仍空/半空，MA20 继续失真，形成“有 done 的静默降级”。
**Suggestion**: 冷启动 rollback 时不要写 done，或直接 `exit 1` 让 workflow 报错并告警；done 应仅代表“数据前置已满足”。

#### Issue 7 (Medium): §2.2 的 fetch_history_daily 复制清单仍不完整，缺标准化与 UA 策略
**Location**: §2.2
plan 复制了 retry/常量/sina symbol，但没把主站 `data_fetcher` 的列标准化流水线（`_normalize_columns/_standardize_dataframe`）和 UA 注入策略纳入“必须项”。对 csindex/sina 混合返回的列差异与反爬策略，这两块是高频稳定性基础。
**Suggestion**: §2.2 明确补充：统一列名映射+数值清洗+最小 UA 策略（或明确声明不复制并给出可接受风险与补偿测试）。

#### Issue 8 (Medium): 将 morning `--realtime` 限制为 `choices=["auto","skip"]` 会破坏现有 fixture 回放能力
**Location**: §2.4（位置 1.5）
当前 CLI 支持 `--realtime <fixture_path>` 做离线可复现实验；plan 若改为仅 auto/skip，会让本地/CI 很难对 morning-reconcile 做确定性回放测试，也破坏现有使用兼容性。
**Suggestion**: 保留字符串输入：`auto` / `skip` / fixture path 三态；解析逻辑在 `_build_fetcher` 内处理。

### Positive Aspects
- §10.1 对“为何应检查 D 日 morning”的主链路推导方向是正确的，Round 1 Issue 1 的核心结论应维持撤回。
- §2.3 的 FileChange 收集式单 commit 目标是正确方向，能实质消除“多笔 commit + 中间态”问题。
- §6.4/§6.6/§6.7 把测试、回滚、验收写成可执行门槛，这部分比前两轮明显更成熟。

### Summary
**Top 3 remaining concerns**:
1. 前置检查语义分裂（Python= today.done，workflow=prev_workday.done）导致告警与真实状态不一致。
2. 节假日前一交易日计算仍错误，close-confirm 在长假后会跳错目标日。
3. quant.yml push 仍 `|| true`，事故级“静默失败”模式在主链路继续存在。

**Consensus Status**: NEEDS_REVISION

---
## Round 4 — 2026-04-27
### Overall Assessment
本轮 plan 相比 Round 3 明显收敛：R3 的 8 个问题中 6 个已实质闭环，核心链路（today.done 对齐、节假日回溯、quant push 可见失败、cmd_reconcile 同步、空 changes guard、冷启动失败不写 done）都已覆盖。剩余问题主要是两处“部分修复”：`--realtime` 兼容性在 §2.4 仍自相矛盾，`data_fetcher` 复制清单只补了 `_standardize_dataframe` 但 UA 策略仍挂长期任务。另有两条由新修复引出的执行风险需要收口后再评估通过。
**Rating**: 8/10

### Round 3 Issue Resolution Tracking
| # | Round 3 Issue | Status | Notes |
|---|---|---|---|
| 1 | 前置检查 today.done shell vs Python 分裂 | Resolved | §1.2 改动 2.5 已把 quant.yml shell 前置检查改为查 `morning-reconcile-${TODAY}.done`，与 §1.3 Python 逻辑一致。 |
| 2 | 节假日 prev_trading_day 计算错误 | Resolved | §2.3 改动 3.5 新增 `_prev_trading_day(today, cal)`，并在 §2.3 改动 3 用于计算 `yesterday`。 |
| 3 | quant.yml push `|| true` 静默失败 | Resolved | §1.2 改动 3.5 已改为 `pull --rebase + push` 3 次重试，失败 `exit 1`，不再静默吞错。 |
| 4 | cmd_reconcile 调用点遗漏 | Resolved | §2.5(f) 明确要求同步 `cmd_reconcile` 为 `result, changes = ...; if changes: writer.commit_atomic(...)`。 |
| 5 | 空 changes 调 `commit_atomic` 崩溃 | Resolved | §2.3 改动 3 已加 `if all_changes:`；§2.5(e)(f) 对 close_confirm/reconcile 也明确了 `if changes:` guard。 |
| 6 | 冷启动 rollback 仍写 done | Resolved | §2.3 改动 3 在 done 提交前检查 `cold_start_partial_failure` 并 `sys.exit(1)`，避免写入 done。 |
| 7 | 复制清单缺 `_standardize_dataframe` | Partial | §2.2 已加入 `_standardize_dataframe`；但 R3 原问题里的 UA 策略仍未纳入“必须项”，仅放到 §九长期任务。 |
| 8 | `--realtime choices` 破坏 fixture 兼容 | Partial | §2.5(b) 文字要求“保留字符串不加 choices”是对的，但 §2.4 位置 1.5 代码块仍写了 `choices=["auto", "skip"]`，文档内部矛盾。 |

### New Issues (from Round 3 fixes, if any)
#### Issue 1 (Medium): `_prev_trading_day` 30 天上限异常未在主流程显式兜底
**Location**: §2.3 改动 3.5 + §2.3 改动 3
`_prev_trading_day` 在 30 天内找不到交易日会 `raise RuntimeError`，但 `cmd_morning_reconcile` 片段没有明确捕获/结构化输出。calendar fixture 过期或配置异常时会直接异常栈退出，排障信号不够稳定。
**Suggestion**: 在 `cmd_morning_reconcile` 捕获该异常并输出明确 `::error::` + 可执行修复提示（更新 calendar fixture），再 `sys.exit(1)`。

#### Issue 2 (Medium): 冷启动失败 gate 放在 close-confirm/reconcile 之后，导致这些变更被一起丢弃
**Location**: §2.3 改动 3（cache → close-confirm → reconcile → cold_start_check）
当前顺序是先计算并收集 close-confirm/reconcile changes，再在末尾因 `cold_start_partial_failure` 直接 `sys.exit(1)`；结果是即便 reconcile/confirm 逻辑本可落库，也会全部丢弃。连续失败时可能导致 pending 信号长期不被过期处理。
**Suggestion**: 把冷启动失败判断前移到 cache 阶段后立即处理（失败即退出，不再继续 cc/reconcile），或显式定义“cache 失败时仍允许提交 reconcile”的策略并拆分提交边界。

### Positive Aspects
- Phase 1 的关键一致性问题已补齐：today.done 检查统一到 shell + Python，避免双真相源。
- Phase 2 的核心架构目标保持正确：morning-reconcile 单 commit 收敛、冷启动失败不伪造 done、调用点签名同步已写进执行清单。
- 执行清单可操作性明显提升：§2.5 对 run_signal 改动边界写得足够细，后续实施可直接照单执行。

### Summary
**Top 3 remaining concerns**:
1. §2.4 对 `--realtime` 的说明自相矛盾（代码块有 choices，注释和 §2.5 要求无 choices），R3 Issue 8 仍未完全闭环。
2. `_prev_trading_day` 异常路径缺少结构化兜底，calendar 过期时可观测性不足。
3. 冷启动失败检查位置偏后，会连带丢弃 close-confirm/reconcile 结果，需明确策略并前移或拆分。
**Consensus Status**: NEEDS_REVISION

---
## Round 5 — 2026-04-27
### Overall Assessment
Round 4 的 4 个遗留点在最新 plan 中已全部闭环，关键修复点都有明确代码级落地（不是口头声明）：`--realtime` 兼容性矛盾已消除、`_prev_trading_day` 异常已结构化处理、cold-start gate 已前移到 cache 阶段后立即判定。`UA` 策略也已明确归入长期任务并在本轮被确认“非阻塞”。当前 plan 已达到可实施状态。
**Rating**: 9.5/10

### Round 4 Issue Resolution Tracking
| # | Issue | Status | Notes |
|---|---|---|---|
| 1 | R3 Issue 8：§2.4 位置 1.5 `--realtime choices` 矛盾 | Resolved | 代码块已改为 `p_mr.add_argument("--realtime", default="auto", help=...)`，不再带 `choices`，并保留 fixture path 语义说明。 |
| 2 | R4 New 1：`_prev_trading_day` 异常处理缺失 | Resolved | §2.3 改动 3 已增加 `try/except RuntimeError`，并输出 `::error::...` 后 `sys.exit(1)`。 |
| 3 | R4 New 2：cold_start gate 位置过晚 | Resolved | gate 已前移到 cache 更新后、close-confirm/reconcile 前；`cold_start_partial_failure` 直接报错退出，不再继续后续阶段。 |
| 4 | R3 Issue 7：UA 策略仅长期任务 | Accepted (Non-blocking) | §九长期任务明确记录“quant 子系统独立 UA 注入（防反爬）”；按本轮验收口径该项为长期优化，不阻塞实施。 |

### New Issues (if any)
无新增问题

### Positive Aspects
- 修复粒度准确：本轮针对 Round 4 的三个技术缺口都给出了代码片段级修正，而不是抽象承诺。
- 文档一致性明显提升：`--realtime` 语义、异常处理路径、cold-start 失败策略在 §2.3/§2.4/§2.5 之间已基本对齐。
- 实施可执行性达标：执行清单与验证步骤可直接驱动落地，不再存在阻塞级冲突。

### Summary
**Top remaining concerns** (or 无重大遗留):
1. 无重大遗留（仅长期优化项：UA 注入策略按 §九跟踪）
**Consensus Status**: APPROVED
