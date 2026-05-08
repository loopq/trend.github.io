# 事故复盘 + 全链路修复 plan：quant morning-reconcile 跑通 + cache 实现

> 起草：2026-04-27（Round 1 review 后大改）
> 状态：Round 1 review 已落地——20 issues 中 19 接受、1 反驳（Issue 1 见 §10.1）→ 实施
> 用途：本文档自包含；新 session 仅靠本 plan 执行即可
> 适用对象：执行人 + Claude Code agent

---

## 一、事故现象

### 1.1 时间线

| 时间（SGT） | 事件 |
|---|---|
| 2026-04-24（周五）08:00 | 主站 update.yml mode=morning 触发，**内含 `Quant morning-reconcile` step（line 66-72），continue-on-error: true 静默吞错**（git config 缺失）→ morning-reconcile 实际未跑 |
| 2026-04-25 ~ 04-26 | 周末，无操作 |
| 2026-04-27（周一）08:00 | 主站 update.yml 又跑，quant step 又静默失败 |
| 2026-04-27 14:48 | quant.yml mode=signal 触发：飞书发出"前一工作日 04-24 morning-reconcile 未跑"前置警告；signal 跑完 13 个指数 / 14 个 trigger_buckets（**MA20 极可能全为 NaN**，因 cache 空），到 commit_atomic() 因 git config 缺失 → exit 1 |

### 1.2 关键报错

```
subprocess.CalledProcessError: Command '['git', 'commit', '-m', '[quant] signal generation 2026-04-27']' returned non-zero exit status 128.
scripts.quant.writer.WriterError: git commit failed: Author identity unknown
fatal: empty ident name (for <runner@runnervmeorf1.khuyxa00f1durmelsdgvmvfuth.cx.internal.cloudapp.net>) not allowed
```

### 1.3 仓库当前实际状态

| 文件 | 状态 |
|---|---|
| `docs/data/quant/cache/` | 仅 `.gitkeep`，**13 指数日线 cache 全空** |
| `docs/data/quant/signals/` | 仅 `index.json`，**无任何 day signal 文件** |
| `docs/data/quant/positions.json` | 初始 CASH 态（updated_at 2026-04-25，init 后从未动过） |
| `docs/data/quant/.runs/` | 仅 `signal-2026-04-26.done`（疑测试残留） |

---

## 二、根因诊断（三个独立 bug + 多处违规）

### 2.1 P0-Bug A：所有 yml 缺全局 git config（阻塞性）

`scripts/quant/writer.py:82-87` 的 `LocalWriter.commit_atomic()` 内部直接 `subprocess.run(["git", "commit", ...])`。但：

- `.github/workflows/quant.yml` line 130-141 跑 signal、line 165-172 跑 morning-reconcile 之前**从未配置 git config**
- `.github/workflows/update.yml` line 66-72 的 `Quant morning-reconcile` step 也**没配 git config**，且 `continue-on-error: true` 把异常吞掉

**后果**：
- 04-27 14:48 signal 显式失败
- 主站 update.yml 早 8 点的 quant step 自上线起**从未真正跑通**（静默吞错）
- 这就是 cache 长期为空、04-24 morning-reconcile 缺失的根本原因

### 2.2 P0-Bug B：前置检查 done 文件命名错位（语义错位）

```python
# run_signal.py:163  morning-reconcile 写 today.done
done_file = _runs_done_file(... "morning-reconcile", today.strftime("%Y-%m-%d"))

# run_signal.py:47  signal 前置检查找 yesterday.done
return _runs_done_file(... "morning-reconcile", yesterday.strftime("%Y-%m-%d")).exists()
```

**核心证据链**（必读，否则会误以为现有命名是对的，详见 §10.1 反驳论证）：

```
signal_generator.py:185:  yesterday_policy = bucket.policy_state
                                              │
                                              ▼
                          这是当下 positions.json 的 policy_state
                                              │
                                              ▼
                          最近一次更新者：close_confirm.py:113
                                              │
                                              ▼
                          close-confirm 在 cmd_morning_reconcile 内被调
                                              │
                                              ▼
                          run_signal.py:183-186  today=yesterday（处理 D-1 真值）
```

**所以**：
- D 日 14:48 signal 的 `yesterday_policy` = 上次 close-confirm 写入的 policy_state
- D 日 14:48 想要的语义是"D-1 真值已被 confirm"
- 处理 D-1 真值的是 **D 日 09:05 morning**（不是 D-1 日 morning——D-1 日 morning 处理的是 D-2 真值）
- 因此前置检查必须找 **D 日 morning 是否已跑** → `morning-reconcile-{D}.done` → 即 `today.done`

**现有代码找 yesterday.done 是设计 bug**：那个 done 文件的语义是"D-1 日 morning 已跑（处理了 D-2 真值）"——和 D 日 14:48 signal 用的 yesterday_policy 没有关联。

### 2.3 P1-Bug C：cache 写入路径零实现（功能缺失）

```bash
$ grep -rn "write_cache\|append_daily" scripts/quant/ --include="*.py" | grep -v test_
scripts/quant/cache.py:30:def write_cache(...)         # 定义
scripts/quant/cache.py:42:def append_daily(...)        # 定义
scripts/quant/cache.py:50:    write_cache(...)         # 内部互调
```

**整个 quant 子系统没有任何代码调 `write_cache` / `append_daily`**：

- `cache.py` 提供了完整 read/write/append 工具集，但没人写
- `data_fetcher.py`（quant 版）没有历史日线接口，只有 `stock_zh_index_spot_em`（实时）+ `stock_zh_index_daily`（取最新一行）
- `mvp-plan.md` line 1129 提到的独立 `update_cache.py` 不存在
- `signal_generator.py:179` 和 `close_confirm.py:78,102` 都 `read_cache`，但读到的永远是空 DataFrame，导致 `splice_realtime` 后只有"today"一行，`compute_ma20` 必然返回 NaN

### 2.4 已知架构违规（顺势在本次范围内一并修）

#### 2.4.1 `cmd_morning_reconcile` 内部 3 笔独立 commit，破坏 mvp-plan §3.7 "单 commit 多文件原子提交"

```python
# run_signal.py:160-209 当前
confirm_signals_with_close(...)        # close_confirm.py:130-139 内部 writer.commit_atomic([3 files])
reconcile_pending_signals(...)         # reconcile.py:84       内部 writer.commit_atomic([N files])
writer.commit_atomic([done_file], ...) # run_signal.py:200     第 3 笔
```

morning-reconcile 实际是 **3 笔有序 commit**，不是设计承诺的"一次原子提交"。Phase 2 加 cache 写入会变成第 4 笔——架构错位必须先修。

#### 2.4.2 `cmd_signal_for_one_day` 直接 `write_text` 写 done，绕过 LocalWriter

