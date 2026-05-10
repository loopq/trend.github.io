> Design: ./2026-05-10-faber-gtaa-and-equal-weight-aggregator-design.html

# 共享前置 + B Faber GTAA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **双件结构约定**：本 plan 是**进度板**，不含代码片段。每个 task 的代码、参数、测试 case 都在 design.html 对应 § 章节，implementer 第一步是 `Read agents/plans/2026-05-10-faber-gtaa-and-equal-weight-aggregator-design.html` 拿 § X.X 内容再 Edit。

**Goal:** 在 `scripts/backtest/` 落地 Faber GTAA 月线 MA10 趋势策略 + 共享前置（aggregator 字段 + equal-weight 流程 + combined-27 universe + N 策略对比报告），跑出 3 策略对比报告（v9-baseline / v9.3-bear / faber-gtaa）。

**Architecture:** 给 `Strategy` dataclass 加 `aggregator: str` 字段（默认 `"cycle-calmar"` = 现有行为）。`run.py:_run_one_strategy` 按 `aggregator` dispatch 到三条路径（`cycle-calmar` 旧逻辑剥离 / `equal-weight` 新增 / `cross-sectional-topk` 占位）。Faber 走 `equal-weight`：单 cycle (M)、27 指数等权 1/N、Decider 信号决定 in/out。架构图见 design.html §3 SVG。

**Tech Stack:** Python 3.9+、pandas、pytest。沿用现有 `scripts/backtest/strategy/` 框架。

---

## Pre-flight

- [ ] **P1: Read design.html 全文**

  ```
  Read /Users/loopq/dev/git/loopq/trend.github.io/agents/plans/2026-05-10-faber-gtaa-and-equal-weight-aggregator-design.html
  ```

  重点关注 §0（隔离铁律）、§3（aggregator 设计）、§5（equal-weight 流程伪代码）、§6（Faber Decider 完整代码）、§7（报告改造代码）、§8（验收 10 条断言）。

- [ ] **P2: 确认当前分支干净 + 现有测试全过**

  ```bash
  git status   # 应为 nothing to commit
  source venv/bin/activate
  pytest scripts/backtest/test_*.py -v --tb=short 2>&1 | tail -3
  ```

  Expected: `44 passed` （现有套件 + 路径修复后状态，base SHA `38c0c7b`）

---

## Task 1: 注册 universe `combined-27`

**Files:**
- Modify: `scripts/backtest/run.py`（在 `UNIVERSES` dict 旁加 `_build_combined_27_universe` 工厂 + 注册 entry）

**详情指向:** design.html §2 表（27 个指数代码、名称、source、category 完整列表）

- [ ] **Step 1**: Read design.html §2 拿 27 个 IndexMeta 字段（code / name / source / category）。注意 source 分配规则：A 股宽基/主题/行业 = `cs_index` 或 `sina_index`（同 v9_registry / main-online）；港股 = `hk`；美股 = `us`；BTC = `crypto`；XAU/XAG = `spot_price`。
- [ ] **Step 2**: 在 `run.py` 加 `_build_combined_27_universe()` 函数（仿现有 `_build_main_online_universe`），返回 27 IndexMeta 列表
- [ ] **Step 3**: `UNIVERSES` dict 加 `"combined-27": _build_combined_27_universe`
- [ ] **Step 4**: 烟测 v9-baseline 在新 universe 跑通：

  ```bash
  source venv/bin/activate
  python -m scripts.backtest.run --strategy v9-baseline --universe combined-27 --windows 3 2>&1 | tail -5
  ```

  Expected: 输出 `加载 27 个指数数据 ...` + `3 年 总 CAGR ...% / MDD ...%` + 退出码 0

- [ ] **Step 5**: Commit

  ```bash
  git add scripts/backtest/run.py
  git commit -m "[backtest] T1: 注册 universe combined-27（v9 14 + main-online 16 去重 = 27 个）"
  ```

---

## Task 2: `Strategy.aggregator` 字段 + `Decider.required_indicators` 字段

**Files:**
- Modify: `scripts/backtest/strategy/protocol.py`

**详情指向:** design.html §3 末（Strategy dataclass 改动 + 三 aggregator 值定义）+ §6.3 顶部（Decider Protocol 加 required_indicators 字段）

