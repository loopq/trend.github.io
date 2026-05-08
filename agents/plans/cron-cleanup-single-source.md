# Quant 定时器单路化清理 Plan

> **状态**：待执行（v3，已吸收 Codex Round 1+2 review，consensus MOSTLY_GOOD）
> **作者**：用户 + Claude（Linus 模式）
> **日期**：2026-04-27 19:00 SGT；v2 修订 20:30 SGT；v3 修订 21:00 SGT
> **关联事故**：[`incident-2026-04-27-signal-failure.md`](incident-2026-04-27-signal-failure.md)
> **review 记录**：[`reviews/cron-cleanup-single-source-review.md`](reviews/cron-cleanup-single-source-review.md)
> **deadline**：2026-04-28 SGT 08:00 之前合并到 main（与 Phase 1 同 deadline）

---

## 一、背景

### 1.1 触发原因

04-27 18:37 push Phase 1 之后，观察 GitHub Actions 历史发现 3 个意外现象：

| Run | 时间 SGT | 触发源 | 行为 |
|---|---|---|---|
| Quant #10 ❌ 8s | 12:34 PM | quant.yml schedule | mode 推断 fallback `HOUR_UTC=04` 不匹配 → exit 1 |
| Quant #12 ❌ 8s | 05:10 PM | quant.yml schedule | 同上，`HOUR_UTC=09` 不匹配 → exit 1 |
| Heartbeat #1 ❌ 24s | 05:12 PM | quant-heartbeat.yml schedule | 哨兵预期行为：今日 signal 未产出 → 告警 |

根因有二：

1. **GitHub schedule 时区是 UTC + 抖动严重**（实测延迟 2–3.5 小时），导致原计划 `06:50 UTC` 的备路实际跑在 `09:10 UTC`，原计划 `01:05 UTC` 的备路跑在 `04:34 UTC`
2. quant.yml 的 mode 解析 fallback 写死 `HOUR_UTC=06/01`，schedule 延迟超过 ~30 分钟就推不出 mode → `::error::无法确定 mode` → exit 1

### 1.2 Linus 三问

| 问题 | 回答 |
|---|---|
| 这是个真问题还是臆想出来的？ | **真问题**。GitHub schedule 既不准时也不可靠；备路把简单数据流变成「主路+备路」双源。 |
| 有更简单的方法吗？ | **有**。彻底删除 GitHub schedule 备路 + 哨兵；定时唯一来源 = cron-job.org 外部 cron；用户主动检查替代哨兵告警。 |
| 会破坏什么吗？ | **会破坏冗余容灾能力**——这是本 plan 的核心代价，由用户显式接受。具体残余风险见 §四.3。删除 schedule 备路后，cron-job.org 整体不可用就是单点；删除哨兵后，14:55 自动告警变为人工自检。除此之外的"行为不变"风险见 §四.1。 |

### 1.3 用户原话

> "我从来没有要求用 github 定时器，那个定时任务不准，后面都是统一用的 cronjob 外部定时"
>
> "去除这个所谓的哨兵模式，错了我自己会检查，不需要哨兵"
>
> "其实早上不需要再单独起一个 morning-rec action，直接复用就够了，触发时间都是一致的"

---

## 二、最终架构

### 2.1 数据流（消除所有特殊情况）

```
cron-job.org 只配 2 条任务：
   ┌───────────────────────────────────────────────┐
   │ ① morning      08:00 Mon-Sat (Asia/Shanghai)  │ → repository_dispatch:morning
   │ ② signal       14:48 Mon-Fri (Asia/Shanghai)  │ → repository_dispatch:quant-trigger
   └───────────────────────────────────────────────┘
            │                                │
            ▼                                ▼
   ┌──────────────────────┐         ┌──────────────────────┐
   │ update.yml (morning) │         │ quant.yml (signal)   │
   │  ├─ main.py morning  │         │  ├─ 前置检查 today.done│
   │  ├─ deploy 主站       │         │  ├─ run_signal       │
   │  └─ morning-reconcile│ 写 done │  └─ push + deploy    │
   │     step (顺带跑)     │ ◄───────┤                      │
   └──────────────────────┘         └──────────────────────┘
```

