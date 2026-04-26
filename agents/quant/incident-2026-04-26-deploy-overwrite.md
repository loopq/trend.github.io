# 事故复盘与修复 plan：quant.yml deploy 覆盖主站首页

> 起草：2026-04-26
> 状态：用户已确认 4 项决策（紧急回滚 + 修 deploy + 纳入 D5/D6 + pre-commit hook + backfill archive）
> 用途：本文档自包含；新 session 仅靠本 plan 执行即可
> 适用对象：执行人 + Claude Code agent（不需要再回看对话历史）

---

## 一、事故复盘

### 1.1 事故发生顺序（git evidence）

| 时间（SGT）| commit | 事件 |
|---|---|---|
| 2026-04-25 08:01 | `27db7ba Update trend data - morning` | `update.yml`（鱼盆趋势主链路）跑 morning，把 **4-24** 数据生成到 docs/index.html 并 push 到 gh-pages，line 标题：`<title>鱼盆趋势模型v2.0 - 2026.04.24</title>` |
| 2026-04-26 14:34 | **`f51bb4e [quant] sync docs/ (mode=deploy, run=24950240961)`** | 用户手动触发新加的 quant.yml mode=deploy → peaceiris publish `./docs` 到 gh-pages → **main 上的 docs/index.html（停留在 4-12 旧版）覆盖 gh-pages**，线上首页回退到 `<title>鱼盆趋势模型v2.0 - 2026.04.12</title>` |
| 2026-04-26 14:43 | `4a137ef [quant] sync docs/ (mode=signal)` | cron-job test run 触发 quant.yml mode=signal → 又跑了一次 deploy step → 结果一样（main 没变，仍 4-12）|

事故仅持续不到 1 小时即被发现。

### 1.2 根因

`.github/workflows/quant.yml` 内的 deploy step：

```yaml
- uses: peaceiris/actions-gh-pages@v3
  with:
    publish_dir: ./docs   # ❌ 整个 docs 目录都同步到 gh-pages
    keep_files: true       # 这个只防止删除，不防止覆盖
```

**`keep_files: true` 的语义**：仅控制「不删除 gh-pages 上 publish_dir 里没有的文件」（所以 archive/2026-04-24.html 没丢）。**publish_dir 里有的文件依然会覆盖 gh-pages 上的同名文件**。

`docs/index.html` 在 main 分支长期是历史快照（最后修改 2026-04-13 commit `79ee454`），每次 quant.yml 调 deploy 都会把这个旧快照推到 gh-pages 覆盖最新版本。

### 1.3 影响范围

#### 主站首页

| 位置 | 当前状态 | 期望状态 |
|---|---|---|
| 线上 https://trend.loopq.cn/ | `2026.04.12` 数据（4-13 跑的） | `2026.04.24` 数据（4-25 早上 update.yml 跑的）|
| gh-pages 上 `index.html` | 同上 4-12 | 同上 4-24 |
| main 上 `docs/index.html` | 4-12（永远没变过）| 实际上 main 上的 docs/index.html 应该是历史快照，**不应该作为 deploy 源** |

#### archive 历史

| 时间段 | 状态 |
|---|---|
| 2026-01-16 ~ 01-30 | ✅ main + gh-pages 都有（9 个文件）|
| **2026-01-31 ~ 2026-04-11** | ❌ **完全缺失**（main 和 gh-pages 都没有，约 50 个交易日丢失）|
| 2026-04-12 | ✅ |
| 2026-04-23 | ✅（用户本地手动跑生成的，已 commit 进 main）|
| 2026-04-24 | ✅ gh-pages 有；main 没有（gh-pages 上的不会被本次事故删掉，因为 keep_files=true）|

archive 历史断层是事故前就存在的（update.yml 那段时间没跑成功），需要 backfill。

#### 数据安全

- ✅ `docs/data/quant/*` 量化系统数据全部安全
- ✅ `docs/quant/*` 量化前端代码全部安全
- ✅ 鱼盆趋势主链路代码（scripts/main.py 等）未被修改
- ❌ 仅 gh-pages 上 index.html 被覆盖到 4-12