- [ ] **Step 1**: Read design.html §3 + §6.3 拿两个字段的精确签名（默认值、类型）
- [ ] **Step 2**: protocol.py 给 `Strategy` dataclass 加 `aggregator: str = "cycle-calmar"`（末尾、有默认值）
- [ ] **Step 3**: protocol.py 给 `Decider` Protocol 加 `required_indicators: Tuple[Tuple[str, str, int], ...] = ()` 字段（带默认值，向后兼容）
- [ ] **Step 4**: 跑现有 pytest 套件确认零退化（现有 `MA20CrossDecider` / `BearTrendFilter` 不显式声明该字段，靠 Protocol 默认值兜底）：

  ```bash
  pytest scripts/backtest/test_*.py -v --tb=short 2>&1 | tail -3
  ```

  Expected: `44 passed`

- [ ] **Step 5**: 烟测 v9-baseline 数值不变：

  ```bash
  python -m scripts.backtest.run --strategy v9-baseline --universe v9 --windows 3,5,8,10 2>&1 | tail -6
  ```

  Expected 数值（与 design.html §8.1 第 3 条断言对照）：3 年 15.32% / -12.55%；5 年 10.98% / -19.69%；8 年 11.51% / -22.12%；10 年 9.29% / -22.25%（**逐字一致**才能进 Task 3）

- [ ] **Step 6**: Commit `[backtest] T2: Strategy 加 aggregator + Decider 加 required_indicators 字段（向后兼容）`

---

## Task 3: `_ensure_indicators` helper

**Files:**
- Modify: `scripts/backtest/engine.py`（追加 `_ensure_indicators` 函数 + `run_with_strategy` 入口处调用）

**详情指向:** design.html §6.3 完整代码（含 protocol 改动 + helper 实现 + getattr 兜底调用点）

- [ ] **Step 1**: Read design.html §6.3 拿 `_ensure_indicators` 实现
- [ ] **Step 2**: engine.py 在 `run_with_strategy` 函数定义之前加 `_ensure_indicators(data, requirements)` helper（按 §6.3 代码块）
- [ ] **Step 3**: `run_with_strategy` 函数体最顶部加一行调用：`_ensure_indicators(data, getattr(strategy.decider, "required_indicators", ()))`
- [ ] **Step 4**: 跑现有 pytest 套件确认零退化（现有 Decider `required_indicators` 默认空 tuple，helper 跳过；新 Decider 在 Task 7 引入）：

  ```bash
  pytest scripts/backtest/test_*.py -v --tb=short 2>&1 | tail -3
  ```

  Expected: `44 passed`

- [ ] **Step 5**: Commit `[backtest] T3: engine 新增 _ensure_indicators helper（按 Decider.required_indicators 按需补 MA 列）`

---

## Task 4: `_run_one_strategy` 拆分为 `_run_cycle_calmar` + dispatch

**Files:**
- Modify: `scripts/backtest/run.py`

**详情指向:** design.html §3 SVG 架构图（dispatch 关系）+ §4 dispatch 完整代码

- [ ] **Step 1**: Read design.html §4 拿 dispatch 函数体（`if/elif/else` 三分支）
- [ ] **Step 2**: 把现有 `_run_one_strategy` 函数体（cycle-split + Calmar 流程）原样剥离成新私有函数 `_run_cycle_calmar(strat, registry, windows)`，**逻辑零改动**
- [ ] **Step 3**: 重写 `_run_one_strategy` 为 dispatch 路由（按 §4 代码块）。`equal-weight` 分支暂调一个 stub `_run_equal_weight` （Task 5 实现），`cross-sectional-topk` 抛 `NotImplementedError`
- [ ] **Step 4**: 跑 v9-baseline / v9.3-bear 在 v9 universe 数值不变（验证 cycle-calmar 路径一字未变）：

  ```bash
  python -m scripts.backtest.run --compare v9-baseline,v9.3-bear --universe v9 --windows 3,5,8,10 2>&1 | tail -10
  ```

  Expected: 数值与 design.html §8.1 第 4 条断言对照，逐字一致

- [ ] **Step 5**: Commit `[backtest] T4: _run_one_strategy 拆 dispatch（cycle-calmar 路径剥离零改动）`

---

## Task 5: `_run_equal_weight` 实现

**Files:**
- Modify: `scripts/backtest/run.py`（添加 `_run_equal_weight` 函数体，替换 Task 4 的 stub）

**详情指向:** design.html §5 完整伪代码（含函数体 + 关键复用点 callout）