**核心简化**：morning-reconcile 不再有独立 cron 入口，完全嵌入 update.yml morning step。所谓"morning-reconcile"只是 update.yml 的一个内部子步骤名，对外不暴露。

### 2.2 触发矩阵

| 时间 SGT | 触发源 | workflow | mode | 行为 |
|---|---|---|---|---|
| 08:00 工作日+周六 | cron-job.org `morning` | update.yml | — | 主站数据更新 + 部署 + morning-reconcile（顺带）+ 写 today.done |
| 14:48 工作日 | cron-job.org `quant-trigger`（mode=signal）| quant.yml | signal | 前置检查 today.done → 生成信号 → push + 部署 quant 子树 |
| 任何时刻 | 用户手动 | quant.yml / update.yml | 任意 | `workflow_dispatch` 应急通道（保留）|

### 2.3 删除清单

| 删除项 | 原因 |
|---|---|
| quant.yml `schedule:` 块（2 条 cron）| GitHub schedule 不准；备路本身就是冗余特殊情况 |
| quant.yml mode 解析里 HOUR_UTC fallback | schedule 块删了，这段就是不可达死代码 |
| quant-heartbeat.yml 整个文件 | 用户明确不要哨兵；删 schedule 后哨兵 schedule 也不能用，自洽 |
| cron-job.org 上的"morning-reconcile" 独立任务（如已配）| 触发时机与 morning 完全一致，并入 morning step 即可 |

---

## 三、改动清单（精确）

### 3.1 `.github/workflows/quant.yml`

**删除 line 24-27**（`schedule:` 整块）：

```yaml
  schedule:
    # GitHub schedule 时区固定 UTC；备路（主路 cron-job.org 失效时兜底）
    - cron: '50 6 * * 1-5'    # 14:50 SGT = 06:50 UTC，备 signal mode
    - cron: '5 1 * * 1-5'     # 09:05 SGT = 01:05 UTC，备 morning-reconcile mode
```

**删除 line 49-54**（mode 解析里的 schedule fallback）：

```bash
          if [ -z "$MODE" ] && [ "${{ github.event_name }}" = "schedule" ]; then
            # 根据 cron 表达式推断
            HOUR_UTC=$(date -u +%H)
            if [ "$HOUR_UTC" = "06" ]; then MODE="signal"; fi
            if [ "$HOUR_UTC" = "01" ]; then MODE="morning-reconcile"; fi
          fi
```

**修订 line 10 注释**：

```yaml
- signal              # 14:48 盘中信号生成（cron-job.org 主路 + GitHub schedule 备路）
```
改成
```yaml
- signal              # 14:48 盘中信号生成（cron-job.org 触发）
```

**修订 line 44 注释**：

```bash
# mode 来源优先级：workflow_dispatch input > repository_dispatch payload > schedule 推断
```
改成
```bash
# mode 来源：workflow_dispatch input 或 repository_dispatch payload（cron-job.org）
```

### 3.2 `.github/workflows/quant-heartbeat.yml`

**整个文件删除**（`git rm`）。

### 3.3 `scripts/quant/check_readiness.py`

**line 80**（`must_exist` 列表移除哨兵 + 新增 `must_not_exist` 反向断言）：

```python
must_exist = ["quant.yml", "quant-heartbeat.yml", "quant-test.yml", "update.yml"]
```
改成
```python
must_exist = ["quant.yml", "quant-test.yml", "update.yml"]

# 单路化反向断言：以下文件必须不存在（防误恢复）
must_not_exist = ["quant-heartbeat.yml"]
for f in must_not_exist:
    out.append(
        Check(f"workflow {f} 已删").passed() if not (wf_dir / f).exists()
        else Check(f"workflow {f} 已删").failed(f"{f} 仍存在，违反单路化")
    )
```

**line 104**（quant.yml keywords 移除 `schedule:` + 新增反向断言）：

```python
for keyword in ["mock-test", "morning-reconcile", "deploy", "init", "concurrency", "schedule:", "peaceiris"]:
```
改成
```python
for keyword in ["mock-test", "morning-reconcile", "deploy", "init", "concurrency", "peaceiris"]:
    out.append(...)  # 保持原 if/else 结构

# 反向断言：quant.yml 不得再出现 schedule 块（防 GitHub schedule 备路误回归）
out.append(
    Check("quant.yml 不含 schedule:").passed() if "schedule:" not in quant_yml
    else Check("quant.yml 不含 schedule:").failed("发现残留 schedule 块，违反单路化")
)
```

