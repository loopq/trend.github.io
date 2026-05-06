# Quant Morning-Reconcile 缓存化 + Signal 自探测 — 完整 Spec

> 状态：v4 final
> 日期：2026-05-07
> 触发事件：
> - 2026-05-04 飞书误报「morning-reconcile 未跑」（5-4 是劳动节调休休市，本不该跑 signal，更不该报警告）
> - 2026-05-06 14:48 同样误报（5-6 节后第一交易日，主站 should_deploy=false 把 quant 搭车一并拦下）
> - 前端「需确认 (0)」无法判断今日是否真的跑过 quant
> - **审计发现**：`docs/data/quant/cache/` 自 4-27 起一直为空，生产路径从未调用 `append_daily/write_cache`，signal_generator 与 close_confirm 拿到空 DataFrame → MA20 算不出，整个 quant 在生产是**空壳运行**

---

## 1. 四个具象问题

| # | 问题 | 时间 | 根因 |
|---|------|------|------|
| P1 | 非交易日发警告 | 2026-05-04 | fixture `trading_calendar_2026-04.json` 错把 5-4 标为交易日 + morning-reconcile 没跑（被主站门控拦） |
| P2 | 节后交易日发警告 | 2026-05-06 | 5-6 8AM 主站 should_deploy=false（沪深300 数据停在 4-30）→ quant morning-reconcile 搭车被一并拦下 |
| P3 | 前端无运行状态 | 持续 | docs/quant/index.html:115 只显示「需确认 (0)」，看不到当日 morning-reconcile / signal 是否跑过、跑出几条 |
| P4 | 历史 K cache 从未被填充 | 持续 | 仅 `cache.py` 提供 `append_daily/write_cache`，**生产代码无人调用** → signal/close_confirm 算不出 MA20 → signals_count=0、confirmed=0 全空跑 |

底层共同根因：
- 用静态 `trading_calendar.json` + 主站 `should_deploy` 串行门控判断"今天该不该跑"
- cache 只读不写，是个未连接的设计意图

---

## 2. 2026 节假日真实日历（关键事实）

**清明节 2026**（共 3 天连休）：4-4 周六（休）、4-5 周日（清明节，休）、4-6 周一（调休，休）、4-7 周二恢复交易。

**劳动节 2026**（共 5 天连休）：5-1 周五（劳动节，休）、5-2 周六（休）、5-3 周日（休）、5-4 周一（调休，休）、5-5 周二（调休，休）、5-6 周三恢复交易。

⚠️ 之前 v1 错误结论的根源就是把 5-4/5-5 当交易日。本 spec 修正。

---

## 3. 整体方案（一气呵成）

### 3.1 流程图

```
cron-job.org 每日触发 → update.yml (repository_dispatch type=morning)
        ↓
   主站 main.py 跑 morning（内部判断 should_deploy）
        ↓
   ┌───── should_deploy=true ─────┐    ┌───── should_deploy=false ─────┐
   │ 主站 page 部署 + 邮件通知    │    │ 主站不部署                    │
   └──────────────┬───────────────┘    └──────────────┬────────────────┘
                  └──────────┬─────────────────────────┘
                             ▼
        Quant morning-reconcile step（不再受 should_deploy 拦截）
            1. 拉 13 指数历史 K（800 天） → append_daily 增量更新 cache
            2. 探测 cache 最新交易日 X
            3. 读上次 done.latest_trading_day = X_prev
            4. X > X_prev → 追赶式 confirm + 推进 policy_state
            5. X == X_prev → 仅写"今日已检查"缓存
            6. reconcile 跨日 pending → expired
            7. 原子写 morning-reconcile-{today}.done

cron-job.org 14:48 触发 → quant.yml (repository_dispatch type=signal)
        ↓
   signal 入口拉 fetch_indices(13) + fetch_etfs(13) ← 仅 2 次 AkShare 网络调用
   结果空（< 阈值）→ skipped_non_trading_day（静默 skip）
   结果有 → 用 read_cache 读本地历史 K + 实时拼 MA20 → 决策 → 写 signal-{today}.done
```

**不变**：cron-job.org 触发器、update.yml 入口、quant.yml 入口、yesterday_policy 来自 `bucket.policy_state`、close_confirm 算法本体。

**变化**：
- 去掉 `should_deploy` 对 quant 的拦截
- **morning-reconcile 增加历史 K 增量拉取（修 P4）**
- morning-reconcile 改为缓存式 + 追赶式
- signal 删除前置检查 + 自探测
- 前端加状态文字
- 生产不再读 fixture trading_calendar.json

### 3.2 每件事的具体新行为

**A. quant morning-reconcile（搭 update.yml 车，但每次都跑）**

每次 update.yml 跑（无论 should_deploy 真假），quant morning-reconcile step 都执行：