```python
# run_signal.py:144-149
done_file.parent.mkdir(parents=True, exist_ok=True)
done_file.write_text(json.dumps({...}))   # ← 绕过 writer
```

#### 2.4.3 `quant.yml:142-153` shell 直接 mkdir + cat + git add + git commit + git push 写 signal-{date}.done，绕过 LocalWriter

完全自起炉灶，**违反 writer.py 顶部硬约束**："禁止任何代码绕过本抽象直接写状态文件"。

#### 2.4.4 cache 文件会同时进 main 和 gh-pages（若不显式排除）

- `update.yml:81` `peaceiris publish_dir: ./docs` 直接发布整个 docs（含 cache 子目录）
- `quant.yml:252` `publish_dir: /tmp/quant-publish` 由前置 step 把 `docs/data/quant` 整体 cp 进去，**也会包含 cache**

违反"cache 只进 main"设计意图。

---

## 三、终极目标（基于 mvp-plan 设计意图）

```
                  ┌──────────────────────────┐
                  │  cache/{code}.csv        │  ← 仅在 main，不在 gh-pages
                  │  历史日线（800 天起）    │
                  └────────┬─────────────────┘
                           │ read
                           ▼
   morning 8:00 ──────► splice ◄──── 14:48 signal
   增量 append ▲           │           │ (拼当日实时)
              │            ▼           ▼
        历史日线增量    MA20         MA20
        (akshare retry)  (回正)       (信号)
        ↓
      单 commit 多文件原子提交
      (cache + positions + signals + done)
```

**核心约束**：
- 历史记录缓存（cache/{code}.csv，13 指数，每日 append）
- 当天行情实时获取（fetcher.fetch_indices，不缓存）
- morning 写 cache，signal 读 cache + 实时拼接
- **每次 morning-reconcile 是 1 笔 commit；每次 signal 是 1 笔 commit**（mvp-plan §3.7 硬约束）
- cache 进 main 不进 gh-pages

---

## 四、修复方案（两 phase 顺序实施）

### Phase 1：基础设施（修 P0-A + P0-B + 已知违规 2.4.2/2.4.3 + concurrency）

#### 1.1 update.yml：加 git config + concurrency + push 重试不静默 + 排除 cache from gh-pages

**位置**：`.github/workflows/update.yml`

**改动 1（顶层加 concurrency，与 quant.yml 共享 group）**：

```yaml
on: ...

concurrency:
  group: quant-state-main
  cancel-in-progress: false

jobs: ...
```

> 这避免 update.yml 与 quant.yml 同时 push main 的竞态。两边都用 `quant-state-main` group → 排队执行不并发。

**改动 2（在 `Setup Python` step 之后、`Install dependencies` 之前新增）**：

```yaml
- name: Configure git identity（quant morning-reconcile 内部 commit 用）
  run: |
    git config user.email "github-actions[bot]@users.noreply.github.com"
    git config user.name "github-actions[bot]"
```

**改动 3（line 66-72 Quant morning-reconcile step 之后、Deploy 之前，加可见的 push step，去掉 `|| true`）**：

```yaml
- name: Push quant morning-reconcile commits（不静默吞错）
  if: steps.run_script.outputs.should_deploy == 'true' && steps.mode.outputs.mode == 'morning'
  continue-on-error: true   # 此 step 失败仍允许主站 trend deploy 继续；但失败必须可见
  run: |
    set -e
    for i in 1 2 3; do
      if git pull --rebase --autostash origin main && git push origin main; then
        echo "✅ quant morning-reconcile commits pushed"
        exit 0
      fi
      echo "::warning::push 失败（attempt $i/3），sleep 后重试"
      sleep $((RANDOM % 10 + 5))
    done
    echo "::error::quant morning-reconcile push failed after 3 retries"
    exit 1
```

> `continue-on-error: true` 保留——主站趋势数据推送不应因 quant 失败而阻塞；但 step 内部不再 `|| true`，**失败有 warning + error annotation 可见**（不会再像 Bug A 那样静默吞）。

**改动 4（line 76-84 peaceiris step 增加 cache 排除）**：

```yaml
- name: Deploy to GitHub Pages
  if: steps.run_script.outputs.should_deploy == 'true'
  uses: peaceiris/actions-gh-pages@v4
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
    publish_dir: ./docs
    exclude_assets: '.github,data/quant/cache/**'   # ← 保留默认 .github 排除 + 新增 cache 排除（peaceiris@v4 自定义会覆盖默认值）
    user_name: 'github-actions[bot]'
    user_email: 'github-actions[bot]@users.noreply.github.com'
    commit_message: 'Update trend data - ${{ steps.mode.outputs.mode }}'
```

> peaceiris@v4 `exclude_assets` 默认值是 `.github`（已通过 README 验证支持 glob 逗号分隔）。**自定义会完全覆盖默认值**——必须显式写 `'.github,data/quant/cache/**'`，否则 `.github` workflow 配置会被发布到 gh-pages 泄漏。

#### 1.2 quant.yml：加 git config + 删两处重复 + 删 line 142-153 + 排除 cache from gh-pages

**位置**：`.github/workflows/quant.yml`

**改动 1（在 `Install dependencies` step 之后、所有 mode 分支之前新增）**：

```yaml
- name: Configure git identity（所有 mode 共用，mock-test 也无害）
  run: |
    git config user.email "github-actions[bot]@users.noreply.github.com"
    git config user.name "github-actions[bot]"
```

> mock-test 顺序兼容：硬门 #1（line 74-79，移除 git remote 凭据）在 line 91 Install deps **之前**已经跑完，git config 在它之后跑——不影响隔离。硬门 #3（line 199-205，零 diff）也不破——git config 写 .git/config 不入工作区。

**改动 2（删除）**：

- line 149-150（写 .runs/done step 内部的 `git config`）
- line 177-178（push morning-reconcile step 内部的 `git config`）

**改动 2.5（重写 line 107-128 shell 前置检查 — 与 Python 端 today.done 语义对齐，避免双重真相源）**：

```yaml
- name: 前置检查（signal）— 今日 morning-reconcile 已完成
  if: steps.m.outputs.mode == 'signal' && env.SKIP_SIGNAL != 'true'
  run: |
    DONE_FILE="docs/data/quant/.runs/morning-reconcile-${{ steps.m.outputs.TODAY }}.done"
    if [ ! -f "$DONE_FILE" ]; then
      MSG="⚠️ 量化前置检查：今日 ${{ steps.m.outputs.TODAY }} 的 morning-reconcile 未跑，yesterday_policy 可能失真"
      echo "::warning::$MSG"
      curl -s -X POST "${{ secrets.FEISHU_WEBHOOK_URL }}" \
        -H "Content-Type: application/json" \
        -d "{\"msg_type\":\"text\",\"content\":{\"text\":\"$MSG\"}}" || true
    else
      echo "::notice::✅ 今日 ${{ steps.m.outputs.TODAY }} 的 morning-reconcile 已完成"
    fi
```