### 3.4 文档最小同步（v2 新增 — Codex Round 1 Issue 9）

延后做的代价是 runbook 与代码不一致期间运维误判。本 plan 必须在同 commit 内做最小同步：

**`docs/agents/quant/deployment-plan.md`** 在文件顶部 frontmatter 之后立即插入（不改正文，下次单独 commit 重写正文）：

```markdown
> ⚠️ **本文档部分内容已废弃（2026-04-27）**：
> §一.3「备路：GitHub native schedule」「Heartbeat 哨兵」「PAT 双 token」涉及 GitHub schedule 备路 + heartbeat 哨兵的章节已不适用。
> 当前架构请参见 [`cron-cleanup-single-source.md`](cron-cleanup-single-source.md)。
> 本文正文将在下次 commit 单独重写。
```

**`docs/agents/quant/mvp-plan.md`** 在文件顶部插入相同的废弃声明（指向同一份 cleanup plan）。

**`docs/agents/quant/incident-2026-04-27-signal-failure.md`** 不动（事故归档，不主动修订历史文档），但在 §决策 #6 / §6.3.3 后追加一行注解：

```markdown
> 注：04-27 晚上观察到 GitHub schedule 备路非预期触发，已通过 cron-cleanup-single-source.md 清理；上述"备路"描述仅作历史参考。
```

### 3.5 保留不动

| 文件 | 保留理由 |
|---|---|
| `.github/workflows/keepalive.yml` | 45 天空 commit 防 GitHub 60 天禁用 Actions，与业务定时无关 |
| `.github/workflows/quant-test.yml` | PR CI 跑 pytest，不是定时业务 |
| `.github/workflows/update.yml` | 已确认无 schedule，仅 `workflow_dispatch` + `repository_dispatch:morning`，morning-reconcile step 已就位 |

---

## 四、影响分析

### 4.1 破坏性评估（v2 修订 — Codex Round 1 Issue 12）

> 「风险」一列改为残余风险量化，不再写"0"——删备路 + 删哨兵本身就是用户接受的容灾能力降级。

| 受影响位置 | 改前 | 改后 | 残余风险 |
|---|---|---|---|
| quant.yml schedule 备路 | 14:50 / 09:05 SGT 兜底（虽延迟严重）| 不存在 | **中**：cron-job.org 主路单点，整体不可用时无自动兜底（详见 §4.3） |
| quant.yml mode 解析 | 含死代码 fallback | 仅 dispatch 两源 | 0（删的是不可达分支） |
| quant-heartbeat.yml | 14:55 SGT 哨兵告警 | 不存在 | **中**：14:55 自动告警变人工 SOP（详见 §4.3）|
| update.yml morning step | 不变 | 不变 | **低**：周一 / 节假日次日 should_deploy=false 时 morning-reconcile 不跑 → today.done 缺失 → 14:48 误报飞书 warning（详见 §4.3 残余风险 R4）|
| `data/quant/.heartbeat` 文件 | 之前由哨兵写 | 不再写 | 0（grep 全代码仅 deployment-plan.md 文档提到，无生产代码引用）|
| pytest 86 + 6 用例 | PASS | PASS | 0（已 grep 验证 `scripts/quant/tests/` 不含 schedule/heartbeat 引用）|
| check_readiness.py 31 PASS | PASS | 删 2 个 + 加 2 个反向断言后仍 31 PASS | 0（覆盖范围对齐）|

### 4.2 行为变化（预期改进）

| 行为 | 改前 | 改后 |
|---|---|---|
| schedule 触发的"无法确定 mode" 红 | 每天发生 1-2 次 | 不再发生 |
| 哨兵 14:55 误告警（事故日已发） | 信号炸了 → 哨兵叫 | 用户自检（每日 14:55 看飞书 + Actions） |
| morning-reconcile 触发路径数 | 3 条（cron-job.org morning 钩子 + GitHub schedule 09:05 备路 + 用户手动）| **1 条**（cron-job.org morning 钩子 + 手动应急）|
| cron-job.org 任务数 | 2-3（morning + signal + 可能的独立 morning-reconcile）| **2**（morning + signal）|
| Actions 历史可读性 | 混杂 schedule/scheduled/dispatch | 仅 `repository_dispatch` + `workflow_dispatch` |

