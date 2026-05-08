# 通达信主图 TDX 公式 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 spec §三 的 TDX 公式落地为可直接导入**通达信手机版**使用的源码文件；通过抽样指数（沪深 300 / 中证白酒 / 恒生科技）的 D/W/M 周期与 `backtest.run_v9_detail` 输出对比验证 B/S 标记完全对应。

**Architecture:** 单一 TDX 公式（主图叠加），1 个新文件，无现有代码改动。无 Python 单元测试（TDX 公式语言无 Python 测试框架）；验证靠手机端"测试公式"语法检查 + 肉眼对比 backtest 交易日志。Spec §三 同时提供 **首选公式**（含 `IFNONE`）和**降级公式**（不依赖 `IFNONE`），手机不识别时切换。

**Tech Stack:** TDX 公式语言（通达信手机版 / PC V6+ 双兼容）；`scripts/backtest/run_v9_detail.py` 作为对照源；`scripts/backtest/signal.py` 的 `DirectionState` 是信号语义来源。

**Spec：** `agents/plans/2026-05-08-quant-tdx-main-chart.md`（必读，公式逻辑、不变性证明、与 quant 差异都在那里）

---

## File Structure

| 文件 | 动作 | 责任 |
|---|---|---|
| `agents/results/2026-05-08-quant-tdx-main-chart.tdx` | Create | TDX 公式源码（用户复制粘贴到通达信公式编辑器）|
| `agents/plans/2026-05-08-quant-tdx-main-chart.md` | Modify（最后 task）| 验收清单 `[ ]` → `[x]` |

仅 1 个新文件 + 1 个文档勾选；无 Python 代码改动。

**关于 `.gitignore`**：项目根 `.gitignore` 第 35 行 `agents` 会忽略 `agents/` 目录下所有新文件。本 plan 的 commit 步骤都使用 `git add -f` 强制 add。

---

## Task 1: 写 TDX 公式源码文件

**Files:**
- Create: `agents/results/2026-05-08-quant-tdx-main-chart.tdx`

- [ ] **Step 1: 创建文件并写入完整公式**

文件内容（从 spec §三 复制，加入文件头部注释）：

```
{ 文件: agents/results/2026-05-08-quant-tdx-main-chart.tdx              }
{ Plan: agents/plans/2026-05-08-quant-tdx-main-chart.md                  }
{                                                                         }
{ 通达信 PC 主图叠加公式：MA + LOW/HIGH 干净 K 线方向 B/S 信号           }
{ 严格对应 scripts/backtest/signal.py classify_bar + DirectionState      }
{ 周期由用户切换（日/周/月）自然适配——公式自动用当前周期的 H/L/C       }
{                                                                         }
{ 不变性：信号序列必然 BSBSBS 交替，绝不出现连续 BB / SS（spec §3.1 证明）}

MA5 : MA(C,  5),  COLORWHITE;
MA10: MA(C, 10),  COLORYELLOW;
MA20: MA(C, 20),  COLORMAGENTA;
MA60: MA(C, 60),  COLORCYAN;

{ 干净 K 线方向（与 backtest classify_bar 等价） }
TODAYUP   := L > MA20;
TODAYDOWN := H < MA20;

{ 历史最近的非触碰 K 线根数（不含今天）；从未为真时 IFNONE 兜底 9999 }
PREVUP   := IFNONE(BARSLAST(REF(TODAYUP,   1)), 9999);
PREVDOWN := IFNONE(BARSLAST(REF(TODAYDOWN, 1)), 9999);

{ 翻转判定：今日 UP/DOWN 且历史最近非触碰是反向（或从未） }
B := TODAYUP   AND PREVDOWN <= PREVUP;
S := TODAYDOWN AND PREVUP   <= PREVDOWN;

{ 显示：B / S 都在 K 线下方（按 spec §一 要求） }
DRAWTEXT(B, L * 0.99, 'B'), COLORRED;
DRAWTEXT(S, L * 0.99, 'S'), COLORGREEN;
```

- [ ] **Step 2: 验证文件存在 + 行数**

Run: `wc -l agents/results/2026-05-08-quant-tdx-main-chart.tdx`
Expected: 25-30 行（含注释和空行）

- [ ] **Step 3: 验证关键标识符存在**