> **关键**：原 shell 端在算 PREV_WORKDAY 找 prev.done，与 Python 端 `_check_today_morning_reconcile_done` 改成查 today.done 后**语义分裂**——飞书警告基于旧逻辑、Python 警告基于新逻辑。这里把 shell 也改成查 today.done，让两端单一真相源。

**改动 3（删除 line 142-153 整段——signal-{date}.done 不再由 yml 自起炉灶写，改由 cmd_signal_for_one_day 内部走 writer 一笔提交）**：

参见 §1.4。

**改动 3.5（line 174-180 push morning-reconcile step：3 次重试 + 不静默吞错，与 update.yml 对称）**：

```yaml
- name: Push morning-reconcile commits
  if: steps.m.outputs.mode == 'morning-reconcile' && env.SKIP_MR != 'true'
  run: |
    set -e
    for i in 1 2 3; do
      if git pull --rebase --autostash origin main && git push origin main; then
        echo "✅ morning-reconcile commits pushed"
        exit 0
      fi
      echo "::warning::push 失败（attempt $i/3），sleep 后重试"
      sleep $((RANDOM % 10 + 5))
    done
    echo "::error::morning-reconcile push failed after 3 retries"
    exit 1
```

> 原 step `git push origin main || true` 是"事故根因模式同源"——本地 commit 成功但远端未落库 + workflow 表面成功。决策 #7 "failure must be visible" 必须覆盖 quant.yml 而不只 update.yml。

**改动 4（line 230-256 deploy step 内 cp 阶段排除 cache）**：

```yaml
- name: 准备 quant-only publish 目录（cache 仅进 main 不进 gh-pages）
  if: steps.m.outputs.mode != 'mock-test'
  run: |
    set -e
    rm -rf /tmp/quant-publish
    mkdir -p /tmp/quant-publish/data
    if [ -d docs/quant ]; then
      cp -r docs/quant /tmp/quant-publish/
    fi
    if [ -d docs/data/quant ]; then
      cp -r docs/data/quant /tmp/quant-publish/data/
      # 排除 cache（仅进 main 不进 gh-pages）
      rm -rf /tmp/quant-publish/data/quant/cache
    fi
```

#### 1.3 run_signal.py：前置检查找 today.done + 同步改 check_readiness.py

**位置 1**：`scripts/quant/run_signal.py:40-47`

**改动**：

```python
def _check_today_morning_reconcile_done(repo_root: Path, cfg, today: date) -> bool:
    """signal 前置检查：今日 morning-reconcile 是否已跑。

    语义：D 日 14:48 signal 用的 yesterday_policy 来源于 D 日 09:05 morning-reconcile
    对 D-1 真值的 confirm（写入 positions.json.policy_state）。所以前置检查必须确认
    D 日 morning 已跑——找 morning-reconcile-{today}.done。

    详见 plan §2.2 + §10.1。
    """
    return _runs_done_file(repo_root, cfg, "morning-reconcile", today.strftime("%Y-%m-%d")).exists()
```

调用点 line 113-115 同步改：

```python
if not _check_today_morning_reconcile_done(repo_root, cfg, today):
    print(f"::warning::今日 morning-reconcile 未跑，yesterday_policy 可能失真", file=sys.stderr)
```

**位置 2**：`scripts/quant/check_readiness.py:153`

**改动**：

```python
(src / "run_signal.py", "_check_today_morning_reconcile_done", "run_signal.py signal 前置检查"),
```

> 不改这一行会导致 `python -m scripts.quant.check_readiness` 静态自检从 PASS 变 FAIL，影响后续 CI gate。

#### 1.4 重构 cmd_signal_for_one_day：done 走 writer

**位置**：`scripts/quant/run_signal.py:103-157`

**改动**：把 line 144-149 的 `done_file.write_text(...)` 改为通过 `writer.commit_atomic` 提交：

```python
# 写 .runs/signal-{date}.done 幂等标记（与 signals/positions/index 合并到 run_signal_generation 的 commit）
done_payload = json.dumps({
    "completed_at": datetime.now().isoformat(timespec="seconds"),
    "trigger": "manual" if args.mock_now else "auto",
    "signals_count": len(result.signals),
}, ensure_ascii=False, indent=2)

# run_signal_generation 已经把 signals/positions/index 提了 1 笔 commit；
# 这里走 writer 再加 1 笔提交 done，保留 quant.yml 端不再自己写 done（删 yml line 142-153）
writer.commit_atomic(
    [FileChange(path=done_file, content=done_payload)],
    message=f"[quant] mark signal-{today.strftime('%Y-%m-%d')} done",
)
```

> 现状 `run_signal_generation` 内部已 commit 一笔（signals + positions + index），这一步是第 2 笔（done）——本次不重构 signal 链路成"单 commit"（与 morning-reconcile 重构同步做工作量更大），列入 §八 YAGNI；当前焦点是**所有 commit 都走 writer**，杜绝 yml shell 直接 git commit。

---

### Phase 2：cache 链路 + cmd_morning_reconcile 单 commit 重构

#### 2.1 重构 cache.py：拆 `merge_daily`（纯计算）/ `append_daily`（薄壳）

**位置**：`scripts/quant/cache.py`

**新增**：

```python
def merge_daily(cache_dir: Path | str, index_code: str, new_df: pd.DataFrame) -> pd.DataFrame:
    """纯计算：读 + concat + dedup + sort，返回合并后 DataFrame，不落盘。

    用于 writer 收集模式——morning-reconcile 拿 merge 结果走 commit_atomic 一次性提交。
    """
    existing = read_cache(cache_dir, index_code)
    new = new_df.copy()
    if not isinstance(new.index, pd.DatetimeIndex):
        new = new.set_index("date")
    merged = pd.concat([existing, new])
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    return merged
```

**保留**（薄壳，向后兼容）：

```python
def append_daily(cache_dir: Path | str, index_code: str, new_df: pd.DataFrame) -> pd.DataFrame:
    """增量 append；按 date dedup（保留最新）。返回合并后的 DataFrame 并落盘。"""
    merged = merge_daily(cache_dir, index_code, new_df)
    write_cache(cache_dir, index_code, merged)
    return merged
```

**新增**（DataFrame → CSV 字符串，供 FileChange 用）：

```python
def to_csv_string(df: pd.DataFrame) -> str:
    """将 cache DataFrame 序列化为 CSV 字符串（标准列、date 索引重置）。"""
    out = df.copy()
    out.index.name = "date"
    out = out.reset_index()
    cols = [c for c in CSV_COLUMNS if c in out.columns]
    return out[cols].to_csv(index=False)
```

> `append_daily` 原签名保留——`test_cache.py` 不破；新代码用 `merge_daily + writer`。