### 4.3 残余风险清单（v2 重写 — Codex Round 1 Issue 1/2/3/4）

| ID | 风险 | 触发条件 | 用户应对（人工 SOP）| 是否本 plan 修复 |
|---|---|---|---|---|
| **R1** | cron-job.org 整体故障 → 无任何信号触发 | 14:55 SGT 飞书无消息 + Actions 无新 run | 手动 `gh workflow run quant.yml -f mode=signal -f mock_now=...`；启用 cron-job.org 自带"任务失败邮件通知" | 不修（用户接受单点）。**v3 警示**：若 Phase 2.6（启用 cron-job 失败邮件）尚未完成，则上线到 Phase 2.6 完成期间 R1/R3 处于**高风险运行态**——无任何自动告警通道，仅靠用户每日 14:55 人工自检 |
| **R2** | morning-reconcile 失败但 update.yml 标绿 | step 内 `continue-on-error: true` 故障被吞 | 14:48 signal 前置检查会发飞书 warning（**best-effort**：依赖 `curl ... \|\| true` 不吞掉 webhook 失败 + signal 当日确实触发）；用户每日 14:55 自检 Actions | 不修（保持主站故障隔离的核心设计） |
| **R3** | 信号系统全链路告警依赖飞书 webhook 单通道 | webhook 失效（PAT 过期 / 飞书机器人关闭 / 网络） | 启用 cron-job.org 任务失败邮件 + GitHub Actions 默认失败邮件作第二通道 | 不修（外部资源用户管理）。**v3 警示**：同 R1，Phase 2.6 完成前为高风险运行态 |
| **R4** | 周一 / 节假日次日 today.done 缺失 → 14:48 飞书 warning（误报但不阻塞）| `scripts/main.py` should_deploy=false（昨天非交易日）→ morning-reconcile step 跳过 → 当日无 today.done | 收到 warning 后忽略；信号正常生成不受影响 | **不修**，列入 [`incident-2026-04-27-signal-failure.md`](incident-2026-04-27-signal-failure.md) **Phase 2 必修**：morning-reconcile 与 signal 前置检查统一基于交易日历（cache 链路实现时一并 calendar 一致化）|
| **R5** | 节假日边界（如五一）跨节场景 | 长假后第一交易日 prev_workday 计算 + done 文件命名 | 在 incident plan §6.5 已有五一实测用例 | **不修**，同 R4，列入 incident Phase 2 |

**关键认知**：R1/R2/R3 是用户**显式接受**的设计权衡（删备路 + 删哨兵 + 单 webhook）；R4/R5 是**已知缺陷**留待 Phase 2，不在本 plan 范围内但必须列入清单防被忽视。

---

## 五、验证步骤

### 5.1 改动后本地验证（push 前）

```bash
cd /Users/loopq/dev/git/loopq/trend.github.io
source venv/bin/activate

# 1) yml 语法检查（Python yaml lib）
python -c "import yaml; yaml.safe_load(open('.github/workflows/quant.yml'))" && echo OK
python -c "import yaml; yaml.safe_load(open('.github/workflows/update.yml'))" && echo OK

# 2) 确认 quant-heartbeat.yml 已删
test ! -f .github/workflows/quant-heartbeat.yml && echo "OK 已删"

# 3) 反向断言：测试套件 / yml / 业务脚本不再含 schedule/heartbeat 残留（v2 新增 — Issue 11；v3 改用 if 显式结构 — Issue B）
#    期望：所有断言均输出 OK
echo "--- 反向断言 ---"
if grep -rn "schedule\|heartbeat\|quant-heartbeat" scripts/quant/tests/ ; then echo "FAIL pytest 套件仍含残留"; else echo "OK pytest 套件干净"; fi
if grep -n "schedule:\|HOUR_UTC" .github/workflows/quant.yml ; then echo "FAIL quant.yml 仍含残留"; else echo "OK quant.yml 干净"; fi
if test -f .github/workflows/quant-heartbeat.yml ; then echo "FAIL heartbeat workflow 仍存在"; else echo "OK heartbeat workflow 已删"; fi

# 4) check_readiness 全 PASS（应保持 31 PASS / 0 FAIL）
python -m scripts.quant.check_readiness

# 5) pytest 全 PASS（86 + 6 + Phase 1 新增 3）
pytest scripts/quant/tests/ -v
```