1. **拉历史 K 填 cache**（新增）：对 cfg.indices 里 13 个指数，调用 `scripts.data_fetcher.DataFetcher.fetch_index(code, source)` 拉 800 天日线 → `append_daily(cache_dir, code, df)` 增量合并
2. 从已填好的 cache 读最新一行 → 「最新历史 K 线日」X
3. 读上一次 `morning-reconcile-*.done` 里的 `latest_trading_day = X_prev`
4. **X > X_prev**：进入追赶式 confirm 分支，按日期顺序对 (X_prev, X] 区间每个交易日跑 close_confirm，policy_state 推进到 X 的真值
5. **X == X_prev**：no-op（不动 policy_state，仅写"今日已检查"缓存）
6. 跑 reconcile（跨日 pending → expired，与现有逻辑一致）
7. 原子写 `morning-reconcile-{today}.done`，含 `latest_trading_day` 等新字段

**B. signal 14:48（自探测 + 缓存命中 + 删除前置检查）**

quant.yml 14:48 cron 触发：

1. 入口拉今日实时行情：`fetcher.fetch_indices(13)`（一次 AkShare）+ `fetcher.fetch_etfs(13)`（一次 AkShare）
2. 用沪深300（cfg.sentinel_symbol，默认 `000300`）作为哨兵：从 fetch_indices 结果里 get → 拿不到价 → `skipped_non_trading_day`，**不写 done、不发通知、不警告**
3. 拿到 → 走信号生成（不再前置检查 morning-reconcile）：
   - 对每个 bucket：`read_cache(cache_dir, idx_code)` 读本地历史 K（**零网络**）→ `splice_realtime` 拼今日实时 → MA20
   - `yesterday_policy = bucket.policy_state`（**保持现状**，由 morning-reconcile 维护真值）
   - 走 signal_engine → 写 `signals/{today}.json` + 更新 positions.json
4. 原子写 `signal-{today}.done`

**关键耗时控制**：
- 14:48 signal 总网络请求 = **2 次**（fetch_indices + fetch_etfs，全市场全量）
- 历史 K 全部命中本地 cache（13 次 read_cache，本地 IO < 50ms）
- 总耗时预算 ≤ 10s（远低于 14:48 → 15:00 的 12 分钟窗口）

**关键：删除 quant.yml 的「前置检查 morning-reconcile」step（line 102-114）**——signal 自包含。

**C. 前端状态展示**

`docs/quant/index.html` 在「🔔 需确认 (X)」标题旁渲染状态文字，数据源是两个 `.runs/*.done` 文件：

| morning-reconcile | signal | 显示文字 |
|--------------------|--------|----------|
| ✅ 已跑 | ✅ 已跑 | `· 5-6 已检查 · {N} 信号` |
| ✅ 已跑 | ❌ 未跑 | `· 5-6 已检查 · 当日非交易` |
| ❌ 未跑 | — | `· 5-6 未跑` |

### 3.3 主站影响隔离硬约束（Linus "Never break userspace"）

**这是不可妥协的红线**。任何实施步骤违反以下任意一条都必须停下重新设计：

#### 禁止修改

| 类别 | 文件/路径 | 状态 |
|------|-----------|------|
| 主站 Python 代码 | `scripts/main.py` | **不动一行** |
| 主站数据获取 | `scripts/data_fetcher.py` | **只读复用 import**，禁止修改公共 API（quant 仅 `from scripts.data_fetcher import DataFetcher`） |
| 主站计算 | `scripts/calculator.py` | 不动 |
| 主站生成 | `scripts/generator.py`、`scripts/ranking_store.py`、`scripts/templates/` | 不动 |
| 主站持久化 | `scripts/ranking_history.json`、`docs/index.html`、`docs/archive/`、`docs/api/` | 不动 |
| update.yml 主站 step 链 | `Checkout`/`Setup Python`/`Install dependencies`/`Configure git identity`/`Determine run mode`/`Run update script`/`Deploy to GitHub Pages`/`Send email notification` | 这 8 个 step **完全不动** |
| 主站 GitHub Pages 部署 | `gh-pages` 分支 | quant 不写 gh-pages |

#### 允许修改

| 类别 | 文件/路径 | 改动性质 |
|------|-----------|----------|
| update.yml | line 75-99 两个 quant step 的 `if` 条件 | 仅删 `should_deploy == 'true' &&` 半段 |
| quant.yml | 删除前置检查 step + signal step 去 `--calendar` | 删 + 改 |
| quant 代码 | `scripts/quant/run_signal.py`（cmd_morning_reconcile + cmd_signal_for_one_day）、`scripts/quant/data_fetcher.py`（FixtureFetcher 加 fetch_history）、`scripts/quant/config.yaml`（加 sentinel_symbol） | 重构 + 新增 |
| 前端 | `docs/quant/index.html`、`docs/quant/style.css` | 加状态文字（quant 子页面，不影响主站首页） |

#### 故障隔离已有保护（必须保持）

- `update.yml` line 77 `continue-on-error: true` 在 quant morning-rec step 上 → quant 失败不影响后续主站 deploy
- `update.yml` line 87 `continue-on-error: true` 在 quant push step 上 → push 失败不影响后续 deploy
- 部署 step `exclude_assets: '.github,data/quant/cache/**'`（line 107）→ cache CSV 不发布到 gh-pages（避免 5MB+ 数据污染）
- `concurrency: quant-state-main`（line 21-23）→ 防 quant push 与下次主站跑并发
- quant push 走 `main` 分支；主站 deploy 走 `gh-pages` 分支 → 互不干扰

#### 新增风险的兜底

