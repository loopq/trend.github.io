# 量化信号系统 — 部署上线 plan

> 版本：v2.1.1
> 起草日期：2026-04-25
> 最后修订：2026-04-26（Round 2 review MOSTLY_GOOD 8.3/10 后微调：mock-test 凭据双保险 / 动态 concurrency / 显式 run 标记）
> 适用范围：**首次上线** + **后续运维 / 故障处理 / 本地开发与线上数据隔离**
> 前置：`docs/agents/quant/mvp-plan.md` v1.5 已实施（86 pytest + 10 selenium 全过）

## 重大设计调整（v2.0 vs v1.0）

| 项 | v1.0（已废弃）| v2.0（当前）|
|---|---|---|
| Workflow 数量 | 3 个独立 yml（signal/cache/close-confirm/test）| **2 个**：`quant.yml` 多 mode 主控 + `quant-test.yml` PR 测试不变 |
| cron-job.org 任务数 | 3 个（09:00/14:48/15:30）| **1 个**（仅 14:48）+ GitHub schedule 二级兜底 + heartbeat 监控 |
| 09:00 reconcile + 15:30 close-confirm | 独立 cron | 合并成 `morning-reconcile` mode（独立调度，可挂 update.yml 钩子但有自身兜底）|
| close-confirm 时机 | 当日 15:30（数据可能未稳定）| **次日 09:00**（用昨日真实收盘价，100% 稳定）|
| gh-pages 同步 | quant workflow 末尾自动 peaceiris deploy | **改为显式 `deploy` mode**，与 commit 解耦，加 concurrency group 防并发 |
| Mock 测试模式 | 无 | 新增 `mock-test` mode，QUANT_DATA_ROOT=/tmp/... 隔离 + 末尾 `git status` 断言 + 禁 push/deploy/webhook 硬门 |
| Writer 防 lost-update | 简单 retry（有覆盖丢失风险） | **mergeFn 回调机制 + operation_id 幂等键 + schema 合同**：retry 时拉最新 → 校验 → merge → 重试 |
| 与 v1.5 关系 | N/A | 见下方「v1.5 → v2.0 兼容矩阵」 |

## v1.5 → v2.0 兼容矩阵（review M-12 修订）

`mvp-plan.md v1.5` 已实施 = **本期 MVP 完成的代码**；本 deployment-plan v2.0 列出的 P0 待办 = **上线前还要再改的**。两者关系：

| 模块 | v1.5 已实施 | v2.0 上线前还要改 |
|---|---|---|
| `scripts/quant/` 13 个 .py 模块 | ✅ 完整（86 pytest 90.2% cov） | 加 `QUANT_DATA_ROOT` env 支持 + `mock-test` 子命令 + `--realtime auto` |
| `docs/quant/` 网页 + lib | ✅ 完整（10 selenium 全过） | `writer.js` 加 mergeFn 模式 + operation_id 幂等键 |
| 3 个独立 workflow | ✅ 已写（signal/cache/close-confirm）| **删除**，合并为 `quant.yml` 多 mode |
| `quant-test.yml` PR 测试 | ✅ 已写 | 不变 |
| `update.yml` 早间钩子 | ❌ 未加 | 加 `morning-reconcile` step（continue-on-error）|
| gh-pages 同步链路 | ❌ 缺 deploy step | quant.yml 内置 + 加 concurrency group |
| 飞书机器人 / PAT / cron-job.org | ❌ 用户外部资源 | 上线前用户自行配置 |
| AkShare 真实接入 | ❌ 仍用 fixture | 切实盘前必须实施 |

**结论**：v1.5 的「本地走通」目标已达成；v2.0 是把它改造成「真实可上线」的延伸，**不是从零重写**，是定向重构。

本文档是把"本地走通的 MVP"推到**真实线上跑**所需的全部端到端步骤。包含：

1. 你（用户）必须亲自做的 6 件事（外部资源准备）
2. GitHub Pages 部署机制说明（首次 push 后会发生什么）
3. 首次部署 step-by-step（含验证步骤）
4. 线上测试 checklist（10 个工作日 paper trading 期）
5. **本地 demo vs 线上数据隔离规范**（避免本地误推假数据）
6. 监控、故障处理、回滚预案
7. 切实盘前的最后检查

---

## 一、上线前置 — 你必做的 6 件事

这 6 件事是**外部资源准备**，与代码无关，必须在 push main 之前或 14:48 第一次跑信号之前完成。

### 1. 飞书自建机器人 + Webhook

**步骤**：
1. 飞书 PC/手机端 → 创建群 `量化信号`（仅你自己也行）
2. 群设置 → 群机器人 → 添加机器人 → 自定义机器人
3. 命名 `Quant Signal Bot`，可选添加头像
4. 设置中可选「自定义关键词」白名单（推荐填 `量化`、`信号` 让出错时不被屏蔽）
5. 拿到 Webhook URL，形如 `https://open.feishu.cn/open-apis/bot/v2/hook/<UUID>`

**验收**：用 curl 发一条测试卡片：

```bash
curl -X POST "https://open.feishu.cn/open-apis/bot/v2/hook/<UUID>" \
  -H "Content-Type: application/json" \
  -d '{"msg_type":"text","content":{"text":"量化测试 OK"}}'
# 期望响应：{"code":0,"msg":"ok"}
# 飞书群应收到一条消息
```

### 2. Fine-grained PAT（GitHub Personal Access Token）

**步骤**：
1. 打开 https://github.com/settings/personal-access-tokens/new
2. 名称：`quant-trend-pages`
3. 过期时间：**90 天**（到期前会到邮箱提醒）
4. Repository access：**Only select repositories** → 选 `loopq/trend.github.io` 这一个
5. Permissions（Repository permissions）：
   - **Contents**: **Read and write** ✅（必勾）
   - **Metadata**: **Read-only**（自动勾选）
   - **以下全部禁勾**：Actions / Administration / Pages / Pull requests / Issues / Workflows / Discussions / 其他
6. Generate token → 复制（只显示一次）

**校验**：
```bash
TOKEN="ghp_xxx"
curl -s -H "Authorization: Bearer $TOKEN" https://api.github.com/repos/loopq/trend.github.io | jq '.name, .full_name, .permissions'
# 期望：name = "trend.github.io"; permissions 含 push:true
```

⚠️ **不要 commit 到代码或写到 .env 文件**。仅在网页 settings 页运行时输入存 localStorage。

### 3. 触发链 — 主备双路 + heartbeat（review C-1 修订）

**v1.0 → v2.0 → v2.1**：原本只 1 个 cron-job.org 任务，存在单点故障。本节升级为**主备双路 + 哨兵 heartbeat**：

#### 主路：cron-job.org 1 个任务

| 项 | 值 |
|---|---|
| Title | `Quant Signal 14:48 (Primary)` |
| URL | `https://api.github.com/repos/loopq/trend.github.io/dispatches` |
| Method | `POST` |
| Schedule | `Mon-Fri at 14:48` (Asia/Shanghai 时区) |
| Headers | `Accept: application/vnd.github+json` `Authorization: Bearer <PAT_FOR_CRON>` `Content-Type: application/json` |
| Body | `{"event_type":"quant-trigger","client_payload":{"mode":"signal"}}` |

#### 备路：GitHub native schedule（容灾兜底）

`quant.yml` 自带 `schedule` cron 作为二级触发：

```yaml
on:
  workflow_dispatch: {...}
  repository_dispatch: {types: [quant-trigger]}
  schedule:
    # 14:50 SGT = 06:50 UTC（GitHub schedule 时区固定 UTC）
    # 比 cron-job.org 主路晚 2 分钟，主路成功 → 当日哨兵跳过；主路失败 → 备路兜底
    - cron: '50 6 * * 1-5'
    # 09:05 SGT = 01:05 UTC （备 morning-reconcile）
    - cron: '5 1 * * 1-5'
```

**幂等性保证**（review H-3）：`quant.yml` mode=signal 启动时检查 `data/quant/signals/{today}.json` 是否已存在 + 是否有 `pending` 状态信号；如果今日已跑过 → 立即退出 0（不重复发飞书、不重复 commit）。这就是「主路成功后备路无害」的机制。

#### Heartbeat 哨兵（review C-1）

`quant.yml` 在所有 mode 末尾写 `data/quant/.heartbeat` 文件（commit 进 main）。

新增独立 workflow `quant-heartbeat.yml`，每天 14:55 SGT 跑：

```yaml
on:
  schedule:
    - cron: '55 6 * * 1-5'   # 14:55 SGT
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: 检查今日是否产出 signals
        run: |
          TODAY=$(TZ=Asia/Shanghai date +%Y-%m-%d)
          if [ -f "docs/data/quant/signals/${TODAY}.json" ]; then
            echo "✅ 今日信号已产出"
          else
            echo "::error::❌ 今日 ${TODAY} 信号文件未产出，可能 cron 主备双路都失败"
            # 发飞书告警（用 FEISHU_WEBHOOK_URL secret）
            curl -X POST "${{ secrets.FEISHU_WEBHOOK_URL }}" \
              -H "Content-Type: application/json" \
              -d "{\"msg_type\":\"text\",\"content\":{\"text\":\"⚠️ 量化哨兵警告：${TODAY} 14:55 仍未发现信号文件\"}}"
            exit 1
          fi
```