### 5.2 push 后线上验证（v2 修订 — Codex Round 1 Issue 7、Issue 8）

> 命令均改为可直接 copy/paste，日期动态注入。

```bash
# 公共：本机时区取今日（用于断言期望文件名）
TODAY=$(TZ=Asia/Shanghai date +%F)
echo "TODAY=$TODAY"

# 6) 手动 dispatch mock-test（验证主链路未被破坏）
gh workflow run quant.yml -f mode=mock-test
sleep 5
RUN_ID=$(gh run list --workflow=quant.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch "$RUN_ID"
# 期望：5 道硬门 PASS、零 diff

# 7) 手动 dispatch morning-reconcile（验证 yml 语义正确）
gh workflow run quant.yml -f mode=morning-reconcile
sleep 5
RUN_ID=$(gh run list --workflow=quant.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch "$RUN_ID"
# 期望：写 morning-reconcile-${TODAY}.done、push 成功

# 8) 手动 dispatch update.yml morning --force（incident plan §6.3.1 步骤 4）
gh workflow run update.yml -f mode=morning -f force=true
sleep 5
RUN_ID=$(gh run list --workflow=update.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch "$RUN_ID"
# 期望：主站部署成功 + quant morning-reconcile step 跑通

# 9) 拉最新 main 验证 done 文件落地
git fetch origin main
git log --oneline origin/main -5
git show "origin/main:docs/data/quant/.runs/morning-reconcile-${TODAY}.done" | head -3
# 期望：文件存在
```

### 5.3 04-28 自然链路观察（v2 修订 — Issue 8 动态日期）

```bash
TOMORROW=$(TZ=Asia/Shanghai date -v+1d +%F)   # mac
# 或 TOMORROW=$(TZ=Asia/Shanghai date -d "+1 day" +%F)  # linux
```

| 时间 SGT | 检查点 |
|---|---|
| 08:00 后 | Actions 出现 `Update Trend Data` repository_dispatch 绿；main 上有 `morning-reconcile-${TOMORROW}.done` |
| 08:10 前 | 无任何 schedule 触发的 run（所有 run actor 应该是 loopq 或 cron-job.org PAT 用户） |
| 14:48 后 | 飞书收到 signal 消息；无前置检查 warning；`signals/${TOMORROW}.json` 落地 |

---

## 六、回滚剧本（v2 修订 — Codex Round 1 Issue 10；v3 修 — Round 2 Issue 7/10 残留：消除 `<id>` 占位符 + 加第二通道验收）

> 取 RUN_ID 通用片段：

```bash
get_latest_run() {
  local wf=$1
  gh run list --workflow="$wf" --limit 1 --json databaseId --jq '.[0].databaseId'
}
```

| 故障场景 | 回滚步骤 | 回滚后验收命令（直接可执行）|
|---|---|---|
| 04-28 早 8 点 cron-job.org morning 没触发 | `gh workflow run update.yml -f mode=morning -f force=true` | `RUN_ID=$(get_latest_run update.yml); gh run watch "$RUN_ID"`；`git fetch origin main && git log origin/main -1` 看 morning-reconcile commit |
| 14:48 cron-job.org signal 没触发 | `gh workflow run quant.yml -f mode=signal -f mock_now=$(TZ=Asia/Shanghai date -Iseconds)` | `RUN_ID=$(get_latest_run quant.yml); gh run watch "$RUN_ID"` + 飞书收到信号 |
| 想恢复 GitHub schedule 备路 + 哨兵 | `git revert <this-commit>`（`git rm` 通过 revert 自动恢复 quant-heartbeat.yml）| revert 后顺跑两条：① `gh workflow run quant.yml -f mode=mock-test; sleep 5; RUN_ID=$(get_latest_run quant.yml); gh run watch "$RUN_ID"`（5 道硬门 PASS）② `gh workflow run quant.yml -f mode=signal -f mock_now=$(TZ=Asia/Shanghai date -Iseconds); sleep 5; RUN_ID=$(get_latest_run quant.yml); gh run watch "$RUN_ID"`（手动验签）|
| 单点：cron-job.org 整体不可用 | 用户手动 dispatch 当日缺失的 workflow（同上）| 同上 + **第二通道验收**：cron-job.org 后台 → 任务详情 → "Notification settings" 显示已勾选 "Notify on failure (email)"；GitHub Actions 默认失败邮件已到达 |