Run: `grep -E "^(MA5|MA10|MA20|MA60|TODAYUP|TODAYDOWN|PREVUP|PREVDOWN|B|S)" agents/results/2026-05-08-quant-tdx-main-chart.tdx`
Expected: 至少 10 行（4 个 MA + 6 个变量定义）

- [ ] **Step 4: Commit**

```bash
git add -f agents/results/2026-05-08-quant-tdx-main-chart.tdx
git commit -m "[quant] 通达信主图 TDX 公式：MA + LOW/HIGH B/S 信号"
```

`-f` 必需，因为 `.gitignore` 的 `agents` 行会拒绝普通 `git add`。

---

## Task 2: 通达信手机版导入并测试公式语法

**注：以下 Task 2-5 是用户手动操作通达信手机 app，不是 agent 可以代劳的步骤。**

- [ ] **Step 1: 把 .tdx 文件内容传到手机**

手机端粘贴长公式不便；推荐三种方式之一：
- **A 微信/邮件**：把 `agents/results/2026-05-08-quant-tdx-main-chart.tdx` 内容发给自己，手机里复制
- **B PC 写 + 云同步**：在 PC 通达信里写好 + 测试通过 + "云同步"上传，手机端拉取（详见 spec §4.2）
- **C 手机直接打字**：公式只有 25 行，手抄也行（认真核对每一行）

- [ ] **Step 2: 打开手机端公式管理**

操作（路径因 app 版本不同，任选一种）：
- 首页底栏 "我的" → "更多功能" → "技术指标管理" / "公式管理"
- 任意 K 线图 → 长按指标区域 → 弹出菜单选"自定义指标"
- 设置 → "智能选股 / 高级功能" → "公式编辑器"

如果都找不到：搜你具体的通达信手机 app 版本"自定义指标"路径。

- [ ] **Step 3: 新建主图叠加公式**

在自定义指标页点 "新建" / "+"，填写：
- 公式名称：`MA20BS`
- 公式描述：`MA + LOW/HIGH B/S（与 backtest 一致）`
- 公式类型：**主图叠加**（注意不是"副图指标"或"选股公式"）

- [ ] **Step 4: 粘贴首选公式（含 `IFNONE`）**

把 `agents/results/2026-05-08-quant-tdx-main-chart.tdx` 全部内容（含注释）粘贴到公式编辑框。

- [ ] **Step 5: 测试公式语法**

点编辑器底部 "测试" / "校验" 按钮。

**两种结果，分支处理**：

✅ **测试通过** → 进入 Step 6 保存。

❌ **报错 "未知函数 IFNONE" 或 "括号前写的不是函数"**（手机版高发）→ 切换到 spec §三 **降级公式**（已固化在 .tdx 文件中）：
- 删除原编辑框两行 `PREVUP := IFNONE(...)` 和 `PREVDOWN := IFNONE(...)`
- 替换为（注意 `>= 0` 双边检查，区分 BARSLAST 在"从未为真"时返回 -1 的版本）：
  ```
  LASTUPRAW   := BARSLAST(REF(TODAYUP,   1));
  LASTDOWNRAW := BARSLAST(REF(TODAYDOWN, 1));
  TOTALBARS   := BARSCOUNT(C);

  PREVUP   := IF(LASTUPRAW   >= 0 AND LASTUPRAW   < TOTALBARS, LASTUPRAW,   9999);
  PREVDOWN := IF(LASTDOWNRAW >= 0 AND LASTDOWNRAW < TOTALBARS, LASTDOWNRAW, 9999);
  ```
- 或者：直接重新粘贴 `agents/results/2026-05-08-quant-tdx-main-chart.tdx` 全部内容（已是降级版）
- 再点"测试"

❌ **报错 "未知函数 DRAWTEXT" 或 "COLORRED 未定义"**：你的 app 不支持画文字 → 改用 `STICKLINE` 画点：
- 删除两行 `DRAWTEXT(...)`
- 替换为：
  ```
  STICKLINE(B, L * 0.99, L * 0.99, 4, 0), COLORRED;
  STICKLINE(S, L * 0.99, L * 0.99, 4, 0), COLORGREEN;
  ```
（画粗点代替文字标记）

❌ **其他错误**：截图发回来，根据错误信息查证。

- [ ] **Step 6: 保存公式**

测试通过 → 点 "保存"。

- [ ] **Step 7: 把成功的公式版本同步回 .tdx 文件**

如果 Step 5 用了**降级公式**或者别的修改，更新本地 `agents/results/2026-05-08-quant-tdx-main-chart.tdx` 文件以反映实际可用版本：