非交易日：哨兵脚本先调 trading_calendar 判断，非交易日直接退出 0。

#### PAT 双 token（review H-11 部分采纳）

| Token | 用途 | 存储 | 轮换 |
|---|---|---|---|
| Web PAT | 用户网页 writer.js 写状态文件 | 浏览器 localStorage | 90 天，settings 页显示「剩余 X 天」+ 邮件提醒 |
| Cron PAT | cron-job.org dispatch 触发 | cron-job.org 后台 | 90 天，月度 Runbook 检查（见下） |

**轮换 Runbook**（每月 1 号检查）：

```
[ ] 进 https://github.com/settings/personal-access-tokens 看 2 个 token 剩余天数
[ ] < 30 天 → 立即生成新 token
[ ] Web PAT：在网页 settings 页 → 清除旧 PAT → 输入新 PAT → 验证有效性通过
[ ] Cron PAT：cron-job.org 后台 → 编辑任务 → 替换 Authorization header
[ ] 用 mode=mock-test 验证两个 token 都正常
```

**拒绝 GitHub App 方案**（review H-11 完整建议）：私人工具，GitHub App 配置 + 安装令牌轮换增加运维成本，PAT 双 token + 轮换 Runbook 已足够。

**验收**：cron-job.org 「Test run」点击后 30s 内 GitHub Actions 应有新 run；当日交易日有信号则飞书收到消息；14:55 哨兵 workflow 跑通 + 不报警。

### 4. 修订 v9-summary.md 笔误（可选独立小 PR）

`docs/agents/backtest/v9-summary.md` 第 62 行用户已在本次 squash 中改正（"V9.2（14 指数）" → "13 指数"），无需额外动作。

### 5. paper_trading 模式确认

`docs/data/quant/positions.json` 中 `paper_trading: true`，已是默认 init 状态。**前 10 个工作日不要切实盘**。

切实盘条件：
- ≥ 10 工作日观察 SLO 三档时延全部达标（信号写完 < 14:50 / 飞书首条 < 14:51 / 飞书全部 < 14:52）
- 推送到达率 ≥ 95%
- close-confirm 假信号率 ≤ 15%
- ≥ 5 次成功在网页 PAT 确认成交流程跑通

切换方式：手动改 positions.json `paper_trading: false`，或 settings 页加按钮（暂未实现）。

### 6. AkShare 真实数据接入 + 降级策略矩阵（review H-8 修订）

当前 workflow 使用 `scripts/quant/tests/fixtures/realtime_2026-04-25.json` 作为 mock 数据源。**真实跑通需要把这个 fixture 替换为 AkShare 实时拉取 + 加降级策略**。

**实施**（P0）：在 `run_signal.py` 加 `--realtime auto` 分支，直接调 `AkShareFetcher`（已实现，见 `data_fetcher.py:80-130`）。

#### 数据缺失降级策略矩阵

| 缺失场景 | 阈值 | 动作 | 通知 |
|---|---|---|---|
| 单个指数实时价缺失 | 1 个 | 跳过该指数所有 bucket（D/W/M），其他指数照常 | 飞书 INFO 卡片注明 |
| 单个 ETF 实时价缺失 | 1 个 | 跳过该指数所有 bucket（无法计算 suggested_shares）| 飞书 INFO |
| 指数缺失 ≥ 5/13 | 阈值 | 全量跳过当日信号生成，写 `signals/{date}.json` 标记 `is_skipped: true, reason: "data_unavailable"` | 飞书 ERROR + workflow exit 1 |
| 指数 + ETF 缺失共 ≥ 8/26 | 阈值 | 同上 | 同上 |
| 同一指数多源价格分歧 > 5% | 偏差 | 按主源（cs_index）跑，副源仅记日志 | 飞书 WARN |
| 主源（cs_index）调用失败 | 网络 | 自动重试 2 次（线性退避 5s/15s）→ 仍失败 → 切备用源（sina_index）| 飞书 WARN |
| 主备双源都失败 | 兜底 | workflow exit 1，等次日重跑 | 飞书 ERROR + GitHub Actions 默认邮件 |

#### 实施代码骨架

```python
# scripts/quant/data_fetcher.py 加策略
def fetch_with_fallback(codes, fallback_source='sina_index'):
    quotes = AkShareFetcher().fetch_indices(codes)
    missing = [c for c in codes if c not in quotes]
    if missing:
        log.warning(f"主源缺 {len(missing)} 个指数，切备用源: {missing}")
        backup_quotes = SinaIndexFetcher().fetch_indices(missing)
        quotes.update(backup_quotes)
    return quotes

# scripts/quant/run_signal.py 加阈值检查
def check_data_completeness(quotes, codes, threshold=5):
    missing = [c for c in codes if c not in quotes]
    if len(missing) >= threshold:
        raise DataAvailabilityError(f"缺失 {len(missing)}/{len(codes)} ≥ 阈值 {threshold}")
    return missing
```

#### 验证

切实盘前手动跑一次：

```bash
python -c "
from scripts.quant.data_fetcher import AkShareFetcher
fetcher = AkShareFetcher()
indices = fetcher.fetch_indices(['399997','399989','931151','000819','931079','399808','931071','930721','399967','399673','000688','000813','399976'])
print(f'指数: {len(indices)}/13')
etfs = fetcher.fetch_etfs(['161725','512170','515790','512400','515050','516160','515980','516520','512660','159949','588000','159870','515030'])
print(f'ETF: {len(etfs)}/13')
"
# 期望：13/13 + 13/13 全到
# 不全到 → 单独排查（备用接口或暂从池中剔除该指数）
```

---

## 二、GitHub Pages 部署机制说明（v2.0 设计）

### 部署链路

```
                  [真值层 - main 分支]                          [展示层 - gh-pages 分支]
        ┌──────────────────────────────────┐               ┌──────────────────────────┐
        │  docs/                           │               │  docs/                   │
        │   ├── index.html (鱼盆首页)       │               │   ├── index.html         │
        │   ├── archive/...                │   显式同步     │   ├── archive/...        │
        │   ├── quant/* (网页)              │   ──────►    │   ├── quant/*            │
        │   └── data/quant/*  (状态)        │               │   └── data/quant/*       │
        └──────────────────────────────────┘               └──────────────────────────┘
            ↑                                                      ↑
            push main 不自动触发同步                                  GitHub Pages 服务
            （这是你想要的）                                          https://loopq.github.io/trend.github.io
```

**触发同步的 4 种方式**（明确 + 可控）：