---

## 二、修复决策（用户已确认）

| 决策项 | 选项 | 理由 |
|---|---|---|
| Q1 紧急回滚 4-24 数据 | **A. 立即手动恢复** | 不等明天 update.yml；同时恢复 history 缺失部分 |
| Q2 D5/D6 hotfix 是否纳入 | **纳入** | 修改量小，逻辑统一，避免周一 14:48 cron 重复警告 |
| Q3 pre-commit hook 防本地误推 | **纳入** | 一次性写好，安装一次永久生效 |
| Q4 backfill 1 月底-4 月初 archive | **A. 本次顺手做** | 历史数据完整性优先 |

---

## 三、执行步骤（按顺序，不可跳序）

### 前置：确认起点

```bash
cd /Users/loopq/dev/git/loopq/trend.github.io
git status --short
# 期望：未 push 的工作树有 1 个 hotfix commit（已存在）：
#   d1b3aa0 fix(quant): morning-reconcile 修复 + close-confirm 支持 --realtime auto
git log --oneline origin/main..HEAD
```

如果 `git status` 显示有任何 modified/untracked 文件，先用 `git stash` 暂存或 commit 干净。

### Step 1：紧急恢复 main 上的 docs/index.html + 找回 4-24 archive

**目的**：把 main 分支上的 `docs/index.html` 恢复到 4-24 版本（与 gh-pages 上 27db7ba 时一致）；同时把 gh-pages 上有但 main 上缺的 `archive/2026-04-24.html` 拉回 main。

```bash
cd /Users/loopq/dev/git/loopq/trend.github.io

# 1.1 从 27db7ba（gh-pages 上 4-25 那次推上去的 commit）拷出最新 index.html
git show 27db7ba:index.html > docs/index.html

# 1.2 拷 archive/2026-04-24.html
git show 27db7ba:archive/2026-04-24.html > docs/archive/2026-04-24.html

# 1.3 拷 archive/index.html（归档列表，可能也更新了）
git show 27db7ba:archive/index.html > docs/archive/index.html

# 1.4 验证拷贝结果
grep -o '<title>[^<]*' docs/index.html | head -1
# 期望：<title>鱼盆趋势模型v2.0 - 2026.04.24
ls -la docs/archive/2026-04-24.html
# 期望：文件大小 ≈ 55526 bytes

# 1.5 暂不 commit，留到 Step 7 一起 commit
```

### Step 2：修 quant.yml deploy step（核心防覆盖）

**目的**：让 quant.yml 推 gh-pages 时**只同步 quant 资源**，不动主站 index.html / archive。

**改动文件**：`.github/workflows/quant.yml`

找到现有的 deploy step（mode != mock-test 时跑），用以下内容替换：

```yaml
      # ============ deploy step（除 mock-test 外都跑；只同步 quant 资源不动主站）============
      - name: 准备 quant-only publish 目录（仅 quant 资源，绝不碰主站）
        if: steps.m.outputs.mode != 'mock-test'
        run: |
          set -e
          rm -rf /tmp/quant-publish
          mkdir -p /tmp/quant-publish/data
          # 仅拷贝 quant 子树，不碰 docs/index.html / docs/archive / docs/css / docs/js / docs/CNAME 等主站资源
          if [ -d docs/quant ]; then
            cp -r docs/quant /tmp/quant-publish/
          fi
          if [ -d docs/data/quant ]; then
            cp -r docs/data/quant /tmp/quant-publish/data/
          fi
          echo "publish 目录内容："
          find /tmp/quant-publish -type f | head -30
          echo "总文件数：$(find /tmp/quant-publish -type f | wc -l)"

      - name: 同步 quant-only 目录到 gh-pages（keep_files=true 保留主站既有）
        if: steps.m.outputs.mode != 'mock-test'
        uses: peaceiris/actions-gh-pages@v3
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: /tmp/quant-publish
          keep_files: true   # 必须 true，保留 gh-pages 上的 index.html / archive / css / js / CNAME
          user_name: 'github-actions[bot]'
          user_email: 'github-actions[bot]@users.noreply.github.com'
          commit_message: '[quant] sync /quant + /data/quant (mode=${{ steps.m.outputs.mode }}, run=${{ github.run_id }})'
```