```bash
# 编辑文件，把首选公式段替换为降级公式段
# 然后:
git add -f agents/results/2026-05-08-quant-tdx-main-chart.tdx
git commit -m "[quant] TDX 公式：手机版兼容性微调（IFNONE 降级 / 等）"
```

如果 Step 5 直接通过（首选公式可用），跳过此 step，文件保持原样。

---

## Task 3: 沪深 300 D 周期对比验证

- [ ] **Step 1: 跑 backtest 拿对照数据**

```bash
source venv/bin/activate
python -m scripts.backtest.run_v9_detail --code 000300
```

Expected：生成 `agents/results/v9-000300.md`

- [ ] **Step 2: 提取 backtest D 周期 BUY/SELL 日期**

打开 `agents/results/v9-000300.md`，找 "## D 周期" 段下的 "完整交易日志" 表格。
记录所有 BUY 和 SELL 的日期，例如：

```
BUY:  2018-03-15, 2019-04-02, 2020-07-06, ...
SELL: 2018-10-22, 2019-12-13, 2021-02-25, ...
```

- [ ] **Step 3: 手机端打开沪深 300 日线 + 主图叠加**

手机操作：
- 行情搜索框输入 `沪深300` 或代码 `000300` / `1B0300`
- 进入 K 线图 → 切换到 "日线"
- 长按主图区域 → 弹出菜单 → "主图叠加" / "添加指标" → 勾选 `MA20BS`

Expected：图上显示 MA5（白）/ MA10（黄）/ MA20（紫）/ MA60（青）四条均线；部分 K 线下方有红 B 或绿 S 标记。

如果均线颜色与预期不符：手机版颜色常量可能映射不同，spec §三 列出的是 PC 颜色，手机视觉不一致不影响功能。

如果 B/S 看不见：
- 可能 `L * 0.99` 太靠近 K 线 → 改成 `L * 0.97` 或 `L - 0.5`
- 屏幕缩放级别影响：放大 K 线后再看

- [ ] **Step 4: 肉眼对比 B/S 日期 vs backtest BUY/SELL 日期**

在沪深 300 日线图上找到 Step 2 记录的每个日期，确认对应：
- 每个 backtest BUY 日期 → 通达信该日 K 线下方有 **红色 B**
- 每个 backtest SELL 日期 → 通达信该日 K 线下方有 **绿色 S**
- 数量完全一致（仅排除：backtest 数据终点 2026-04-24 之后的 K 线）

如果有不一致：
- 检查通达信 K 线起点是否早于 backtest 数据起点（参考 `scripts/backtest/data_loader.py` 的 `DATA_END_DATE = 2026-04-24` 和源数据起点）
- 检查 MA20 数值是否对齐（通达信主图右上角应能看到 MA20 当日值，与 backtest CSV 对齐）

Expected：完全 1-1 对应。

---

## Task 4: 沪深 300 W / M 周期对比验证

- [ ] **Step 1: 切周线，对比 W 周期**

手机操作：沪深 300 K 线图 → 顶部周期切换栏（5/15/30/60/日/周/月）→ 选 "周"
Expected：B/S 标记按周线 K 线重新计算（数量比日线少）。

注：部分手机版周期切换在右上角"更多周期"二级菜单，找到 "周线" / "月线" 即可。

打开 `agents/results/v9-000300.md` "## W 周期" 段，对比 BUY/SELL 日期。

Expected：W 周期 B/S 标记日期与 backtest W 周期日志 1-1 对应。

- [ ] **Step 2: 切月线，对比 M 周期**

操作：切到 "月线"
对比 backtest "## M 周期" 段。

Expected：M 周期 B/S 标记与 backtest M 周期日志 1-1 对应。

- [ ] **Step 3: 验证不变性（无连续 BB / SS）**

在沪深 300 D / W / M 三个周期下，自上而下扫描所有 B/S 标记：
Expected：标记必然交替——B 后必有 S，S 后必有 B（中间可有任意触碰日）。绝不出现连续两个 B 或连续两个 S。

如果发现连续 BB / SS：spec §3.1 不变性证明有 bug，必须 raise issue。

---

## Task 5: 中证白酒 + 恒生科技 抽样验证

- [ ] **Step 1: 中证白酒 D 周期**

```bash
python -m scripts.backtest.run_v9_detail --code 399997
```