| 新增风险 | 兜底 |
|----------|------|
| morning-rec 拉历史 K 13 次 AkShare（C0）失败 | `continue-on-error: true` 已护身；下次跑增量 append 自愈 |
| morning-rec 增加 30s 耗时 | 整个主站 morning step 总耗时仍 < 5 分钟（主站本身 ~1.5 分钟，quant 30s+15s commit），cron-job.org timeout 200s 足够 |
| AkShare 拉历史 K 时阻塞主站 deploy | quant 两个 step 在主站 `Run update script` 之后、`Deploy to GitHub Pages` 之前；continue-on-error 保证 quant 卡死不影响 deploy |
| quant push 与主站 deploy 串行竞争 main 分支 | 现有方案 quant push main → 之后 deploy gh-pages，串行无竞争 |

### 3.4 14:48 signal 耗时分析（再 check）

新方案 vs 现状：

| 项目 | 现状（v0） | v4 |
|------|-----------|----|
| 实时拉取 | 2 次 AkShare（fetch_indices 全市场 + fetch_etfs 全市场）| **不变** 2 次 |
| 历史 K 拉取 | 0 次（read_cache 拿空，但本就跑） | 0 次（read_cache 命中已填的 cache）|
| 本地 IO | 13 次 read_cache（空文件，几乎 0ms） | 13 次 read_cache（实文件，每次 ~5ms） |
| 前置检查 step | curl 飞书 webhook 1 次 | **删除** |
| 总网络调用 | 2 次 | **2 次（不增）** |
| 总耗时预算 | ~5s | ~5-10s |

**结论**：v4 不增加 14:48 signal 的网络请求次数，反而修了 P4 让 signal 真正能算出 MA20。耗时增长仅来自 read_cache 真读到数据后的 splice + MA20 计算（< 1s）。

---

## 4. 节假日时间线完整回测

> 表头：
> - **update.yml 跑** = cron-job.org 触发 + main.py 完成（无论 should_deploy 真假，main.py 都 exit 0）
> - **主站部署** = should_deploy=true，page 部署到 gh-pages
> - **quant morning-rec** = update.yml 内部 step，每次都跑（含 cache 增量更新）
> - **quant signal** = quant.yml 14:48 独立触发

### 4.1 清明节（2026-04-02 ~ 2026-04-08）

| 日期 | 性质 | update.yml | 主站部署 | quant morning-rec (08:00) | quant signal (14:48) | policy_state 终态 |
|------|------|------------|----------|---------------------------|----------------------|-------------------|
| 4-2 周四 | 交易 | ✅ | ✅ | cache append 4-1，探测=4-1，confirm 4-1，缓存「最新 4-1」 | 拉到 → read_cache 拿 4-1 K + 实时 → policy=4-2 | 4-2 (provisional) |
| 4-3 周五 | 交易 | ✅ | ✅ | cache append 4-2，探测=4-2，confirm 4-2 | policy=4-3 | 4-3 (provisional) |
| 4-4 周六 | 休 | ✅ | ✅ | cache append 4-3，探测=4-3，confirm 4-3 | skip | 4-3 (confirmed) |
| 4-5 周日 | 休（清明） | ✅ | ❌ | cache 拉到 4-3 无新增，no-op | skip | 4-3 (confirmed) |
| 4-6 周一 | 休（调休） | ✅ | ❌ | cache 同上 no-op | skip | 4-3 (confirmed) |
| 4-7 周二 | 交易 | ✅ | ❌ | cache 拉到 4-3 仍无新增（A股 8AM 还没 4-7 K），no-op | 拉到 → read_cache 拿 4-3 K + 4-7 实时 → policy=4-7 | 4-7 (provisional) |
| 4-8 周三 | 交易 | ✅ | ✅ | cache append 4-7，探测=4-7，confirm 4-7 | policy=4-8 | 4-8 (provisional) |

### 4.2 劳动节（2026-04-30 ~ 2026-05-07）

| 日期 | 性质 | update.yml | 主站部署 | quant morning-rec | quant signal (14:48) | policy_state 终态 |
|------|------|------------|----------|---------------------|----------------------|-------------------|
| 4-30 周四 | 交易 | ✅ | ✅ | cache append 4-29，confirm 4-29 | policy=4-30 | 4-30 (provisional) |
| 5-1 周五 | 休（劳动节） | ✅ | ✅ | cache append 4-30，confirm 4-30 | skip | 4-30 (confirmed) |
| 5-2 周六 | 休 | ✅ | ❌ | cache 无新增，no-op | skip | 4-30 (confirmed) |
| 5-3 周日 | 休 | ✅ | ❌ | 同上 | skip | 4-30 (confirmed) |
| 5-4 周一 | 休（调休） | ✅ | ❌ | 同上 | skip | 4-30 (confirmed) |
| 5-5 周二 | 休（调休） | ✅ | ❌ | 同上 | skip | 4-30 (confirmed) |
| 5-6 周三 | 交易 | ✅ | ❌（昨日 5-5 非交易） | cache 拉到 4-30 仍无新增（5-5 休市无 K，5-6 当日盘中），no-op | 拉到 → read_cache 拿 4-30 K + 5-6 实时 → policy=5-6 | 5-6 (provisional) |
| 5-7 周四 | 交易 | ✅ | ✅ | cache append 5-6，confirm 5-6 | policy=5-7 | 5-7 (provisional) |