- [ ] **Step 1**: Read design.html §5 拿 `_run_equal_weight` 完整代码
- [ ] **Step 2**: run.py 实现 `_run_equal_weight(strategy, registry, windows)`，按 §5 代码块逐行实施。注意：
  - cycles 长度必须 = 1，否则抛 ValueError
  - 调 `engine.run_with_strategy(data, strategy, ...)`，cycles=("M",) 让 engine 内只跑 M cycle（已有行为）
  - **不**调 compute_allocation（不 rewrite r.strategy_name）
  - 调用 Task 6 的 `run_portfolio_window_equal_weight`（先 stub 暂返 None，Task 6 实现完后联调）

- [ ] **Step 3**: 跑现有 pytest 套件零退化：

  ```bash
  pytest scripts/backtest/test_*.py -v --tb=short 2>&1 | tail -3
  ```

  Expected: `44 passed`（cycle-calmar 路径不动，equal-weight 等 Task 6+7 联调）

- [ ] **Step 4**: Commit `[backtest] T5: 实现 _run_equal_weight（单 cycle + 等权聚合）`

---

## Task 6: `window_engine.run_portfolio_window_equal_weight` 实现

**Files:**
- Modify: `scripts/backtest/window_engine.py`（追加 `run_portfolio_window_equal_weight` 函数 + 复用 `IndexContribution` / `WindowResult`）

**详情指向:** design.html §5 末段（"新增 run_portfolio_window_equal_weight" 段落）+ 现有 `run_portfolio_window` 函数作为参照

- [ ] **Step 1**: Read design.html §5 末段确认接口（同 `run_portfolio_window` 的入参 / 返回 `WindowResult`，但不调 `compute_allocation`，每指数 INDEX_CAPITAL 起步）
- [ ] **Step 2**: window_engine.py 加 `run_portfolio_window_equal_weight(index_data, full_results, window_years, as_of) -> WindowResult` 函数。参考现有 `run_portfolio_window` 结构，但跳过 Calmar 权重切分——每指数直接用 `BucketGroup(name=cycle, buckets=[Bucket(timeframe=cycle, capital=INDEX_CAPITAL)])` 在窗口内重跑 `run_strategy`，组合层等权聚合
- [ ] **Step 3**: 联调 Task 5 + Task 6——run.py 的 `_run_equal_weight` 调用此函数。先用 v9-baseline (cycles=("D","W","M")) 试跑会失败（cycles 长度 ≠ 1），但用 stub 验证 dispatch 路径正常进入 equal-weight 分支（**预期失败信号**：抛 ValueError "equal-weight requires single cycle"）：

  ```bash
  python -c "
  from scripts.backtest.strategy import Strategy, get
  from scripts.backtest.strategy.builtin import MA20CrossDecider
  s = Strategy(name='test-eq', decider=MA20CrossDecider(), filters=(), cycles=('M',), aggregator='equal-weight')
  # 手工 register 测试：略，用现有 v9-baseline 不行因为它是 cycle-calmar
  print('equal-weight stub OK，等 Task 7 注册 faber-gtaa 后端到端跑')
  "
  ```

  Expected: 至少 import 不报错

- [ ] **Step 4**: Commit `[backtest] T6: window_engine 新增 run_portfolio_window_equal_weight（不用 Calmar，每指数等权 INDEX_CAPITAL 起步）`

---

## Task 7: `FaberMonthlyMaDecider` 实现 + 注册 `faber-gtaa`

**Files:**
- Modify: `scripts/backtest/strategy/builtin.py`（追加 `FaberMonthlyMaDecider` 类 + `@register("faber-gtaa")` 工厂）
- Modify: `scripts/backtest/test_strategy_builtin.py`（追加 7 个测试，case 见 design.html §6.4 表）

**详情指向:** design.html §6.1（Decider 完整代码）+ §6.2（注册）+ §6.4 测试 case 表

- [ ] **Step 1**: 写 7 个失败测试（Read design.html §6.4 表抄 case 名 + 输入 + 期望，参照 `TestMA20CrossDecider` 风格）：

  ```bash
  pytest scripts/backtest/test_strategy_builtin.py::TestFaberMonthlyMaDecider -v 2>&1 | tail -3
  ```

  Expected: ImportError 或 7 failed（Faber 类未实现）