#### 2.2 quant data_fetcher.py：加 fetch_history_daily（13 指数，主备 + retry + 限流）

**位置**：`scripts/quant/data_fetcher.py::AkShareFetcher`

**实现要求**（必须满足，不可省略）：

1. **接口签名**：`def fetch_history_daily(self, code: str, days: int) -> pd.DataFrame`
2. **主源**：`ak.stock_zh_index_hist_csindex(symbol=code, start_date=..., end_date=...)`，列名 rename 中→英
3. **备源**：`ak.stock_zh_index_daily(symbol=sina_code)`（用 `_to_sina_symbol` 转换）
4. **retry decorator**：`@retry_on_network_error(max_retries=2, delay=1.0)`——quant 子系统**独立复制一份**主站装饰器（不跨 import，drift 风险接受，详见决策表）
5. **限流**：调用方（cmd_morning_reconcile 的 cache 增量循环）每个指数之间 `time.sleep(0.5)`
6. **超时**：days ≥ 200 时单调用 timeout 30s（用 `signal.alarm` 或 akshare 自身参数）
7. **缺失返回**：fail-soft——返回空 DataFrame 而不是 raise（让调用方决定是否回滚）

**复制清单**（quant 独立实现，不跨 import 主站，避免子系统耦合）：

| 项 | 源（主站 scripts/data_fetcher.py） | 目标（scripts/quant/data_fetcher.py） |
|---|---|---|
| `retry_on_network_error` 装饰器 | line 72-100 | 复制 |
| `EXTRA_DAYS_BUFFER` 常量 | line 60 | 复制（值 30） |
| `NETWORK_ERRORS` tuple | line 63-69 | 复制 |
| 列名 rename map（中→英） | line 294-295 | 复制 |
| `_standardize_dataframe`（数值清洗 + 列裁剪 + 去重） | 主站 fetcher 内同名方法 | 复制（cs_index/sina 列差异统一） |
| `_to_sina_symbol` sina 前缀转换 | line 141-147（quant 已有简化版） | 现有版可用，无需扩展 |

> **drift 风险声明**：quant 复制后不再追主站变更。主站若因接口失效修了 cs_index 处理，需独立修复 quant 副本。这是为换取"子系统独立、互不耦合"接受的成本。

#### 2.3 重构 cmd_morning_reconcile 为 FileChange 收集模式（实现 1 笔 commit）

**位置**：`scripts/quant/run_signal.py:160-209` + `close_confirm.py:130-139` + `reconcile.py:84`

**目标语义**：`cmd_morning_reconcile` 主函数在末尾**唯一一次** `writer.commit_atomic` 提交全部 changes（cache × 13 + signals + positions + index + done）。

**改动 1**：`close_confirm.confirm_signals_with_close()` 改成**返回 `tuple[dict, list[FileChange]]`** 而不是内部 commit。**同时删除 `writer` 参数**——helper 不再 commit，writer 由调用方持有。

```python
def confirm_signals_with_close(
    *, cfg, today, book, fetcher, repo_root,    # writer 参数已删除
) -> tuple[dict, list[FileChange]]:
    """...
    返回 (汇总, FileChange 列表)；调用方负责 commit。
    """
    ...
    changes = [
        FileChange(path=signals_path, content=...),
        FileChange(path=positions_path, content=...),
        FileChange(path=index_path, content=...),
    ]
    return result_dict, changes
```

> **同步改 cmd_close_confirm 调用点**（`run_signal.py:246-255`）：原 `confirm_signals_with_close(..., writer=writer)` 改成 `result, changes = confirm_signals_with_close(...); writer.commit_atomic(changes, message=...)`，让 cmd_close_confirm 子命令也走 1 笔 commit。

**改动 2**：`reconcile.reconcile_pending_signals()` 同样改返回 `tuple[dict, list[FileChange]]`，删除内部 `writer.commit_atomic` 调用（line 84）。**同时删除 `writer` 参数**——签名变更与 close_confirm 对称。

**改动 3**：`cmd_morning_reconcile` 主函数收集所有 FileChange + cache 增量 + done 标记 → **唯一一次** commit_atomic。**前置：argparse 必须新增 `--calendar` 参数声明**（详见改动 5）。

```python
def cmd_morning_reconcile(args, cfg, repo_root: Path) -> None:
    today = datetime.fromisoformat(args.mock_now).date() if args.mock_now else date.today()
    done_file = _runs_done_file(repo_root, cfg, "morning-reconcile", today.strftime("%Y-%m-%d"))
    if done_file.exists():
        print(json.dumps({"status": "skipped_already_done", ...}))
        return

    # ★ 新增：calendar gate（详见 §2.4 + 改动 5 argparse 声明）
    cal = _load_calendar(Path(args.calendar)) if args.calendar else (lambda d: True)
    if not cal(today):
        print(json.dumps({"status": "skipped_non_trading_day", "date": today.strftime("%Y-%m-%d")}))
        return

    # 找前一交易日（必须用 calendar 回溯，不能仅跳周末——节假日如 5/1 也要跳）
    try:
        yesterday = _prev_trading_day(today, cal)
    except RuntimeError as e:
        print(f"::error::prev_trading_day 失败：{e}（极可能 calendar fixture 过期，请更新 scripts/quant/tests/fixtures/trading_calendar_*.json）", file=sys.stderr)
        sys.exit(1)

    fetcher = _build_fetcher(args.realtime) if args.realtime != "skip" else None
    book = load_positions(repo_root / cfg.paths["positions"])
    writer = LocalWriter(repo_root, mode=args.writer_mode)

    all_changes: list[FileChange] = []

    # === 1. cache 增量更新（fetcher None 时跳过整段） ===
    cache_changes, cache_summary = _update_cache_incremental(
        repo_root=repo_root, cfg=cfg, today=today, fetcher=fetcher,
    )

    # ★ cold_start_partial_failure 前移到此处（cache 阶段后立即处理）：
    # cache 是后续 close-confirm/reconcile 的前置数据，cache 不全就别继续；
    # 也避免 close-confirm/reconcile 的 changes 被 sys.exit 一起丢弃
    if cache_summary.get("skipped_reason", "").startswith("cold_start_partial_failure"):
        print(f"::error::cache 冷启动部分失败 → 跳过 close-confirm/reconcile/done，等下次重试。{cache_summary}", file=sys.stderr)
        print(json.dumps({"status": "cold_start_partial_failure", **cache_summary}))
        sys.exit(1)

    all_changes.extend(cache_changes)

    # === 2. close-confirm 昨日（用真实昨日收盘价 confirm 昨日 provisional 信号） ===
    cc_summary = {"confirmed": 0, "false_signals": 0, "skipped_reason": None}
    yesterday_signal_file = repo_root / cfg.paths["signals_dir"] / f"{yesterday.strftime('%Y-%m-%d')}.json"
    if fetcher is not None and yesterday_signal_file.exists():
        cc_summary, cc_changes = confirm_signals_with_close(
            cfg=cfg, today=yesterday, book=book, fetcher=fetcher,
            repo_root=repo_root,
        )
        all_changes.extend(cc_changes)
    else:
        cc_summary["skipped_reason"] = "no signals file" if not yesterday_signal_file.exists() else "fetcher disabled"

    # === 3. reconcile 跨日 pending → expired ===
    rec_summary, rec_changes = reconcile_pending_signals(cfg=cfg, today=today, repo_root=repo_root)
    all_changes.extend(rec_changes)

    # === 4. done 标记 ===
    done_payload = json.dumps({
        "completed_at": datetime.now().isoformat(timespec="seconds"),
        "cache_update": cache_summary,
        "close_confirm": cc_summary,
        "reconcile": rec_summary,
    }, ensure_ascii=False, indent=2)
    all_changes.append(FileChange(path=done_file, content=done_payload))

    # === 5. ★ 唯一一次 commit_atomic（空 changes 时跳过，writer 对空 list 抛 WriterError） ===
    if all_changes:
        writer.commit_atomic(
            all_changes,
            message=f"[quant] morning-reconcile {today.strftime('%Y-%m-%d')}",
        )
    else:
        print(json.dumps({"status": "no_changes", "date": today.strftime('%Y-%m-%d')}))

    print(json.dumps({...}))
```