**关键边界 5-6**：跨 5 天连假后第一交易日。
- 主站不部署（昨日 5-5 非交易）→ 这就是 P2 误报场景
- **新方案下 quant morning-rec 仍然跑**（去掉 should_deploy 拦截）；cache 拉历史发现仍是 4-30，no-op
- signal 14:48 拉到 5-6 实时 + read_cache 拿 4-30 历史 → MA20 跨 5 天连假合成 → yesterday_policy=4-30、today_policy 由 5-6 实时决定 → 写 provisional policy=5-6
- 5-7 早间 cache append 5-6 → confirm 5-6 真值

**两个时间线均预期 0 次飞书警告 + 真实 MA20 计算（修了 P4）。**

⚠️ 假设前提：cron-job.org 在每天（含周末/节假日）触发 update.yml。如果它周末不触发，那 5-2 5-3 4-4 4-5 这些天 quant morning-rec 也不跑——这些天 fetcher 也探测不到新数据，跑也是 no-op，**不影响下游正确性**。

---

## 5. 改动清单（5 处，比 v3 多 1 处 C0）

### C0. （新增）scripts/quant/run_signal.py — morning-reconcile 增加历史 K 增量拉取

修 P4。在 `cmd_morning_reconcile` 早期阶段（探测 latest_X 之前）插入：

```python
def _refresh_history_cache(cfg, repo_root: Path) -> dict[str, "pd.DataFrame"]:
    """对 13 个指数拉 800 天历史日线，append 到本地 cache，返回 {code: df}。

    复用 scripts.data_fetcher.DataFetcher（主站版）的 fetch_index：
    - 自带主备源 fallback（cs_index → sina_index）
    - 自带网络重试（@retry_on_network_error 装饰器）
    - 800 天历史足够算 MA20 (D/W/M)
    """
    from scripts.data_fetcher import DataFetcher  # 只读复用，禁止改主站
    from .cache import append_daily

    cache_dir = repo_root / cfg.paths["cache_dir"]
    fetcher = DataFetcher()
    out: dict[str, pd.DataFrame] = {}
    for spec in cfg.indices:
        try:
            df = fetcher.fetch_index(spec.index_code, spec.source)
            if df is not None and not df.empty:
                merged = append_daily(cache_dir, spec.index_code, df)
                out[spec.index_code] = merged
        except Exception as e:
            print(f"warning: refresh cache for {spec.index_code} failed: {e}", file=sys.stderr)
            # 单个指数失败不影响其他；下次跑增量自愈
            continue
    return out


def _detect_latest_trading_day_from_cache(cache_dir: Path, sentinel_code: str) -> date | None:
    """从已填的 cache 读沪深300 最新交易日。"""
    from .cache import latest_date
    ts = latest_date(cache_dir, sentinel_code)
    return ts.date() if ts is not None else None
```

`cmd_morning_reconcile` 调用顺序：

```python
# C0 新增：先填 cache
caches = _refresh_history_cache(cfg, repo_root)
# 用 cache 读最新交易日（替代之前直接调 fetcher.fetch_history）
latest_X = _detect_latest_trading_day_from_cache(
    repo_root / cfg.paths["cache_dir"],
    cfg.sentinel_symbol,
)
# 后续 close_confirm / reconcile 都直接 read_cache（已填好）
```

`scripts/quant/config.yaml` 新增：
```yaml
sentinel_symbol: "000300"   # 沪深300 哨兵，用于探测最新交易日
```

### C1. update.yml — 去掉 quant 两个 step 的 should_deploy 拦截

```diff
   - name: Quant morning-reconcile（合并 reconcile + close-confirm；故障隔离不影响主链路）
-    if: steps.run_script.outputs.should_deploy == 'true' && steps.mode.outputs.mode == 'morning'
+    if: steps.mode.outputs.mode == 'morning'
     continue-on-error: true   # 保留：quant 失败不影响 deploy
     run: |
       python -m scripts.quant.run_signal morning-reconcile \
         --mock-now "$(TZ=Asia/Shanghai date -Iseconds)" \
         --writer-mode commit
     env:
       TZ: Asia/Shanghai

   - name: Push quant morning-reconcile commits（不静默吞错）
-    if: steps.run_script.outputs.should_deploy == 'true' && steps.mode.outputs.mode == 'morning'
+    if: steps.mode.outputs.mode == 'morning'
     continue-on-error: true   # 保留
     run: |
       set -e
       for i in 1 2 3; do
         if git pull --rebase --autostash origin main && git push origin main; then
           echo "✅ quant morning-reconcile commits pushed"
           exit 0
         fi
         ...
```

仅删 `steps.run_script.outputs.should_deploy == 'true' &&` 半段，保留 `mode == 'morning'` + `continue-on-error: true`。

⚠️ 不加 `if: always()`：main.py 失败率>33% sys.exit(1) 时 quant 跟着 skip 是保守且正确的（数据源异常时让 quant 带病跑更危险）。

### C2. quant.yml — 删除前置检查 step + signal step 去 --calendar

