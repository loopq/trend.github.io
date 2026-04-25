# 量化信号系统 MVP — 产品需求与实施计划

> 版本：v1.5
> 起草日期：2026-04-25
> 最后修订：2026-04-25（用户调整范围：本期 MVP 只做"本地走通"，外部依赖全 mock）
> 范围：基于 V9.2 回测结果，落地一套半自动量化信号系统
> 形式：PRD（产品需求）+ TDD 实施计划

---

## 一、需求背景

### 1.1 当前现状
- `trend.github.io` 主站每日推送 13+ 全球指数对 MA20 的趋势状态（早间 morning 模式），定位是「监控仪表盘」。
- 子项目 `scripts/backtest/` 已完成 V4 → V5 → V6 → V9 多版本策略回测，**V9.2 验证 13 个中证/国证指数等权 + V4.1 Calmar 权重 D/W/M 内部分配**，3 年净 CAGR **+14.81%**、5 年 **+10.44%**（万一免五账户、扣交易磨损）。
- 用户拥有华宝、国元两个证券账户（万一免五，资金 < 50 万，无 QMT 量化资格）。

### 1.2 问题
- 回测结论存在，但**没有任何机制把策略信号传递给真人去执行**。
- 现有早间 morning 模式只能看「昨天收盘后的状态」，**无法在盘中尾盘时段触发买卖建议**——而 D/W/M 策略的下单时机是「每个 D/W/M 周期最后一个交易日的尾盘」。
- 用户需要在盘中（A 股 15:00 收盘前）拿到信号，**手动**到券商下单。靠人工每天盯盘 + 心算 MA20 不可行。

### 1.3 为什么是「半自动」而非「全自动」
- **资金门槛**：QMT/PTrade 通常要求金融资产 ≥ 50 万 + 量化资格审核，用户当前账户达不到。
- **EasyTrader 模拟点击**：依赖券商 GUI，稳定性差，券商客户端升级即崩。MVP 阶段引入会**把"信号是否对"和"下单是否成功"两个问题耦合到一起**，调试困难。
- **半自动的天然好处**：14:48 实时价 ≠ 15:00 收盘价的偏差在全自动模式下是大问题（可能下错单），但在半自动下变成优势——用户能瞄一眼 K 线决定要不要执行，等于免费给策略加了一道**人工真伪过滤**。

---

## 二、需求目标

> **每个交易日 14:48 自动生成 V9.2 当日 BUY/SELL 信号，通过飞书机器人推送到用户手机，用户在 14:48–14:57 集合竞价开始前手动下单，并在网页上输入实际成交价/数量做记录；前两周 paper trading（不实买不实卖）以打通流程，验证后切实盘。**

---

## 三、核心原则

### 3.1 半自动 = 系统出信号 / 人工审核执行
系统不直接下单。所有买卖动作由用户在券商端手动完成，再回到系统记录"实际成交价 + 实际成交数量"。

### 3.2 买卖必须严格配对（无 mock，无虚拟，尊重现实）
- **BUY 信号生成前提**：bucket `actual_state == CASH`
- **SELL 信号生成前提**：bucket `actual_state == HOLD`
- **「没买就是没买」**：用户跳过 BUY 后即使下穿也不发 SELL（你压根没买过，卖什么）
- **「不重复买」**：用户已经在 HOLD 状态，即使再次出现"上穿"也不发 BUY（已经持仓）
- 程序内强校验所有状态切换合理性；状态不一致 = bug，必须暴露报警

### 3.3 严格按 V9.2 回测信号语义（错过即错过）
- 信号判定仅来自「上穿事件」（昨日 below MA20 + 今日 above MA20）和「下穿事件」（反向）
- **不**回溯触发任何"补仓"信号
- 用户跳过即错过该周期完整行情，等下次完整周期（下穿+上穿）重新有机会
- 这是 V9.2 14.81% CAGR 的隐含前提，违反 = 偏离回测 = 实盘 PnL 不可解释

### 3.4 测试先行（TDD）
- Phase 1 纯逻辑层：测试覆盖率 ≥ 90%
- Phase 2 IO 层：测试覆盖率 ≥ 70%
- Phase 6 paper trading 2 周对账：作为最终集成验收

### 3.5 与生产链路解耦
- 量化信号系统在 `scripts/quant/` 子模块，**不修改** `scripts/main.py`、`scripts/data_fetcher.py` 等生产链路代码
- 共享只读资源（如交易日历、AkShare 数据接口），不共享可写状态

### 3.5.1 本地走通目标（MVP 实施期默认）
本期实施目标是在**本地把整个流程跑通**：所有 Python 代码 + 前端代码 + 测试 + workflow 文件齐全，TDD 全部通过，dry-run 端到端能跑通。**外部依赖全部 mock**，不依赖任何上线侧配置。

| 外部依赖 | 上线版 | 本地走通版（MVP 实施期）|
|---|---|---|
| 定时触发 | cron-job.org → repository_dispatch | 命令行 `python scripts/quant/run_signal.py --mock-now=2026-04-25T14:48:00+08:00` |
| 飞书推送 | 真发到 webhook URL | mock：写入 `data/quant/notify-outbox/{ts}.json` 模拟"已发送" |
| GitHub Git Data API 写文件 | 真调 API 写远端 | 本地分支直接写文件 + git commit（writer.py 抽象支持 `dry_run` / `local` 模式）|
| AkShare 实时行情 | 真调 API | mock fixture：`scripts/quant/tests/fixtures/realtime/{date}.json` |
| AkShare 历史日线 | 真调 API（首次拉 800 天）| 真调一次落地缓存，之后用本地 `data/quant/cache/*.csv` |
| 飞书 webhook URL | GitHub Secret `FEISHU_WEBHOOK_URL` | 环境变量 / `.env.local`（本地）+ `mock://feishu`（测试）|
| GitHub PAT | 网页运行时用户输入存 localStorage | 不需要本地配置（前端测试用 mock localStorage）|
| Paper trading 真实流程 | 10 个连续工作日观察 | **fixture 重放**：用历史日线模拟 10 个交易日，`run_signal.py --replay-window=2026-04-11..2026-04-25` |

**结论**：本期实施完成后，**整套流程在本地全部能 mock 跑通**；上线前只需要补：① 真实飞书 webhook URL ② cron-job.org 任务 ③ 用户在网页输 PAT，**不修改任何代码**。

### 3.6 入口密码 gate（弱保护）
- `docs/quant/` 所有页面访问前，前端 JS 先检查 localStorage `quant_auth` 标记
- 未通过 → 弹窗输入密码 → 计算 MD5 → 与硬编码常量 `eaf4f812fc1a6abc3e9b8182171ffc21`（密码 `weiaini` 的 MD5）比对
- 匹配后写 `localStorage.setItem('quant_auth', '1')`，永久生效（除非清缓存）
- **不防撞库 / 不防 brute force**：MD5 常量在前端 JS 源代码可见，懂技术者 5 分钟绕过；目的仅是防止偶然访问 / 搜索引擎索引 / 别人借用浏览器误点
- 这层保护与 GitHub PAT（写状态钥匙）相互独立：通过密码 gate 只能进入页面看数据，要写数据仍要 PAT
- **建议每季度轮换密码一次**：生成新 hash 替换前端常量并 commit，旧设备 localStorage 失效后重新输入

### 3.7 单写者原子提交（统一所有写路径）
- 任何状态文件（`positions.json` / `transactions.json` / `signals/*.json` / `signals/index.json`）的写入都必须**单 commit 打包多文件**，避免双文件非原子写造成账本漂移
- 实现：统一通过 `writer.py`（后端）/ `writer.js`（前端）抽象，内部用 GitHub Git Data API（`/git/blobs` + `/git/trees` + `/git/commits` + `/git/refs/heads/main`）一次 commit 写多文件，commit 时带 parent SHA 做乐观锁
- **硬约束**：禁止任何代码绕过 writer 直接调 GitHub Contents API 或单文件 PUT。code review 检查项。
- 14:48 workflow 单 commit 写：`signals/YYYY-MM-DD.json` (新文件) + `signals/index.json` (append) + `positions.json` (仅 policy_state 字段，merge 不覆盖)
- 用户网页确认单 commit 写：`transactions.json` (append) + `positions.json` (actual_state/shares/cash) + `signals/YYYY-MM-DD.json` (status，merge 同信号)
- 09:00 reconcile 单 commit 写：所有需要 `pending → expired` 的 `signals/{date}.json` + `signals/index.json`
- 15:30 close-confirm 单 commit 写：`signals/{today}.json` (provisional/confirmed_by_close/policy_state 修正) + `positions.json` (回正 policy_state) + `signals/index.json`
- **冲突处理**：parent SHA 不一致 → 重新拉最新 → 重 apply 修改 → 重试 commit（最多 3 次，超过则报警人工介入）

### 3.7.1 同日幂等合并规则（防重跑覆盖）
- 任何重跑信号生成（手动 dispatch / 重试 / cron 重发）时，**禁止**直接覆盖已存在的 `signals/YYYY-MM-DD.json`
- 写入逻辑：
  1. 若文件不存在 → 直接写
  2. 若文件已存在 → per-signal merge：
     - **可覆盖字段**：`provisional` / `confirmed_by_close` / `etf_realtime_price` / `bucket_cash` / `min_lot_cost` / `affordable` / `suggested_shares` / `expected_cost` / `warning` / `policy_state` 字段
     - **保留字段（永不覆盖）**：`status` / `actual_price` / `actual_shares` / `skip_reason` / `external_funded` / `confirmed_at` / `expired_at` / `expired_reason`
- 测试用例：故意 14:48 跑两次，第二次跑时第一次的 confirmed/skipped 信号 status 字段不变

### 3.8 信号双阶段（provisional → final）
- 14:48 触发用实时价生成的信号默认是 `provisional=true`：可能因尾盘 12 分钟波动而被收盘价证伪
- 15:30 收盘后 close-confirm 脚本读取真实 15:00 收盘价 → 重判信号 → 写回 `confirmed_by_close=true|false`
- 用户实际下单决策仍然基于 14:48 的 provisional 信号（盘中决策窗口要求）
- close-confirm 仅用于**事后统计假信号率**和**未确认的悬空信号清理**：用户没在当日确认 + close 不证实 → 自动 expired

---

## 四、范围

### 4.1 在 MVP 范围
- ✅ 14:48 触发的盘中信号生成（13 指数 D 每日 / W 周末 / M 月末）
- ✅ 飞书机器人单条信号卡片推送
- ✅ 静态网页 `docs/quant/`：密码 gate、总览页、需确认列表、历史操作、单指数详情（仿 backtest code.md，**不限条数**）、设置页
- ✅ 入口密码 gate（前端 MD5 比对 + localStorage 永久缓存）
- ✅ 用户 PAT（fine-grained）+ localStorage 鉴权 + 通过 writer.js 抽象（内部 GitHub Git Data API 单 commit 多文件原子提交）写状态文件
- ✅ 实际成交价/数量人工录入
- ✅ Paper trading 开关（前 2 周默认 ON，所有信号默认跳过）
- ✅ 09:00 morning 缓存增量更新
- ✅ 跨日状态隔离 / D/W/M bucket 复利隔离 / 13 等权初始化（每指数 1 万 = 总 13 万）

### 4.2 不在 MVP 范围
- ❌ 全自动下单（QMT / EasyTrader）
- ❌ 第二个证券账户的多账户分配
- ❌ 总市值收益曲线图
- ❌ 漂移自动对账（你账户实际持仓 vs 系统持仓的自动校验）
- ❌ 多通道推送（不做飞书 + 邮件双发）
- ❌ K 线 sparkline / 技术图表
- ❌ 微信 server酱 / Telegram bot 通道（飞书已够）
- ❌ 移动 App / 桌面 App（纯网页 + 飞书消息）

---

## 五、核心使用场景（用户视角）