**改动 3.5（新增 helper `_prev_trading_day`，run_signal.py 顶部）**：

```python
def _prev_trading_day(today: date, cal) -> date:
    """从 today 回溯，找前一个 calendar 标记为交易日的日期。"""
    d = today - timedelta(days=1)
    while not cal(d):
        d -= timedelta(days=1)
        if (today - d).days > 30:
            raise RuntimeError(f"prev_trading_day: 30 天内未找到交易日 from {today}")
    return d
```

> 原 `while yesterday.weekday() >= 5` 仅跳周末，遇五一/国庆这种连假**会把节假日当成"前一工作日"** → close-confirm 找不到 signals 文件 → 跳过 → 但实际真值在更早的交易日上。必须用 calendar 回溯。

**改动 4**：新增 `_update_cache_incremental` helper（放在 `run_signal.py`，文件顶部需补 `import time`；如未来 run_signal.py 过胖可拆出独立模块 `scripts/quant/cache_updater.py`）：

```python
def _update_cache_incremental(
    *, repo_root: Path, cfg, today: date, fetcher,
) -> tuple[list[FileChange], dict]:
    """13 指数 cache 增量更新；fetcher None 时跳过；冷启动 + 增量统一逻辑。

    返回 (FileChange 列表, 汇总)。失败 fail-soft（不 raise，调用方继续 close-confirm）。
    """
    if fetcher is None:
        return [], {"skipped_reason": "fetcher disabled (--realtime skip)"}

    from .cache import latest_date, merge_daily, to_csv_string
    cache_dir = repo_root / cfg.paths["cache_dir"]
    changes: list[FileChange] = []
    updated, failed = 0, 0
    pending_writes: list[tuple[str, pd.DataFrame]] = []   # 收集成功结果，全成功才一次性 append

    for spec in cfg.indices:
        last = latest_date(cache_dir, spec.index_code)
        if last is not None and last.date() >= today:
            continue   # cache 已最新（last >= today），跳过该指数
        days = 800 if last is None else (today - last.date()).days + 5

        new_df = fetcher.fetch_history_daily(spec.index_code, days=days)
        if new_df is None or new_df.empty:
            failed += 1
            continue
        pending_writes.append((spec.index_code, new_df))
        time.sleep(0.5)   # 限流防 cs_index 限流

    # 冷启动整体回滚：13 个里只要有 ≥ 1 个失败 → 整体放弃（cache 保持原状）
    is_cold_start = any(latest_date(cache_dir, spec.index_code) is None for spec in cfg.indices)
    if is_cold_start and failed > 0:
        return [], {"skipped_reason": f"cold_start_partial_failure ({failed}/13 failed, rollback)"}

    # 提交：merge + to_csv → FileChange
    for code, new_df in pending_writes:
        merged = merge_daily(cache_dir, code, new_df)
        changes.append(FileChange(
            path=cache_dir / f"{code}.csv",
            content=to_csv_string(merged),
        ))
        updated += 1

    return changes, {"updated": updated, "failed": failed, "is_cold_start": is_cold_start}
```

#### 2.4 morning-reconcile 加 calendar gate + yml 传递 --calendar

**位置 1**：`run_signal.py::cmd_morning_reconcile`（已包含在 §2.3 改动 3 中）

**位置 1.5（关键，否则 yml 传 --calendar 会 argparse error）**：`run_signal.py:287-290` morning-reconcile subparser 新增 argument 声明：

```python
p_mr = sub.add_parser("morning-reconcile", help="早间 reconcile + close-confirm 合并")
p_mr.add_argument("--mock-now", required=True)
p_mr.add_argument("--realtime", default="auto", help="fixture 路径 / 'auto' 走 AkShare / 'skip' 不跑 close-confirm")
p_mr.add_argument("--writer-mode", default="write_only")
p_mr.add_argument("--calendar", default=None, help="可选；若提供则跳过非交易日（防节假日写脏 done）+ 用 calendar 回溯前一交易日（不只跳周末）")
```

> 注意：`--realtime` 当前声明（line 289）`default="auto"` 不带 choices——支持 fixture path 用法（mock-test fixture 回放 / 本地确定性测试）。**不要在本次新增 choices=["auto","skip"]**，否则破坏 fixture 兼容。保持当前字符串声明 + help 文案。

**位置 2**：`.github/workflows/quant.yml:165-172`

```yaml
- name: 跑 morning-reconcile
  if: steps.m.outputs.mode == 'morning-reconcile' && env.SKIP_MR != 'true'
  run: |
    python -m scripts.quant.run_signal morning-reconcile \
      --mock-now "${{ steps.m.outputs.TODAY }}T09:05:00+08:00" \
      --calendar scripts/quant/tests/fixtures/trading_calendar_2026-04.json \
      --realtime auto \
      --writer-mode commit
```

**位置 3**：`.github/workflows/update.yml:69-72`

```yaml
- name: Quant morning-reconcile（合并 reconcile + close-confirm；故障隔离不影响主链路）
  if: steps.run_script.outputs.should_deploy == 'true' && steps.mode.outputs.mode == 'morning'
  continue-on-error: true
  run: |
    python -m scripts.quant.run_signal morning-reconcile \
      --mock-now "$(TZ=Asia/Shanghai date -Iseconds)" \
      --calendar scripts/quant/tests/fixtures/trading_calendar_2026-04.json \
      --realtime auto \
      --writer-mode commit
```

> calendar fixture 必须每月（或季度）更新——加进 §九 长期任务，避免 5/8 后失效。