```diff
       - name: Run Quant Signal
         if: ${{ inputs.mode == 'signal' && inputs.skip_signal != 'true' }}
         run: |
-          if [ ! -f "docs/data/quant/.runs/morning-reconcile-${TODAY}.done" ]; then
-            curl -X POST "${FEISHU_WEBHOOK_URL}" -d '{...}'
-          fi
           python -m scripts.quant.run_signal signal \
             --mock-now "..." \
-            --calendar scripts/quant/tests/fixtures/trading_calendar_2026-04.json \
             --realtime auto --writer-mode commit
```

如果前置检查是独立 step（line 102-114），整段删除。`--calendar` 改为可选（mock-test 子命令仍 required）。

quant.yml **不新增 morning-reconcile mode**——生产 morning-rec 走 update.yml；run_signal.py 的 cmd_morning_reconcile 仍然存在给手动 / mock-test 用。

### C3. scripts/quant/run_signal.py — cmd_morning_reconcile 缓存式 + 追赶式

替换现有 `cmd_morning_reconcile`（line 163-212）：

```python
def cmd_morning_reconcile(args, cfg, repo_root: Path) -> None:
    today = datetime.fromisoformat(args.mock_now).date() if args.mock_now else date.today()
    done_file = _runs_done_file(repo_root, cfg, "morning-reconcile", today.strftime("%Y-%m-%d"))
    if done_file.exists():
        print(json.dumps({"status": "skipped_already_done", "date": today.strftime("%Y-%m-%d")},
                         ensure_ascii=False))
        return

    fetcher = _build_fetcher(args.realtime) if args.realtime != "skip" else None
    book = load_positions(repo_root / cfg.paths["positions"])
    writer = LocalWriter(repo_root, mode=args.writer_mode)
    cache_dir = repo_root / cfg.paths["cache_dir"]

    # === C0：先增量填 cache（13 指数历史 K）===
    _refresh_history_cache(cfg, repo_root)

    # === 探测最新交易日 X（直接从 cache 读，避免再网调）===
    latest_X = _detect_latest_trading_day_from_cache(cache_dir, cfg.sentinel_symbol)
    X_prev = _read_last_latest_trading_day(repo_root, cfg)

    advance_history = []
    cc_result = {"confirmed": 0, "false_signals": 0, "files_changed": []}
    policy_advanced = False

    # === 追赶式 confirm ===
    if latest_X is not None and (X_prev is None or latest_X > X_prev):
        for trading_day in _enumerate_trading_days_between(cache_dir, cfg.sentinel_symbol, X_prev, latest_X):
            yesterday_signal_file = repo_root / cfg.paths["signals_dir"] / f"{trading_day.strftime('%Y-%m-%d')}.json"
            if yesterday_signal_file.exists() and fetcher is not None:
                day_result = confirm_signals_with_close(
                    cfg=cfg, today=trading_day, book=book, fetcher=fetcher,
                    repo_root=repo_root, writer=writer,
                )
                advance_history.append({
                    "trading_day": trading_day.strftime("%Y-%m-%d"),
                    "confirmed": day_result["confirmed"],
                    "false_signals": day_result["false_signals"],
                })
                cc_result["confirmed"] += day_result["confirmed"]
                cc_result["false_signals"] += day_result["false_signals"]
                cc_result["files_changed"].extend(day_result["files_changed"])
        policy_advanced = bool(advance_history)

    # === reconcile 跨日 pending → expired ===
    rec_result = reconcile_pending_signals(cfg=cfg, today=today, repo_root=repo_root, writer=writer)

    # === 写新格式 done ===
    done_payload = json.dumps({
        "completed_at": datetime.now().isoformat(timespec="seconds"),
        "checked_date": today.strftime("%Y-%m-%d"),
        "latest_trading_day": latest_X.strftime("%Y-%m-%d") if latest_X else None,
        "policy_advanced": policy_advanced,
        "policy_advance_history": advance_history,
        "close_confirm": cc_result,
        "reconcile": rec_result,
    }, ensure_ascii=False, indent=2)
    writer.commit_atomic(
        [FileChange(path=done_file, content=done_payload)],
        message=f"[quant] mark morning-reconcile-{today.strftime('%Y-%m-%d')} done",
    )

    print(json.dumps({...}, ensure_ascii=False, indent=2))


def _read_last_latest_trading_day(repo_root: Path, cfg) -> date | None:
    """扫描 .runs/ 下所有 morning-reconcile-*.done，返回最近一份的 latest_trading_day。"""
    runs_dir = repo_root / cfg.paths["data_root"] / ".runs"
    if not runs_dir.exists():
        return None
    files = sorted(runs_dir.glob("morning-reconcile-*.done"), reverse=True)
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            X = data.get("latest_trading_day")
            if X:
                return datetime.fromisoformat(X).date()
        except (json.JSONDecodeError, KeyError):
            continue
    return None  # 旧格式 done 无此字段 → 退化为"全量探测"


def _enumerate_trading_days_between(cache_dir: Path, sentinel_code: str, X_prev: date | None, X: date) -> list[date]:
    """从 cache 已填的沪深300 日线读取 (X_prev, X] 区间的交易日。"""
    from .cache import read_cache
    df = read_cache(cache_dir, sentinel_code)
    days = sorted(d.date() if hasattr(d, "date") else d for d in df.index.unique())
    if X_prev is None:
        return [X]
    return [d for d in days if X_prev < d <= X]
```