- [ ] **Step 2**: Read design.html §6.1 拿 `FaberMonthlyMaDecider` 完整代码，追加到 builtin.py 末尾
- [ ] **Step 3**: Read design.html §6.2 拿注册代码，加 `@register("faber-gtaa")` 工厂到 builtin.py 末尾
- [ ] **Step 4**: 跑测试确认通过：

  ```bash
  pytest scripts/backtest/test_strategy_builtin.py -v --tb=short 2>&1 | tail -5
  ```

  Expected: `30 passed`（23 原 + 7 新）

- [ ] **Step 5**: 端到端联调（Task 5+6+7 一起验证 equal-weight 路径）：

  ```bash
  python -m scripts.backtest.run --list 2>&1 | grep faber
  python -m scripts.backtest.run --strategy faber-gtaa --universe combined-27 --windows 3 2>&1 | tail -5
  ```

  Expected: `--list` 含 `faber-gtaa` 一行；单策略跑通输出 `3 年 总 CAGR ...% / MDD ...%`

- [ ] **Step 6**: Commit `[backtest] T7: 实现 FaberMonthlyMaDecider + 注册 faber-gtaa（Faber 2007 月线 MA10 趋势）`

---

## Task 8: `compare_report` N 策略支持改造

**Files:**
- Modify: `scripts/backtest/compare_report.py`（改 `render_portfolio_table` / `render_per_index_diff_table` / `write_compare_report` 接受 N≥2 策略）
- Modify: `scripts/backtest/test_compare_report.py`（保留现有 N=2 测试 + 加 1 个 N=3 测试）
- Modify: `scripts/backtest/run.py`（`--compare` 接受逗号分隔任意多策略名，第一个作 base）

**详情指向:** design.html §7（render 函数新签名 + 报告输出格式 + CLI 改动）

- [ ] **Step 1**: Read design.html §7 拿三个函数新签名 + 报告 N=3 示例输出格式
- [ ] **Step 2**: 加一个 N=3 失败测试到 test_compare_report.py：构造 3 个 mock WindowResult，断言输出含 3 策略名 + 2 个 Δ 行：

  ```bash
  pytest scripts/backtest/test_compare_report.py -v --tb=short 2>&1 | tail -3
  ```

  Expected: 4 passed (3 原 + 1 新)，但新测试失败因 render 函数还是 N=2 hard-coded

- [ ] **Step 3**: 改 `render_portfolio_table`：input `Sequence[Tuple[str, list]]` 长度 ≥ 2，第一个作 base，每窗口输出 N 行策略 + (N-1) 行 Δ
- [ ] **Step 4**: 改 `render_per_index_diff_table`：每个非 base 策略一份子表
- [ ] **Step 5**: 改 `write_compare_report`：results_by_strategy ≥ 2 key，第一个 key 作 base
- [ ] **Step 6**: 改 `run.py:main` 的 `--compare` 解析：split 后接受 ≥ 2 个名字（不再是恰好 2），按顺序传给 `write_compare_report`，第一个作 base
- [ ] **Step 7**: 跑测试 + 现有 v9 universe 报告数值不变（validate N=2 路径 backward compat）：

  ```bash
  pytest scripts/backtest/test_compare_report.py -v
  python -m scripts.backtest.run --compare v9-baseline,v9.3-bear --universe v9 --windows 3,5,8,10 2>&1 | tail -10
  ```

  Expected: pytest 4 passed；CLI 跑出报告，组合层数值与 design.html §8.1 第 4 条断言一致

- [ ] **Step 8**: Commit `[backtest] T8: compare_report 改 N≥2 策略支持（第一个作 base，输出 N 策略行 + (N-1) Δ 行）`

---

## Task 9: 回归验证（隔离不变量 5 条断言）

**Files:** 无新增；纯跑命令验证

**详情指向:** design.html §8.1 验收表（5 条断言）

- [ ] **Step 1**: 断言 1——scripts/quant/ 零修改：

  ```bash
  git diff 38c0c7b..HEAD -- scripts/quant/ scripts/main.py docs/
  ```

  Expected: 输出为空

- [ ] **Step 2**: 断言 2——pytest 全过：

  ```bash
  pytest scripts/backtest/test_*.py -v --tb=short 2>&1 | tail -3
  ```

  Expected: 不少于 52 passed（44 原 + 7 Faber Decider + 1 N=3 compare = 52）