### 5.0 场景：首次访问 — 密码 gate
> 用户首次访问 `loopq.github.io/trend.github.io/quant/`（任何子页面同理）→ 弹窗：
> ```
> ┌─────────────────────────────┐
> │  量化信号系统 - 访问验证      │
> │                              │
> │  请输入访问密码：            │
> │  [______________]           │
> │                              │
> │  [确认]                      │
> └─────────────────────────────┘
> ```
> - 用户输入密码 → 前端计算 MD5 → 与硬编码的 `eaf4f812fc1a6abc3e9b8182171ffc21` 比对
> - 匹配 → 写 `localStorage.setItem('quant_auth', '1')` → 进入页面
> - 不匹配 → 提示"密码错误"，输入框清空，留在弹窗
> - **localStorage 永久生效**（除非用户手动清浏览器缓存）
> - 不做尝试次数限制、不做撞库防护（私人工具，弱安全场景）
> - 鉴别凭据是「访问 quant 入口」的钥匙，与 GitHub PAT（写状态文件的钥匙）独立

### 5.1 场景：日常 14:48 收到飞书通知
> 工作日下午 14:48，用户手机飞书弹出一条卡片消息：
> ```
> [D-BUY] 中证白酒 (161725)
> 建议买入 200 股 @ ¥1.234
> 触发：close 1.234 > MA20 1.220 (+1.15%)
> bucket 现金 ¥1,234 → 买后剩 ¥987
> [→ 确认 / 跳过]
> ```
> 用户点击「确认 / 跳过」按钮 → 跳转到 `loopq.github.io/trend.github.io/quant/` 总览页（已通过 5.0 密码 gate）。

### 5.2 场景：日常网页查看
> 用户访问 `/quant/` 总览页：
> - 顶部「需确认（3 条）」区块：今日待处理信号
> - 中部「13 指数当前状态」卡片：每个指数 D/W/M bucket 的 actual_state（HOLD/CASH/N/A）+ 累计盈亏 + 点击进入单指数详情页
> - 底部「最近 7 天操作」时间线：已确认/已跳过的历史
> - 右上角配置入口

### 5.2.1 场景：单指数详情页（仿 backtest code.md 风格）
> 用户从总览卡片或导航点击「中证白酒 (399997)」→ `/quant/index/399997.html`：
>
> ```
> 中证白酒 (399997) → 招商中证白酒 (161725)
> ─────────────────────────────────────
> 当前状态总览
>   D bucket: HOLD 5800@¥1.236  →  ¥7,168.80 (+0.32%)
>   W bucket: CASH ¥610.00
>   M bucket: HOLD 1800@¥1.180  →  ¥2,124.00 (+5.62%)
>   合计市值 ¥9,902.80    起始 ¥10,000    累计盈亏 -0.97%
> ─────────────────────────────────────
> Calmar 权重快照
>   D 72.7% / W 6.1% / M 21.2%（V4.1 算法）
>   V9.2 best 策略：D    best alpha：+210.03%
> ─────────────────────────────────────
> 完整交易日志（分 D / W / M 三段，每段全量）
>
> ── D bucket 全部交易（按时间正序）──
>   #1  2026-04-08 BUY    5800@¥1.230  -¥7,134.00  fee ¥0.71
>   #2  2026-04-15 SELL   5800@¥1.220   +¥7,076.00 fee ¥7.78  PnL -1.49%
>   #3  2026-04-22 BUY    5800@¥1.236  -¥7,168.80  fee ¥0.72
>   ... 全部 N 条不分页
>
> ── W bucket 全部交易 ──
>   #1  2026-03-13 BUY    490@¥1.245  -¥610.05  fee ¥0.06
>   #2  2026-04-04 SELL   490@¥1.260  +¥617.40  fee ¥0.68  PnL +1.20%
>   ... 全部 M 条
>
> ── M bucket 全部交易 ──
>   #1  2026-02-28 BUY    1800@¥1.180  -¥2,124.00  fee ¥0.21
>   ... 全部 K 条
> ─────────────────────────────────────
> 历史信号（含 skipped）
>   按日期倒序展示该指数的所有历史信号 + status + 实际成交（如有）
>   可筛选：仅 D / 仅 W / 仅 M / 仅 confirmed / 仅 skipped
> ```
>
> **不做条数限制**，前端一次性渲染所有交易（按 V9.2 5 年回测频次估算每 bucket 30-50 条，13 指数 × 3 段 = 一个指数页 100-150 条，浏览器无压力）。
> 风格参照 `docs/agents/backtest/{code}.md` 的「完整交易日志」段落，但展示载体是网页 HTML 表格而不是 Markdown。

### 5.3 场景：用户确认成交
> 用户在券商 App 下完单（实际成交 200 股 @ ¥1.236）→ 回到网页点击「✅ 已成交」→ 弹窗：
> ```
> [D-BUY] 中证白酒 (161725) 建议 200 股 @¥1.234
> ─────────────────────────────────────
> ● 已成交：
>   实际成交价：[1.236  ] 元
>   实际成交数：[200    ] 股
>   备注（可选）：[                ]
> ─────────────────────────────────────
> [取消]  [确认提交]
> ```
> 提交后：
> - `transactions.json` append 一条 BUY 记录
> - `positions.json` 该 bucket `actual_state` CASH → HOLD，shares=200，avg_cost=1.236，cash 减少 247.20
> - `signals/YYYY-MM-DD.json` 该信号 `status=confirmed`
> - 网页前端乐观更新 UI（不等部署）+ 静默 fetch 验证

### 5.4 场景：用户跳过 / 无法成交
> 弹窗选「○ 跳过」+ 跳过原因（下拉）：
> - 主动跳过（不看好走势）
> - 涨停 / 跌停无法成交
> - 临停 / 停牌
> - 现金不够（外部不补）
> - 其他（备注）
>
> 提交后：
> - `transactions.json` 不追加（不算成交）
> - `positions.json` 不变（actual_state 保持）
> - `signals/...json` 该信号 `status=skipped`，附带 `skip_reason`

### 5.5 场景：异常 — 现金不足
> bucket 现金 80 元 < ETF 一手 123.40 元 → 信号 `affordable=false`：
> ```
> [D-BUY] 中证白酒 (161725)
> ⚠️ bucket 现金 ¥80 < 一手 ETF ¥123.40
> 建议跳过；如外部补充资金后下单，请在确认时勾选「外部补充资金」并填写实际成交
> ```
> 飞书 + 网页都显示警告。用户决策：
> - 跳过 → 自然（cash 累积到下次）
> - 外部补充资金后下单 → 弹窗多一项「☑ 突破 bucket 隔离（外部资金）」勾选，记录在 transactions 中 `external_funded=true` 用于事后审计

### 5.6 场景：异常 — PAT 过期
> 用户点确认 → 网页调 GitHub API 返回 401 → 网页弹窗：
> ```
> 你的 GitHub Token 已过期或失效。
> 请重新生成 Fine-grained PAT（仅限 loopq/trend.github.io 仓库的 Contents 读写权限），
> 然后粘贴到下方输入框。
> [输入新 PAT]  [应用]
> ```
> 应用后写入 localStorage，重试上次操作。

### 5.7 场景：自动 — 09:00 缓存更新
> 每天 09:00 GitHub Actions 触发 `scripts/quant/update_cache.py`：
> - 拉 13 指数昨日日线 → append 到 `data/quant/cache/{code}.csv`
> - 验证缓存最新日期 == 昨日交易日（节假日则前移）
> - commit 缓存到 main 分支
>
> 用户对此无感知。

### 5.8 场景：自动 — 节假日
> 14:48 触发但今天是节假日（akshare 交易日历判断为非交易日）：
> - 脚本立即退出，不更新任何文件
> - 不发飞书消息

### 5.9 场景：异常 — cron-job.org 失效
> 14:48 应该触发但 cron-job.org 没发请求（历史上偶尔发生）：
> - 用户发现没收到飞书 → 打开 GitHub Actions 页面
> - 手动触发 `quant-signal.yml` workflow_dispatch 按钮
> - 紧急情况下用户也可在终端 `gh workflow run quant-signal.yml`

---

## 六、关键决策与前因后果

### 6.1 决策：V6（行业指数）→ V9.2（中证/国证 + ETF）
- **背景**：V6 跑出 18.08% 净 CAGR（3 年）但用的是同花顺一级行业指数（881xxx），A 股**不能直接买指数**，且大部分 THS 一级行业**没有跟踪 ETF**。
- **结果**：实战版换成 V9.2 的 13 个中证/国证指数（10 个已有 ETF 代码 + 3 个常见 ETF 待补）。代价是 CAGR 降一档：3 年 14.81% / 5 年 10.44%。
- **代价的合理性**：V6 的 18% 不可达（无可投标的）；V9.2 的 14.81% 可达。

### 6.2 决策：半自动 → 不做全自动
- **背景**：用户两个证券账户金融资产 < 50 万，无 QMT/PTrade 资格；EasyTrader 模拟点击 Windows 依赖 + 不稳定。
- **结果**：MVP 仅做「信号 + 推送 + 人工确认」。
- **副产物**：14:48 实时价 vs 收盘价偏差在半自动下被人工审核 cover，反而是优势。

### 6.3 决策：飞书机器人 → 不做付费 server酱微信
- **背景**：server酱免费版 5 条/天，13 指数信号会超额；付费版 ¥18/月。Telegram bot 国内手机要翻墙。
- **结果**：飞书自建机器人，完全免费、无限量、国内手机原生通知、富文本卡片体验更好。用户已用飞书。

### 6.4 决策：网页按钮 + PAT localStorage → 不做后端 / 不用 GitHub Issue
- **背景**：用户偏好网页原生按钮 UI，不想用 Issue 跳转。GitHub 仓库写权限必须有鉴权方。
- **结果**：用户运行时输入 fine-grained PAT 存浏览器 localStorage，前端通过 `writer.js` 抽象调用 GitHub Git Data API 单 commit 多文件写状态文件。
- **风险与缓解**：
  - PAT 仅授权 `loopq/trend.github.io` 单仓库 Contents Read/Write，90 天过期
  - 私人工具场景无第三方脚本注入点 → XSS 风险接近 0
  - PAT 泄露最坏后果 = 该公开仓库被改 README，攻击面有限

### 6.5 决策：信号判断用「指数 K 线」/ 下单数用「ETF 实时价」
- **背景**：V9.2 回测全部用指数 K 线（如 399997 close vs MA20）。
- **结果**：
  - 信号判定：拉 13 指数实时价 + 历史日线缓存 → 算 MA20 → 判信号
  - suggested_shares 计算：拉 13 ETF 实时价 → bucket_cash // (etf_price × 100) × 100
  - 两批 API 调用，AkShare 都有
- **代价**：ETF 跟踪误差 < 1%/年，远小于 V9.2 净 CAGR

### 6.6 决策：13 等权 + V4.1 Calmar 内部权重
- **背景**：V9.2 回测的 14.81% 数字基于此分配。
- **结果**：每指数 1 万元（共 13 万），bucket 内按 Calmar 表（D/W/M 比例）分配。3 个 ❌ bucket（中证医疗 W、CS智汽车 W、中证军工 W）不创建，**有效 bucket = 36 个**。

### 6.7 决策：14:48 触发（提前 2 分钟到 14:50 → 14:48）
- **背景**：14:50 触发 → GitHub Actions runner 冷启动 30-60s → 推送到达可能 14:51-52 → 给用户 5 分钟决策（14:57 集合竞价开始）。窗口紧。
- **结果**：触发提前到 **14:48**。runner 启动 + 拉数据 + 计算 + 推送 ≈ 1-2 分钟，14:50 前后到达，给用户 7 分钟决策。

### 6.8 决策：全 CASH 启动 / 不做 bootstrap 补仓信号
- **背景**：13 指数中部分 bucket 当前已经在 HOLD 状态（close 已在 MA20 上方多日）。是否回溯触发"补仓"信号？
- **结果**：**不**做 bootstrap。所有 bucket 起始 CASH，等下次完整"上穿事件"才发 BUY 信号。
- **代价**：错过"启动时已在 HOLD"的 bucket 的当前行情。Paper trading 阶段不实买不实亏，对验证流程无影响。
- **理由**：保留 V9.2 信号语义干净（仅响应上穿/下穿事件），符合"尊重现实，没买就是没买"原则。