**关键变化**：
- `publish_dir` 从 `./docs`（约 270 个文件）改为 `/tmp/quant-publish`（仅 50+ 个 quant 相关文件）
- 主站 `index.html` / `archive/` / `css/` / `js/` / `CNAME` **物理上不在 publish_dir 里**，永远无法被 quant 推送过程触碰

### Step 3：D5 hotfix — quant.yml signal mode 前置检查智能找前一交易日

**目的**：当前实现用 `date -1d` 找昨日，遇到周一会找周日（非交易日）从而误报「昨日 morning-reconcile 未跑」。改用 Python 调 `trigger.is_trading_day` 找前一**工作日**。

**改动文件**：`.github/workflows/quant.yml`

找到 `前置检查（signal）— 昨日 morning-reconcile 已完成` step，整体替换为：

```yaml
      - name: 前置检查（signal）— 前一工作日 morning-reconcile 已完成
        if: steps.m.outputs.mode == 'signal' && env.SKIP_SIGNAL != 'true'
        run: |
          # 用 Python 找前一个工作日（跳过周末）
          PREV_WORKDAY=$(python3 -c "
          from datetime import date, timedelta
          d = date.fromisoformat('${{ steps.m.outputs.TODAY }}')
          d -= timedelta(days=1)
          while d.weekday() >= 5:
              d -= timedelta(days=1)
          print(d.strftime('%Y-%m-%d'))
          ")
          DONE_FILE="docs/data/quant/.runs/morning-reconcile-${PREV_WORKDAY}.done"
          if [ ! -f "$DONE_FILE" ]; then
            MSG="⚠️ 量化前置检查：前一工作日 ${PREV_WORKDAY} 的 morning-reconcile 未跑，今日 signal 可能用陈旧 yesterday_policy"
            echo "::warning::$MSG"
            curl -s -X POST "${{ secrets.FEISHU_WEBHOOK_URL }}" \
              -H "Content-Type: application/json" \
              -d "{\"msg_type\":\"text\",\"content\":{\"text\":\"$MSG\"}}" || true
          else
            echo "::notice::✅ 前一工作日 ${PREV_WORKDAY} 的 morning-reconcile 已完成"
          fi
```

**关键变化**：
- 用 Python 找前一工作日（避免周一找周日的 bug）
- 周一找上周五 / 周二找周一（正确逻辑）

### Step 4：D6 hotfix 验证（已在 hotfix commit `d1b3aa0` 中修了）

**已修内容**（无需再改代码）：
- `cmd_morning_reconcile`：用 `today - timedelta(days=1)` 找前一工作日（跳周末）
- 检查 `signals/{yesterday}.json` 是否存在再调 `confirm_signals_with_close`，没存在则 skip 标记 `no signals file for yesterday`
- 全套 86 pytest 通过

**本 step 仅做验证**，命令：

```bash
cd /Users/loopq/dev/git/loopq/trend.github.io
source venv/bin/activate
python -m pytest scripts/quant/tests/ --tb=short -q
# 期望：86 passed
```

### Step 5：pre-commit hook 防本地误推 docs/index.html / docs/archive/{date}.html

**目的**：本地 `git commit` 含主站 docs 文件改动时报警 + 拒绝（除非 `--no-verify`）。

#### 5.1 创建 hook 脚本

**新建文件**：`scripts/git-hooks/pre-commit`