- [ ] **Step 3**: 断言 3——v9-baseline on v9 universe 数值不变：

  ```bash
  python -m scripts.backtest.run --strategy v9-baseline --universe v9 --windows 3,5,8,10 2>&1 | tail -6
  ```

  Expected: 3年 15.32%/-12.55%、5年 10.98%/-19.69%、8年 11.51%/-22.12%、10年 9.29%/-22.25% **逐字一致**

- [ ] **Step 4**: 断言 4——v9-baseline + v9.3-bear on v9 universe 报告数值不变：

  ```bash
  python -m scripts.backtest.run --compare v9-baseline,v9.3-bear --universe v9 --windows 3,5,8,10 2>&1 | tail -10
  diff <(grep -E "^\| [0-9]+ 年" agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear.md) <(grep -E "^\| [0-9]+ 年" agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-v9universe.md) | head
  ```

  Expected: diff 仅 markdown 格式差异（如 `**−`、`pp` 等），数值列**逐字一致**

- [ ] **Step 5**: 断言 5——v9-baseline + v9.3-bear on main-online universe 数值不变：

  ```bash
  python -m scripts.backtest.run --compare v9-baseline,v9.3-bear --universe main-online --windows 3,5,8,10 2>&1 | tail -10
  diff <(grep -E "^\| [0-9]+ 年" agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear.md) <(grep -E "^\| [0-9]+ 年" agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-mainonline.md) | head
  ```

  Expected: diff 仅 markdown 格式差异，数值逐字一致

- [ ] **Step 6**: 5 条全过才进 Task 10。任何一条失败 → BLOCKED → 排查回滚。**本 task 不产生 commit**（纯验证）。

  断言全过则 **删除** Step 4/5 跑出的临时 `2026-05-10-compare-v9-baseline-vs-v9.3-bear.md`（裸文件名版本）：

  ```bash
  rm -f agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear.md
  ```

---

## Task 10: 跑 3 策略 compare on combined-27

**Files:** 输出报告到 `agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-faber-gtaa.md`

**详情指向:** design.html §8.2（新功能验收表）

- [ ] **Step 1**: 跑 compare 命令：

  ```bash
  source venv/bin/activate
  time python -m scripts.backtest.run --compare v9-baseline,v9.3-bear,faber-gtaa --universe combined-27 --windows 3,5,8,10 2>&1 | tee /tmp/3way-compare.log | tail -15
  ```

  Expected: 退出码 0；总耗时 ≤ 5 分钟（27 指数 × 3 策略，缓存全有时纯 CPU）；输出含 `加载 27 个指数数据` × 3 + 12 行 `N 年 总 CAGR ...% / MDD ...%`

- [ ] **Step 2**: 检查报告文件生成：

  ```bash
  ls -la agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-faber-gtaa.md
  head -40 agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-faber-gtaa.md
  ```

  Expected: 文件存在；前 40 行含三策略组合层表（baseline / bear / faber 三行 + 2 个 Δ 行 per 窗口 = 5 行 × 4 窗口 = 20 行表数据）

- [ ] **Step 3**: 人工 sanity check：组合层数值合理（CAGR 不为 0 / MaxDD 为负 / 三策略数值有差异）。如 faber 数值与 baseline 完全一样 → 是 bug；如 faber CAGR > 0 且与 baseline 数据有 ≥ 0.5pp 差 → 通过 sanity

- [ ] **Step 4**: 本 task 不 commit 报告（Task 11 加完中文解读后一起 commit）

---

## Task 11: 报告中文解读 + commit

**Files:** Edit `agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-faber-gtaa.md`（追加中文解读章节，不改数值表）

**详情指向:** design.html §10（报告内容 5 项）—— 一句话结论 / 三策略横向对比 / 与 bear 路线对比 / 适合的 universe 子集 / 后续可调方向

- [ ] **Step 1**: 在数值表之前/之后插入 5 个中文解读段落（按 §10 list）。参考 `agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-mainonline.md` 的解读风格（一句话结论 → 数据观察 → 建议）
- [ ] **Step 2**: 关键解读维度：
  - **vs baseline**：faber 是赢还是输？跨 4 窗口的 ΔCAGR 是正/负？
  - **vs bear**：之前 v9.3-bear "加 filter" 路线全输 1.3-3.1pp；这次 "加新策略" 路线效果如何对比？
  - **分指数**：哪些指数 faber 跑赢 baseline？哪些跑输？模式是什么（A 股 vs 港股 vs 美股 vs 商品）？
  - **后续方向**：调 MA10 → MA20？仅在某 universe 子集应用？