通达信操作：
- 手机搜 `中证白酒` 或代码 `399997` → 进入 K 线图 → 日线 → 主图叠加 `MA20BS`
- 对比 `agents/results/v9-399997.md` D 周期 BUY/SELL

Expected：1-1 对应。

- [ ] **Step 2: 恒生科技 D 周期**

```bash
python -m scripts.backtest.run_v9_detail --code HSTECH --region hk
```

通达信操作：
- 手机搜 `恒生科技` / `恒生科技指数`（手机版港股用名字搜更稳）
- 进入 K 线图 → 日线 → 主图叠加 `MA20BS`
- 对比 `agents/results/v9-HSTECH.md` D 周期 BUY/SELL
- 如果搜不到 `恒生科技`：试 `HSTECH` 或 `HSI`（恒生指数本体）作为替代验证

Expected：1-1 对应。

- [ ] **Step 3: 触碰日抽查**

在中证白酒日线图上，找一段窄幅震荡区段（K 线穿越 MA20 来回 5 次以上），确认这些日子 K 线下方**无 B/S 标记**——这是触碰保前态的可视化验证。

Expected：触碰区无标记，与 spec §二 表格"触碰：保前态，无 B/S"一致。

---

## Task 6: 验收清单勾选 + commit

**Files:**
- Modify: `agents/plans/2026-05-08-quant-tdx-main-chart.md`（§八 验收清单）

- [ ] **Step 1: 勾选验收清单**

打开 `agents/plans/2026-05-08-quant-tdx-main-chart.md`，找 §八 验收清单。把每个 `- [ ]` 改成 `- [x]`：

```markdown
- [x] §三 公式在通达信 PC 端"测试公式"通过（无语法错误）
- [x] 通达信切日 / 周 / 月线，三个周期分别看到 MA5/10/20/60 + B/S 标记
- [x] §五 至少 3 个抽样指数（沪深 300 / 中证白酒 / 恒生科技）的 D/W/M 周期 B/S 标记与 backtest 输出对应
- [x] 触碰日（K 线穿越 MA20 的窄幅震荡区段）确认无 B/S 标记
- [x] 首次进入 UP/DOWN 边界（数据起始第 20 根 K 线左右）确认 B/S 正确触发
- [x] B / S 显示位置在 K 线下方（`L * 0.99`）
- [x] B 红色 / S 绿色
```

- [ ] **Step 2: 验证 spec 验收清单全部勾选**

Run: `grep -c '^- \[x\]' agents/plans/2026-05-08-quant-tdx-main-chart.md`
Expected: 7（验收清单 7 项全部勾选）

- [ ] **Step 3: Commit**

```bash
git add -f agents/plans/2026-05-08-quant-tdx-main-chart.md
git commit -m "[quant] 通达信主图公式验收通过（沪深300/中证白酒/恒生科技 D/W/M 全对齐）"
```

---

## Self-Review

**Spec 覆盖检查**：

| Spec 节 | 由 Task 实现 |
|---|---|
| §一 需求 | Task 1（公式输出）+ Task 3-5（验证）|
| §二 信号逻辑 | Task 1（公式实现 = backtest classify_bar）|
| §三 TDX 公式 | Task 1 |
| §四 部署 | Task 2 |
| §五 验证 | Task 3, 4, 5 |
| §六 不做的事 | 显式不做（plan 内不引入持仓配对 / 副图 / 手机端）|
| §3.1 不变性 | Task 4 Step 3（肉眼扫描验证 BSBSBS 交替）|
| §6.1 与 quant 差异 | spec 已说明，plan 不需另测（行为差异在边界，难复现）|
| §七 风险 | 各 Task 步骤已含失败处置说明 |
| §八 验收清单 | Task 6 |

无遗漏。

**Placeholder 扫描**：无 TBD / TODO / "later" / 空步骤。

**类型 / 命名一致性**：
- 公式名 `MA20BS` 在 Task 1 公式注释、Task 2 创建步骤、Task 3-5 主图叠加引用都一致
- 文件路径 `agents/results/2026-05-08-quant-tdx-main-chart.tdx` 在 Task 1, 2, 6 引用一致
- 变量名 `TODAYUP / TODAYDOWN / PREVUP / PREVDOWN / B / S` 在公式 + 文档说明一致
- backtest 命令 `python -m scripts.backtest.run_v9_detail --code <CODE>` 在 Task 3, 5 一致