### 6.9 决策：跳过即错过 / 不发补仓提醒
- **背景**：用户跳过 BUY 后，actual=CASH 但 policy=HOLD。是否每周提醒"该补仓"？
- **结果**：**不**提醒。跳过 = 永久错过该周期，等下次完整周期（下穿+上穿）。
- **理由**：违反 V9.2 严格信号语义会让实盘 vs 回测偏离不可解释。

### 6.10 决策：入口密码 gate 用 MD5 硬编码 / 不做服务端鉴权
- **背景**：用户希望 quant 入口加一道门，防止搜索引擎索引 / 别人借浏览器误进 / 偶然访问。安全等级要求弱（接受懂技术者 5 分钟绕过）。
- **结果**：前端 JS 硬编码 `weiaini` 的 MD5（`eaf4f812fc1a6abc3e9b8182171ffc21`），用户输入 → 算 MD5 → 比对 → 写 `localStorage.quant_auth=1`。一次输入永久生效。
- **理由**：不引入后端、不引入 OAuth，与项目"零后端"哲学一致；明确接受不防 brute force（MD5 在源代码可见）；与 GitHub PAT 鉴权链路独立（PAT 防写、密码防进）。
- **不选**：sessionStorage（每次开浏览器要输烦）；后端密码校验（违反零后端原则）；HTTP Basic Auth（GitHub Pages 不支持）。

### 6.11 决策：单指数详情页不限条数 / 仿 backtest code.md
- **背景**：用户希望单指数详情页能查到所有历史交易（D/W/M 各自全量）+ 历史信号，不要翻页。
- **结果**：前端一次性渲染全部交易记录，分 D/W/M 三段。参考 `docs/agents/backtest/{code}.md` 的"完整交易日志"风格。
- **可行性**：V9.2 五年回测频次 = 每 bucket 30-50 条，13 指数 × 3 段一个指数页 100-150 条，浏览器渲染无压力。
- **代价**：transactions.json 整文件 fetch（300 天 × 5-10 条 = 1500-3000 条 ≈ 几百 KB）。前端做 in-memory 过滤即可。

### 6.12 决策：单 commit 多文件 / 不引入命令队列模式
- **背景**（review Round 1 Issue 1）：前端写 `transactions+positions` 双文件、workflow 写 `signals+positions.policy_state` 双文件，都是非原子，任一 PUT 失败即漂移。
- **候选方案**：
  - A. 用 GitHub Contents API 逐文件 PUT（已被 Round 1 review 否决）
  - B. 改单写者命令队列模式：前端只写 `commands/{ts}.json`，workflow 消费 → 单 commit 更新所有文件
  - C. 单 commit 多文件原子提交（用 Git Data API：blobs + trees + commits + refs）
- **采纳 C**：原子性达成 + 不引入异步消费链路的复杂度。前端写入路径仅多 30-50 行 JS 包装。
- **拒绝 B**：会引入「用户点完确认 → 等 workflow 消费 → 用户重新刷新看结果」的延迟链路，破坏当前的乐观更新 UX。

### 6.13 决策：信号状态机扩展 expired / 09:00 reconcile
- **背景**（review Round 1 Issue 2）：W/M 信号若未在当日确认，跨日时仅靠 `pending` 一种状态会悬空，UI 也会出现"昨日 W 还在等待确认"的混淆。
- **结果**：信号 status 增加 `expired` 第四值。每日 09:00 morning workflow 跑 reconcile：
  1. 读所有 `signals/*.json`，找出 `status==pending` 且 `date < today` 的信号
  2. 标记为 `expired`，附 `expired_at` + `expired_reason="not_confirmed_within_window"`
  3. positions.json `actual_state` 不变（用户没操作 = 没买/没卖）
- **拒绝 superseded / cancelled**：actual_state 严格配对（§3.2）已防止重复信号；用户主动跳过用 skipped 即可，不需要 cancelled。

### 6.14 决策：信号双阶段 provisional → final（不影响用户决策窗口）
- **背景**（review Round 1 Issue 3）：14:48 用实时价更新 policy_state 在尾盘 12 分钟剧烈波动时会产生假信号，污染长期统计。
- **结果**：14:48 信号默认 `provisional=true`；15:30 close-confirm 脚本用真实收盘价重判，写 `confirmed_by_close=true|false`。
- **用户行为不变**：仍在 14:48-14:57 决策窗口下单。差别在事后能统计假信号率（paper trading 阶段重要的验证数据）。
- 收盘验证不一致的 pending 信号 → 与 09:00 reconcile 合并清理为 expired。

### 6.15 决策：明确 SLO（飞书首条到达 p95 < 14:51）
- **背景**（review Round 1 Issue 4）：原 plan 用"1-2 分钟完成 + 7 分钟决策窗口"是描述性而非可验证。
- **结果**：定义可量化 SLO 并在 workflow 内埋点：
  - 信号生成结束（写 signals.json 完成）：p95 < 14:50:00（2 分钟）
  - 飞书首条到达：p95 < 14:51:00（3 分钟）
  - 飞书全部到达：p95 < 14:52:00（4 分钟）
- 推送方式从「每信号 1 卡片，串行 throttle」改为「单卡片汇总 + 链接到详情页」，减少串行耗时。
- Paper trading 10 个工作日内有 ≥ 9 天达 SLO 视为通过验收（允许 1 天波动）。

### 6.16 决策：通知失败硬失败（不再 silently log）
- **背景**（review Round 1 Issue 5）：通知是 MVP 核心价值，"信号生成成功但用户没收到" = MVP 失败。
- **结果**：飞书 webhook 发送失败 → 3 次指数退避重试（5s / 15s / 45s）→ 仍失败 = workflow exit 非 0 → GitHub Actions 默认发邮件到 GMAIL_USER。
- **MVP 不引入次级通道**（飞书 + 邮件双发是未来扩展）。

### 6.17 决策：基线快照锁定 13 指数
- **背景**（review Round 1 Issue 9）：`docs/agents/backtest/v9-summary.md` 第 62 行版本对比表写"V9.2（14 指数）"与正文"13 指数"矛盾。
- **校对结果**：经过逐行比对，**v9-summary.md 第 62 行的"14 指数"是笔误**：
  - 第 1 行明确"13 个手动精选指数（V9.2 版，已移除 中证500/中证1000/电力/中证2000 四个低波动指数）"
  - 排名表第 18-30 行恰为 13 行，编号 1-13
  - Calmar 权重表第 38-50 行也是 13 行
- **结果**：plan 锁定 **13 指数**为 V9.2 基线（与 V9.2 实际指数清单一致），附录 A 完整列出。验收时按 13 指数复现回测口径。同时**待办**：在 v9-summary.md 修订笔误（不在 MVP plan 范围，单独做）。

### 6.18 决策：Paper trading 10 个交易日（5 + 5 双阶段）
- **背景**：MVP 上线即真金白银投入风险高。需要先验证信号链路稳定 + 用户 UX 完整。
- **结果**：拆两阶段（详见 §10 Phase 6 / §11.2）：
  - **6.A auto_skip（前 5 个工作日）**：信号自动 skip，positions/transactions 几乎不动。验证：链路稳定性、推送到达率、close-confirm 假信号率、reconcile 正确性
  - **6.B manual_mock_confirm（后 5 个工作日）**：用户走完整确认/跳过流程，transactions 标记 `paper=true`，positions 双状态正常切换。验证：用户决策路径、单 commit 原子性、UX
- **验证项汇总**：SLO 三档时延 / 推送到达率 / 缓存陈旧风险 / 假信号率 / reconcile / PAT 流程 / 单 commit 原子性 / 网页确认 UX / Paper PnL vs V9.2 偏差（详见 §11.2）

---

## 七、数据契约

### 7.1 `data/quant/positions.json` — 36 bucket 当前状态

```json
{
  "version": 1,
  "updated_at": "2026-04-25T14:51:00+08:00",
  "paper_trading": true,
  "buckets": {
    "399997-D": {
      "index_code": "399997",
      "index_name": "中证白酒",
      "etf_code": "161725",
      "etf_name": "招商中证白酒",
      "calmar_weight": 0.727,
      "initial_capital": 7270.0,
      "actual_state": "CASH",
      "policy_state": "HOLD",
      "shares": 0,
      "avg_cost": 0.0,
      "cash": 7270.0,
      "last_action_date": null,
      "last_action_type": null
    }
    // 36 个 key（13 × 3 - 3 个 ❌）
  }
}
```

- `actual_state`: 用户实际持仓状态，由确认操作变更（CASH / HOLD）
- `policy_state`: 策略期望状态，由 close vs MA20 算出（CASH / HOLD），每次 14:48 跑完更新
- `paper_trading`: true 时网页提示「Paper Trading 模式，所有操作不影响真实账户」
- `last_action_date` / `last_action_type`: 最近一次 confirmed 的成交记录指针

### 7.2 `data/quant/signals/YYYY-MM-DD.json` — 当日信号

```json
{
  "date": "2026-04-25",
  "trigger_time": "14:48:00+08:00",
  "is_trading_day": true,
  "trigger_buckets": ["D"],
  "index_realtime_prices": {
    "399997": 1.234,
    "399989": 0.987
  },
  "etf_realtime_prices": {
    "161725": 1.236,
    "159875": 0.985
  },
  "signals": [
    {
      "id": "2026-04-25-399997-D",
      "bucket_id": "399997-D",
      "action": "BUY",
      "trigger_event": "policy_cash_to_hold",
      "trigger_condition": "close 1.234 > MA20 1.220 (+1.15%)",
      "yesterday_policy": "CASH",
      "today_policy": "HOLD",
      "actual_state": "CASH",
      "etf_realtime_price": 1.236,
      "bucket_cash": 7270.0,
      "min_lot_cost": 123.60,
      "affordable": true,
      "suggested_shares": 5800,
      "expected_cost": 7168.80,
      "warning": null,
      "provisional": true,
      "confirmed_by_close": null,
      "status": "pending",
      "actual_price": null,
      "actual_shares": null,
      "skip_reason": null,
      "external_funded": false,
      "confirmed_at": null,
      "expired_at": null,
      "expired_reason": null
    }
  ]
}
```

- `trigger_event`: `policy_cash_to_hold` (BUY) / `policy_hold_to_cash` (SELL)
- `status`: `pending` / `confirmed` / `skipped` / **`expired`**（next-day reconcile 自动迁移）
- `skip_reason`: `manual` / `limit_up` / `limit_down` / `suspended` / `insufficient_cash` / `other`
- `provisional`: 是否为 14:48 实时价生成（未经收盘价确认）
- `confirmed_by_close`: 15:30 close-confirm 脚本写入。`true` = 收盘价仍触发同方向 / `false` = 假信号 / `null` = 未跑过 close-confirm
- `expired_at` / `expired_reason`: 09:00 reconcile 写入

### 7.3 `data/quant/transactions.json` — 成交流水（append-only）

```json
{
  "transactions": [
    {
      "tx_id": "tx-2026-04-25-399997-D-001",
      "date": "2026-04-25",
      "bucket_id": "399997-D",
      "signal_id": "2026-04-25-399997-D",
      "action": "BUY",
      "shares": 200,
      "price": 1.236,
      "amount": 247.20,
      "fee": 0.0247,
      "external_funded": false,
      "paper": true,
      "note": "",
      "confirmed_at": "2026-04-25T14:53:21+08:00"
    }
  ]
}
```

- `paper`: paper trading 阶段（无论 auto_skip 还是 manual_mock_confirm 模式）的成交记录均为 `true`，实盘后切 `false`。便于事后过滤分析。

### 7.4 `data/quant/signals/index.json` — 信号文件索引（前端按需 fetch 用）

由于浏览器无法对 GitHub Pages 静态目录做通配符列表，需要显式索引：

```json
{
  "version": 1,
  "updated_at": "2026-04-25T14:50:00+08:00",
  "entries": [
    {
      "date": "2026-04-25",
      "file": "signals/2026-04-25.json",
      "signal_count": 3,
      "pending_count": 1,
      "confirmed_count": 1,
      "skipped_count": 1,
      "expired_count": 0,
      "buckets": ["D"]
    }
  ]
}
```