> **关于"外部配置回滚"**：本 plan 不要求改 cron-job.org（仅建议清理多余的 morning-reconcile 任务，可选不做），所以代码回滚后 cron-job.org 端无须同步动作。如果用户**自行删过** cron-job.org 任务，需要恢复时按 [`deployment-plan.md`](deployment-plan.md) §一.3 配置参数表重新创建。

---

## 七、执行清单

**Phase 1（代码 + 文档最小同步，单 commit）**：

- [ ] 1.1 改 `.github/workflows/quant.yml`：删 schedule 块 + 删 mode fallback + 改 2 处注释
- [ ] 1.2 `git rm .github/workflows/quant-heartbeat.yml`
- [ ] 1.3 改 `scripts/quant/check_readiness.py:80,104`：移除 quant-heartbeat.yml + schedule: 关键字 + **新增 `must_not_exist` 反向断言** + **新增 `quant.yml 不含 schedule:` 反向断言**
- [ ] 1.4 **加文档废弃声明**（v2 新增 — Issue 9）：deployment-plan.md / mvp-plan.md 顶部插入指向本 cleanup plan 的废弃 banner；incident-2026-04-27-signal-failure.md §决策 #6 / §6.3.3 加历史注解
- [ ] 1.5 本地跑反向 grep（§5.1 步骤 3）确认 schedule/heartbeat 全代码无残留
- [ ] 1.6 本地跑 pytest 全 PASS
- [ ] 1.7 本地跑 check_readiness 全 PASS（应仍 31 PASS / 0 FAIL，覆盖范围与单路化对齐）
- [ ] 1.8 用户 review diff 后 push 到 main（用户自推，agent 不推）

**Phase 2（cron-job.org 端清理，cron-job.org 网站登录恢复后立即做 — v3 警示：2.6 是 R1/R3 主要缓解，越晚做高风险运行态越长）**：

- [ ] 2.1 cron-job.org 恢复后登录后台
- [ ] 2.2 确认现有 morning 任务（08:00 SGT）still active + PAT not expired
- [ ] 2.3 确认现有 signal 任务（14:48 SGT）still active + PAT not expired
- [ ] 2.4 如果之前临时新建过 morning-reconcile 任务 → 删除
- [ ] 2.5 「Test run」一次 morning + 一次 signal 验证 dispatch 链路
- [ ] 2.6 **🚨 启用 cron-job.org 任务失败邮件通知**作第二告警通道（**Round 2 Issue A**：唯一覆盖 R1/R3 的自动机制；cron-job.org 恢复登录后**第一时间**做，不要再延后）
- [ ] 2.7 验证 GitHub Actions 默认失败邮件能到达用户邮箱（GitHub → Settings → Notifications → Actions: Email = checked）

**Phase 3（线上验证，紧贴 deadline）**：

- [ ] 3.1 手动 dispatch quant.yml mode=mock-test 验证硬门
- [ ] 3.2 手动 dispatch quant.yml mode=morning-reconcile 验证 done 文件
- [ ] 3.3 手动 dispatch update.yml mode=morning --force 验证主链路
- [ ] 3.4 04-28 08:00 后看 Actions 自然链路绿
- [ ] 3.5 04-28 14:48 后看飞书 + signals/2026-04-28.json 落地

---

## 八、未在本次范围内（YAGNI）

| 项 | 暂不做的理由 |
|---|---|
| deployment-plan.md / mvp-plan.md 正文重写 | 顶部加废弃 banner + 指向本 cleanup plan 即可避免 runbook 冲突，正文重写工作量大下次专门 commit；本次仅做最小同步（§3.4）|
| update.yml 内 morning-reconcile step 改 `continue-on-error: false` | 主站部署不能因 quant 子系统挂掉而停发，这是核心设计 |
| 加新的"软告警"机制替代哨兵 | 用户明确选择「自己检查」，不再加；用 cron-job.org 任务失败邮件 + GitHub Actions 默认失败邮件作 free-tier 第二通道（Phase 2.6）|
| 修复周一 / 节假日次日 today.done 误报（R4/R5）| 列入 incident plan Phase 2，与 cache 链路 calendar 一致化一同处理；本 plan 仅承认其为残余风险 |
| Phase 2 cache 链路实现 | 独立后续阶段，与本 plan 无关 |