### C4. scripts/quant/run_signal.py — cmd_signal_for_one_day 自探测 + 删前置检查

替换 `cmd_signal_for_one_day`（line 103-160）：

```diff
 def cmd_signal_for_one_day(args, cfg, repo_root: Path) -> None:
     today = datetime.fromisoformat(args.mock_now).date() if args.mock_now else date.today()

     done_file = _runs_done_file(repo_root, cfg, "signal", today.strftime("%Y-%m-%d"))
     if done_file.exists():
         print(json.dumps({"status": "skipped_already_done", ...}, ensure_ascii=False))
         return

-    if not _check_today_morning_reconcile_done(repo_root, cfg, today):
-        print(f"::warning::今日 morning-reconcile 未跑，yesterday_policy 可能失真", file=sys.stderr)

-    cal = _load_calendar(Path(args.calendar))
     fetcher = _build_fetcher(args.realtime)
+    cal = lambda d: True  # 自探测代替静态 calendar
     ...

     result = run_signal_generation(
         cfg=cfg, today=today, cal=cal, book=book, fetcher=fetcher,
         writer=writer, repo_root=repo_root,
     )

     if result.skipped_non_trading_day:
         print(json.dumps({"status": "skipped_non_trading_day", "date": result.date}, ensure_ascii=False))
         return  # 不写 done，不发通知
```

`signal_generator.run_signal_generation` 内部需调整：当 `fetcher.fetch_indices` 返回的沪深300 哨兵价缺失时，设置 `skipped_non_trading_day=True` 提早返回。这是替代静态 calendar 的核心点。

同时删除 `_check_today_morning_reconcile_done` 函数。`--calendar` 参数对 signal 子命令改为可选。

### C5. docs/quant/index.html — 前端状态文字

```javascript
// docs/quant/index.html (around line 113-118)
async function renderRunStatus(today) {
  const mr = await fetch(`/data/quant/.runs/morning-reconcile-${today}.done`).then(r => r.ok ? r.json() : null);
  const sg = await fetch(`/data/quant/.runs/signal-${today}.done`).then(r => r.ok ? r.json() : null);
  if (mr && sg) return ` · ${today} 已检查 · ${sg.signals_count} 信号`;
  if (mr && !sg) return ` · ${today} 已检查 · 当日非交易`;
  return ` · ${today} 未跑`;
}

const status = await renderRunStatus(todayStr);
el.innerHTML = `<div class="section"><h2>🔔 需确认 (${signals.length})<span class="run-status">${status}</span></h2>...`;
```

CSS（`docs/quant/style.css`）：
```css
.run-status { font-size: 0.7em; color: #888; font-weight: normal; margin-left: 8px; }
```

---

## 6. 数据契约变更

### 6.1 `morning-reconcile-{date}.done`（新格式 v2）

```json
{
  "completed_at": "2026-05-06T08:00:42",
  "checked_date": "2026-05-06",
  "latest_trading_day": "2026-04-30",
  "policy_advanced": false,
  "policy_advance_history": [],
  "cache_refresh": {"updated_codes": ["000300", "000016", ...], "failed_codes": []},
  "close_confirm": {"confirmed": 0, "false_signals": 0, "files_changed": []},
  "reconcile": {"expired_count": 0, "files_changed": []}
}
```

新增 `cache_refresh` 字段记录 C0 的 13 指数 cache 更新结果（便于审计）。

向后兼容：旧 done 无 `latest_trading_day` 时退化为"仅 confirm 最新一天"。

### 6.2 `signal-{date}.done`（不变）

```json
{"completed_at": "...", "trigger": "auto", "signals_count": 0}
```

文件不存在 = 今天 signal 没跑。

### 6.3 `positions.json`（schema 不变）

`bucket.policy_state` 含义不变。更新时机变化：morning-reconcile 探测到新交易日 K 线时回正（跨假期延后多天）。

### 6.4 `docs/data/quant/cache/{code}.csv`（新增数据存在）

每个指数一个 CSV，列 `date,close,open,high,low,volume`，覆盖 800 天日线。每天 morning-reconcile 增量 append。

`update.yml` 部署 step 已 exclude `data/quant/cache/**`（line 107）→ cache 不会发布到 gh-pages（避免 5MB+ 数据冗余传输）。

---

## 7. 实施 plan（TDD 顺序）

### 7.1 Step 1：节假日 fixture（先于代码）

```
scripts/quant/tests/fixtures/holiday_qingming_2026/
  ├── history_000300.csv   # 沪深300 日线 4-1 ~ 4-8（4-4 4-5 4-6 缺）
  ├── realtime_2026-04-02.json … realtime_2026-04-08.json（仅交易日）
  └── README.md

scripts/quant/tests/fixtures/holiday_labor_2026/
  ├── history_000300.csv   # 沪深300 日线 4-29 ~ 5-7（5-1~5-5 缺）
  ├── realtime_2026-04-30.json … realtime_2026-05-07.json
  └── README.md
```

`FixtureFetcher` 扩展：
- `fetch_history(symbol, source, days) -> DataFrame`（读 history_*.csv）
- `fetch_realtime(symbol)`（按 mock-now 路由，找不到返回 None）