- 每次 14:48 workflow 写入新 signals/YYYY-MM-DD.json 后，同 commit 更新 index.json append 一条
- 每次 09:00 reconcile（pending → expired）后，同 commit 更新 index.json 的对应日期条目
- 前端先 fetch index.json → 决定要拉哪些日期文件 → 按需 lazy load

### 7.5 `data/quant/cache/{index_code}.csv` — 历史日线缓存

CSV 表头：`date,close,open,high,low,volume`，行按日期升序。每个指数一个文件，共 13 个。

### 7.6 `scripts/quant/config.yaml` — 配置

```yaml
total_capital: 130000   # 总本金 13 万
per_index_capital: 10000  # 每指数 1 万

indices:
  - index_code: "399997"
    index_name: "中证白酒"
    data_source: "cs_index"
    etf_code: "161725"
    etf_name: "招商中证白酒"
    calmar_weights:
      D: 0.727
      W: 0.061
      M: 0.212
  # ... 13 个指数

trigger:
  signal_time: "14:48"
  cache_update_time: "09:00"
  timezone: "Asia/Shanghai"

paper_trading:
  enabled_until: "2026-05-09"  # 起步后 2 周
  mode: "auto_skip"  # auto_skip | manual_mock_confirm | off
  # auto_skip: 信号自动 skip（前 1 周纯观测）
  # manual_mock_confirm: 用户走完整确认流程，transactions 标记 paper=true（第 2 周）
  # off: 实盘

slo:
  signals_written_p95_seconds: 120   # 14:48 起算，p95 < 14:50 写完 signals.json
  feishu_first_arrival_p95_seconds: 180  # p95 < 14:51 飞书首条到达
  feishu_all_arrival_p95_seconds: 240    # p95 < 14:52 飞书全部到达

notification:
  channel: "feishu"
  webhook_secret: "FEISHU_WEBHOOK_URL"
  retry: { count: 3, backoff_seconds: [5, 15, 45] }  # 指数退避
  fail_workflow_on_unrecoverable_failure: true       # 重试耗尽 → workflow 非 0 退出 → GitHub 默认发邮件
```

---

## 八、状态机与信号生成

### 8.1 bucket 双状态模型

```
actual_state: CASH | HOLD
  - CASH: 用户实际未持有 ETF（含从未买入、已卖出）
  - HOLD: 用户实际持有 ETF（数量 = bucket.shares）
  - 状态切换由「用户确认操作」触发，绝不被信号生成自动改变

policy_state: CASH | HOLD
  - 由 close vs MA20 计算：close > MA20 → HOLD，close <= MA20 → CASH
  - 每次 14:48 跑完都重新计算并写入 positions.json
```

### 8.2 信号生成规则（严格配对 + bucket 级隔离）

```python
class StateInvariantError(Exception):
    """状态机不变量违反；bucket 级隔离，单 bucket 报错不影响其他 bucket"""
    def __init__(self, bucket_id, reason):
        self.bucket_id = bucket_id
        self.reason = reason
        super().__init__(f"[{bucket_id}] {reason}")


def generate_signal(bucket, today_close, ma20, yesterday_policy):
    today_policy = "HOLD" if today_close > ma20 else "CASH"

    # 上穿事件
    if yesterday_policy == "CASH" and today_policy == "HOLD":
        if bucket.actual_state == "CASH":
            return BUY signal  # 含 provisional=True
        else:
            # actual=HOLD 但 yesterday_policy=CASH —— 数据不一致
            raise StateInvariantError(bucket.id,
                "actual=HOLD 但 yesterday_policy=CASH，状态机异常")

    # 下穿事件
    elif yesterday_policy == "HOLD" and today_policy == "CASH":
        if bucket.actual_state == "HOLD":
            return SELL signal
        else:
            # 用户跳过过 BUY，actual=CASH，下穿不发卖（尊重现实）
            return None

    else:
        return None  # 状态未变，无信号


# 主流程：bucket 级隔离
def run_signal_for_all_buckets(buckets, ...):
    signals = []
    errors = []
    for bucket in buckets:
        try:
            sig = generate_signal(bucket, ...)
            if sig:
                signals.append(sig)
        except StateInvariantError as e:
            errors.append(e)
            log.error(f"bucket {e.bucket_id} 状态异常：{e.reason}（不影响其他 bucket）")
            continue
    if errors:
        notify_feishu_alert(errors)  # 异常聚合一条飞书警告
    return signals
```

**为什么不用 assert**：生产环境若以 `python -O` 启动会去掉 assert；且 assert 抛 AssertionError 会让整批信号中断。改成 `StateInvariantError` 显式异常 + bucket 级 try/except 隔离 = 单桶故障不影响整体（review Round 1 Issue 13）。

### 8.3 跳过的语义

| 情况 | bucket.actual | bucket.policy | 后续行为 |
|---|---|---|---|
| 跳过 BUY | CASH | HOLD | policy 维持 HOLD 期间无信号；下穿不发 SELL；下次上穿（先回 CASH 再 HOLD）才有 BUY |
| 跳过 SELL | HOLD | CASH | policy 维持 CASH 期间无信号；上穿不发 BUY（已持仓）；下次下穿（先回 HOLD 再 CASH）才有 SELL |

### 8.4 不可能信号（StateInvariantError + bucket 级隔离）

以下情况说明 positions.json 与 transactions.json 状态错乱，抛 `StateInvariantError`、bucket 级隔离、聚合一条飞书警告卡片：

- BUY 信号生成时 `actual_state == HOLD`（理论被严格配对防住，出现即数据 bug）
- SELL 信号生成时 `actual_state == CASH`（理论被严格配对防住）
- positions.json `actual_state==HOLD` 但 `shares == 0`
- positions.json `actual_state==CASH` 但 `shares > 0`
- transactions append 后 positions 未同步更新（差额检查：sum(transactions for bucket) ≠ position.shares × position.avg_cost）

### 8.5 09:00 reconcile（信号悬空清理）

每日 09:00 morning workflow 跑 `scripts/quant/reconcile.py`：

```python
def reconcile_pending_signals():
    today = today_trading_date()
    index = read_signals_index()
    files_to_commit = ["data/quant/signals/index.json"]  # 索引必改

    for entry in index.entries:
        if entry.date >= today:
            continue
        if entry.pending_count == 0:
            continue
        signals = read_signals_file(entry.file)
        any_changed = False
        for sig in signals:
            if sig.status == "pending":
                sig.status = "expired"
                sig.expired_at = now_iso()
                sig.expired_reason = "not_confirmed_within_window"
                any_changed = True
        if any_changed:
            files_to_commit.append(entry.file)
            update_index_entry(index, entry.date)  # pending_count -= n, expired_count += n

    # 单 commit 一次性提交所有变更（避免循环内 commit 产生中间态）
    if len(files_to_commit) > 1:
        writer.commit_atomic(files_to_commit, commit_message=f"reconcile pending → expired {today}")
```

- 修订点（Round 2 Issue 8）：先收集所有待改文件，**循环外**一次 commit，避免 N 次 commit 中部分成功部分失败
- positions.json `actual_state` 不动（用户没操作 = 没买/没卖）
- 索引文件同步更新：pending_count 减少、expired_count 增加
- 不发飞书通知（用户已经"消极跳过"，不需要再打扰）

### 8.6 15:30 close-confirm（provisional → final，含 policy_state 回正）

每个交易日 15:30 触发 `scripts/quant/close_confirm.py`（A 股 15:00 完全收盘 + 数据可拉到当日收盘价）：

```python
def confirm_signals_with_close():
    today_signals = read_today_signals()
    positions = read_positions()
    files_to_commit = []  # 收集，单 commit 多文件

    for sig in today_signals:
        if not sig.provisional:
            continue
        # 用真实 15:00 收盘价重判
        close = fetch_today_close(sig.index_code)
        ma20 = recompute_ma20_with_close(sig.index_code, close)
        true_today_policy = "HOLD" if close > ma20 else "CASH"
        # 与 14:48 时的 today_policy 比对
        sig.confirmed_by_close = (true_today_policy == sig.today_policy)
        sig.provisional = False  # 已 final
        # 关键：回正 policy_state（无论 confirmed 还是 false 都用真值）
        positions.buckets[sig.bucket_id].policy_state = true_today_policy

    # 同时遍历无信号的 bucket（今日可能没生成信号但 close vs MA20 有变化）
    for bucket_id, bucket in positions.buckets.items():
        close = fetch_today_close(bucket.index_code)
        ma20 = recompute_ma20_with_close(bucket.index_code, close)
        bucket.policy_state = "HOLD" if close > ma20 else "CASH"

    # 单 commit 多文件
    writer.commit_atomic([
        f"data/quant/signals/{today}.json",
        "data/quant/positions.json",
        "data/quant/signals/index.json"
    ], commit_message=f"close-confirm {today}")
```

- **关键设计**：close-confirm 是 policy_state 的**最终真值来源**。14:48 写入的 policy_state 是 provisional（用实时价），close-confirm 用收盘价覆盖。次日 14:48 读 `yesterday_policy = positions.buckets[bid].policy_state` 时用的是真值，不会因尾盘波动产生级联错误。
- close-confirm 不改 `signals.status`（不影响用户已确认/已跳过的状态）；status 处理在 §8.5 reconcile 完成
- 假信号率统计（避免分母歧义）：当日参与 close-confirm 的信号数为 N（即原 `provisional==True` 的信号集合）；分子 = 这些信号中 `confirmed_by_close==False` 的数量；**假信号率 = 分子 / N**。在 paper trading 阶段是重要观察指标（≤ 15% 视为正常基线）。
- 节假日不跑 close-confirm（trigger 二次判断）

---

## 九、架构与模块

### 9.1 模块图

```
                  cron-job.org
                       │
            ┌──────────┼──────────┐
            │          │          │
        14:48         09:00   workflow_dispatch
        signal       cache    (手动)
            │          │          │
            ▼          ▼          ▼
       ┌─────────────────────────────┐
       │   GitHub Actions runner     │
       └────────────┬────────────────┘
                    │
                    ▼
       ┌─────────────────────────────┐
       │   scripts/quant/            │
       │   ├── config.py             │
       │   ├── state.py              │
       │   ├── signal_engine.py      │
       │   ├── trigger.py            │
       │   ├── affordability.py      │
       │   ├── cache.py              │
       │   ├── data_fetcher.py       │
       │   ├── notifier.py           │
       │   ├── signal_generator.py   │
       │   ├── update_cache.py       │
       │   └── run_signal.py         │
       └────────────┬────────────────┘
                    │
                    ▼
       ┌─────────────────────────────┐
       │  data/quant/                │
       │  ├── positions.json         │
       │  ├── transactions.json      │
       │  ├── signals/YYYY-MM-DD.json│
       │  └── cache/*.csv            │
       └────────────┬────────────────┘
                    │
        ┌───────────┴────────────┐
        │                        │
        ▼                        ▼
   ┌───────────┐          ┌──────────────┐
   │ 飞书 webhook│          │ docs/quant/  │
   │ (push)    │          │ (静态网页)    │
   └───────────┘          └──────┬───────┘
                                 │
                                 ▼
                          ┌──────────────────────┐
                          │ 用户浏览器             │
                          │ ① 密码 gate (MD5)    │
                          │ ② PAT (localStorage) │
                          │ ③ 写状态文件          │
                          └──────────────────────┘
```

**前端访问流程**：

```
用户访问 /quant/* 任意页面
    │
    ▼
检查 localStorage.quant_auth == '1' ?
    │           │
    ▼ NO        ▼ YES
弹窗输入密码    继续
计算 MD5
比对 eaf4f812fc1a6abc3e9b8182171ffc21
    │
    ▼ 匹配
写 localStorage.quant_auth = '1'
继续
    │
    ▼
检查 localStorage.github_pat ?（仅写操作前需要）
    │           │
    ▼ NO        ▼ YES
PAT 输入弹窗   继续读/写文件
```

### 9.2 关键模块职责