---

## 九、与 incident plan 的关系

| 维度 | incident-2026-04-27-signal-failure | 本 plan |
|---|---|---|
| 触发 | 04-27 14:48 signal 实际失败 | Phase 1 push 后观察到的 schedule/heartbeat 误触发 |
| 范围 | 6 个根因修复（git config / concurrency / push retry / 前置检查 / writer / done 路径）| 单一主题：删 GitHub schedule + 哨兵 + 文档最小同步 + 反向断言 |
| Phase | Phase 1 (已合并 82bed93) + Phase 2 (cache 链路 + calendar 一致化，待开始) | 独立 Phase（可与 incident Phase 2 并行）|
| 残余风险归属 | R4/R5（calendar 一致化）| R1/R2/R3（用户接受的容灾权衡）|
| Deadline | 04-28 SGT 08:00（共享）| 04-28 SGT 08:00（共享）|

本 plan 与 incident Phase 2（cache 链路）**无技术依赖**，可独立合并。但同享 04-28 deadline——本 plan 改动量小，建议**优先合并本 plan**，再做 incident Phase 2（届时 R4/R5 也一并解决）。

---

## 十、修订日志

### v3（Codex Round 2 review 吸收，2026-04-27 21:00 SGT）

| Round 2 Issue | 严重度 | 处理 | 落点 |
|---|---|---|---|
| A 第二通道告警放在 Phase 2 可延后 | Medium | **不强制前移**（cron-job.org 现登录不可用），但加显式高风险窗口警示 + Phase 2.6 标 🚨 优先 | §4.3 R1/R3 v3 警示行、§七 Phase 2 标题 + 2.6 |
| B `! grep` 在交互式 zsh 不稳 | Low | §5.1 步骤 3 改 if/else 显式结构 | §5.1 |
| 7/10 残留 `<id>` 占位符 | — | §六 加 `get_latest_run` helper + 全部命令改可执行；新增 cron-job 故障的"第二通道验收" | §六 |

### v2（Codex Round 1 review 吸收，2026-04-27 20:30 SGT）

| Issue | 严重度 | 处理 | 具体落点 |
|---|---|---|---|
| 1 today.done 与 update 门控冲突 | Critical | **降级为残余风险** R4，列入 incident Phase 2 必修 | §4.3 R4 |
| 2 节假日边界 | High | 同 1，残余风险 R5 | §4.3 R5 |
| 3 cron-job.org 故障 ≠ 软告警 | High | 措辞修正：明确为人工 SOP；启用 cron 任务失败邮件作第二通道 | §4.3 R1、§七 Phase 2.6 |
| 4 morning-reconcile 失败可见性 | High | 措辞降级为 best-effort | §4.3 R2 |
| 5 删 schedule 关键字未补反向断言 | Medium | check_readiness 加反向断言 | §3.3 |
| 6 删 heartbeat 必检未补 must_not_exist | Medium | check_readiness 加 must_not_exist | §3.3 |
| 7 `gh run watch <run-id>` 占位符 | Medium | 改为 gh run list 取 ID + watch 两行 | §5.2 |
| 8 写死 04-27 日期 | Low | 改 ${TODAY} / ${TOMORROW} 动态 | §5.2、§5.3 |
| 9 文档延后同步会冲突 | High | 提升到 Phase 1 必做（最小同步：废弃 banner）| §3.4、§七 1.4 |
| 10 回滚剧本不完整 | Medium | 加回滚验收命令；澄清外部配置无须同步 | §六 |
| 11 pytest 不涉及应给可复验命令 | Suggestion | §5.1 加反向 grep | §5.1 |
| 12 Linus 三问与风险表自相矛盾 | High | 重写第 3 问回答；§4.1 风险列改为残余风险量化 | §1.2、§4.1 |

**未采纳**：无（12 条全部接受，区别仅在 Issue 1/2 降级为残余风险列入 incident Phase 2 而非本 plan 内修复）。