```bash
#!/bin/bash
# 量化系统：防本地误推主站 docs 文件 hook
# 检测 commit 是否含 docs/index.html 或 docs/archive/{YYYY-MM-DD}.html 改动
# 命中则报警并拒绝；如确实需要 commit（如 backfill 历史），用 git commit --no-verify

set -e

DOCS_CHANGED=$(git diff --cached --name-only --diff-filter=ACMRT 2>/dev/null \
  | grep -E '^docs/(index\.html|archive/[0-9]{4}-[0-9]{2}-[0-9]{2}\.html|archive/index\.html)$' || true)

if [ -n "$DOCS_CHANGED" ]; then
  echo "" >&2
  echo "🚨 pre-commit hook 拒绝：检测到主站 docs 文件改动" >&2
  echo "" >&2
  echo "改动的文件：" >&2
  echo "$DOCS_CHANGED" | sed 's/^/  - /' >&2
  echo "" >&2
  echo "原因：这些文件由 GitHub Actions update.yml 自动生成 + 推到 gh-pages，" >&2
  echo "      本地 commit 它们会污染 main 分支，导致下次 deploy 把过时版本覆盖到线上。" >&2
  echo "" >&2
  echo "解决：" >&2
  echo "  - 如果是本地跑 main.py morning 测试产生的，请丢弃改动：" >&2
  echo "      git restore --staged docs/index.html docs/archive/" >&2
  echo "      git restore docs/index.html docs/archive/" >&2
  echo "" >&2
  echo "  - 如果确实要 commit（例如 backfill 历史 archive），用 --no-verify：" >&2
  echo "      git commit --no-verify -m 'fix: backfill archive 2026-XX-XX'" >&2
  echo "" >&2
  exit 1
fi

exit 0
```

#### 5.2 创建一键安装脚本

**新建文件**：`scripts/install-hooks.sh`

```bash
#!/bin/bash
# 一键安装 git pre-commit hook
# 用法：bash scripts/install-hooks.sh

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK_SRC="$PROJECT_ROOT/scripts/git-hooks/pre-commit"
HOOK_DST="$PROJECT_ROOT/.git/hooks/pre-commit"

if [ ! -f "$HOOK_SRC" ]; then
  echo "❌ source hook 不存在: $HOOK_SRC"
  exit 1
fi

mkdir -p "$PROJECT_ROOT/.git/hooks"

# 备份已有 hook（如果有）
if [ -f "$HOOK_DST" ] && [ ! -L "$HOOK_DST" ]; then
  cp "$HOOK_DST" "$HOOK_DST.bak.$(date +%s)"
  echo "已备份已有 hook 到 $HOOK_DST.bak.<timestamp>"
fi

# 安装 symlink（这样以后改 source 自动生效）
ln -sfn "$HOOK_SRC" "$HOOK_DST"
chmod +x "$HOOK_SRC"

echo "✅ pre-commit hook 已安装: $HOOK_DST → $HOOK_SRC"
echo ""
echo "测试 hook："
echo "  echo 'test' >> docs/index.html"
echo "  git add docs/index.html"
echo "  git commit -m 'test'   # 应被拒绝"
echo "  git restore --staged docs/index.html && git restore docs/index.html"
```

#### 5.3 安装并测试 hook

```bash
chmod +x scripts/git-hooks/pre-commit scripts/install-hooks.sh
bash scripts/install-hooks.sh
# 期望：✅ pre-commit hook 已安装
```

### Step 6：backfill 1 月底-4 月初的 archive 历史

**目的**：补 main 分支上 `2026-01-31` 至 `2026-04-11` 之间的 archive html 文件（约 50 个交易日缺失）。

**注意**：这一步会通过 backfill_archive.py 调 AkShare API 拉历史数据 + 用 generator 重新生成 archive html。**因为我们刚装了 pre-commit hook，commit 这些 archive 改动需要 `--no-verify`**。