| 模块 | 职责 | 测试覆盖率目标 |
|---|---|---|
| `config.py` | 加载 yaml；生成 36 个有效 bucket（跳过 ❌）；按 Calmar 切分本金 | ≥ 95% |
| `state.py` | positions/transactions 读写；状态机切换强校验；StateInvariantError + bucket 级隔离 | ≥ 95% |
| `signal_engine.py` | MA20 计算；周/月线重采样；实时价 + 缓存拼接；信号判定（严格配对） | ≥ 95% |
| `trigger.py` | 是否交易日 / 周末 / 月末判断；半日休市识别；今日跑哪些 bucket | ≥ 90% |
| `affordability.py` | 现金不足一手判定；suggested_shares 计算 | ≥ 95% |
| `cache.py` | 增量 append 缓存；最新日期校验；fixture / live 模式切换 | ≥ 80% |
| `data_fetcher.py` | AkShare 实时全量 + ETF 实时价拉取；重试 + 失败兜底 | ≥ 70% |
| `notifier.py` | 飞书 webhook POST；单卡片汇总；3 次指数退避重试；失败抛异常让 workflow fail | ≥ 80% |
| `writer.py` | **新增**：GitHub Git Data API 单 commit 多文件原子提交封装；parent SHA 乐观锁 + 3 次重试 | ≥ 90% |
| `signal_generator.py` | 端到端：trigger → 拉数据 → 算信号 → 写 signals.json + 更新 index.json + positions.policy_state（**单 commit**） | ≥ 80% |
| `reconcile.py` | **新增**：09:00 跨日清理（pending → expired），单 commit 多文件 | ≥ 90% |
| `close_confirm.py` | **新增**：15:30 收盘价 reconcile（provisional → confirmed_by_close） | ≥ 80% |

### 9.3 触发时序

**14:48 信号生成流程**（SLO p95 < 14:51 飞书首条到达）：

```
T+0:00  cron-job.org 发送 repository_dispatch
T+0:05  GitHub Actions runner 启动（冷启动 30-60s）
T+0:45  Python 环境就绪，加载 config + positions
T+0:50  trigger.py：判断今天是否交易日 → 是
        判断今天跑哪些 bucket → ["D"]（或周五加 W、月末加 M）
T+1:00  data_fetcher.py：拉 13 指数实时价（一次 API）+ 13 ETF 实时价（一次 API）
T+1:10  signal_engine.py：从缓存读历史日线 + 拼接今日实时 → 算 MA20
        对每个 bucket 计算 today_policy、yesterday_policy、生成信号（含 provisional=true）
T+1:20  signal_generator.py + writer.py：
        【单 commit】写 signals/YYYY-MM-DD.json + 更新 signals/index.json + 更新 positions.policy_state
        埋点：写入完成时间戳到日志（SLO 监测）
T+1:30  notifier.py：单卡片汇总所有信号（不再每信号一卡）+ 链接到详情页
        失败 → 5s/15s/45s 重试 → 仍失败 → workflow exit 1 → GitHub 默认发邮件
T+1:30 ~ T+3:00  GitHub Pages 部署 docs/quant/（用户网页同步刷新看到）
SLO: 信号写完 < T+2:00；飞书首条到达 < T+3:00
```

**09:00 缓存更新 + reconcile 流程**：

```
T+0:00  cron-job.org 发 dispatch
T+0:30  runner 启动
T+1:00  update_cache.py 拉 13 指数昨日日线 → append cache/*.csv
T+1:30  reconcile.py：扫描 signals/index.json，把昨日及之前的 pending → expired
T+1:45  【单 commit】写 cache/*.csv + signals/*.json (expired 字段) + signals/index.json
```

**15:30 close-confirm 流程**（A 股 15:00 收盘后）：

```
T+0:00  cron-job.org 发 dispatch（仅交易日）
T+0:30  runner 启动
T+1:00  close_confirm.py 拉今日收盘价 + 重判信号 + 写 confirmed_by_close
        + 同步遍历无信号 bucket，回正所有 bucket 的 policy_state
T+1:15  【单 commit】写 signals/{today}.json + positions.json (policy_state 回正) + signals/index.json
```

---

## 十、TDD 实施计划

### Phase 0：脚手架（预估 0.5 天）

| 任务 | 验收 |
|---|---|
**Phase 0 范围调整（MVP 实施期）**：仅做"本地走通"必需的代码骨架与配置；上线前才需要的人工动作（真实飞书机器人、PAT 申请、cron-job.org 配置、外链联调）全部移到 §10 Phase 7（切实盘前的上线清单）。