---

## 五、决策清单（已确认）

| # | 决策点 | 选项 | 理由 |
|---|---|---|---|
| 0 | cache 持久化位置 | **commit 进 main，不进 gh-pages**（peaceiris exclude_assets） | runner ephemeral 销毁不丢；可审计；体积可忽略；不污染部署源 |
| 1 | 冷启动 vs 增量 | **统一逻辑**（cache 空 → 800 天，否则 last+1~today），冷启动有失败则整体回滚 | 消除特殊情况；防止部分写入 → 永久缺失某区间 |
| 2 | ak 历史接口 | **复用主站 pattern**（csindex 主 + sina 备），不跨 import，复制清单见 §2.2 | 已验证可用；保子系统独立，drift 风险接受 |
| 3 | cache 范围 | **仅 13 指数 index**（不含 14 ETF） | ETF 仅需当日实时价不需历史 MA20 |
| 4 | 04-27 morning-reconcile.done | **不补**（决策 A），但有 deadline | 04-28 早 8 点 update.yml 修复后自然跑 morning（写 04-28.done），前置检查改成找 today.done 后链路自洽。**前提：Phase 1 必须 04-28 SGT 08:00 之前合并到 main**——否则 04-28 14:48 signal 仍会发出虚警，需手写一个 morning-reconcile-2026-04-27.done 兜底 |
| 5 | morning-reconcile 是否单 commit | **重构为 FileChange 收集模式**（§2.3） | 符合 mvp-plan §3.7 硬约束；消除架构违规 2.4.1 |
| 6 | concurrency 策略 | **update.yml 与 quant.yml 共享 group `quant-state-main`**，`cancel-in-progress: false` | 消除多 push 竞态；时间窗 8:00/9:05 错开排队执行 |
| 7 | push 失败处理 | **3 次重试 + 失败 exit 1（warning/error 可见，不 \|\| true 静默）** | "failure must be visible"；本次事故根因就是 silent failure 模式 |

> 📝 **历史注解（2026-04-27 21:00 SGT）**：本表决策 #6 提到的"8:00/9:05 错开排队"中的 09:05 GitHub schedule 备路在 04-27 晚上观察到非预期触发（详见 [`cron-cleanup-single-source.md`](cron-cleanup-single-source.md) §1.1）。已通过 cleanup plan 删除 GitHub schedule 备路与 heartbeat 哨兵，定时唯一来源改为 cron-job.org 单路。本表中"备路"语义仅作历史归档参考。

---

## 六、影响分析与验证

### 6.1 Phase 1 破坏性评估

| 受影响位置 | 改前 | 改后 | 风险 |
|---|---|---|---|
| update.yml quant step | 静默失败 | 跑通；commit + push main 可见且重试；故障仍隔离主站 | 0 |
| update.yml concurrency | 无 | 与 quant.yml 共享 quant-state-main | 0（排队不丢任务） |
| quant.yml signal/morning/init | python writer commit fatal | 全局 git config 就位 | 0 |
| mock-test mode | 不 commit（5 道硬门拦截） | git config 不入工作区，硬门 #3 不破 | 0（验证清单含一次 mode=mock-test 跑通） |
| signal 前置检查 | 永远找不到 yesterday.done → 始终警告 | 找 today.done，命名对齐 → 正常通过 | 0 |
| cmd_signal_for_one_day done 写法 | `write_text` 绕过 writer | 走 `writer.commit_atomic` | 0（writer 本就支持单文件提交） |
| quant.yml 写 signal-{date}.done | shell 自起炉灶 | 删除（done 由 cmd_signal 内部写） | 0 |
| check_readiness.py:153 marker | grep 旧函数名 | 同步改 marker | 0（自检仍 PASS） |
| peaceiris exclude_assets | 整 docs 同步 | 排除 cache 子目录 | 0（cache 仍在 main，前端不依赖 gh-pages 上的 cache） |

### 6.2 Phase 2 行为变化（预期改进）

| 行为 | 改前 | 改后 |
|---|---|---|
| morning-reconcile commit 数 | 3 笔（close-confirm + reconcile + done） | **1 笔**（cache + close-confirm + reconcile + done 合并） |
| close_confirm 第二段 policy_state 回正 | cache 空 → splice 后 MA20=NaN → 跳过所有 bucket | cache 有 800 天 → 真实 MA20 → 真正回正 |
| signal_generator MA20 计算 | NaN → errors 列表填满 → 信号 0 条 | 真实 MA20 → 正常生成信号 |
| positions.json 状态机 | 永远 CASH 态 | 按真实 MA20 跨 CASH/HOLD 切换 |
| `--realtime skip` 模式 | cmd_morning_reconcile 遇到 `fetcher.fetch_indices()` 直接崩 | cache 增量 + close-confirm 都跳过，仅跑 reconcile + 写 done | 

> Phase 2 上线后**第一次** morning-reconcile 跑会比较慢（13 指数 × 800 天 ≈ 60s+ 网络），是一次性成本。之后每天 ~10s（13 × +5 天）。

### 6.3 验证步骤

#### 6.3.1 Phase 1 验证（合并后立即手动触发）

1. **触发 quant.yml mode=mock-test**（验证硬门）：
   - 期望：5 道硬门全 PASS；工作区零 diff；git config 不破坏隔离

2. **触发 quant.yml mode=morning-reconcile**（mock_now 留空，默认 today=04-27）：
   - 期望：python writer commit 成功（不再 Author identity 错）
   - 期望：写出 `morning-reconcile-2026-04-27.done`（cache 仍空 → close-confirm 第二段 NaN 跳过 → policy_state 不动）
   - 期望：commit 数 = 1（done 标记单 commit）
   - 期望：push 成功（concurrency group 工作；不 silent failure）

3. **触发 quant.yml mode=signal --mock-now 2026-04-27T14:48 --writer-mode dry_run**（dry_run 不进 main）：
   - 期望：前置检查找 today.done = 2026-04-27.done → 通过（步骤 2 已生成）
   - 期望：errors 列表仍含 NaN（cache 仍空，符合预期）

4. **触发 update.yml mode=morning --force**（验证主站早 8 点链路）：
   - 期望：quant step 不再静默失败；写 `morning-reconcile-{TODAY}.done`；push 进 main；deploy step 排除 cache

#### 6.3.2 Phase 2 验证（合并后立即手动触发）

1. **触发 quant.yml mode=morning-reconcile**：
   - 期望：fetcher 拉 13 指数 800 天历史，60s 内完成；retry 触发可见
   - 期望：commit 包含 13 个 `cache/{code}.csv` + done + (close-confirm changes 若有) + (reconcile changes 若有)，**仅 1 笔 commit**
   - 期望：close-confirm 第二段用真实 MA20 回正所有 bucket policy_state
   - 期望：cache 文件**仅在 main**（gh-pages 不出现）