```bash
cd /Users/loopq/dev/git/loopq/trend.github.io
source venv/bin/activate

# 6.1 先验证 backfill 命令（dry-run 一天）
python scripts/backfill_archive.py --start 2026-02-03 --end 2026-02-03 --debug 2>&1 | head -20
# 期望：输出找到交易日 + 生成 docs/archive/2026-02-03.html

# 6.2 真正跑 backfill 1 月底到 4 月初
python scripts/backfill_archive.py --start 2026-02-03 --end 2026-04-11
# 注意：1-31 ~ 2-2 是周末，跳过；--start 2026-02-03 是 2 月第一个交易日
# 期望：脚本会跳过非交易日，只生成交易日的 archive
# 工作量预估：约 50 个交易日 × 每天 30s API 调用 = 25 分钟

# 6.3 验证生成情况
ls docs/archive/2026-02-*.html docs/archive/2026-03-*.html docs/archive/2026-04-0*.html docs/archive/2026-04-1*.html 2>&1 | head -20
echo "---"
echo "新生成 archive 文件数：$(ls docs/archive/2026-02-*.html docs/archive/2026-03-*.html docs/archive/2026-04-0*.html docs/archive/2026-04-1*.html 2>/dev/null | wc -l)"
# 期望：约 50 个文件

# 6.4 重新生成 archive/index.html（归档列表页）
# backfill_archive.py 应该会自动更新 index；如果没有，跑一次 main.py 生成（但这会改 docs/index.html，需要后续 restore）
# 简单做法：让 backfill 自己重新写 index.html 列表，不动主页 docs/index.html

# 6.5 验证主页 docs/index.html 没有被改回 4-12
grep -o '<title>[^<]*' docs/index.html | head -1
# 期望仍然：<title>鱼盆趋势模型v2.0 - 2026.04.24
# 如果变成其他日期，说明 backfill_archive.py 误改了 index.html，需要还原：
#   git show 27db7ba:index.html > docs/index.html
```

**重要**：如果 `backfill_archive.py` 副作用改了 `docs/index.html`（不应该，但要 verify），用 `git show 27db7ba:index.html > docs/index.html` 还原。

### Step 7：验收 + commit + push + 部署

#### 7.1 跑全套测试

```bash
source venv/bin/activate
python -m pytest scripts/quant/tests/ --tb=short -q
# 期望：86 passed

python scripts/quant/check_readiness.py
# 期望：31 PASS / 0 FAIL

python scripts/quant/tests/run_browser_tests.py
# 期望：10/10 passed
```

#### 7.2 验证修改文件清单

```bash
git status --short
# 期望看到（含已经存在的 hotfix d1b3aa0 之外的新改动）：
#   M  .github/workflows/quant.yml          ← Step 2 + Step 3
#   M  docs/index.html                      ← Step 1
#   M  docs/archive/index.html              ← Step 1
#   ?? docs/archive/2026-04-24.html         ← Step 1
#   ?? docs/archive/2026-02-03.html ... 2026-04-11.html  ← Step 6（约 50 个）
#   ?? scripts/git-hooks/pre-commit         ← Step 5
#   ?? scripts/install-hooks.sh             ← Step 5
```

#### 7.3 commit（注意 docs/* 改动需用 --no-verify）

分两次 commit，便于追溯：