- [ ] **Step 3**: Commit 报告：

  ```bash
  git add -f agents/results/2026-05-10-compare-v9-baseline-vs-v9.3-bear-faber-gtaa.md
  git commit -m "[backtest] T11: 产出 v9-baseline vs v9.3-bear vs faber-gtaa 三策略对比报告（含中文解读）"
  ```

---

## Task 12: 范围检查（生产隔离不变量）

**Files:** 无；纯检查 + 决定是否回滚

**详情指向:** design.html §11 关键不变量

- [ ] **Step 1**: 全部 commit 后再次 git diff 排除 scripts/quant/ + scripts/main.py + docs/：

  ```bash
  git diff 38c0c7b..HEAD --name-only | grep -E '^(scripts/quant/|scripts/main\.py|docs/)' || echo "OK: 生产 + 前端干净"
  ```

  Expected: `OK: 生产 + 前端干净`

- [ ] **Step 2**: 跑 quant 现有测试零退化：

  ```bash
  pytest scripts/quant/tests/ --tb=short 2>&1 | tail -3
  ```

  Expected: `179 passed`（与 base SHA `38c0c7b` 时一致）

- [ ] **Step 3**: 跑 backtest 全套零退化：

  ```bash
  pytest scripts/backtest/test_*.py -v --tb=short 2>&1 | tail -3
  ```

  Expected: 不少于 52 passed

- [ ] **Step 4**: 本 task 不 commit。如任何步骤失败 → 排查违反的不变量 → 回滚相关 commit

---

## Plan 完成后

待 12 个 task 全部 PASS 后，给用户**周期 1 完成报告**：

- 列出 commit 序列（11 个 [backtest] commits）
- 每个 task 的关键产出
- 三策略对比报告链接
- 用户审完批准 → 进 C 周期（Donchian 200）

---

## Spec 覆盖度自查（writing-plans skill 要求）

| design.html § | 对应 Task |
|---|---|
| §0 隔离铁律 | Task 9（5 条断言验收） |
| §1 背景与目标 | 不需 task（纯说明） |
| §2 Universe combined-27 | Task 1 |
| §3 aggregator 字段 + dispatch SVG | Task 2（字段）+ Task 4（dispatch） |
| §4 dispatch 代码 | Task 4 |
| §5 equal-weight 流程 | Task 5（_run_equal_weight）+ Task 6（portfolio aggregator） |
| §6.1 FaberMonthlyMaDecider | Task 7 |
| §6.2 注册 faber-gtaa | Task 7（合并） |
| §6.3 required_indicators 协议 + _ensure_indicators | Task 2（协议）+ Task 3（helper） |
| §6.4 测试 case 表 | Task 7 Step 1 |
| §7 报告 N 策略改造 | Task 8 |
| §8.1 隔离断言 5 条 | Task 9 |
| §8.2 新功能验收 4 条 | Task 7 Step 5 + Task 10 |
| §9 测试范围 | Task 9 Step 2 + Task 12 Step 3 |
| §10 报告内容 | Task 11 |
| §11 关键不变量 | Task 12 |
| §12 风险表 | 不需 task（已在 design 文档化） |
| §13 不在范围 | 不需 task |

13 章节全部映射，无遗漏。

## Placeholder 扫描

- 无 TBD / TODO / "implement later"
- 每个 step 有具体命令或 Read 锚点
- "详情指向" 都指 design.html 具体 §
- 验收命令 + Expected 输出齐全

## 类型一致性

- `aggregator: str = "cycle-calmar"` 跨 Task 2 / 4 / 5 一致
- `required_indicators: Tuple[Tuple[str, str, int], ...]` 跨 Task 2 / 3 / 7 一致
- `_run_equal_weight` / `run_portfolio_window_equal_weight` / `FaberMonthlyMaDecider` 函数/类名跨 task 一致
- `faber-gtaa` 策略名跨 Task 7 / 10 / 11 一致

## 双件结构守约

- plan.md 无任何 Python 代码片段（除 Bash 验收命令）
- 每个 task 都用 "Read design.html § X.X" 而非 "implement the following" + 内嵌代码
- 第一行有 `> Design: ./<topic>-design.html` 互链
- design.html `<head>` 已含 `<meta name="plan" content="./<topic>.md">` 反向链接