2. **触发 quant.yml mode=signal --mock-now 2026-04-28T14:48 --writer-mode dry_run**（用未来日避免污染当下状态机；cache 已有真历史到 04-24/04-27）：
   - 期望：errors 列表为空
   - 期望：signals/2026-04-28.json 生成（dry_run 仅打印不入库）；不发飞书

#### 6.3.3 04-28 自然链路观察

- 08:00 update.yml 触发 → quant morning-reconcile 跑通（增量 +1 天 cache，~10s）→ push main + concurrency 串行
- 14:48 quant.yml signal 触发 → 前置检查找 morning-reconcile-2026-04-28.done（08:00 写的）→ 通过（无飞书警告）→ 正常生成信号

> 📝 **历史注解（2026-04-27 21:00 SGT）**：本节描述的 04-28 自然链路仍然有效，但**触发源已收敛为单路 cron-job.org**（不再有 GitHub schedule 09:05 备路也不再有 14:55 heartbeat 哨兵）。详见 [`cron-cleanup-single-source.md`](cron-cleanup-single-source.md)。同时已知缺陷：周一 / 节假日次日 should_deploy=false 时 morning-reconcile 不会跑（cleanup plan §4.3 R4/R5），列入本 incident plan **Phase 2 必修**（cache 链路实现时一并 calendar 一致化）。

### 6.4 回归测试（push 前必跑）

每个 phase push 到 main 之前，本地必须跑通：

```bash
cd /Users/loopq/dev/git/loopq/trend.github.io
source venv/bin/activate
pytest scripts/quant/tests/ -v
```

**门槛**：
- Phase 1 push 前：现有 86 用例 + 6 集成测试**全 PASS**（git config / 重命名不破现有测试）
- Phase 2 push 前：86 + 6 + 新增 `merge_daily` 幂等测试 + `fetch_history_daily` mock 测试 + `_update_cache_incremental` 整体回滚测试**全 PASS**
- 不允许 skip / xfail 旧用例
- 覆盖率不下降

### 6.5 节假日预案

`scripts/quant/tests/fixtures/trading_calendar_2026-04.json` 当前涵盖 2026-03-30 ~ 2026-05-08。

**5/1-5/3 五一假期跨节预演**（在 4-30 之前手动跑）：

```bash
python -m scripts.quant.run_signal morning-reconcile \
  --mock-now 2026-05-04T09:05:00+08:00 \
  --calendar scripts/quant/tests/fixtures/trading_calendar_2026-04.json \
  --realtime auto \
  --writer-mode dry_run
```

期望：prev_workday=2026-04-30；写 `morning-reconcile-2026-05-04.done`；不在 5/1-5/3 误写 done。

### 6.6 回滚剧本

| 故障 | 回滚步骤 |
|---|---|
| 单指数 cache 损坏（如列名异常） | `rm docs/data/quant/cache/<code>.csv` + commit + push → 下次 morning-reconcile 自动冷启动该指数 |
| 整体 Phase 2 回退 | `git revert <phase2-commit-sha>` + `git rm docs/data/quant/cache/*.csv` + commit + push |
| positions.json 污染 | 手动触发 `quant.yml mode=init`（重置 CASH 初态） |
| Phase 1 修复后 cache 仍长期空 | 检查 cron-job.org 是否在触发 update.yml；检查 update.yml quant step 日志是否报错（concurrency 是否被卡住） |

### 6.7 验收标准（acceptance criteria）

| Phase | 通过条件（可量化） |
|---|---|
| Phase 1 | 1) `python -m scripts.quant.check_readiness` 全 PASS；2) `pytest scripts/quant/tests/` 全 PASS；3) 手动触发 mode=morning-reconcile 后 main 上有 `morning-reconcile-{today}.done`；4) 手动触发 mode=mock-test 后工作区零 diff；5) update.yml mode=morning --force 跑完，main 出现 quant 提交（peaceiris 部署成功且 gh-pages 不含 cache 路径） |
| Phase 2 | 1) `docs/data/quant/cache/*.csv` 共 13 个文件，每个行数 ≥ 600（800 天减约 200 节假日）；2) morning-reconcile 完成后**仅 1 笔 commit**（git log -1 显示包含 cache + done + 可能的 signals/positions）；3) signal 跑完 `result.invariant_errors` 为空；4) positions.json 至少有 1 个 bucket policy_state 不为 CASH（取决于真实 MA20，不强制 HOLD） |
| 04-28 自然链路 | 1) 飞书无前置警告；2) `morning-reconcile-2026-04-28.done` 自然出现；3) signal 生成至少 1 条信号（如有）or skipped_non_trading_day 正常退出 |

---

## 七、执行清单（按顺序）

### Phase 1（修 bug，独立可合并）

- [ ] 1.1 修 `.github/workflows/update.yml`：加全局 git config + concurrency group + push step（重试不静默） + peaceiris exclude_assets cache
- [ ] 1.2 修 `.github/workflows/quant.yml`：加全局 git config，删 line 142-153 整段 + 内联 git config 两处；deploy step cp 阶段 rm cache
- [ ] 1.3 改 `scripts/quant/run_signal.py:40-47, 113-115`：函数重命名 + 找 today.done
- [ ] 1.4 改 `scripts/quant/check_readiness.py:153`：marker 同步改名
- [ ] 1.5 改 `scripts/quant/run_signal.py:103-157` `cmd_signal_for_one_day`：done 走 writer.commit_atomic
- [ ] 1.6 本地跑 `pytest scripts/quant/tests/ -v` 全 PASS
- [ ] 1.7 本地跑 `python -m scripts.quant.check_readiness` 全 PASS
- [ ] 1.8 用户 review diff 后 push 到 main（用户自推，agent 不推）
- [ ] 1.9 手动触发 quant.yml mode=mock-test 验证硬门
- [ ] 1.10 手动触发 quant.yml mode=morning-reconcile（cache 仍空，验证 commit 路径修复）
- [ ] 1.11 手动触发 update.yml mode=morning --force 验证主站早 8 点链路

### Phase 2（cache 实现 + 单 commit 重构）