```bash
# Commit A：quant 系统修复（D5/D6 + deploy 不覆盖主站 + pre-commit hook）
git add .github/workflows/quant.yml \
        scripts/git-hooks/pre-commit \
        scripts/install-hooks.sh
git commit -m "$(cat <<'EOF'
fix(quant): deploy step 仅同步 quant 资源 + D5 前置检查智能找前一工作日 + pre-commit hook 防本地误推

事故复盘：2026-04-26 14:34 quant.yml mode=deploy 触发时，peaceiris publish_dir: ./docs 把 main 上停留在 4-12 的旧 docs/index.html 推到 gh-pages 覆盖了线上最新的 4-24 版本。

修复（事故原因）：
- quant.yml deploy step 改用 /tmp/quant-publish 临时目录（仅含 docs/quant + docs/data/quant），物理上不可能覆盖 docs/index.html 等主站资源
- keep_files=true 配合保留 gh-pages 上 update.yml 维护的 index.html / archive / css / js / CNAME

D5 hotfix：
- quant.yml signal mode 前置检查改用 Python 找前一工作日（替代 date -1d 周一找周日的 bug）
- 周一会找上周五，周二找周一

防本地误推：
- 新增 scripts/git-hooks/pre-commit：检测 docs/index.html / docs/archive/{date}.html 改动则拒绝 commit
- 新增 scripts/install-hooks.sh：一键 ln -s 到 .git/hooks/pre-commit
- backfill / 紧急修复时用 git commit --no-verify 跳过

完整事故 plan：docs/agents/quant/incident-2026-04-26-deploy-overwrite.md
EOF
)"

# Commit B：紧急恢复线上 4-24 数据 + backfill 历史 archive（用 --no-verify 因为含 docs/* 改动）
git add docs/index.html docs/archive/
git commit --no-verify -m "$(cat <<'EOF'
fix: 紧急恢复线上首页到 4-24 数据 + backfill 1 月底-4 月初 archive 历史

紧急恢复（来自 gh-pages commit 27db7ba 的 4-25 早间 update.yml 推送）：
- docs/index.html: 从 4-12 → 2026-04-24 数据
- docs/archive/2026-04-24.html: gh-pages 上有但 main 上缺失的归档
- docs/archive/index.html: 归档列表页

backfill 历史（约 50 个交易日 archive html）：
- docs/archive/2026-02-03.html ~ 2026-04-11.html
- 来源：scripts/backfill_archive.py 调 AkShare 历史数据生成
- 目的：history 不间断（事故前 update.yml 在这段时间没跑成功）

注：本 commit 用 --no-verify 跳过 pre-commit hook（hook 检测 docs/* 改动是预期保护）
EOF
)"

# 验证
git log --oneline origin/main..HEAD
# 期望（从旧到新）：
#   d1b3aa0 fix(quant): morning-reconcile 修复 + close-confirm 支持 --realtime auto
#   <new1>  fix(quant): deploy step 仅同步 quant 资源 + ...
#   <new2>  fix: 紧急恢复线上首页到 4-24 数据 + backfill ...
```

#### 7.4 push 到远端

```bash
git push origin main
```

#### 7.5 触发 deploy mode 把修复后的 quant + 4-24 主页推上 gh-pages

```bash
# 命令行 dispatch（需要 gh CLI 已认证）
gh workflow run quant.yml -f mode=deploy

# 或浏览器：https://github.com/loopq/trend.github.io/actions/workflows/quant.yml
# → Run workflow → mode=deploy
```

等 1-2 分钟，workflow 跑完。

#### 7.6 线上验证

```bash
sleep 90  # 等 gh-pages 部署完成

# 主站应回到 4-24
/usr/bin/curl -s https://trend.loopq.cn/ | grep -o '<title>[^<]*' | head -1
# 期望：<title>鱼盆趋势模型v2.0 - 2026.04.24

# archive/2026-04-24.html 仍在
/usr/bin/curl -s -o /dev/null -w "HTTP %{http_code}\n" https://trend.loopq.cn/archive/2026-04-24.html
# 期望：HTTP 200

# 抽样验证 backfill 文件
/usr/bin/curl -s -o /dev/null -w "HTTP %{http_code}\n" https://trend.loopq.cn/archive/2026-03-15.html
# 期望：HTTP 200

# quant 入口仍正常
/usr/bin/curl -s -o /dev/null -w "HTTP %{http_code}\n" https://trend.loopq.cn/quant/
# 期望：HTTP 200
```

#### 7.7 浏览器最终验证

打开 https://trend.loopq.cn/

期望看到：
- 标题：「鱼盆趋势模型v2.0 - 2026.04.24」
- 多空 PK 仪表盘 / 板块数据 / 归档链接等都正常
- 点击「归档列表」→ 能看到 1 月份 9 个 + 2-3-4 月新 backfill 的 50 个 + 4-12/4-23/4-24 共约 60 个 archive 文件