### 7.2 Step 2：测试用例（先红）

`scripts/quant/tests/test_morning_reconcile_cache.py`：

```python
def test_cache_refresh_appends_history():
    """C0：morning-reconcile 调 _refresh_history_cache 后，cache_dir 下出现 13 个 CSV"""

def test_first_run_no_prior_done():
    """首次跑（无上次 done）→ 仅 confirm latest_X 一天 + 写新格式 done"""

def test_no_new_data_writes_noop_cache():
    """X == X_prev → policy_advanced=false + 仅写 done"""

def test_catch_up_confirm_across_holiday():
    """X_prev=4-30, X=5-6 → policy_advance_history 含 [{5-6, ...}]"""

def test_qingming_timeline_e2e():
    """按 §4.1 表格逐日跑，断言 done + policy_state + cache 内容"""

def test_labor_timeline_e2e():
    """按 §4.2 表格逐日跑，断言同上"""

def test_idempotent_same_day_run():
    """同日重复跑 → 第二次 skip"""

def test_old_format_done_backward_compat():
    """无 latest_trading_day → 退化"""
```

`scripts/quant/tests/test_signal_self_detection.py`：

```python
def test_signal_skip_when_no_realtime():
    """fetch_indices 不含 sentinel_symbol → skipped_non_trading_day"""

def test_signal_run_when_realtime_available():
    """fetch_indices 含 sentinel → 正常跑 + 写 done"""

def test_signal_no_longer_warns():
    """删除前置检查 → 即使 morning-reconcile-{today}.done 不存在也不警告"""

def test_signal_holiday_5_6_after_5day_break():
    """5-6 14:48：cache 提供 4-30 K + 实时 → 信号正常生成（修 P4 + 跨假期）"""

def test_signal_uses_cache_zero_history_network_calls():
    """断言 fetcher.fetch_history 在 signal 流程内调用次数 == 0（全部走 read_cache）"""
```

`scripts/quant/tests/test_main_isolation.py`（主站隔离回归）：

```python
def test_quant_failure_does_not_block_main_deploy():
    """模拟 morning-rec 抛异常 → main.py 仍正常 exit 0 + 模拟 deploy step 仍执行"""

def test_quant_does_not_modify_main_state_files():
    """跑完 morning-rec 后 ranking_history.json/docs/index.html 文件 mtime 不变"""
```

### 7.3 Step 3：实现（让测试转绿）

1. `FixtureFetcher.fetch_history` + `fetch_realtime`
2. `_refresh_history_cache` + `_detect_latest_trading_day_from_cache`（C0）
3. `_read_last_latest_trading_day` + `_enumerate_trading_days_between`
4. 重写 `cmd_morning_reconcile`（C3）
5. 重写 `cmd_signal_for_one_day` + `run_signal_generation` 自探测分支（C4）
6. 端到端节假日 fixture 回放

### 7.4 Step 4：workflow + 配置

1. `update.yml`：删 `should_deploy == 'true' &&` 半段（C1，仅改 if 行）
2. `quant.yml`：删前置检查 step + 去 `--calendar`（C2）
3. `scripts/quant/config.yaml`：加 `sentinel_symbol: "000300"`
4. cron-job.org 不动

### 7.5 Step 5：前端

`docs/quant/index.html` + `docs/quant/style.css`（C5）。本地 `cd docs && python -m http.server 8000` 预览三种 done 组合。

### 7.6 Step 6：回归 + 部署

1. `pytest scripts/quant/tests/` 全套绿（含主站隔离回归测试）
2. 本地 dry-run：
   ```bash
   python -m scripts.quant.run_signal morning-reconcile \
     --mock-now 2026-05-07T08:00:00+08:00 --realtime auto --writer-mode dry_run
   ```
   预期 console 输出 `cache_refresh.updated_codes` 含 13 个指数 + `latest_trading_day=2026-05-06`
3. 提 PR，CI 通过
4. 合 main，cron 沿用现有触发，观察 5-8 早间真实 morning-rec 跑得对不对（cache 出现 13 个 CSV、done 含 latest_trading_day=2026-05-07）

---

## 8. 验收清单

实现完成必须全部通过：

### 8.1 单元 + 集成测试

- [ ] morning-rec 跑完 cache_dir 下出现 13 个 CSV（修 P4）
- [ ] morning-rec 探测到新交易日 → confirm + 推进 policy + 写 done.latest_trading_day
- [ ] morning-rec 探测无新交易日 → no-op（policy 不变）+ 仅写 done
- [ ] morning-rec 跨假期追赶 → policy_advance_history 含对应交易日
- [ ] morning-rec 同日重复跑 → 第二次 skip
- [ ] signal 拉不到实时 → skipped_non_trading_day + 不写 done + 不发通知
- [ ] signal 拉到实时 → 用 cache 历史 + 实时算出真实 MA20 → 写 done（修 P4）
- [ ] signal 同日重复跑 → 第二次 skip
- [ ] 旧 done 文件无 latest_trading_day → 新跑能正常退化
- [ ] **signal 全流程 fetcher.fetch_history 调用次数 == 0**（全部命中 cache）

### 8.2 端到端 fixture 回放