- [ ] 2.1 改 `scripts/quant/cache.py`：加 `merge_daily` + `to_csv_string`；保留 `append_daily` 薄壳
- [ ] 2.2 改 `scripts/quant/data_fetcher.py`：加 `AkShareFetcher.fetch_history_daily`，复制 retry decorator + EXTRA_DAYS_BUFFER + NETWORK_ERRORS + 列名 rename + 主备 fallback
- [ ] 2.3 改 `scripts/quant/close_confirm.py:130-139`：`confirm_signals_with_close` 改返回 `tuple[dict, list[FileChange]]`，删内部 commit_atomic
- [ ] 2.4 改 `scripts/quant/reconcile.py:84`：`reconcile_pending_signals` 同样改返回 + 删内部 commit
- [ ] 2.5 改 `scripts/quant/run_signal.py`：(a) 顶部 `import time`；(b) morning-reconcile subparser 加 `--calendar` argument 声明（保留 `--realtime` 当前字符串声明不加 choices）；(c) 新增 `_prev_trading_day(today, cal)` helper（calendar 回溯，跳节假日）；(d) `cmd_morning_reconcile` 加 calendar gate + 用 `_prev_trading_day` 算 yesterday + 加 `_update_cache_incremental` helper + 收集所有 FileChange + 冷启动部分失败时不写 done + sys.exit(1) + 仅当 `all_changes` 非空才 commit_atomic；(e) `cmd_close_confirm`（line 246-255）调用点同步改成 `result, changes = ...; if changes: writer.commit_atomic(changes, ...)`；(f) `cmd_reconcile`（line 316-317）调用点同步改成 `result, changes = ...; if changes: writer.commit_atomic(changes, ...)`
- [ ] 2.6 改 `.github/workflows/quant.yml:165-172` + `update.yml:69-72`：传 `--calendar` 参数（位置 1.5 argparse 声明先到位）
- [ ] 2.7 加 pytest 单测：`merge_daily` 幂等 + `fetch_history_daily` mock + `_update_cache_incremental` 整体回滚 + cmd_morning_reconcile 单 commit 断言
- [ ] 2.8 本地跑 `pytest scripts/quant/tests/ -v` 全 PASS（86 + 6 + 新增）
- [ ] 2.9 用户 review diff 后 push 到 main
- [ ] 2.10 手动触发 quant.yml mode=morning-reconcile 验证 cache 写入 + 单 commit
- [ ] 2.11 手动触发 quant.yml mode=signal --mock-now 2026-04-28T14:48 --writer-mode dry_run 验证 signal 生成

### 自然链路观察

- [ ] 3.1 04-28 08:00 update.yml 自然触发 → 验证 morning-reconcile 跑通 + cache 增量 +1 天
- [ ] 3.2 04-28 14:48 quant.yml signal 自然触发 → 验证无前置警告 + 生成信号
- [ ] 3.3 5/4 跨五一节预演（§6.5）

---

## 八、未在本次范围内（YAGNI）

| 项 | 暂不做的理由 |
|---|---|
| 独立 `update_cache.py` 脚本（mvp-plan §1129 提及） | 用 morning-reconcile 内联实现替代，少一个文件 |
| ETF 历史日线缓存 | 仅需当日实时，无 MA20 需求 |
| `cmd_signal_for_one_day` 单 commit 重构（让 signals + positions + index + done 一笔提交） | 当前 run_signal_generation 内部已 commit 一笔，再加 done 是第 2 笔；与 morning-reconcile 同步重构工作量大，本次仅修 yml 端违规和 done 走 writer，单 commit 化留后续 |
| 800 天首次拉取的进度条/分批 | 60s 一次性成本可接受；retry + 整体回滚已防风险 |
| update.yml `continue-on-error: true` 改 false | 保留主站隔离原则；step 内部已不再 silent，可见性已足 |
| writer.py 内部自配 git identity | 当前依赖外部 git config 是合理的关注点分离 |
| GithubApiWriter 实现（mvp-plan §3.7） | 上线 Phase 7 之前再实施 |
| 04-27 之前可能存在的状态机失真排查 | positions.json 是初始 CASH 态，无失真可言 |
| 14:48 signal 14/14 progress 全 NaN 的根因取证 | 已用 cache 空解释；Phase 2 后自动消失 |

---

## 九、长期任务（追踪）

| 项 | 节奏 | 责任 |
|---|---|---|
| `trading_calendar_2026-04.json` fixture 更新（覆盖至少未来 60 天） | 每月底前更新下月 + 双月预留 | 用户 / 月度 SOP |
| 主站 vs quant data_fetcher drift 巡检（cs_index 接口表头变化） | 季度 | 用户 / 触发时机：主站 fetcher 改动 |
| Phase 2 后 cache 损坏率监控（哪个指数 retry 频繁失败） | 持续 | 通过 morning-reconcile done 文件 cache_update.failed 计数观察 |
| `quant.yml` peaceiris@v3 → v4 升级（与 update.yml 对齐） | 一次性 | 本次事故修复不强制；与 §1.2 cp+rm 排除 cache 路径无冲突，但版本一致性收益 |
| quant 子系统独立 UA 注入（防反爬） | 当遇到限流时 | quant 跑独立 process，不经过主站 main.py 的 `requests.Session.request` monkey-patch；目前共享 akshare 默认 UA。若 cache 拉取频繁触发限流再启动；§2.2 复制清单暂未含此项 |

---

## 十、附录

### 10.1 Round 1 review Issue 1（Bug B 反驳论证）

Round 1 reviewer 主张 "现有 `_check_yesterday_morning_reconcile_done` 找 prev_workday.done 才是对的"，论点：

> Mon 14:48 signal 要确认 Fri 真值已被 confirm → 找 morning-reconcile-Fri.done（Fri 09:05 morning 写的）

**反驳**（基于代码事实链）：

| 时刻 | 代码事实 | 处理对象 |
|---|---|---|
| Thu 14:48 | signal 生成 provisional 信号（基于 Thu 实时价 splice） | Thu signals → signals/2026-Thu.json |
| Thu 收盘 | （等待） | — |
| Fri 09:05 morning | `cmd_morning_reconcile(today=Fri) → confirm_signals_with_close(today=Thu)` | **处理 Thu 真值**，写 morning-reconcile-Fri.done |
| Fri 14:48 | signal 用 `bucket.policy_state`（Fri 09:05 morning 刚回正） | yesterday_policy = Thu 真值 close 的 policy_state ✓ |
| Fri 收盘 | （等待） | — |
| Mon 09:05 morning | `cmd_morning_reconcile(today=Mon) → confirm_signals_with_close(today=Fri)` | **处理 Fri 真值**，写 morning-reconcile-Mon.done |
| Mon 14:48 | signal 用 `bucket.policy_state`（Mon 09:05 morning 刚回正） | yesterday_policy = Fri 真值 close 的 policy_state ✓ |

**结论**：Mon 14:48 signal 用的 yesterday_policy 来源于 **Mon 09:05 morning** 的 close-confirm，不是 Fri 09:05 morning。

reviewer 误以为"Fri 09:05 morning 处理 Fri 真值"——**实际上 Fri 09:05 morning 处理的是 Thu 真值**。Fri 真值是 Mon 09:05 morning 处理的，写的是 Mon.done。

所以前置检查应该找 **today.done**（即"今日 09:05 morning 已跑过"），即 plan §1.3 的修复方向。reviewer Issue 1 误读语义，拒绝接受。

> 反驳保留在此附录而非删除是为了避免后续 reviewer 重复提出同一论点。