打开 https://trend.loopq.cn/quant/ → 输 `weiaini` → 看到干净 init 状态（如 plan v2.1.1 描述）。

---

## 四、验收清单（全部必过）

| 验收项 | 期望 |
|---|---|
| `git log` 含 3 个 commit（d1b3aa0 + 2 个新）| ✅ |
| pytest 86/86 全过 | ✅ |
| readiness check 31/31 PASS | ✅ |
| selenium 前端测试 10/10 | ✅ |
| pre-commit hook 已安装 + 测试拒绝 docs/index.html 改动 | ✅ |
| 线上 https://trend.loopq.cn/ 标题为 2026.04.24 | ✅ |
| 线上 archive 文件数 > 60（含新 backfill）| ✅ |
| 线上 https://trend.loopq.cn/quant/ HTTP 200 | ✅ |
| `gh workflow run quant.yml -f mode=mock-test` 仍跑通 5 道硬门 | ✅ |
| **手动测试**：`echo x >> docs/index.html && git add docs/index.html && git commit -m 'test'` 应被 hook 拒绝 | ✅ |

---

## 五、风险点 + 回滚预案

### 5.1 backfill API 失败 / 部分日期跑不出来

**症状**：`backfill_archive.py` 报 AkShare 接口超时 / 数据缺失

**处理**：
1. 重试 `python scripts/backfill_archive.py --start <跳过的日期>`
2. 如某些日期实在拉不到（API 历史数据缺失），可以接受 history 仍部分缺失，先做主修复（Step 1-5 + Step 7），backfill 单独后续做

### 5.2 quant.yml deploy step 修改后 mock-test 不工作

**症状**：mock-test 模式触发的 quant.yml 在新的 deploy step 上失败

**根因排查**：deploy step 已加 `if: steps.m.outputs.mode != 'mock-test'`，应不会跑。如果跑了，检查 if 条件 yaml 语法。

### 5.3 pre-commit hook 误拦正常工作流

**症状**：本地 commit 普通量化代码改动也被 hook 拒绝

**根因**：检查 `git diff --cached --name-only` 是否真的没有 docs/index.html / archive/{date}.html。

**绕过**：临时 `git commit --no-verify`；或卸载 hook：`rm .git/hooks/pre-commit`。

### 5.4 push 后 line index.html 仍是 4-12

**症状**：Step 7.6 验证发现线上仍 4-12

**排查**：
1. `gh workflow run quant.yml -f mode=deploy` 是否真的跑完？看 Actions 页面
2. peaceiris publish 是否真的从 `/tmp/quant-publish` 推（而不是 `./docs`）？看 workflow log
3. 如果 deploy 跑完但线上还是 4-12，说明 main.docs/index.html 没被恢复——重做 Step 1.1

### 5.5 紧急回滚（如果整个事故修复反而把事情搞糟）

```bash
# 回滚到事故修复前的状态（hotfix d1b3aa0 之前的最后一个 commit）
git reset --hard 47aeba5

# 然后重新 push
git push origin main --force-with-lease

# 注意：gh-pages 不需要回滚——它一直是 update.yml 单独维护的，
#       quant.yml deploy 修复后不再覆盖
```

---

## 六、附录：相关 commit SHA / 文件路径

### 关键 commit

| SHA | 含义 |
|---|---|
| `27db7ba` | 4-25 早间 update.yml 推上 gh-pages 的「正确版」index.html（4-24 数据），Step 1 从这恢复 |
| `f51bb4e` | **事故 commit**：4-26 14:34 quant.yml mode=deploy 把 main.docs 推到 gh-pages 覆盖 |
| `4a137ef` | 4-26 14:43 cron test 触发的 quant.yml mode=signal，又跑了一次 deploy（无害）|
| `47aeba5` | 事故修复前的最后稳定 commit（量化 P0-Core 重构）|
| `d1b3aa0` | 已 commit 的 hotfix（morning-reconcile + close-confirm --realtime auto）|

### 关键文件