| 触发方式 | 时机 | 说明 |
|---|---|---|
| `update.yml` cron 早间触发 | 每个交易日 + 周六 | 跑 main.py morning 后顺带同步全部 docs/* （含 quant）|
| `quant.yml mode=signal` 内部步骤 | 14:48 跑完后 | 信号刚生成 → 立即同步当日 signals.json + index.json + positions.json |
| `quant.yml mode=morning-reconcile` 内部步骤 | 早间 update.yml 钩子 | reconcile + close-confirm 后同步 |
| `quant.yml mode=deploy` 手动 | 用户 `gh workflow run quant.yml -f mode=deploy` | 紧急同步（如 quant 资源被改但没跑信号）|

**关键认知**：
- **push main 永远不触发 gh-pages 部署**（与你诉求一致）
- gh-pages 只在 workflow **主动决定要发**时同步
- 14:48 信号 → 同 commit 内自己同步 gh-pages → 用户 14:51 刷新网页就能看到

### gh-pages 同步实施（待补 P0）

在 `quant.yml` 加一个共享的 deploy step（被 signal / morning-reconcile / deploy mode 复用）：

```yaml
# .github/workflows/quant.yml 内的 deploy step
- name: 同步 docs/data/quant 到 gh-pages（增量）
  if: inputs.mode == 'signal' || inputs.mode == 'morning-reconcile' || inputs.mode == 'deploy'
  uses: peaceiris/actions-gh-pages@v3
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
    publish_dir: ./docs
    keep_files: true   # 关键：增量覆盖，保留 gh-pages 已有归档/css/js
    user_name: 'github-actions[bot]'
    user_email: 'github-actions[bot]@users.noreply.github.com'
    commit_message: '[quant] sync docs/* (mode=${{ inputs.mode }}) ${{ github.event.head_commit.message || ''auto'' }}'
```

`mock-test` mode 不调 deploy（数据在 /tmp，没东西可同步）。

### 验证 quant 资源是否到达 gh-pages

```bash
# 验证 docs/quant/index.html 已上线
curl -I https://loopq.github.io/trend.github.io/quant/index.html
# 期望 200

# 验证 docs/data/quant/positions.json 已上线
curl https://loopq.github.io/trend.github.io/data/quant/positions.json | jq '.buckets | length'
# 期望 36（init 状态）

# 验证当日信号（14:48 后）
TODAY=$(date +%Y-%m-%d)
curl https://loopq.github.io/trend.github.io/data/quant/signals/${TODAY}.json | jq '.signals | length'

# 验证 lib js
curl -I https://loopq.github.io/trend.github.io/quant/lib/config.js
# 期望 200
```

---

## 二点五、多 mode `quant.yml` 设计（v2.0 核心）

3 个独立 workflow → **1 个 `quant.yml` + mode 参数**。仿 `update.yml` 的 morning + force 模式。

### 5 种 mode

| mode | 触发方式 | 做什么 | 写 main 分支 | 同步 gh-pages | 发飞书 |
|---|---|---|---|---|---|
| `signal` | repository_dispatch (cron 14:48) + workflow_dispatch + GitHub schedule 14:50 备路 | 14:48 盘中信号生成 + close vs MA20 判定 + provisional 写入 | ✅ | ✅ | ✅ |
| `morning-reconcile` | update.yml 早间钩子 + workflow_dispatch + GitHub schedule 09:05 备路 | 用昨日真实收盘价 confirm provisional + 回正 policy_state + 跨日 pending → expired | ✅ | ✅ | ❌ |
| `deploy` | workflow_dispatch（手动） | 仅同步 docs/data/quant → gh-pages（紧急用）| ❌ | ✅ | ❌ |
| `mock-test` | workflow_dispatch（手动） | 用 fixture 跑全套，环境变量隔离到 /tmp，末尾 git status 断言 + 禁 push/deploy/真 webhook 硬门 | ❌ | ❌ | ❌（NoOp）|
| `init` | workflow_dispatch（手动，仅首次或重置） | 初始化 positions.json 为干净 36 bucket 全 CASH | ✅ | ✅ | ❌ |

### Mode 互斥矩阵 + 动态 concurrency（review H-3、H-4 修订；review N-2 修正）

**关键修订（N-2）**：v2.1 初版顶层 concurrency 与「mock-test 可并行」矩阵冲突。改为**动态 group**：

```yaml
# .github/workflows/quant.yml 顶层
concurrency:
  # mock-test 用独立 group 不阻塞主链路；其他 mode 共用 quant-state-main
  group: ${{ inputs.mode == 'mock-test' && 'quant-mock-test' || 'quant-state-main' }}
  cancel-in-progress: false       # 排队等待，不取消
```

**互斥矩阵**（一致版）：

|  | signal | morning-reconcile | deploy | mock-test | init |
|---|---|---|---|---|---|
| signal | 串行（quant-state-main 串行）| 串行 | 串行 | **可并行**（mock-test 用独立 group） | 串行 |
| morning-reconcile | 串行 | 串行 | 串行 | 可并行 | 串行 |
| deploy | 串行 | 串行 | 串行 | 可并行 | 串行 |
| mock-test | 可并行 | 可并行 | 可并行 | **mock-test 自身串行**（避免重复跑撞 /tmp 目录）| 可并行 |
| init | 串行 | 串行 | 串行 | 可并行 | 串行（fail-fast 防误执行）|

**`init` 的特殊保护**：mode=init 启动时检查 `data/quant/positions.json` 是否已 commit + 是否有非空 transactions；有则 fail-fast 要求 `--force` 确认，避免误清空。

**Run 完成标记**（review N-3 修订）：原 v2.1 用「signals/{date}.json 含 pending」判幂等，对「无信号日」误判会导致备路重复跑。改为**显式 run 标记**：

每次 mode=signal / morning-reconcile 跑完最后一步写：

```
docs/data/quant/.runs/{mode}-{date}.done
内容：{"completed_at": "ISO8601", "trigger": "primary|backup|manual", "run_id": "github_run_id"}
```

启动时检查 `.runs/{mode}-{date}.done` 是否存在：
- 存在 → 立即退出 0（无信号日也包含在内）
- 不存在 → 正常执行，最后写入标记

`.runs/` 目录加入 gh-pages 同步范围（用户网页需要看到「今日已跑过」状态）。

**morning-reconcile 前置检查**（review C-2）：`signal` mode 启动时**强制检查**昨日 `.runs/morning-reconcile-{yesterday}.done` 是否存在；如果不存在 → fail-fast 报「昨日 morning-reconcile 未跑」+ 飞书警告。这避免「yesterday_policy 用 provisional 值」的级联错误。

### mock-test mode 的硬隔离设计（review H-5 修订）

**目的**：保证「mock 测试 100% 不污染线上数据」。除了 QUANT_DATA_ROOT 隔离，还加 5 道硬门（v2.1.1 加固）：

```yaml
- name: Checkout（mock-test 专用：禁持久化凭据）
  if: inputs.mode == 'mock-test'
  uses: actions/checkout@v4
  with:
    persist-credentials: false   # 硬门 #0（review N-1）：不保留默认 GITHUB_TOKEN 到 git remote

- name: 硬门 #1 — 移除 git remote 凭据（review N-1）
  if: inputs.mode == 'mock-test'
  run: |
    # 双保险：即使 checkout 漏配置 persist-credentials，也强制移除
    git config --unset-all "http.https://github.com/.extraheader" || true
    git remote set-url origin "https://invalid-mock-no-push@github.com/${GITHUB_REPOSITORY}.git"
    echo "✅ git remote 凭据已移除，任何 push 必失败"

- name: mock-test 模式（完全隔离）
  if: inputs.mode == 'mock-test'
  env:
    QUANT_DATA_ROOT: /tmp/quant-test    # 覆盖 docs/data/quant 路径
    QUANT_REALTIME_FIXTURE: scripts/quant/tests/fixtures/realtime_2026-04-25.json
    QUANT_NOTIFIER: disabled            # NoOp，不发飞书也不写 outbox
    QUANT_WRITER_MODE: dry_run          # 不真写文件
    GITHUB_TOKEN: ''                    # 硬门 #2：清空 env token
  run: |
    mkdir -p /tmp/quant-test/{cache,signals,notify-outbox}
    python -m scripts.quant.run_signal init
    python -m scripts.quant.run_signal mock-test \
      --mock-now ${{ inputs.mock_now }} \
      --calendar scripts/quant/tests/fixtures/trading_calendar_2026-04.json \
      --realtime $QUANT_REALTIME_FIXTURE

- name: 硬门 #3 — 工作区零 diff 断言
  if: inputs.mode == 'mock-test'
  run: |
    if [ -n "$(git status --porcelain)" ]; then
      echo "::error::❌ mock-test 后工作区有改动，违反隔离原则！"
      git status
      exit 1
    fi
    echo "✅ 工作区零 diff，隔离验证通过"

- name: 硬门 #4 — 禁部署到 gh-pages（yml if 条件已排除）
  if: inputs.mode == 'mock-test'
  run: echo "✅ mock-test 永不调 deploy step"

- name: 硬门 #5 — 输出测试报告（不写仓库）
  if: inputs.mode == 'mock-test'
  run: |
    echo "## Quant Mock Test Report" >> $GITHUB_STEP_SUMMARY
    echo "数据隔离根目录：/tmp/quant-test（不在仓库内）" >> $GITHUB_STEP_SUMMARY
    echo "GITHUB_TOKEN env 已清空 + git remote 凭据已移除，任何 push 必失败" >> $GITHUB_STEP_SUMMARY
    cat /tmp/quant-test/signals/*.json | jq '.' >> $GITHUB_STEP_SUMMARY
```

**5 道硬门**（review N-1 加固）：
0. **persist-credentials: false** → checkout 不写默认 GITHUB_TOKEN 到 git config
1. **git remote 改无效 URL + unset extraheader** → 即使有残留 token 也无法 push（双保险）
2. **GITHUB_TOKEN env 清空** → workflow 内任何 git API 调用失效
3. **git status 零 diff 断言** → mock 跑后工作区任何修改都 fail
4. **deploy step yml `if` 条件排除 mock-test** → gh-pages 永不更新
5. **NoOpNotifier + GITHUB_STEP_SUMMARY 输出** → 真飞书 webhook 永不被调用

**代码侧需要补的功能**（**P0 待办**，未实施）：

| 改动 | 文件 | 说明 |
|---|---|---|
| `QUANT_DATA_ROOT` 环境变量 | `config.py::load_config` | 启动时读 env，覆盖 yaml 的 paths.data_root |
| `QUANT_NOTIFIER=disabled` | `notifier.py` | 加 NoOpNotifier 实现（连 outbox 也不写）|
| `QUANT_REALTIME_FIXTURE` env 默认值 | `run_signal.py` | --realtime 不传时回退到 env |
| `mock-test` 子命令 | `run_signal.py` 加 `mock-test` | 一站式跑 + 输出报告 |

### 用户调用示例

```bash
# 14:48 触发（cron-job.org 自动）
curl -X POST https://api.github.com/repos/loopq/trend.github.io/dispatches \
  -d '{"event_type":"quant-trigger","client_payload":{"mode":"signal"}}'

# 手动跑次日 morning-reconcile（如果当日 update.yml 早间钩子失败）
gh workflow run quant.yml -f mode=morning-reconcile

# 手动跑 mock 测试（验证逻辑，不动线上数据）
gh workflow run quant.yml -f mode=mock-test -f mock_now=2026-04-25T14:48:00+08:00

# 紧急同步 docs/data/quant 到 gh-pages（不跑信号）
gh workflow run quant.yml -f mode=deploy

# 重置 positions.json 到干净 init 状态（实盘起步前）
gh workflow run quant.yml -f mode=init
```

### update.yml 钩子（早间触发链）

`update.yml` 在 `Run morning` step 之后加一个 `Run quant morning-reconcile` step：

```yaml
# .github/workflows/update.yml（追加 step，不修改主链路）
- name: Quant morning-reconcile（合并 reconcile + close-confirm）
  if: success()  # 仅 main.py 成功后才跑
  continue-on-error: true   # 失败不阻塞鱼盆趋势主链路
  run: |
    python -m scripts.quant.run_signal morning-reconcile \
      --mock-now $(date -u +'%Y-%m-%dT%H:%M:%SZ')
```

**关键设计**：`continue-on-error: true` 隔离故障——quant 失败**不影响**鱼盆趋势主链路 push gh-pages 的部署。

---

## 三、首次部署 step-by-step（v2.0 简化）

### Step 1：检查未 push 内容

```bash
git log --oneline origin/main..HEAD
# 期望 2 个 commit：
#   2689b4e feat(quant): MVP 本地走通 - V9.2 半自动量化信号系统
#   d3eab9d 量化交易体系：V3-V9.2 多版本回测 + 信号系统 MVP plan
```

### Step 2：补完所有 P0 待办（部署前必做，见第八节 C）

按优先级实施 6 项 P0 改动：

1. 把 3 个 yml 合并成 `quant.yml` 多 mode 主控（删除 `quant-cache.yml` / `quant-close-confirm.yml` / `quant-signal.yml`，保留 `quant-test.yml` 的 PR 测试用）
2. 新 `quant.yml` 内置 deploy step（peaceiris/actions-gh-pages，keep_files: true）
3. `update.yml` 加 `Quant morning-reconcile` step（continue-on-error）
4. 实施 `QUANT_DATA_ROOT` 环境变量 + `QUANT_NOTIFIER=disabled` + `mock-test` 子命令
5. 实施 AkShare 真实接入（`--realtime auto`，含 13 指数 + 13 ETF 实跑验证）
6. 实施 writer.js mergeFn 模式（防 lost-update）

P0 改动完成后单独 commit（建议 1 个 commit），跑全套测试通过后再 push。

### Step 3：push 到 origin/main

```bash
git push origin main
# 不会触发 gh-pages 部署（这是你想要的）
# main.py / 鱼盆趋势主链路完全不受影响
```

### Step 4：手动触发首次同步

两种选择：

**A. 等下一次 update.yml 早间 cron 自然触发**（被动，可能要等到次日）

**B. 手动 dispatch quant.yml deploy mode**（主动，立即生效）

```bash
gh workflow run quant.yml -f mode=deploy
# 或 GitHub Actions 网页 → quant.yml → Run workflow → mode=deploy
```

等 1-2 分钟，gh-pages 应同步完成。

### Step 5：验证线上 quant 入口可访问

```
https://loopq.github.io/trend.github.io/quant/
```

应弹密码框 → 输入 `weiaini` → 进入控制台。

期望看到：
- 顶部 ⚠️ Paper Trading 横幅
- 总览：总成本 ¥130,000 / 总资产 ¥130,000 / 持仓 ¥0（干净 init）
- 需确认：0 条
- 13 指数卡片：全部 CASH 状态
- 最近操作：暂无

### Step 6：在 settings 页配 PAT

```
https://loopq.github.io/trend.github.io/quant/settings.html
```

输入第一节 step 2 生成的 PAT → 保存 → 「验证有效性」点击 → 期望 `✅ PAT 可访问目标仓库`

### Step 7：cron-job.org 1 个任务激活

激活第一节 step 3 配置的 **唯一一个 14:48 任务**。

### Step 8：先跑一次 mock-test 验证整套链路（不动线上）

```bash
gh workflow run quant.yml -f mode=mock-test -f mock_now=2026-04-25T14:48:00+08:00
```

GitHub Actions 跑完后看 step summary：
- 显示「数据隔离根目录：/tmp/quant-test」
- 显示 X 条 mock 信号
- main 分支无任何 commit（验证不污染）
- gh-pages 不更新（验证不部署）

### Step 9：mock 通过后，下一个交易日 14:48 自动跑真实信号

cron-job.org 14:48 触发 → quant.yml mode=signal → 生成信号 + 推飞书 + commit main + 同步 gh-pages → 14:51 你刷新网页能看到 + 飞书已收到。

---

## 三点五、GitHub 数据存储 + 防覆盖（v2.0 重点）

### 数据存储

```
                 [真值层]                                [展示层]
                 main 分支                               gh-pages 分支
       ┌──────────────────────────────┐            ┌──────────────────────┐
       │  docs/data/quant/            │            │  docs/data/quant/    │
       │   ├── positions.json          │ explicit  │   （只读快照）        │
       │   ├── transactions.json       │ deploy    │                      │
       │   ├── signals/                │  ────►    │                      │
       │   │   ├── index.json          │  mode     │                      │
       │   │   └── {YYYY-MM-DD}.json   │           │                      │
       │   ├── cache/{code}.csv        │           │                      │
       │   └── notify-outbox/{ts}.json │           │                      │
       └──────────────────────────────┘            └──────────────────────┘
            ↑                                              ↑
       多个写者                                       用户浏览器只读 fetch
       （并发可能）                                     （cache-busting）
```

**真值在 main 分支**；gh-pages 是**显式同步的快照**。所有写操作走 main 分支，gh-pages 仅在 mode=signal/morning-reconcile/deploy 时被覆盖式更新（`keep_files: true` 增量）。

### 三个 tracked 状态文件 vs 生成产物

| 文件 | 是否进 git | 写者 | 重要性 |
|---|---|---|---|
| **positions.json** | ✅ 追踪 | 用户网页 + 14:48 + morning-reconcile | 🔴 严重，账本核心 |
| **transactions.json** | ✅ 追踪 | 仅用户网页 append | 🔴 严重，成交流水 |
| **signals/index.json** | ✅ 追踪 | 14:48 + morning-reconcile | 🟡 中等，丢失可重建（扫描 signals/*.json）|
| signals/{YYYY-MM-DD}.json | ❌ gitignore（**待改！**）| 14:48 + morning-reconcile + 用户网页 | 🟡 中等 |
| cache/{code}.csv | ❌ gitignore | morning-reconcile | 🟢 可重新拉 |
| notify-outbox/{ts}.json | ❌ gitignore | mock dry-run | 🟢 仅本地调试 |

**⚠️ 重要修订**：当前 `.gitignore` 把 `signals/2*.json` 全部排除，这是**错的**——线上 14:48 workflow commit 进 main 后必须能被 gh-pages 同步。要改成**只忽略本地 mock 产物，不忽略真实信号**。

修复方式（待补 P0）：

```gitignore
# 当前（错）
docs/data/quant/signals/2*.json

# 改成（对）
# 不再用 pattern ignore signals 文件
# 通过 paper_trading 字段 + 提交者（github-actions[bot]）区分线上 vs 本地
# 本地 demo 时人工注意 git status，或用 QUANT_DATA_ROOT=/tmp 隔离
```

更彻底的修复：实施 `QUANT_DATA_ROOT` 环境变量后（见多 mode 章节），本地 demo 全部走 /tmp，仓库的 docs/data/quant/signals/ 永远只有 workflow 写的真实数据。这样 .gitignore 不需要 ignore signals/{date}.json。

### 三层防覆盖机制

**第 1 层：单 commit 多文件原子提交**（已实现 §3.7）

一次 commit 同时写多文件，要么全成功要么全失败。不存在「写 A 成功 + 写 B 失败」中间态。

**第 2 层：parent SHA 乐观锁**（已实现 §3.7）

```
writer 提交流程：
  1. GET /git/refs/heads/main → base_sha
  2. POST /git/blobs (新内容)
  3. POST /git/trees (with base_tree)
  4. POST /git/commits (with parent=base_sha)
  5. PATCH /git/refs/heads/main (with new_commit_sha, force=false)
     失败 422 = ref 已被别人改 → 重试（最多 3 次）
```

**第 3 层：同日幂等合并规则**（已实现 §3.7.1）

signals/{date}.json 重跑时按字段保护：
- **可覆盖**：provisional / confirmed_by_close / etf_realtime_price / suggested_shares
- **永不覆盖**：status / actual_price / actual_shares / skip_reason / external_funded / confirmed_at / expired_at

### 🚨 还存在的 Lost Update 风险（P0 待修）

**场景**：

```
T+0   用户网页 fetch positions.json（v1）
T+1   14:48 workflow 写 positions.json (v1 → v2，更新所有 bucket policy_state)
T+2   用户网页提交确认（基于 v1 的 actual_state 修改）
       writer.js POST /git/refs PATCH 失败（parent=v1，但 ref 已是 v2）
T+3   writer.js retry → GET 最新 ref（v2）
T+4   writer.js 用旧的 file content（基于 v1）+ parent=v2 PATCH → 成功
T+5   ❌ workflow 在 v2 写入的 policy_state 更新被覆盖丢失
```

**修复（待实施 P0）**：writer.js 增加 **mergeFn 合同 + operation_id 幂等键 + schema 校验 + 错误码协议**（review H-6、H-7 修订）。

#### mergeFn 合同（review H-7）

```typescript
// mergeFn 输入输出契约
interface MergeFn {
  (latestRawContent: string): MergeResult;
}

type MergeResult =
  | { ok: true,  newContent: string, operation_id: string }      // 正常 merge
  | { ok: false, code: 'NOT_FOUND',      message: string }       // 目标对象不存在
  | { ok: false, code: 'ALREADY_DONE',   message: string }       // 幂等命中，无需写入
  | { ok: false, code: 'SCHEMA_INVALID', message: string }       // JSON / schema 不符
  | { ok: false, code: 'CONFLICT',       message: string };      // 业务状态冲突
```

#### operation_id 幂等键（review H-6）

每次写入操作必须带唯一 `operation_id`：调用方生成 `${action}-${signalId}-${nonce}`，写入时先查重。

#### 完整调用示例（确认成交）

```js
const opId = `confirm-${signalId}-${crypto.randomUUID()}`;

QuantWriter.commitAtomic({
  files: [
    {
      path: 'docs/data/quant/transactions.json',
      mergeFn: (latestRaw) => {
        let txs;
        try { txs = JSON.parse(latestRaw); } catch (e) {
          return { ok: false, code: 'SCHEMA_INVALID', message: 'transactions.json 不是合法 JSON' };
        }
        if (!Array.isArray(txs.transactions)) {
          return { ok: false, code: 'SCHEMA_INVALID', message: 'transactions 字段必须是数组' };
        }
        if (txs.transactions.some(t => t.operation_id === opId)) {
          return { ok: false, code: 'ALREADY_DONE', message: `op ${opId} 已记录` };
        }
        txs.transactions.push({ ...newTx, operation_id: opId });
        return { ok: true, newContent: JSON.stringify(txs, null, 2), operation_id: opId };
      },
    },
    {
      path: `docs/data/quant/signals/${date}.json`,
      mergeFn: (latestRaw) => {
        const data = JSON.parse(latestRaw);
        const sig = data.signals.find(s => s.id === signalId);
        if (!sig) return { ok: false, code: 'NOT_FOUND', message: `signal ${signalId} 不在文件中` };
        // 状态条件写：仅 pending 可转 confirmed/skipped
        if (sig.status !== 'pending') {
          return { ok: false, code: 'CONFLICT', message: `signal status=${sig.status}, 期望 pending` };
        }
        Object.assign(sig, { status: 'confirmed', actual_price: price, actual_shares: shares, operation_id: opId });
        return { ok: true, newContent: JSON.stringify(data, null, 2), operation_id: opId };
      },
    },
    {
      path: 'docs/data/quant/positions.json',
      mergeFn: (latestRaw) => {
        const pos = JSON.parse(latestRaw);
        const b = pos.buckets[bucketId];
        if (!b) return { ok: false, code: 'NOT_FOUND', message: `bucket ${bucketId} 不存在` };
        if (b.actual_state !== 'CASH') {
          return { ok: false, code: 'CONFLICT', message: `actual_state=${b.actual_state}, 期望 CASH` };
        }
        b.actual_state = 'HOLD';
        b.shares = actualShares;
        b.cash -= cost;
        b.last_op_id = opId;
        return { ok: true, newContent: JSON.stringify(pos, null, 2), operation_id: opId };
      },
    },
  ],
  message: `[PAPER] [quant] confirm ${signalId} op=${opId}`,
});
```

#### writer 内部流程

```
attempt(retriesLeft):
  1. GET ref → base_sha
  2. 对每个 file：GET 当前 content → 调 mergeFn(currentContent)
     - mergeFn 返回 ok:false → 业务错误，立即抛 MergeContractError 给前端（不重试）
     - mergeFn 返回 ok:true → 收集 newContent
  3. POST blobs → POST trees → POST commits → PATCH ref
  4. 422 (parent SHA 冲突) → retriesLeft--, attempt(retriesLeft)
  5. 其他 HTTP 错误 → 直接抛
```

#### 前端错误处理协议

| `MergeResult.code` | 前端动作 |
|---|---|
| `ok: true` | 弹绿色 toast「✅ 已确认」+ 刷新页面 |
| `ALREADY_DONE` | 弹蓝色 toast「ℹ️ 此操作已完成，无需重复」+ 刷新页面 |
| `NOT_FOUND` | 弹红色对话框「信号已消失（可能已过期），请刷新页面」 |
| `CONFLICT` | 弹红色对话框「状态冲突（可能已被其他操作处理），请刷新查看最新状态」 |
| `SCHEMA_INVALID` | 弹红色对话框「数据格式异常，请联系管理员检查」+ 上报 console.error |
| 网络错误（非业务）| writer 内部重试 3 次；耗尽 → 弹红色 toast「网络错误，刷新重试」|

**实施位置**：`docs/quant/lib/writer.js` + `docs/quant/index.html` 调用方改造。约 80 行新代码。

### Paper trading 模式的 commit 标记

为方便事后区分 paper 数据 vs 实盘数据，writer.js 在 paper_trading=true 时给 commit message 加前缀：

```
[PAPER] [quant] confirm 2026-04-25-399997-D
[REAL]  [quant] confirm 2026-04-26-399997-D
```

切实盘时，可以用 `git log --grep="\[PAPER\]"` 一键筛出所有 paper 期 commit，决定是否归档/打 tag。

---

## 四、线上测试 checklist（10 个工作日 paper trading）

按 mvp-plan §10 Phase 6 / §11.2 验收标准：

### 第 1 周（auto_skip 模式，5 个工作日）

| 验证项 | 通过标准 | 怎么验证 |
|---|---|---|
| 14:48 信号准时性 | p95 < 14:50:00 写完 signals.json | GitHub Actions run 时间戳 |
| 飞书首条到达 | p95 < 14:51:00 | 看飞书消息时间戳 |
| 飞书全部到达 | p95 < 14:52:00 | 多条信号时观察 |
| 推送到达率 | ≥ 95% | 5 天中至多 1 天失败 |
| close-confirm 假信号率 | ≤ 15% | 累计 5 天的 signals/{date}.json 中 confirmed_by_close=false 比例 |
| reconcile 正确性 | pending 跨日 → expired | 制造一条 pending 不确认 → 次日 09:00 后查 status |
| StateInvariantError 隔离 | 单 bucket 报错不影响其他 | 故意改 positions.json shares=0 但 actual_state=HOLD |
| 节假日跳过 | trigger.py 正确 skip | 五一假期前后 |

### 第 2 周（manual_mock_confirm 模式，5 个工作日）

| 验证项 | 通过标准 |
|---|---|
| PAT 流程 | ≥ 5 次成功在网页确认（输入价数 → 单 commit 写入成功）|
| 单 commit 原子性 | git log --name-only 看每次确认对应 1 commit + ≥ 2 文件 |
| 至少 1 次 PAT 重新生成 | 模拟 PAT 过期 → 弹窗 → 重新输入 |
| 至少 1 次故意跳过 + 1 次 external_funded | 验证 skip / 外部补充资金路径 |
| Paper PnL vs V9.2 偏差 | ≤ 5%（如果信号样本 ≥ 5 条）|
| 网页 UX | 1 分钟内完成单条信号确认 |

### 用户每日对账（5 分钟）

每日 15:30 之后：
1. 打开 GitHub Actions 看 quant.yml（signal mode）+ quant-heartbeat.yml + update.yml（含 morning-reconcile step）是否都跑通
2. 飞书群看消息送达 + heartbeat 无报警
3. 网页 history.html 看当日信号是否合理
4. 用 V9.2 回测代码 reproduce 同一日的 D 信号 → 比对（应完全一致）

---

## 五、🚨 本地 demo vs 线上数据隔离规范

**这是最关键的一节，避免本地误推假数据污染线上。**

### 当前数据文件的两类边界

| 文件 | 是否进 git | 谁修改 | 风险 |
|---|---|---|---|
| `docs/data/quant/positions.json` | **是**（init 状态）| 仅线上网页确认 + workflow 写 | ⚠️ 本地 demo 跑信号会覆盖 |
| `docs/data/quant/transactions.json` | **是**（空数组）| 仅线上网页确认时 append | ⚠️ 同上 |
| `docs/data/quant/signals/index.json` | **是**（空 entries）| workflow 写 | ⚠️ 同上 |
| `docs/data/quant/signals/{date}.json` | **否（gitignore）** | workflow 写 | ✅ 本地 demo 不会推 |
| `docs/data/quant/cache/{code}.csv` | **否（gitignore）** | workflow 写 | ✅ |
| `docs/data/quant/notify-outbox/{ts}.json` | **否（gitignore）** | dry-run 写 | ✅ |

### 本地 demo 安全工作流

**做 demo 之前**：

```bash
# 1. 备份线上当前的 3 个 tracked 状态文件（避免覆盖丢失）
cp docs/data/quant/positions.json /tmp/positions-backup.json
cp docs/data/quant/transactions.json /tmp/transactions-backup.json
cp docs/data/quant/signals/index.json /tmp/signals-index-backup.json
```

**做 demo**：

```bash
# 2. 跑 demo，覆盖本地 3 个文件
python -m scripts.quant.run_signal init   # 重置 positions
# 跑 mock 信号 / 注入 mock 数据 / 启动 server / 看 UI ...
```

**demo 之后 + push 之前**（最关键）：

```bash
# 3. 还原 3 个 tracked 状态文件到线上版本
cp /tmp/positions-backup.json docs/data/quant/positions.json
cp /tmp/transactions-backup.json docs/data/quant/transactions.json
cp /tmp/signals-index-backup.json docs/data/quant/signals/index.json

# 4. 一定要 git status 确认这 3 个文件无 diff
git status docs/data/quant/
# 期望：只有 untracked（被 gitignore 的 cache/csv、notify-outbox/json、signals/{date}.json）
# 不应该看到 positions.json / transactions.json / signals/index.json 的 modification
```

### 更安全的做法（强烈推荐）

把 demo 完全隔离到一个**临时目录**，不动 `docs/data/quant/`：

```bash
# 跑 demo 时用环境变量覆盖路径
QUANT_DATA_ROOT=/tmp/quant-demo python -m scripts.quant.run_signal init
```

**待办**：当前 `run_signal.py` 没实现 `QUANT_DATA_ROOT` 环境变量覆盖。**强烈建议在切实盘前补这个 feature**，避免人工操作疏忽。

---

## 六、监控 + 故障处理

### 日常监控

| 渠道 | 看什么 | 频率 |
|---|---|---|
| 飞书群 | 是否每日 14:48 收到卡片 | 每日 |
| GitHub Actions | quant.yml + quant-heartbeat.yml + update.yml morning-reconcile step 是否全绿 | 每日 |
| 网页 history.html | 信号合理性 | 每日 |
| GitHub Email（workflow 失败默认发）| 工作流失败邮件 | 实时 |

### 故障处理

| 故障 | 表现 | 处理 |
|---|---|---|
| 飞书消息漏发 | 14:51 还没收到 | 1. 查 GitHub Actions run；2. log 找 NotifierUnrecoverableError；3. 检查 webhook URL 是否被吊销 |
| AkShare 拉数据失败 | workflow 报 missing realtime | 1. 重试 `gh workflow run quant.yml -f mode=signal`；2. 切备用 source（cs_index → sina_index） |
| PAT 过期 | 网页弹「PAT 失效」| settings 页重新输入；同时检查 cron-job.org 的 PAT 是否也到期，分别更新 |
| cron-job.org 失效 | 14:48 当日没触发 | 手动 `gh workflow run quant.yml -f mode=signal`；考虑切到 GitHub schedule（5-30min 延迟，不推荐）|
| 同日重跑覆盖用户 status | 不应该发生（§3.7.1 幂等保护）| 检查是否有 bug，回滚到上一 commit |
| **Lost Update（用户网页 + workflow 并发）** | positions/transactions 某次提交后字段被覆盖 | 检查 writer.js mergeFn 是否实施；未实施则属预期风险，重新让用户操作 |
| StateInvariantError 频繁触发 | 飞书警告卡片刷屏 | 检查 positions.json 是否被本地 demo 污染（见第五节）|
| update.yml 早间 morning-reconcile 失败 | 次日 14:48 用错的 yesterday_policy 算信号 | continue-on-error 隔离不影响主链路；signal mode 启动时 fail-fast 检测 + 飞书警告；手动 `gh workflow run quant.yml -f mode=morning-reconcile` 补跑后再跑 signal |
| gh-pages 没同步（用户网页看不到当日信号）| 14:48 后 fetch signals 404 | 1. 看 quant.yml 的 deploy step 是否跑通；2. 手动 `gh workflow run quant.yml -f mode=deploy` 强制同步 |
| 14:48 跑了但信号写错（要回滚）| signals/{date}.json 内容错误 | `git revert <bad_commit>` + `gh workflow run quant.yml -f mode=deploy` 重新同步 |
| **Heartbeat 哨兵报警**（14:55 当日无 signals）| 飞书收到「⚠️ 量化哨兵警告」消息 | 1. 看 GH Actions 是否主备双路都跑了；2. 都没跑 → 手动 dispatch；3. 跑了但失败 → 看具体错误日志 |
| **GitHub schedule 备路误触发**（主路已成功）| 当日 quant.yml 跑 2 次 | 幂等检查保证第二次启动后立即退出（不重复发飞书 / 不重复 commit），无害 |
| **mode=init 误执行**（已有交易历史时）| init 启动时 fail-fast | init 检测 transactions.json 非空时拒绝执行，要求人工 `--force` 确认 |
| **mergeFn 返回 NOT_FOUND/CONFLICT** | 用户网页弹错误对话框 | 用户刷新页面看最新状态；如确认是 bug 则人工修 positions.json |
| **AkShare 缺数 ≥ 阈值（5/13）** | quant.yml signal mode workflow exit 1 | 飞书 ERROR + GitHub 默认邮件；手动看是否数据源问题，确认无误后等次日重跑 |
| **paper→real 切换数据混叠** | migrate 脚本检测到混合 fail-fast | 用户先归档 + 重置后再切；切换后打 git tag `paper-trading-end-{date}` |

### 紧急回滚

如果某天发现量化系统的 commit 误改了主链路：

```bash
# 找出最后一个安全的 commit
git log --oneline | head -10

# 强制把某个文件回到旧版本（不影响其他文件）
git checkout <commit_sha> -- scripts/main.py

# 或全量回滚（小心！）
git revert <bad_commit_sha>
```

---

## 七、切实盘前最后检查（10 个工作日后）

| 检查项 | 通过标准 |
|---|---|
| Phase 6 验收全过 | 见第四节 checklist |
| AkShare 真实接入 | `--realtime auto` 已实施 + 至少 5 天稳定运行 |
| `quant.yml` 多 mode 工作流 | 5 个 mode 全部跑过（signal / morning-reconcile / deploy / mock-test / init） |
| gh-pages 同步链路 | quant.yml deploy step 跑通且 gh-pages 真实更新 |
| QUANT_DATA_ROOT 环境变量 | 已实施（避免本地 demo 污染线上）|
| writer.js mergeFn 模式 | 已实施 + 至少有 1 次 lost-update 候选场景验证（mock 并发）|
| 飞书消息 SLO p95 ≤ 14:51 | 实测达标 |
| close-confirm 假信号率 ≤ 15% | 实测达标 |
| update.yml morning-reconcile 钩子 | 至少跑过 5 个早间，无失败 |
| 用户主观信心 | 看了 10 天信号，能用 V9.2 回测 reproduce 100% |

### 切实盘动作 — 标准迁移脚本（review M-9 修订）

⚠️ **不要只改 `paper_trading: true → false`**。需要按下列顺序执行迁移脚本，避免 paper 流水与 real 流水混叠：

#### 一键迁移脚本 `scripts/quant/migrate_paper_to_real.py`（P0 待实施）

```python
"""Paper Trading → 实盘迁移（一次性，幂等）

执行内容：
1. 锁定窗口：检查当下不是交易时间（避免 14:48-15:00 跑），否则 fail-fast
2. 检查所有 transactions 都是 paper=true（如果有 real，说明已经切换过了，fail-fast）
3. 归档：把 transactions.json 整文件复制到 transactions-paper-archive-{date}.json
4. 重置 transactions.json 为空数组（实盘从 0 开始计）
5. 重置 positions.json：所有 bucket actual_state=CASH, shares=0, cash=initial_capital
6. paper_trading: true → false
7. 创建 git tag `paper-trading-end-{date}`（标记切换时点）
8. 单 commit 所有变更（writer.py LocalWriter commit 模式）
"""
```

执行：

```bash
python scripts/quant/migrate_paper_to_real.py --confirm
# 期望输出：
#   ✅ 锁定窗口检查通过（当前非 14:48-15:00）
#   ✅ 历史 transactions 全部 paper=true（共 N 条）
#   ✅ 归档：transactions-paper-archive-2026-05-16.json (N 条)
#   ✅ 重置 transactions.json 为空
#   ✅ 重置 positions.json 为 init 状态
#   ✅ paper_trading: false
#   ✅ git tag: paper-trading-end-2026-05-16
#   ✅ commit: feat(quant): paper trading → 实盘第一天
#
# 然后用户做：
#   git push origin main
#   git push origin paper-trading-end-2026-05-16
```

#### 第一笔实盘成交从最小 bucket 起步

切完后**不要立刻全量跑**，等下一次有 BUY 信号时**只执行最小 bucket**（如中证白酒 W bucket，~600 元）。观察 1-2 笔确认无问题后再放开全量。

#### 实盘 Runbook

| 阶段 | 动作 |
|---|---|
| Day 1 | migrate 切换；下一次 BUY 信号 → 仅最小 bucket 实盘下单（其他 bucket 仍跳过） |
| Week 1 | 渐进开放：1 个 bucket → 3 个 → 全量 |
| Month 1 | 与 V9.2 回测同期数据对账，偏差 ≤ 5% |
| Month 3+ | 如稳定，评估全自动下单（QMT/EasyTrader）的可行性 |

---

## 八、附录

### A. 关键命令速查（v2.0）

```bash
# 本地起服务器（路径与线上一致）
cd docs && python -m http.server 8000
# 访问 http://localhost:8000/quant/

# 跑全套 pytest
source venv/bin/activate
python -m pytest scripts/quant/tests/ --cov=scripts/quant \
    --cov-config=scripts/quant/.coveragerc -v

# 分模块覆盖率门禁
python scripts/quant/tests/check_per_module_coverage.py coverage.json

# 前端 selenium 测试
python scripts/quant/tests/run_browser_tests.py

# === GitHub Actions（v2.0 多 mode）===

# mode=mock-test：完全隔离测试（不动线上）
gh workflow run quant.yml -f mode=mock-test -f mock_now=2026-04-25T14:48:00+08:00

# mode=signal：手动跑信号（紧急情况，正常由 cron 14:48 触发）
gh workflow run quant.yml -f mode=signal

# mode=morning-reconcile：手动补跑次日早间合并 reconcile + close-confirm
gh workflow run quant.yml -f mode=morning-reconcile

# mode=deploy：仅同步 docs/data/quant 到 gh-pages（不跑信号）
gh workflow run quant.yml -f mode=deploy

# mode=init：重置 positions.json 到干净 init 状态（实盘起步前用）
gh workflow run quant.yml -f mode=init

# === 本地命令 ===

# 本地隔离 mock 测试（用 /tmp，不动 docs/data/quant）
QUANT_DATA_ROOT=/tmp/quant-test python -m scripts.quant.run_signal mock-test \
    --mock-now 2026-04-25T14:48:00+08:00

# 本地重置 positions.json 到 init 状态
python -m scripts.quant.run_signal init

# === 验证 gh-pages ===

# 看线上 gh-pages 上的 quant 资源
curl https://loopq.github.io/trend.github.io/data/quant/positions.json
curl https://loopq.github.io/trend.github.io/data/quant/signals/index.json

# 看当日信号（14:48 后）
TODAY=$(date +%Y-%m-%d)
curl -s https://loopq.github.io/trend.github.io/data/quant/signals/${TODAY}.json | jq '.signals[] | {id, action, status}'
```

### B. 关键 URL 列表（v2.1 更新）

| 用途 | URL |
|---|---|
| 量化控制台首页 | https://loopq.github.io/trend.github.io/quant/ |
| 历史操作 | https://loopq.github.io/trend.github.io/quant/history.html |
| 设置页（PAT/导出/重置）| https://loopq.github.io/trend.github.io/quant/settings.html |
| 单指数详情 | https://loopq.github.io/trend.github.io/quant/index/{code}.html |
| 前端测试 | https://loopq.github.io/trend.github.io/quant/tests/run.html |
| GitHub Actions 列表 | https://github.com/loopq/trend.github.io/actions |
| **quant.yml** 多 mode 工作流 | https://github.com/loopq/trend.github.io/actions/workflows/quant.yml |
| **quant-heartbeat.yml** 哨兵 | https://github.com/loopq/trend.github.io/actions/workflows/quant-heartbeat.yml |
| **quant-test.yml** PR 测试 | https://github.com/loopq/trend.github.io/actions/workflows/quant-test.yml |
| update.yml（鱼盆趋势主链路 + quant 早间钩子）| https://github.com/loopq/trend.github.io/actions/workflows/update.yml |
| repository_dispatch API | https://api.github.com/repos/loopq/trend.github.io/dispatches |

### B.1 旧 → 新入口映射表（review L-13）

v2.0 把 3 个旧 workflow 合并成 1 个 `quant.yml`，旧入口下线后映射如下：

| 旧 yml（已删除）| 新入口 |
|---|---|
| `quant-signal.yml` | `quant.yml` mode=signal |
| `quant-cache.yml` | `quant.yml` mode=morning-reconcile |
| `quant-close-confirm.yml` | `quant.yml` mode=morning-reconcile（合并）|
| 手动 dispatch 旧 yml | `gh workflow run quant.yml -f mode=<x>` |
| repository_dispatch `quant-signal-trigger` 等 | repository_dispatch `quant-trigger` + `client_payload.mode` 字段 |

### C. 上线前待办清单（v2.1 拆 P0-Core / P0-Deferred，review M-10 修订）

按「最小可上线路径」原则，把原 14 项 P0 拆成两类：

#### P0-Core（部署当天必须完成，约 1-2 天工作量）

**目标**：飞书能收到信号 + 网页能查看 + 用户能确认成交。

##### 代码骨架

- [ ] **C-1** 合并 3 yml → `quant.yml` 多 mode（5 mode：signal/morning-reconcile/deploy/mock-test/init）+ **动态 concurrency**（mock-test=`quant-mock-test`，其他=`quant-state-main`）
- [ ] **C-2** quant.yml 内置 peaceiris deploy step（仅 signal/morning-reconcile/deploy 调用，keep_files=true）
- [ ] **C-3** quant.yml 加 GitHub schedule 二级触发（14:50 SGT 备 signal、09:05 SGT 备 morning-reconcile）+ 幂等检查（启动时检测今日已跑则退出）
- [ ] **C-4** update.yml 加 morning-reconcile step（continue-on-error: true）
- [ ] **C-5** 新建 quant-heartbeat.yml（14:55 检查今日 signals/{date}.json 存在，缺则飞书 + workflow fail）
- [ ] **C-6** 实施 `QUANT_DATA_ROOT` 环境变量（config.py） + `QUANT_NOTIFIER=disabled`（notifier.py NoOpNotifier）
- [ ] **C-7** run_signal.py 加 `mock-test` 子命令 + 末尾 `git status --porcelain` 断言 + 5 道硬门（含 persist-credentials: false + git remote 改无效 URL + GITHUB_TOKEN 清空 + git status 零 diff + deploy 跳过 + NoOpNotifier）
- [ ] **C-8** AkShare 真实接入（run_signal.py --realtime auto + 缺失阈值检查 + 主备源 fallback）
- [ ] **C-9** writer.js mergeFn 合同实施（含 operation_id + schema 校验 + 错误码协议） + 调用方改造
- [ ] **C-10** signal mode 启动时检查昨日 morning-reconcile 已跑（review C-2 fail-fast）
- [ ] **C-11** 修订 .gitignore：去掉 `signals/2*.json` 排除
- [ ] **C-12** 删除旧 3 yml（quant-cache / quant-close-confirm / quant-signal）

##### 外部资源

- [ ] **C-13** 飞书机器人 + webhook → Secret `FEISHU_WEBHOOK_URL`
- [ ] **C-14** Web PAT（fine-grained, Contents R/W, 90 天）
- [ ] **C-15** Cron PAT（独立 fine-grained, 同权限）
- [ ] **C-16** cron-job.org 1 个 14:48 任务激活

##### 验收

- [ ] **C-17** 全套 pytest + selenium 测试通过 + 覆盖率分模块阈值达标
- [ ] **C-18** `python scripts/quant/check_readiness.py` 输出全 PASS（见下方 readiness 脚本）
- [ ] **C-19** push main + 手动 dispatch quant.yml mode=mock-test 验证 5 道硬门全部通过（persist-credentials false、git remote 无效、token 清空、git status 零 diff、deploy 跳过、NoOp）
- [ ] **C-20** 手动 dispatch quant.yml mode=deploy 同步 gh-pages，浏览器访问 quant/ 看到干净 init 状态

**完成 C-1 到 C-20 后即可上线进入 Paper Trading**。

#### P0-Deferred（首次上线后 1 周内补，不阻塞）

- [ ] **D-1** Migrate 脚本 `scripts/quant/migrate_paper_to_real.py`（切实盘前必备，但首次上线时还在 paper 期，先不实施）
- [ ] **D-2** 月度 PAT 轮换 Runbook 文档化（首次上线 90 天后才用到）
- [ ] **D-3** 修订 v9-summary.md "14 指数" 笔误（独立小 PR）
- [ ] **D-4** 单元测试补：mergeFn 各 5 种 MergeResult.code 路径、operation_id 幂等、降级策略矩阵

#### Paper Trading P1（10 个工作日观察）

- [ ] **P1-A** 第 1 周 auto_skip 模式（每日对账 SLO + 推送率 + 假信号率）
- [ ] **P1-B** 第 2 周 manual_mock_confirm 模式（≥ 5 次完整确认流程 + 单 commit 原子性验证）

#### 切实盘 P2

- [ ] **P2-A** 第七节切实盘 7 项检查全过
- [ ] **P2-B** 实施 D-1 migrate 脚本
- [ ] **P2-C** 跑 migrate 脚本（自动归档 paper transactions + 重置 + 打 tag + commit）
- [ ] **P2-D** push + 第一笔从最小 bucket 起步
- [ ] **P2-E** 渐进 Runbook（Week 1: 1 bucket → 3 bucket → 全量）

#### 后续优化（不阻塞）

- [ ] **P3** 收益曲线图 / 漂移自动对账 / 飞书+邮件双通道 / 全自动下单（QMT/EasyTrader 50 万门槛后）

### F. Readiness 检查脚本（review M-10）

`scripts/quant/check_readiness.py`（P0-Core C-18 必备）：

```python
"""上线就绪检查 — 一键 PASS/FAIL 清单。

检查项：
1. config.yaml 13 指数 ETF 全填实（无候选标记）
2. .gitignore 不含 signals/2*.json 排除
3. workflow 文件：quant.yml 存在 + 旧 3 个不存在 + heartbeat 存在 + update.yml 含 morning-reconcile step
4. data 文件：positions.json 36 bucket + 干净 init + transactions.json 空 + signals/index.json entries 空
5. 关键代码 grep 标记：QUANT_DATA_ROOT / NoOpNotifier / mergeFn / operation_id 都存在
6. AkShare 接口 13 + 13 实跑（--with-network 参数才跑）
7. pytest --co --tb=no 收集所有测试不报错
"""

# 用法：
#   python scripts/quant/check_readiness.py           # 不联网
#   python scripts/quant/check_readiness.py --with-network   # 含 AkShare 实跑
#
# 退出码：0 = 全 PASS；1 = 任一 FAIL；2 = 警告（非阻塞）
```

输出示例：

```
=== Quant Readiness Check (2026-04-26) ===

[配置] config.yaml 13 指数 ETF 完整                      ✅ PASS
[配置] .gitignore 不排除 signals/2*.json                ✅ PASS
[Workflow] quant.yml 多 mode 存在                       ✅ PASS
[Workflow] 旧 3 个 yml 已删除                           ✅ PASS
[Workflow] quant-heartbeat.yml 存在                     ✅ PASS
[Workflow] update.yml 含 morning-reconcile step         ✅ PASS
[数据] positions.json 36 bucket 干净 init               ✅ PASS
[数据] transactions.json 空数组                         ✅ PASS
[数据] signals/index.json entries 空                    ✅ PASS
[代码] QUANT_DATA_ROOT 环境变量已实施                    ✅ PASS
[代码] NoOpNotifier 类已实施                            ✅ PASS
[代码] writer.js mergeFn 模式已实施                      ✅ PASS
[代码] operation_id 幂等键已实施                         ✅ PASS
[测试] pytest 收集 86 + 6 用例                          ✅ PASS
[网络] AkShare 13 指数实时价                            ⏭️  SKIP（未带 --with-network）

总结：14 PASS / 0 FAIL / 1 SKIP
✅ 可以上线（建议补跑 --with-network 确认 AkShare 实时数据可达）
```

### D. 参考

- 设计文档：`docs/agents/quant/mvp-plan.md` v1.5
- 代码 review：`reviews/review-20260425-220431-d0c41d.md`
- plan review：`docs/agents/reviews/mvp-plan-review.md`
- V9.2 回测基线：`docs/agents/backtest/v9-summary.md`

### E. v2.x 设计变更日志

#### v2.1.1（2026-04-26 微调，回应 Codex Round 2 评审 4 条新发现）

| # | 修订 | 原 review |
|---|---|---|
| 24 | mock-test 加 **persist-credentials: false** + **git remote 改无效 URL + unset extraheader** 双保险，从 4 道硬门升 5 道 | N-1 mock 凭据绕过 |
| 25 | concurrency 从顶层固定 group 改为**动态 group**：mock-test 用 `quant-mock-test`、其他用 `quant-state-main`；矩阵与 yml 完全一致 | N-2 矩阵不一致 |
| 26 | 幂等检查从「业务 status 字段」改为**显式 `.runs/{mode}-{date}.done` 标记**，无信号日也安全；morning-reconcile 前置检查也用此标记 | N-3 幂等条件过窄 |
| 27 | 文末「review-ready v2.0」→ v2.1.1；P0 编号从 P0-1~P0-10 → C-1~C-20 | N-4 文档残留 |

#### v2.1（2026-04-26 修订，回应 Codex Round 1 评审 13 条）

| # | 变更 | 原 review 编号 |
|---|---|---|
| 11 | 14:48 主路 cron-job.org **+ 备路 GitHub schedule**（14:50 SGT）+ heartbeat 哨兵（14:55 检查） | C-1 单点故障 |
| 12 | signal mode 启动时**前置检查**昨日 morning-reconcile 已跑（fail-fast）| C-2 morning-reconcile 耦合 |
| 13 | 5 mode 加**全局 concurrency `quant-state-main`** + 互斥矩阵 + 启动幂等检查 | H-3 mode 互斥 |
| 14 | gh-pages deploy 加 concurrency group 防并发；明确 `publish_dir: ./docs` 增量含义 | H-4 同步并发 |
| 15 | mock-test 加 **5 道硬门**（v2.1.1 升级）：persist-credentials: false + git remote 改无效 URL + GITHUB_TOKEN 清空 + git status 零 diff 断言 + deploy 跳过 + NoOp | H-5 隔离不足 |
| 16 | mergeFn 加 **operation_id 幂等键** + 状态条件写（pending→confirmed 等）| H-6 缺幂等 |
| 17 | mergeFn 定义 **MergeResult 协议**（5 种 code：NOT_FOUND / ALREADY_DONE / SCHEMA_INVALID / CONFLICT / ok）+ 前端错误处理 | H-7 异常协议 |
| 18 | AkShare 加**降级策略矩阵**（缺失阈值 / 主备源 / 多源分歧）| H-8 备用方案缺细节 |
| 19 | paper→real 加**标准 migrate 脚本**（锁定窗口 / 归档 / 重置 / git tag / 渐进 Runbook）| M-9 切换混叠 |
| 20 | P0 拆 **P0-Core (20 项) + P0-Deferred (4 项)** + readiness 检查脚本 | M-10 复杂度 |
| 21 | PAT 双 token 加**月度轮换 Runbook**（拒绝 GitHub App 过度复杂）| H-11 安全成本 |
| 22 | 新增 **v1.5 → v2.0 兼容矩阵** 列出已实施 vs 待补 | M-12 基线冲突 |
| 23 | 全文术语统一 + **旧 → 新入口映射表** | L-13 文档残留 |

#### v2.0（2026-04-25 初稿，对比 v1.0）

| # | 变更 | 原因 | 影响 |
|---|---|---|---|
| 1 | gh-pages 同步从「每次 push 自动」改成「显式 mode 触发」 | 用户明确不要 push 自动发布 | 部署可控，不浪费 Actions 配额 |
| 2 | 3 个独立 quant workflow → 1 个 `quant.yml` 多 mode | 用户提议仿 update.yml 单文件多 mode | 维护成本降低，模式切换更清晰 |
| 3 | cron-job.org 任务 3 个 → **1 个**（仅 14:48）| 用户疑问 09:00 / 15:30 必要性 | 减少外部依赖（v2.1 加备路兜底）|
| 4 | 09:00 reconcile + 15:30 close-confirm 合并到 `morning-reconcile` mode | 15:30 数据不稳定（akshare 收盘价通常 16-17 点更新）| close-confirm 改用昨日真值，100% 稳定 |
| 5 | morning-reconcile 挂在 update.yml 早间钩子 | 复用现有 cron 链路 | 故障隔离 continue-on-error |
| 6 | 新增 `mock-test` mode + `QUANT_DATA_ROOT` 环境变量 | 用户要求 mock 测试不污染线上数据 | 完全隔离的测试环境（v2.1.1 加 5 道硬门）|
| 7 | 新增 `deploy` mode（仅同步不跑信号） | 紧急修复场景 | 资源同步与信号生成解耦 |
| 8 | writer.js 加 mergeFn 模式 | 防 lost-update | 多写者并发安全（v2.1 加 operation_id + schema 合同）|
| 9 | `.gitignore` 修订：去掉 `signals/2*.json` 排除 | 之前的 ignore 阻止线上 commit signals 进 git | 配合 QUANT_DATA_ROOT 隔离本地 demo |
| 10 | paper_trading commit message 加 `[PAPER]` 前缀 | 切实盘时易于筛选归档 | 实盘切换更安全 |

---

> **本文档为 review-ready v2.1.1 版本**。在按 P0-Core 上线前，建议你过一遍第一、二、二点五、三点五、五、七节，确保理解了「外部资源 / 部署机制 / 多 mode / 数据存储防覆盖 / 数据隔离 / 切实盘迁移」六大块。
>
> **下一步**：按第八节 C 的 **P0-Core C-1 ~ C-20**（17 项代码改动 + 4 项外部资源 + 4 项验收）实施；通过 readiness 检查后进入 Paper Trading（P1-A、P1-B）；10 工作日观察通过后切实盘（P2 含 D-1 migrate 脚本）。