| 任务 | 验收 |
|---|---|
| 创建 `scripts/quant/` 子模块 + `__init__.py` | 目录存在 |
| 创建 `scripts/quant/tests/` + `pytest.ini` + `conftest.py` + `fixtures/` | `pytest scripts/quant/tests/` 能跑空套件 |
| 测试基建：写 `requirements-dev.txt`（pytest + pytest-cov + selenium + chromedriver-autoinstaller）| `pip install -r requirements-dev.txt` 成功 |
| 测试基建：固定 Python 版本 ≥ 3.10（venv 已用）+ 在 README 标注 | venv 启动无错 |
| 测试基建：`.github/workflows/quant-test.yml` PR 触发，`.coveragerc` + `check_per_module_coverage.py` 后置脚本（核心 90% / IO 70% / 端到端 80%）| 文件存在；后置脚本可独立跑 |
| **前端测试方案**：vanilla JS + mini test runner（`docs/quant/tests/run.html`），CI 用 pytest + selenium 驱动 headless chromium，**不引入 npm/Node** | 文件存在；本地 `python scripts/quant/tests/run_browser_tests.py` 可独立跑 |
| 写 `config.yaml`（13 指数 ETF 映射 + Calmar 权重，按附录 A 已封版表）| YAML 解析无错；13 个 ETF 全部填实 |
| 新建 `data/quant/` 空目录 + `.gitkeep`（cache/ + signals/ + notify-outbox/ 子目录）| 目录存在 |
| 新建 `docs/quant/` 目录 + 引入 [js-md5](https://github.com/emn178/js-md5) 单文件库（约 5KB）放 `docs/quant/lib/md5.min.js` | 文件存在，浏览器 import 后 `md5("weiaini")` 返回 `eaf4f812fc1a6abc3e9b8182171ffc21` |
| writer 抽象 `scripts/quant/writer.py`：本地走通模式（写文件 + 本地 `git add/commit` 模拟原子提交）+ 上线模式（GitHub Git Data API）切换 | 单元测试覆盖两种模式 |
| `notifier.py`：dry-run 模式（写 `data/quant/notify-outbox/{ts}.json`）+ 真发模式（POST webhook）切换 | 单元测试覆盖两种模式 |
| 补 `CLAUDE.md` 引用 `scripts/quant/` 子模块 | CLAUDE.md 有指引 |
| **基线快照锁定**：附录 A 已封版（13 指数 + 13 ETF 全部填实，无候选）| 实施期变更需走变更管理 |
| 修订 `docs/agents/backtest/v9-summary.md` 第 62 行 "V9.2（14 指数）" 笔误为 "（13 指数）"（独立小 PR，不阻塞 quant 开发）| 文档一致 |

**移到 Phase 7（上线前清单）的人工动作**（不阻塞本地走通）：

| 任务 | 时机 |
|---|---|
| 用户创建飞书自建机器人 + 拿 webhook URL → GitHub Secret `FEISHU_WEBHOOK_URL` | Phase 7 上线前 |
| 飞书卡片跳转联调（发测试卡片，确认按钮可跳 `https://loopq.github.io/trend.github.io/quant/`）| Phase 7 上线前 |
| cron-job.org 三个 cron 任务（14:48 / 09:00 / 15:30）| Phase 7 上线前 |
| 用户在网页运行时输入 fine-grained PAT（**这本来就是网页内交互，不需要 Phase 0 commit 任何 secret**）| 用户首次访问 quant 页面时 |

### Phase 1：纯逻辑层（TDD，预估 2-3 天）

每个模块：**先写测试 → 写实现 → 通过测试**。所有测试不联网，使用 fixture。

#### 1.1 `config.py`
- 测试：从 yaml 加载 → 生成 36 个 bucket（跳过 3 个 ❌）
- 测试：每指数 1 万 × Calmar 权重切分正确（中证白酒 D=7270, W=610, M=2120）
- 测试：bucket key 格式 `{index_code}-{D|W|M}`
- 测试：缺失 ETF 代码时报错（含 `中证医疗`、`创业板50`、`中证新能` 这 3 个待补的字段校验）

#### 1.2 `state.py`
- 测试：初始 positions.json 创建（36 bucket 全 CASH 状态）
- 测试：BUY confirmed → actual_state CASH→HOLD，cash 减少，shares 增加，avg_cost 写入
- 测试：SELL confirmed → actual_state HOLD→CASH，cash 增加，shares 清零
- 测试：SKIP → 状态不变
- 测试：external_funded BUY → 标记 + cash 计算允许超额
- 测试：transactions.json append-only（已存在不重写）
- 测试：状态不一致抛 `StateInvariantError`（actual=HOLD 但 shares=0 / actual=CASH 但 shares>0 等），bucket 级隔离不中断其他 bucket

#### 1.3 `signal_engine.py`
- 测试 fixture（多种 K 线场景）：上穿日 / 下穿日 / 震荡日 / 持续 HOLD / 持续 CASH
- 测试：MA20 计算正确（手算对照）
- 测试：周线重采样从日线生成（W-FRI 对齐）
- 测试：月线重采样从日线生成（月末对齐）
- 测试：实时价拼接（昨日往前 19 日 + 今日实时 = 20 日 → MA20 输入）
- 测试：信号判定（严格配对）：
  - actual=CASH + 上穿 → BUY
  - actual=HOLD + 下穿 → SELL
  - actual=CASH + 下穿 → None（尊重现实）
  - actual=HOLD + 上穿 → 抛 `StateInvariantError`（不可能信号），单 bucket 报警不影响其他 bucket
  - 状态未变 → None

#### 1.4 `trigger.py`
- 测试：交易日判断（akshare 交易日历 mock）
- 测试：节假日跳过（春节、国庆、清明等多日）
- 测试：今日是否本周最后交易日（周五常态 + 周五节假日前移到周四）
- 测试：今日是否本月最后交易日（月末交易日 vs 月末节假日前移）
- 测试：14:48 跑哪些 bucket：
  - 周一-周四（非月末）→ ["D"]
  - 周五（非月末）→ ["D", "W"]
  - 月末交易日（非周五）→ ["D", "M"]
  - 月末交易日 = 周五 → ["D", "W", "M"]
- 测试：半日休市识别（除夕等）

#### 1.5 `affordability.py`
- 测试：bucket cash >= ETF 一手 → affordable=true，suggested 整手取整
- 测试：bucket cash < ETF 一手 → affordable=false，suggested=0，warning 文本
- 测试：边界（cash 恰好 = 一手）→ affordable=true
- 测试：bucket cash 0 元（首次启动 W bucket 还没分到钱）→ 不发信号

### Phase 2：IO 层（mock + 实跑各一次，预估 2 天）

#### 2.1 `cache.py`
- 测试：从 CSV 读取（mock 文件）
- 测试：append 新一日数据，dedup 重复日期
- 测试：缓存最新日期校验（必须 == 昨日交易日）
- **实跑**：调 AkShare 拉 13 指数 800 天历史，写入 `data/quant/cache/`，验证文件数量 + 行数

#### 2.2 `data_fetcher.py`
- 测试：mock AkShare 实时全量返回 → 提取 13 指数实时价
- 测试：mock ETF 实时报价返回 → 提取 13 ETF 实时价
- 测试：API 失败 → 重试 2 次后抛错
- 测试：单个指数缺失 → 标记 missing，其他指数继续
- **实跑**：14:48 时间窗外手动跑一次 → 验证实时价合理（与同花顺 App 显示对照）

#### 2.3 `notifier.py`
- 测试：飞书 **单卡片汇总**结构（msg_type, header, elements，N 条信号合并到一卡，每条带跳转链接）
- 测试：webhook POST 失败 → 3 次指数退避重试（5s / 15s / 45s）
- 测试：3 次重试后仍失败 → 抛 `NotifierUnrecoverableError` → 调用方（run_signal.py）让 workflow exit 1（GitHub 默认发邮件）
- 测试：成功后 workflow exit 0
- **实跑**：手动发一条「测试信号」到飞书群，确认收到

### Phase 3：信号生成端到端（mock + 实跑，预估 1-2 天）

#### 3.1 `signal_generator.py`
- 测试：mock 一日 13 指数行情 → 生成完整 signals/YYYY-MM-DD.json
- 测试：周五 trigger_buckets=["D","W"] 验证 W 信号也参与
- 测试：月末 trigger_buckets=["D","M"]
- 测试：positions.json 的 policy_state 被更新（actual_state 不动）
- 测试：HOLD 状态不变 = 不进 signals 列表

#### 3.2 `run_signal.py` 端到端
- 测试：mock 全链路（trigger + fetch + engine + notifier）
- **实跑**：14:48 时间窗外手动 dry-run（写 signals 文件、不发飞书）
- **实跑**：14:48 时间窗外手动 full-run（写文件 + 发飞书测试卡片）

### Phase 4：网页前端（预估 3-4 天）

#### 4.1 静态页面框架
- `docs/quant/index.html` 总览页
- `docs/quant/history.html` 历史操作
- `docs/quant/index/{code}.html` 单指数详情（13 个，前端动态路由或预生成）
- `docs/quant/settings.html` 配置
- `docs/quant/auth.js` 共享密码 gate 脚本（所有页面 head 引入）
- 复用 `docs/index.html` 的 CSS 风格

#### 4.2 入口密码 gate（所有页面共享）
- 实现 `docs/quant/auth.js`：
  - 页面加载时立即检查 `localStorage.getItem('quant_auth') === '1'`
  - 已通过：直接放行
  - 未通过：DOM 注入半透明遮罩 + 居中弹窗（输入框 + 确认按钮）
  - 用户输入 → 计算 MD5（用 [js-md5](https://github.com/emn178/js-md5) 单文件 lib，约 5KB）→ 比对硬编码常量 `eaf4f812fc1a6abc3e9b8182171ffc21`
  - 匹配 → `localStorage.setItem('quant_auth', '1')` + 移除遮罩
  - 不匹配 → 输入框清空 + 红色提示"密码错误"
- 测试：
  - 已通过状态下不弹窗
  - 未通过状态下弹窗显示
  - 输入正确密码 → 写 localStorage + 移除遮罩
  - 输入错误密码 → 提示错误 + 留弹窗
  - localStorage 持久化（刷新页面后仍通过）
  - 多页面共享（在 index.html 通过后访问 history.html 不需要再输）

#### 4.3 前端 JS 数据加载
- 测试（前端 vanilla mini test runner，无 npm 依赖）：
  - fetch positions.json + cache-busting `?t=${Date.now()}`
  - fetch transactions.json + 全量加载（**MVP 阶段不分页**；当 transactions.transactions.length > **5000** 触发分片重构告警）
  - **fetch signals/index.json 索引**，根据用户筛选条件按需 lazy load 单日 `signals/YYYY-MM-DD.json`
- 测试：401 错误检测 → 弹窗提示重新输入 PAT
- 测试：transactions 数量超 5000 时控制台 console.warn 提醒分片重构

#### 4.4 PAT 鉴权
- 测试：PAT 写 localStorage / 读 localStorage
- 测试：PAT 有效性试探（GET `/repos/loopq/trend.github.io` 验证可访问，401/404 = 失效）
- 测试：清除 PAT（settings 页按钮）
- **不做权限范围自动校验**：GitHub fine-grained PAT API 不暴露已授权权限范围，无可靠 API 路径校验。settings 页改为：
  - 显示 PAT 创建指引截图（必须勾选 Contents Read/Write、禁勾 Workflows/Actions/Administration/Pages/Pull requests/Issues）
  - 用户自行确认「已按指引配置」复选框
  - 仅做有效性试探（连接 + 读权限）
- 注意：PAT 鉴权与 §4.2 密码 gate 是**两套独立** localStorage 键（`quant_auth` vs `github_pat`），分别管「能不能进页面」和「能不能写状态文件」

#### 4.5 弹窗确认 + GitHub Git Data API（**单 commit 多文件原子提交**）
- 测试：输入校验（成交价 > 0，成交数 100 倍数）
- 实现 `docs/quant/lib/writer.js`：
  ```
  async function commitMultipleFiles(files, commitMessage):
    1. GET /repos/{owner}/{repo}/git/refs/heads/main → 拿 base_sha
    2. GET /repos/{owner}/{repo}/git/commits/{base_sha} → 拿 base_tree_sha
    3. 对每个 file：POST /git/blobs → 拿 blob_sha
    4. POST /git/trees with {base_tree: base_tree_sha, tree: [...{path, mode, type, sha}]}
    5. POST /git/commits with {message, tree: new_tree_sha, parents: [base_sha]}
    6. PATCH /git/refs/heads/main with {sha: new_commit_sha} → 失败（parent 不一致）则从 1 重试
  ```
- 测试：单 commit 同时写 transactions.json + positions.json + signals/{date}.json，且 commit 数 == 1
- 测试：parent SHA 冲突 → 重新拉 base → 重 apply 改动 → 重试 commit（最多 3 次）
- 测试：3 次重试都失败 → 弹窗报错"网络冲突，请刷新重试"
- 测试：乐观更新 UI（点完立即变） + 静默 fetch 验证最新状态

#### 4.6 单指数详情页（仿 backtest code.md）
- 路由：`docs/quant/index/{code}.html`，13 个静态页面（每个指数一个）+ 共享 `docs/quant/index/index.js` 渲染逻辑
- 数据来源：
  - `transactions.json` 全量 fetch + 内存按指数代码 filter（MVP 阶段不分页，5000 条阈值告警）
  - `signals/index.json` 拉索引 → 按指数代码 filter 索引项 → 按需 lazy load 单个 `signals/{date}.json`（**禁止任何通配符 fetch**）
  - 抽公共 loader（`docs/quant/lib/data-loader.js`），所有页面统一通过它访问 signals
- 渲染区段：
  1. **基础信息**：指数名 / 指数代码 / ETF 代码 / ETF 名 / 类别（主题/宽基/行业）
  2. **当前状态总览**：3 bucket（D/W/M）的 actual_state、shares、avg_cost、当前市值（用最近一次 ETF 实时价 mark-to-market）、累计盈亏 %
  3. **Calmar 权重快照**：D/W/M 权重 + V9.2 best 策略 / best alpha（从 v9-summary.md 读）
  4. **完整交易日志**：分 D / W / M 三段独立表格，每段**全量展示**所有 confirmed 交易（按时间正序）
     - 列：序号 / 日期 / action / shares / price / amount / fee / PnL%（仅 SELL 记录显示，相对该 bucket 上一次 BUY）
     - **不分页 / 不限条数**
  5. **历史信号**：按日期倒序展示该指数所有历史信号（含 confirmed / skipped 全部）
     - 筛选：仅 D / 仅 W / 仅 M / 仅 confirmed / 仅 skipped 多选
- 测试：
  - 一个指数 fixture（含 50+ 交易记录）→ 渲染所有交易，不截断
  - 筛选交互：D/W/M 切换显示对应 bucket 段
  - 当前市值计算正确（shares × etf_realtime_price）
  - PnL% 计算正确（SELL 价 - 上次 BUY avg_cost）/ 上次 BUY avg_cost

#### 4.7 设置页
- PAT 输入 / 重置
- 密码 gate 重置：「清除访问授权」按钮 → 清 `localStorage.quant_auth` + 跳转到首页（再次弹密码框）
- Paper trading 开关（默认 true 前 2 周）
- 数据导出（positions / transactions JSON 下载）
- bucket 状态手动重置（应急对账）

### Phase 5：CI/CD（预估 1 天）

#### 5.1 `.github/workflows/quant-signal.yml`
- 触发：`repository_dispatch` (cron-job.org 14:48) + `workflow_dispatch` (手动)
- 步骤：checkout → setup python 3.10+ → install deps → run scripts/quant/run_signal.py
- **埋点 SLO**：脚本启动/数据拉取完成/信号生成完成/单 commit 完成/飞书发送完成 各打时间戳到日志
- 飞书重试耗尽 → workflow exit 1 → GitHub 默认发邮件给 GMAIL_USER

#### 5.2 `.github/workflows/quant-cache.yml`（合并 reconcile）
- 触发：`repository_dispatch` 09:00 + `workflow_dispatch`
- 步骤：拉昨日数据 → append 缓存 → 跑 reconcile.py → 单 commit 写多文件
- 失败时发飞书警告

#### 5.3 `.github/workflows/quant-close-confirm.yml`（**新增**）
- 触发：`repository_dispatch` 15:30（仅交易日，由 cron-job.org filter）+ `workflow_dispatch`
- 步骤：拉今日收盘价 → 跑 close_confirm.py → 单 commit 写 signals/{today}.json + index.json
- 失败时发飞书警告（不阻塞用户已完成的决策）

#### 5.4 `.github/workflows/quant-test.yml`（**新增**，PR 触发）
- 触发：PR opened/synchronize（影响 `scripts/quant/` 或 `docs/quant/` 路径时）
- **后端 pytest（分模块阈值）**：用 `.coveragerc` 配置每模块阈值，CI 跑：
  ```
  pytest scripts/quant/tests/ --cov=scripts/quant --cov-report=term-missing --cov-config=.coveragerc
  ```
  `.coveragerc` 内容（精确反映 §3.4 / §9.2 阈值）：
  ```ini
  [report]
  fail_under = 85   # 整体兜底
  precision = 1
  show_missing = true

  [paths]
  source = scripts/quant

  # 分模块阈值由 hook 脚本检查（pytest-cov 不原生支持分模块 fail_under）
  # 实际由 scripts/quant/tests/check_per_module_coverage.py 在 CI 后置步骤跑
  ```
- 后置步骤 `scripts/quant/tests/check_per_module_coverage.py` 读 `.coverage` 数据，按模块分别校验：
  - 纯逻辑层（config/state/signal_engine/trigger/affordability）：≥ 90%
  - IO 层（cache/data_fetcher/notifier/writer）：≥ 70%
  - 端到端（signal_generator/reconcile/close_confirm）：≥ 80%
  - 任一不达标 → exit 1
- **前端测试**：apt-get install chromium-browser + pip install selenium → pytest 用 selenium 驱动 headless chrome 打开 `docs/quant/tests/run.html` → 通过 JS 桥读取 `window.__TEST_RESULTS__` → 断言全部 pass。**全程不需要 npm**。
- fail-under 或前端 selenium 任一失败 → CI 红

#### 5.5 cron-job.org 配置
- 14:48 每个工作日触发 quant-signal（A 股交易日，cron-job.org filter "周一至周五"，节假日由脚本内部 trigger.py 二次过滤）
- 09:00 每个工作日触发 quant-cache（同上）
- 15:30 每个工作日触发 quant-close-confirm（同上）
- 周末由 cron-job.org filter 跳过（A 股节假日由脚本二次过滤，节假日仍会唤起 runner，脚本判断后立即退出，~5s 浪费可接受）

#### 5.6 部署到 gh-pages
- 现有 `update.yml` peaceiris/actions-gh-pages 复用
- 新增 docs/quant/ 同步部署
- 注意：每次 quant-signal/quant-cache/quant-close-confirm/前端确认操作 commit 都会触发 GitHub Pages 部署（30-90s）；前端用乐观更新 + cache-busting 解决感知延迟

### Phase 6：Paper Trading 2 周（10 个交易日，分两阶段）

**Phase 6.A：第 1 周 auto_skip 模式**（5 个工作日）
- `paper_trading.mode = auto_skip`
- 信号生成、推送、网页归档全跑，但用户**不**做手动确认
- 信号自动 skip，positions/transactions 几乎不动
- 目标：观测信号链路稳定性、推送到达率、close-confirm 假信号率

**Phase 6.B：第 2 周 manual_mock_confirm 模式**（5 个工作日）
- `paper_trading.mode = manual_mock_confirm`
- 用户走完整确认/跳过流程，transactions 标记 `paper=true`
- positions 双状态正常切换
- 目标：验证用户决策路径 + GitHub Git Data API 单 commit + UX

#### 验证项清单

| 验证项 | 通过标准 | 阶段 |
|---|---|---|
| **SLO：信号生成完成** | p95 < 14:50:00（≤ 2 分钟）| 6.A + 6.B |
| **SLO：飞书首条到达** | p95 < 14:51:00（≤ 3 分钟）| 6.A + 6.B |
| **SLO：飞书全部到达** | p95 < 14:52:00（≤ 4 分钟）| 6.A + 6.B |
| 推送到达率 | ≥ 95%（10 个工作日中至多 1 次重试耗尽，导致邮件兜底）| 6.A + 6.B |
| 缓存陈旧风险 | 09:00 morning 缓存更新后，14:48 拉数据时 cache 最新日期 == 昨日交易日 | 6.A + 6.B |
| 节假日跳过 | 期间至少 1 个法定节假日，trigger.py 正确跳过 | 6.A + 6.B |
| **close-confirm 假信号率** | provisional=true 的信号中 confirmed_by_close=false 比例 ≤ 15%（统计基线，超过则报警重新评估 14:48 vs 收盘策略）| 6.A + 6.B |
| reconcile 正确性 | 故意制造 1-2 条 pending 跨日 → 09:00 reconcile 后 status=expired，positions 不变 | 6.A |
| 信号合理性 | 用户每日记录每条信号 → 事后用 V9.2 回测代码 reproduce 比对（误差 0%）| 6.A |
| **PAT 流程** | 用户 ≥ 5 次成功在网页确认（输入价数 → 单 commit 写入成功）| 6.B |
| **单 commit 原子性** | 抓 commit 历史，每次确认操作恰好对应 1 个 commit，且 commit 涉及 ≥ 2 个文件 | 6.B |
| Paper PnL | 期末汇总（仅 6.B 第 2 周）：所有信号假设按建议价数 paper 执行，1 周 PnL vs V9.2 同期回测预期偏差 ≤ 5% | 6.B |
| 网页 UX | 用户主观评价：能在 1 分钟内完成单条信号确认；总览页易读 | 6.B |
| StateInvariantError 处理 | 故意制造一次状态不一致（如手动改 positions.json shares=0 但 actual_state=HOLD）→ workflow 报警但不中断其他 bucket | 6.A |

#### 中途异常处理预案

- 飞书消息漏发 → 重试 3 次后 workflow fail → GitHub 邮件兜底 → 用户登录网页查看
- API 拉数据失败 → 重试 2 次仍失败 → 发飞书警告 → 用户手动 workflow_dispatch
- 缓存陈旧 → 14:48 启动检测 cache 不是昨日 → 报警 + 自动尝试补拉 → 失败则跳过当日信号生成
- PAT 过期 → 网页弹窗提示
- 单 commit 重试 3 次仍冲突 → 弹窗提示用户刷新重试（罕见）

### Phase 7：切实盘（预估 0.5 天）

- 关闭 paper_trading 开关（config.yaml）
- 第一笔小金额验证：选 1 个最小 bucket（如某指数 W bucket）执行真实下单 + 网页确认
- 验证后逐步执行所有信号

---

## 十一、验收标准

### 11.1 Phase 1-5 单元 / 集成测试

- 所有 phase 测试 100% pass
- Phase 1 纯逻辑层覆盖率 ≥ 90%（pytest-cov + CI fail-under）
- Phase 2 IO 层覆盖率 ≥ 70%
- Phase 4 前端 vanilla mini test runner（无 npm）覆盖关键路径，包含：
  - 密码 gate（含正确密码通过 / 错误密码留弹窗 / localStorage 持久化 / 跨页面共享）
  - PAT 写入 / 401 检测 / 弹窗重新输入
  - 单 commit 多文件原子提交（mock GitHub Git Data API）
  - parent SHA 冲突 → 重新拉 + 重 apply + 重试（最多 3 次）
  - 单指数详情页全量交易渲染（不截断）
  - signals/index.json 索引读取 + 按需 lazy load 单日文件
- CI test workflow（`.github/workflows/quant-test.yml`）PR 触发，覆盖率不达标 fail

### 11.2 Phase 6 Paper Trading

**Phase 6.A（第 1 周 auto_skip）**：
- 5 个工作日内：
  - SLO 三档时延全部 p95 达标
  - 飞书消息送达 ≥ 95%
  - close-confirm 假信号率统计基线建立（≤ 15%）
  - 信号合理性人工核对 100% 符合 V9.2 reproduce
  - 故意制造 1 次 pending 跨日 → 09:00 reconcile expired 验证
  - 故意制造 1 次状态不一致 → StateInvariantError + bucket 隔离验证

**Phase 6.B（第 2 周 manual_mock_confirm）**：
- 5 个工作日内：
  - SLO 三档时延继续达标
  - PAT 流程：≥ 5 次成功在网页确认（输入价数 → 单 commit 写入成功）
  - 单 commit 原子性：commit 历史每次确认对应 1 个 commit、≥ 2 个文件
  - 至少 1 次完整 PAT 重新生成 + 重新输入流程
  - 至少 1 次故意跳过 / 1 次故意 external_funded 测试
  - Paper PnL vs V9.2 同期回测偏差 ≤ 5%

### 11.3 Phase 7 实盘第一笔

- 第一笔成交后 3 工作日内 actual_state 与券商 App 实际持仓 100% 一致
- 第一周内出现 1 次卖出后 actual_state 正确切回 CASH

---

## 十二、风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 14:48 实时价 ≠ 收盘价偏差导致假信号 | 中 | 中 | 半自动模式人工过滤；paper trading 期间统计偏差比例 |
| ETF 跟踪误差累积 | 低 | 低 | 长期 < 1%/年，远小于策略 CAGR |
| GitHub Pages 部署延迟（30-90s）| 高 | 低 | 前端乐观更新 + cache-busting fetch raw 文件 |
| GitHub raw URL CDN 缓存 5 分钟 | 高 | 中 | 所有 fetch 加 `?t=${Date.now()}` |
| PAT 泄露（被偷或代码意外提交）| 低 | 中 | fine-grained 单仓库 90 天过期；代码 .gitignore 排除任何 .env |
| cron-job.org 失效 | 低 | 中 | workflow_dispatch 手动按钮 + 用户每日确认收到飞书消息 |
| GitHub Actions runner 排队 | 极低 | 低 | trend.github.io 项目使用率低，免费额度充足 |
| AkShare 实时接口 rate limit | 中 | 中 | 14:48 仅 2 次 API 调用（13 指数 + 13 ETF 各一次全量）+ 重试 2 次 |
| 集合竞价 / 临停 / 涨跌停 | 高 | 低 | 用户跳过即可，skip_reason 记录用于事后分析 |
| 跳过 BUY 后永久错过该周期 | 高 | 中 | 这是 V9.2 严格语义的代价；paper trading 期间允许故意跳过观察 |
| 同 ETF 多 bucket 持仓共享账户混淆 | 中 | 中 | 网页持仓汇总卡片显示「ETF 实际 = D + W + M 之和」+ 用户每月对账提示 |
| 网页 PAT 鉴权过期未及时提示 | 低 | 低 | 401 检测 + 弹窗 + settings 页显示「PAT 90 天有效，剩余 X 天」 |
| 入口密码被技术人员绕过（MD5 在前端可见）| 中 | 低 | 接受。本来就是弱保护，目的仅是防偶然访问 / 搜索引擎索引；真正写状态仍要 PAT 二级守门 |
| 入口密码 MD5 常量泄露到搜索引擎 | 低 | 低 | `eaf4f812fc1a6abc3e9b8182171ffc21` 是常见单词 hash，撞库风险存在但攻击者也只能"进页面看数据"，无写入能力；季度轮换密码 |
| **单 commit 多文件 parent SHA 冲突** | 中 | 低 | 自动重试 3 次 + 超过则弹窗用户刷新重试；workflow 与前端基本错峰（14:48 vs 用户操作时间），冲突概率低 |
| **GitHub Git Data API 流程错误** | 低 | 高 | Phase 4.5 必须 mock + 实跑双重测试覆盖所有分支；写入失败前先校验 base_sha 是否最新 |
| **flutter SLO 不达标（Github Actions runner 排队）** | 低 | 中 | trend.github.io 项目使用率低，免费额度充足；Phase 6 paper trading 期间监测 p95 |
| **close-confirm 假信号率超过 15%** | 中 | 中 | 触发 plan 重新评估：可能要把触发时间从 14:48 改为 14:55 或 14:58，但权衡用户决策窗口 |
| **transactions.json 增长超 5000 条** | 远期 | 中 | 触发分片重构告警；按 `transactions/{year-month}.json` 切分，详情页改 lazy load |
| **PAT 仅 Contents Read/Write、禁 Workflows 权限不被严格执行** | 低 | 中 | settings 页提供 PAT 配置指引（截图 + 必勾/禁勾清单）+ 用户自检确认 + 有效性试探（GitHub fine-grained PAT API 不暴露已授权范围，无法自动校验权限） |

---

## 十三、未来扩展（不在本期）

| 项 | 触发条件 |
|---|---|
| 全自动下单（QMT/EasyTrader）| Paper trading + 实盘运行 ≥ 3 个月稳定，且用户金融资产升至 50 万开通 QMT |
| 第二证券账户多账户分配 | 单账户运行稳定后，按指数分组拆分 |
| 总市值收益曲线图 | 实盘 ≥ 30 天数据后展示 |
| 漂移自动对账 | 找到券商持仓导出 API 后实现 |
| 多通道推送（飞书 + 邮件兜底）| 飞书故障率 > 5% 后增补 |
| 移动端 App | 网页体验 ≥ 6 个月评估后 |
| 其他策略并跑（V6 行业策略）| 等行业指数 ETF 成熟后 |

---

## 十四、参考与依赖

- 上游回测：`docs/agents/backtest/v9-summary.md`
- 上游代码：`scripts/backtest/`（cache.py / data_loader.py 可参考）
- 上游主链路：`scripts/main.py`、`scripts/data_fetcher.py`（不修改，仅参考请求伪装等模式）
- 触发服务：cron-job.org（已用于 morning 模式）
- 数据源：AkShare（cs_index / sina_index / fund_etf_spot_em）
- 飞书自建机器人：用户自行创建，webhook 写入 GitHub Secret `FEISHU_WEBHOOK_URL`
- GitHub Pages：trend.github.io 现有配置

---

## 附录 A：13 指数与 ETF 映射（基线快照已封版，来源 `docs/agents/backtest/v9-summary.md` 排名表）

| 序号 | 指数代码 | 指数名 | 数据源 | ETF 代码 | ETF 名 | D 权重 | W 权重 | M 权重 |
|---|---|---|---|---|---|---|---|---|
| 1 | 931151 | 光伏产业 | cs_index | 515790 | 光伏 ETF | 61.5% | 25.2% | 13.3% |
| 2 | 000819 | 有色金属 | cs_index | 512400 | 有色金属 ETF | 53.1% | 9.7% | 37.2% |
| 3 | 399997 | 中证白酒 | cs_index | 161725 | 招商中证白酒 ETF | 72.7% | 6.1% | 21.2% |
| 4 | 399989 | 中证医疗 | cs_index | 512170 | 易方达中证医疗 ETF | 75.6% | ❌ | 24.4% |
| 5 | 931079 | 5G 通信 | cs_index | 515050 | 5G 通信 ETF | 61.1% | 11.7% | 27.2% |
| 6 | 399808 | 中证新能 | cs_index | 516160 | 国泰中证新能源 ETF | 31.8% | 46.2% | 22.0% |
| 7 | 931071 | 人工智能 | cs_index | 515980 | AI ETF | 63.4% | 20.3% | 16.3% |
| 8 | 930721 | CS 智汽车 | cs_index | 516520 | 智能汽车 ETF | 80.0% | ❌ | 20.0% |
| 9 | 399967 | 中证军工 | cs_index | 512660 | 军工 ETF | 64.8% | ❌ | 35.2% |
| 10 | 399673 | 创业板 50 | sina_index | 159949 | 华安创业板 50 ETF | 21.6% | 23.7% | 54.7% |
| 11 | 000688 | 科创 50 | cs_index | 588000 | 科创 50 ETF | 62.8% | 16.9% | 20.3% |
| 12 | 000813 | 细分化工 | cs_index | 159870 | 化工 ETF | 74.0% | 9.5% | 16.4% |
| 13 | 399976 | CS 新能车 | cs_index | 515030 | 新能源车 ETF | 34.4% | 36.6% | 29.1% |

**有效 bucket 数**：13×3 - 3 = **36**（中证医疗 W、CS 智汽车 W、中证军工 W 不创建，按 V4.1 Calmar 算法 CAGR ≤ 0 剔除）

**待用户确认**：3 个 ETF 代码（中证医疗 / 中证新能 / 创业板 50）的具体选型 — Phase 0 完成。

---

## 附录 B：开发与执行节奏估算

| Phase | 内容 | 预估时长 | 累计 |
|---|---|---|---|
| 0 | 脚手架 | 0.5 天 | 0.5 天 |
| 1 | 纯逻辑层 TDD | 2-3 天 | 3 天 |
| 2 | IO 层 | 2 天 | 5 天 |
| 3 | 信号生成端到端 | 1-2 天 | 7 天 |
| 4 | 网页前端 | 3-4 天 | 11 天 |
| 5 | CI/CD | 1 天 | 12 天 |
| 6 | Paper trading（5 + 5）| 10 个工作日 | ≈ 2 周 |
| 7 | 切实盘第一笔 | 0.5 天 | ≈ 2 周 + 0.5 天 |

**关键路径**：Phase 6 paper trading 是单边阻塞——必须等够时间观察。建议 Phase 0-5 完成后立即上线 paper trading，开发人不停下，可同步规划全自动方案（不在 MVP）。

---

## 变更日志

### v1.1（2026-04-25 当日二修）
- 新增 §3.6 / §5.0 / §6.10：入口密码 gate（密码 `weiaini`，MD5 `eaf4f812fc1a6abc3e9b8182171ffc21`，硬编码前端，localStorage 永久），与 GitHub PAT 鉴权独立
- 重写 §5.2.1 / §10 Phase 4.6：单指数详情页**不限条数**，分 D/W/M 三段全量展示历史交易，参照 `docs/agents/backtest/{code}.md` 风格
- 新增 §6.11：单指数详情页不限条数的设计决策与可行性论证
- 拆分 §10 Phase 4：4.1（页面框架）/ 4.2（密码 gate，新增）/ 4.3（数据加载）/ 4.4（PAT）/ 4.5（确认弹窗）/ 4.6（单指数详情）/ 4.7（设置）
- §9.1 模块图补「前端访问流程」（密码 gate + PAT 双层）
- §10 Phase 0 新增任务：引入 js-md5 库 / 用户生成 PAT / 补齐 3 个待确认 ETF
- §11.1 验收补密码 gate 自动化测试
- §12 风险表补 2 项：密码绕过 / MD5 撞库

### v1.0（2026-04-25 初稿）
- PRD + TDD 实施计划首版
- 涵盖：13 指数 V9.2 信号、半自动模式、飞书推送、网页归档、PAT 鉴权、买卖严格配对、paper trading 2 周

### v1.5（2026-04-25 六修，用户调整范围：本期 MVP 只做"本地走通"，外部依赖全 mock）

**核心范围调整**：
- 新增 §3.5.1「本地走通目标」：明确所有外部依赖（飞书 webhook / GitHub Git Data API / AkShare / cron 触发 / PAT / paper trading）的 mock 边界与本地等价方案
- §10 Phase 0 重写：删除 5 个上线前才需要的人工动作（飞书机器人 / 飞书联调 / cron-job / Secret 配置 / PAT 申请），全部移到 §10 Phase 7「上线前清单」
- 附录 A 封版：13 指数 + 13 ETF 全部填实（来源 `v9-summary.md` 排名表用户已补齐）；标题去掉 Pre-Phase0 标注
- 修正：PAT 是网页运行时输入，不需要 Phase 0 commit 任何 secret（之前误把它列成 Phase 0 阻塞门）

**新增 mock 模式设计**：
- `writer.py`：本地走通模式（写文件 + git commit）vs 上线模式（GitHub Git Data API），通过 `--local-mode` / 环境变量切换
- `notifier.py`：dry-run 模式（写 `data/quant/notify-outbox/{ts}.json`）vs 真发模式
- `run_signal.py`：`--mock-now=<iso8601>` 模拟 cron 触发；`--replay-window=<start>..<end>` 重放历史交易日

**TDD 重新聚焦**：每个模块测试 + 端到端 mock dry-run 跑通整个流程（trigger → fetch → engine → writer → notifier → reconcile → close-confirm），逻辑链路 + 流程贯通。**不需要等真实交易日**。

### v1.4（2026-04-25 五修，回应 Codex Round 3 评审 6 条文档一致性小问题，状态从 NEEDS_REVISION 升 MOSTLY_GOOD）

- §6.18：重写 Paper trading 决策段，与 6.A/6.B 双阶段 + §10/§11.2 验收对齐（Round 3 Issue 1）
- §9.3 时序图：15:30 close-confirm 加写 `positions.json`（policy_state 回正）+ 同步遍历无信号 bucket（Round 3 Issue 2）
- §12 风险表：PAT 校验从「自动校验」改为「配置指引 + 用户自检 + 有效性试探」，与 §10.4.4 对齐（Round 3 Issue 3）
- §10 Phase 1 测试：`assert 抛错` → `抛 StateInvariantError`，与 §8.2/§8.4 对齐（Round 3 Issue 4）
- 附录 A：标题改为「Pre-Phase0 Snapshot（待 Phase 0 阻塞门补齐后封版）」+ 候选 ETF 标记斜体「_Phase 0 待选_」+ 加封版规则说明（Round 3 Issue 5）
- §8.6 假信号率分母改为「当日参与 close-confirm 的信号数 N」，消除歧义（Round 3 Issue 6）
- 文档头版本 v1.3 → v1.4

### v1.3（2026-04-25 四修，回应 Codex Round 2 评审 12 条 issue）

**采纳的 Critical 修订**：
- §8.6 close-confirm 必须**回正 policy_state**（用收盘价覆盖 14:48 provisional 的 policy_state）+ 同步遍历无信号 bucket 也回正 + 单 commit 多文件（解决 Round 2 Issue 1：次日 yesterday_policy 漂移）
- §3.7.1 新增「同日幂等合并规则」：重跑禁止覆盖已确认的 status / actual_* 字段（解决 Round 2 Issue 2：重跑覆盖用户状态）

**采纳的 High 修订**：
- 全文搜索替换 `Contents API` → `Git Data API`；§3.7 加 writer 抽象硬约束「禁止任何代码绕过 writer 直接调 Contents API」（Issue 3）
- §10.2.3 notifier 测试改为「3 次指数退避 → 抛 NotifierUnrecoverableError → workflow exit 1」与决策层（§6.16）一致（Issue 4）
- §10.4.6 单指数详情页数据源改为「signals/index.json + lazy load 单日文件」+ 抽公共 `data-loader.js`（Issue 5）
- §10.5.4 覆盖率门禁拆分模块阈值（用 `.coveragerc` + `check_per_module_coverage.py` 后置脚本），与 §3.4 / §9.2 文档目标对齐（Issue 6）
- 前端 CI 测试方案明确：apt 装 chromium + pip 装 selenium-webdriver + pytest 驱动 headless chrome 跑 `docs/quant/tests/run.html`，**全程不引 npm/Node**（Issue 7）

**采纳的 Medium 修订**：
- §8.5 reconcile 伪代码：循环外**一次** commit 所有变更文件，避免 N 次 commit 中间态（Issue 8）
- Phase 0 ETF 阻塞门：3 个待补 ETF 必须补齐才能进 Phase 1，附 ETF 候选清单（Issue 9）
- Phase 6 周期统一为 **10 个工作日**（5 + 5），所有验收阈值 / 14 天引用 → 10 天（Issue 10）
- §10.4.4 PAT 校验改为「试探有效性 + 用户自行确认指引」，移除"自动校验权限范围"伪安全承诺（Issue 11）

**采纳的 Low 修订**：
- 文档头版本 v1.0 → v1.3，加最后修订日期（Issue 12）

**新增章节**：
- §3.7.1 同日幂等合并规则（重跑保护）
- §10 Phase 0 ETF 阻塞门 + 候选清单

### v1.2（2026-04-25 三修，回应 Codex Round 1 评审 14 条 issue）

**采纳的 Critical / High 修订**：
- §3.7 + §6.12 + §10 Phase 4.5：写路径全部改为 **GitHub Git Data API 单 commit 多文件原子提交** + parent SHA 乐观锁（解决 Issue 1 多写者并发）
- §6.13 + §7.2 + §8.5 + §10 Phase 5.2 + 09:00 流程：信号 status 增加 `expired`，09:00 reconcile 把昨日 pending → expired（解决 Issue 2 信号悬空）
- §3.8 + §6.14 + §7.2 + §8.6 + §10 Phase 5.3：信号增加 `provisional / confirmed_by_close` 字段，新增 15:30 close-confirm workflow（解决 Issue 3 实时价偏差）
- §6.15 + §7.6 + §9.3 + §11.2：明确三档 SLO（信号写完 p95 < 14:50 / 飞书首条 < 14:51 / 飞书全部 < 14:52）（解决 Issue 4）
- §6.16 + §10 Phase 5.1：通知失败硬失败（3 次指数退避重试 → workflow exit 1 → GitHub 邮件兜底）（解决 Issue 5）
- §7.4 + §10 Phase 4.3：新增 `signals/index.json` 索引文件，前端按索引 lazy load（解决 Issue 6 通配符 fetch 不可行）
- §6.17 + §10 Phase 0：基线快照锁定 13 指数 + 标注 v9-summary 笔误（解决 Issue 9）
- §10 Phase 0：测试基建（pytest-cov + CI fail-under + Python 版本锁 + 前端 vanilla mini test runner 不引入 npm）（解决 Issue 10）
- §6.18 + §10 Phase 6 + §11.2：paper trading 拆 6.A auto_skip + 6.B manual_mock_confirm 两阶段（解决 Issue 11）
- §10 Phase 0：飞书卡片跳转联调验收项（解决 Issue 12）
- §8.2 + §8.4：assert → `StateInvariantError` 显式异常 + bucket 级 try/except 隔离（解决 Issue 13）

**部分采纳**：
- Issue 7 不分页：保留 MVP 不分页（用户明确要求 + YAGNI），但加 5000 条阈值告警 → 触发分片重构
- Issue 8 PAT 风险：明确 PAT 权限清单（仅 Contents Read/Write，禁 Workflows / Actions / Administration）+ settings 页校验。**拒绝**改 sessionStorage（用户已明确选 B + 私人工具场景接受）
- Issue 14 密码明文：保留文档示例（PRD 必须可读），加季度轮换说明

**新增/修改的章节**：
- 新增：§3.7 单写者原子提交 / §3.8 信号双阶段
- 新增：§6.12-§6.18（共 7 个新决策段）
- 新增：§7.4 signals/index.json schema
- 新增：§8.2 StateInvariantError 代码框架 / §8.5 reconcile / §8.6 close-confirm
- 新增：`writer.py` / `reconcile.py` / `close_confirm.py` 三个新模块
- 新增：`.github/workflows/quant-close-confirm.yml` / `.github/workflows/quant-test.yml`
- 修改：positions/signals/transactions/config schema 全部更新

### v1.1（2026-04-25 二修）
- 新增 §3.6 / §5.0 / §6.10：入口密码 gate
- 重写 §5.2.1 / §10 Phase 4.6：单指数详情页不限条数
- 拆分 §10 Phase 4：4.1-4.7
- 新增 §6.11：单指数详情页不限条数的设计决策
- §11.1 验收补密码 gate 自动化测试
- §12 风险表补 2 项

---

> **本文档为 review-ready 版本。等待 review agent 反馈后修订。**