- [ ] **清明 4-2 ~ 4-8 全 7 天**：按 §4.1 表格逐日断言 → 0 警告 + 真实 MA20
- [ ] **劳动 4-30 ~ 5-7 全 8 天**：按 §4.2 表格逐日断言 → 0 警告 + 真实 MA20

### 8.3 主站影响隔离回归（§3.3 硬约束验证）

- [ ] grep 确认 `scripts/main.py`、`scripts/data_fetcher.py`、`scripts/calculator.py`、`scripts/generator.py`、`scripts/ranking_store.py`、`scripts/templates/*` 在 v4 PR diff 中**零行改动**
- [ ] update.yml 主站 8 个 step（除 quant 两个）零行改动
- [ ] quant 失败模拟测试：morning-rec 强制抛异常 → main.py 仍 exit 0 + deploy step 仍执行
- [ ] quant push 失败模拟：push step 失败后 deploy step 仍执行（continue-on-error 生效）

### 8.4 静态校验

- [ ] update.yml 两个 quant step 的 `if` 条件已只剩 `mode == 'morning'`
- [ ] update.yml 两个 quant step 仍有 `continue-on-error: true`
- [ ] quant.yml 已删除前置检查 step
- [ ] 生产代码无引用 `trading_calendar_2026-04.json`（grep 仅 tests/ 目录还引用）

### 8.5 前端

- [ ] 三种 done 文件组合下的状态文字正确
- [ ] 本地 http.server 预览渲染正确
- [ ] 主站首页 `docs/index.html` 渲染未受影响（手动对比改前后）

### 8.6 真实部署

- [ ] cron-job.org 触发不变
- [ ] 5-8 早间真实跑：done 含 `latest_trading_day=2026-05-07` + `cache_refresh.updated_codes` 13 项 + `policy_advance_history` 含 5-7
- [ ] 5-8 14:48 真实跑：0 警告 + 真实 signals_count（非全 0）+ 总耗时 < 30s
- [ ] 主站 5-8 部署的 `docs/index.html` 与改前架构功能一致（指数排名等无回退）
- [ ] 后续 7 天不再出现 P1 / P2 / P4 类问题

---

## 9. 风险 & 不在范围

### 9.1 风险

| 风险 | 缓解 |
|------|------|
| AkShare `fetch_realtime` 不稳定 | 复用 `data_fetcher.py` 现有重试装饰器；探测失败按"非交易日"处理 |
| AkShare 拉历史 K 13 次中部分失败 | 单个失败 continue（不抛），下次跑增量 append 自愈；cache_refresh.failed_codes 上报 |
| morning-rec 增加 30s 耗时阻塞 update.yml | quant step `continue-on-error: true` + 主站 deploy step 在 quant 之后；quant 卡死不影响 deploy |
| 旧 done 无 `latest_trading_day` | `.get(..., None)` → 退化为全量探测 |
| 14:48 signal 拉历史 K 时 AkShare 返回当日盘中 K | 显式 `df = df[df["date"] < today]` 排除当日（写在 cache.append_daily 之前的过滤步骤） |
| `.runs/*.done` 部署列表是否包含 | 已确认 `quant.yml:236` 拷贝 `docs/data/quant/`，`.runs` 不在 rm 列表 |
| cache CSV 体积 > 5MB | `update.yml` exclude `data/quant/cache/**`（line 107），不发布到 gh-pages |
| main.py 失败率>33% sys.exit(1) 时 quant 跟着跳过 | 保守做法，本期不加 `if: always()` |

### 9.2 不在本次范围

- AkShare 数据延迟 > 24h 的硬告警（极端边界，留待观察）
- morning-rec 一天多次触发（一天一次足够）
- 自动生成 `trading_calendar.json`（fixture 仍手维护，仅供 pytest）
- 前端「晨检异常」分支（仅 morning-rec 没跑但 signal 跑了的边界，第一版不展示）
- cache 历史 K 体积优化（CSV 压缩 / Parquet 等）
- 主站 `data_fetcher.py` 的 quant 子集抽取（仍原样 import 复用）

---

## 10. v 版本对比

| 维度 | v1 | v2 | v3 | v4（最终） |
|------|----|----|----|-----------|
| 节假日日历 | ❌ 错把 5-4/5-5 当交易日 | ✅ 5-1~5-5 全休 | 同 v2 | 同 v2 |
| update.yml 改动 | 仅去 if | 把 quant step 整段搬走 | 仅去 if 半段（最小改动） | 同 v3 |
| quant.yml 改动 | 仅删前置检查 | 新增 morning-rec mode | 仅删前置检查 | 同 v3 |
| cron-job.org 改动 | 不改 | 新增 08:00 任务 | 不改 | 不改 |
| cache 写入（修 P4） | ❌ 漏 | ❌ 漏 | ❌ 漏 | ✅ 新增 C0 |
| 主站隔离硬约束 | 隐式 | 隐式 | 散落各处 | ✅ §3.3 章节 |
| 14:48 signal 耗时分析 | ❌ | ❌ | ❌ | ✅ §3.4 |
| 改动处数 | 5 | 5 | 4 | 5（含 C0） |

v4 = v3 + 修 P4（cache 写入）+ §3.3 硬约束 + §3.4 耗时分析。