| 文件 | 作用 |
|---|---|
| `.github/workflows/quant.yml` | 量化主控 workflow（Step 2 + Step 3 修改）|
| `.github/workflows/update.yml` | 鱼盆趋势主链路 workflow（**本事故不修改**）|
| `docs/index.html` | 主站首页（Step 1 紧急恢复）|
| `docs/archive/2026-04-24.html` | gh-pages 有 main 缺（Step 1 找回）|
| `docs/archive/{2026-02-03 至 2026-04-11}.html` | 缺失的 history（Step 6 backfill）|
| `scripts/git-hooks/pre-commit` | 防本地误推 hook（Step 5 新建）|
| `scripts/install-hooks.sh` | 一键安装 hook（Step 5 新建）|
| `scripts/backfill_archive.py` | 历史 archive 生成（已存在，Step 6 调用）|
| `scripts/quant/run_signal.py` | morning-reconcile / close-confirm（hotfix d1b3aa0 已修，无新改）|
| `scripts/quant/tests/test_*.py` | 86 个测试用例（Step 4 / Step 7 验证）|

### 关键命令速查

```bash
# 紧急恢复（Step 1）
git show 27db7ba:index.html > docs/index.html
git show 27db7ba:archive/2026-04-24.html > docs/archive/2026-04-24.html
git show 27db7ba:archive/index.html > docs/archive/index.html

# Backfill（Step 6）
python scripts/backfill_archive.py --start 2026-02-03 --end 2026-04-11

# 装 hook（Step 5）
bash scripts/install-hooks.sh

# 测试 + 验收（Step 7.1）
source venv/bin/activate
python -m pytest scripts/quant/tests/ --tb=short -q
python scripts/quant/check_readiness.py

# 修复 commit（Step 7.3）
git add .github/workflows/quant.yml scripts/git-hooks/ scripts/install-hooks.sh
git commit -m "fix(quant): deploy step 仅同步 quant 资源 + D5 + pre-commit hook"

git add docs/index.html docs/archive/
git commit --no-verify -m "fix: 紧急恢复 4-24 + backfill archive"

# Push + deploy（Step 7.4-5）
git push origin main
gh workflow run quant.yml -f mode=deploy

# 线上验证（Step 7.6）
/usr/bin/curl -s https://trend.loopq.cn/ | grep -o '<title>[^<]*'
```

---

## 七、约束 + 注意事项

1. **不要修改 `.github/workflows/update.yml`** — 鱼盆趋势主链路保持原状
2. **不要修改 `scripts/main.py` / `scripts/data_fetcher.py` / `scripts/calculator.py` / `scripts/generator.py` / `scripts/ranking_store.py`** — 主链路代码不动
3. **commit 顺序很重要**：先 commit「修 quant + 装 hook」（不含 docs/*），再 commit「恢复 + backfill docs」（用 --no-verify）。如果反过来，hook 还没安装，第一次 commit 不会被拦——但 docs/* 还是会被 push 上去（结果一样）。坚持顺序为了**测试 hook 真的工作**。
4. **本 plan 文档自身也要 commit**：放 `docs/agents/quant/incident-2026-04-26-deploy-overwrite.md`，与 fix commit 同 push
5. 完成后**保留** `docs/agents/quant/deployment-plan.md`（v2.1.1）；本 incident plan 是临时事故响应文档，作为 deployment-plan 的子事件存档

---

> **完成本 plan 后预期效果**：
> - 线上 https://trend.loopq.cn/ 显示 2026-04-24 数据 ✅
> - history archive 从 2026-01-16 到 2026-04-24 完整无缺 ✅
> - quant.yml deploy step 永远不会覆盖主站 index.html / archive / css / js ✅
> - 周一 14:48 cron 触发 signal 时不会再误报「昨日 morning-reconcile 未跑」✅
> - 本地 git commit docs/index.html 会被 pre-commit hook 拒绝 ✅
> - quant 系统所有功能正常（86 pytest + 31 readiness + 10 selenium 全过）✅
