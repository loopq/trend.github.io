# 通达信主图：MA + LOW/HIGH 干净 K 线 B/S 信号

- **Plan ID**：2026-05-08-quant-tdx-main-chart
- **状态**：待实施
- **范围**：1 个 TDX 公式源码（内嵌于本文档），部署到**通达信手机版**主图叠加（PC 版可作为兼容验证环境）
- **信号语义**：严格对应 `scripts/backtest/signal.py` 的 `classify_bar` + `DirectionState`（不含 `decide_action` 持仓配对）；与 `scripts/quant/signal_engine.py` 的 `derive_policy_state` 翻转事件等价（见 §六 边界）

---

## 一、需求

通达信手机版主图叠加公式，每周期独立显示：

- MA 5 / 10 / 20 / 60 四条均线
- **B**（黄色字，K 线**上方** `H * 1.01`）：方向翻转 DOWN → UP（含历史首次进入 UP）
- **S**（绿色字，K 线**下方** `L * 0.99`）：方向翻转 UP → DOWN（含历史首次进入 DOWN）
- 触碰日（`low ≤ MA20 ≤ high`）：保前态，**无 B/S 标记**

**颜色 / 位置选择理由**：
- B 不用红色——与阳线红 K 视觉融合；黄色与 MA10 同名但单字符 vs 连续线可区分
- B 放上方——突破事件直观；下方常被 MA60 线 / 震荡 K 线挤占
- S 保持下方绿色——破位事件下方提示符合直觉；实测在创业板 50 等指数上清晰可见

周期切换由通达信原生支持——日/周/月线分别用对应周期的 K 线计算 MA20 和 H/L。**不需要在公式里写多周期判断**。

---

## 二、信号逻辑（与 backtest 严格对应）

来源：`scripts/backtest/signal.py`

```python
def classify_bar(high, low, ma20):
    if ma20 is None: return None
    if low > ma20: return UP
    if high < ma20: return DOWN
    return None  # 触碰

class DirectionState:
    state: None | UP | DOWN
    def update(high, low, ma20):
        new_dir = classify_bar(high, low, ma20)
        if new_dir is None: return None, False  # 触碰，state 不变
        if new_dir == self.state: return new_dir, False  # 同向
        self.state = new_dir
        return new_dir, True  # 翻转（含 None→UP/DOWN 首次）
```

TDX 主图的 B / S 标记 = `DirectionState.update` 返回 `flipped=True` 的 K 线。

| 当日 K 线 | 历史上一次"非触碰" | TDX 标记 |
|---|---|---|
| `L > MA20`（UP）| 是 DOWN | **B** |
| `L > MA20`（UP）| 是 UP | 无（同向）|
| `L > MA20`（UP）| 从未出现 | **B**（首次进入）|
| `H < MA20`（DOWN）| 是 UP | **S** |
| `H < MA20`（DOWN）| 是 DOWN | 无 |
| `H < MA20`（DOWN）| 从未出现 | **S**（首次进入）|
| 触碰（`L ≤ MA20 ≤ H`）| - | 无 |
| MA20 数据不足（前 19 根）| - | 无 |

---

## 三、TDX 公式实现

**首选公式（含 `IFNONE` 函数）**：

```
{ MA20 LOW/HIGH 干净 K 线方向 B/S 信号 }
{ 严格对应 scripts/backtest/signal.py classify_bar + DirectionState }
{ 通达信手机版主图叠加；周期由用户切换（日/周/月）自然适配 }
{ Plan: agents/plans/2026-05-08-quant-tdx-main-chart.md }

MA5 : MA(C,  5),  COLORWHITE;
MA10: MA(C, 10),  COLORYELLOW;
MA20: MA(C, 20),  COLORMAGENTA;
MA60: MA(C, 60),  COLORCYAN;

{ ----- 干净 K 线方向（与 backtest classify_bar 等价） ----- }
TODAYUP   := L > MA20;
TODAYDOWN := H < MA20;

{ ----- 历史最近的非触碰 K 线（不含今天） ----- }
{ BARSLAST(REF(X, 1)) = 距 X 上一次为真的 K 线根数；从未为真时 IFNONE 兜底 9999 }
PREVUP   := IFNONE(BARSLAST(REF(TODAYUP,   1)), 9999);
PREVDOWN := IFNONE(BARSLAST(REF(TODAYDOWN, 1)), 9999);

{ ----- 翻转判定 ----- }
{ B：今日 UP 且历史最近"非触碰"不是 UP（即 DOWN 或从未） }
{ S：今日 DOWN 且历史最近"非触碰"不是 DOWN }
B := TODAYUP   AND PREVDOWN <= PREVUP;
S := TODAYDOWN AND PREVUP   <= PREVDOWN;

{ ----- 显示：B 上方黄色（突破），S 下方绿色（破位）----- }
DRAWTEXT(B, H * 1.01, 'B'), COLORYELLOW;
DRAWTEXT(S, L * 0.99, 'S'), COLORGREEN;
```

**降级公式（不依赖 `IFNONE`，手机版必用 / PC 老版本兼容）**：

通达信手机版多数版本**不识别 `IFNONE`**，用 `BARSCOUNT` 间接判断"从未出现"：

```
{ ---- 不依赖 IFNONE 的等价实现 ---- }
{ 其余部分与首选公式相同，仅替换 PREVUP / PREVDOWN 两行： }

LASTUPRAW   := BARSLAST(REF(TODAYUP,   1));
LASTDOWNRAW := BARSLAST(REF(TODAYDOWN, 1));
TOTALBARS   := BARSCOUNT(C);

PREVUP   := IF(LASTUPRAW   >= 0 AND LASTUPRAW   < TOTALBARS, LASTUPRAW,   9999);
PREVDOWN := IF(LASTDOWNRAW >= 0 AND LASTDOWNRAW < TOTALBARS, LASTDOWNRAW, 9999);
```

**为什么是 `>= 0 AND < TOTALBARS` 双边检查**：

`BARSCOUNT(C)` 返回当前 bar 之前的 K 线总数。`BARSLAST` 在"从未为真"时不同通达信版本返回值不一致：
- 部分版本：返回 `-1`
- 部分版本：返回 ≥ TOTALBARS 的大数
- 部分版本：返回 NaN

单边 `< TOTALBARS` 不够——`-1 < TOTALBARS` 会被错误识别为"出现过"。
双边 `>= 0 AND < TOTALBARS` 才能稳定区分：
- 有效值 0 ~ (TOTALBARS-1) → 视为"出现过"，用作距今根数
- `-1` / NaN（NaN 比较返回 false）→ `>= 0` 检查不通过 → 用 9999 兜底
- 异常大数（≥ TOTALBARS）→ `< TOTALBARS` 检查不通过 → 用 9999 兜底

**实测命中**：手机版报错 `IFNONE: 您在括号前写的不是函数`，触发降级路径。`agents/results/2026-05-08-quant-tdx-main-chart.tdx` 已固化为降级公式。

**关键 TDX 函数**：

| 函数 | 含义 |
|---|---|
| `MA(C, N)` | N 日收盘均线 |
| `BARSLAST(cond)` | 距 cond 最后一次为真的 K 线根数（含当前；当前为真 → 0）|
| `REF(X, 1)` | X 后移 1 根（看"昨天的 X"），用于排除今天自身 |
| `IFNONE(X, default)` | X 为 null 时取 default（兜底"从未"场景）|
| `DRAWTEXT(cond, price, text)` | cond 为真时在指定价格高度显示文字 |

**边界正确性证明**（关键场景）：

| 场景 | TODAYUP | PREVUP | PREVDOWN | B | 期望 |
|---|---|---|---|---|---|
| 数据起始 ma20=NaN | False（NaN 比较）| - | - | False | ✓ 无 |
| 首次 UP（前面全 NaN/触碰）| True | 9999 | 9999 | True | ✓ B |
| 触碰日（前一日 UP）| False | 1 | 9999 | False | ✓ 无 |
| 首次 DOWN（前面全 UP）| False | n | 9999 | False | S = True ✓ |
| 连续同向 UP | True | n | 9999 | False（9999 ≤ n 为 False）| ✓ 无 |
| 翻转 UP→DOWN | False | n | 9999→1 | False | S = True ✓ |

### 3.1 不变性：信号序列必然 BSBSBS 交替（绝不会 BB / SS）

**性质**：从公式定义出发，连续两个 B（或两个 S）之间数学上不可能。

**反证**（连续 BB）：设 D_a 标了 B，假设 D_b（D_b > D_a）也想标 B。

1. D_b 标 B 要求 `TODAYUP=True` 且 `PREVDOWN <= PREVUP`。
2. 从 D_a 到 D_b 之间分两种情况：
   - **(a) 之间没有 DOWN K 线**：`PREVDOWN`（D_b 视角）= D_b 与"比 D_a 更早的某个 DOWN"的距离 > `PREVUP`（D_b 视角，最近的 UP K 线在 D_a 或之间）→ `PREVDOWN > PREVUP` → B 条件不成立 ✗
   - **(b) 之间有 DOWN K 线 D_c**：D_c 当时就触发了 S（S 条件成立）→ 在 D_a 与 D_b 之间已经有了 S → "连续 BB"不存在
3. 综上，连续两个 B 不可能。S 同理。

**结论**：信号序列在数学上保证 BSBSBS... 交替（中间可有任意触碰日）。**主图无需任何额外配对逻辑**。

---

## 四、部署 / 使用

### 4.1 通达信手机版（主目标）

通达信手机 app 公式管理路径因版本略有差异，常见路径任选其一：
- 首页底栏 "我的" → "更多功能" → "技术指标管理" / "公式管理"
- 任意 K 线图 → 长按指标区 → 弹出菜单选"自定义指标"
- 设置 → "智能选股 / 高级功能" → "公式编辑器"

操作流程：

1. 在"自定义指标"页点 "新建" / "+"
2. 填写：
   - 公式名称：`MA20BS`
   - 公式类型：**"主图叠加"**（注意不是"副图指标"）
   - 公式描述：`MA + LOW/HIGH B/S`
3. 在公式编辑框粘贴 §三 **首选公式**
4. 点 "测试" / "校验"
   - 若提示"未知函数 IFNONE" → 切换到 §三 **降级公式**重试
5. 通过 → 保存
6. 回到 K 线图 → 切到任一指数 → 长按主图区 → "主图叠加" → 勾选 `MA20BS`
7. 切换周期（日/周/月）观察 B/S 标记

### 4.2 PC 端兼容验证（可选）

如果手机操作粘贴困难，可先在 PC 通达信 V6+ 上写 + 测试公式，再用通达信账号"云同步"到手机：

1. PC 端 → 菜单 "功能" → "公式" → "公式管理器" → "新建" → 主图叠加
2. 按相同流程粘贴 + 测试 + 保存
3. 顶部菜单 "云同步" → 上传公式
4. 手机端登录同账号 → 公式管理 → 拉取云端公式

**重要：手机和 PC 公式语法子集略有不同。即使 PC 跑通，手机仍需在手机上独立测试一次。**

---

## 五、验证（与 backtest 对比）

**目标**：B/S 标记位置 = backtest `DirectionState.update(flipped=True)` 的 K 线。

**步骤**：

1. 选一个 V9 回测覆盖的指数。例如沪深 300（AkShare `000300`，通达信代码 `1B0300`）。
2. 跑 backtest 拿 D/W/M 三个 frequency 的 BUY/SELL 日期：
   ```bash
   python -m scripts.backtest.run_v9_detail --code 000300
   # 输出 agents/results/v9-000300.md，含 D/W/M 三段交易日志
   ```
3. 通达信打开 `1B0300`，公式叠加 `MA20BS`。
4. 对比 D/W/M 周期下的 B/S 标记日期 vs backtest 输出的 BUY/SELL 日期。
5. **验收**：每个 backtest BUY 日期 ↔ 一个 TDX B 标记日期（同根 K 线）；SELL 同理。

**抽样指数**（建议至少 3 个不同特征）：

| 指数 | AkShare | 通达信代码 | 特征 |
|---|---|---|---|
| 沪深 300 | 000300 | 1B0300 | 宽基低波 |
| 中证白酒 | 399997 | 8B7997 | 板块高波 |
| 恒生科技 | HSTECH | 31000940 | 港股 |

**已知边界例外**（不算失败）：

- backtest 数据起点和通达信本地 K 线起点可能不同——比对前确认两边起点对齐
- backtest 数据终点固定 2026-04-24（见 `data_loader.py DATA_END_DATE`），通达信会持续推送新 K 线——比对窗口要落在 [起点, 2026-04-24]

---

## 六、不做的事（明确边界）

- ❌ **持仓配对**（`backtest.signal.decide_action` 的 `position` / `quant.signal_engine.generate_signal` 的 `actual_state`）：TDX 主图无持仓概念，B/S 只标 policy 翻转。用户根据自己持仓决定是否下单。
- ❌ **`quant.derive_policy_state` 的 UNKNOWN 三态**（首日观察期不发信号）：TDX 与 backtest 的 `DirectionState` 一致——首次进入也算翻转。这与 quant 在历史最早期的行为略有不同，但实战盯盘场景下数据足够长，影响可忽略。
- ❌ **副图指标**（成交量、量比、KDJ 等）：本次只做主图。
- ❌ **通达信网页版**：手机和 PC 已覆盖（§四），网页版未测。
- ❌ **`.tne` 编译文件**：无法生成（需通达信内部编译器）。仅交付源码。

### 6.1 与 quant `generate_signal` 的语义差异（重要）

quant 因为有 `actual_state`（实际持仓）会**跳过**某些信号：

| 场景 | quant.generate_signal | TDX 主图 |
|---|---|---|
| `yesterday=HOLD, actual=HOLD, today=CASH` | 发 SELL | 标 S ✓ 一致 |
| `yesterday=HOLD, actual=CASH, today=CASH`（用户跳过过上一次 BUY）| **不发 SELL**（"尊重现实"，§3.2）| **仍标 S** |
| `yesterday=CASH, actual=HOLD` | StateInvariantError 异常 | TDX 无此概念 |

**含义**：TDX 主图比 quant **更激进**——每个方向翻转都标，无论你当前是否持仓。

**用户操作约定**：
- 如果你**严格执行 TDX**（每个 B 都买、每个 S 都卖）：信号序列 BSBSBS 完美配对，无问题。
- 如果你**跳过过一次 B**：之后的 S 在 TDX 上**仍会显示**，你不应该卖（因为没持仓），TDX 标记忽略即可。下一个 B 出现时，可以再决定是否买。

主图的 BSBSBS 序列**不变性**（§3.1）保证了无论你如何选择性执行，不会因为"连续 SS / 连续 BB"导致状态混乱。

---

## 七、风险

| 风险 | 缓解 |
|---|---|
| **手机版不识别 `IFNONE`**（高发） | §三 提供 **降级公式**（`BARSCOUNT` + `IF` 等价实现），切换重试 |
| 手机版 `BARSLAST` 在"从未为真"时返回值不一致 | 降级公式用 `LASTUPRAW < TOTALBARS` 兜底，避开"-1 / null" 不确定行为 |
| 手机版 `DRAWTEXT` 不支持 `COLORRED` 等常量 | 退化为 `STICKLINE(B, L*0.99, L*0.99, 0, 0)` 画点；或 `DRAWNUMBER(B, L*0.99, 1)` 画数字 |
| MA20 边界（前 19 根 NaN）的 `TODAYUP`/`DOWN` 行为 | NaN 比较返回 false，自然不触发 B/S，符合 backtest 数据未就绪语义 |
| 触碰 K 线被用户误以为"信号丢失" | §三 公式注释 + 本文档 §二 表格明确"触碰日保前态" |
| MA60 颜色（青色）与 S 文字颜色（绿色）视觉冲突 | MA60 已选青（不是绿），与 S 绿色区分明显 |
| 周期切换时 B/S 历史"消失" | 通达信切周期会重算所有公式，B/S 按当前周期重新标记——这是预期，不是 bug |
| 用户已有的主图配置被覆盖 | 通达信"主图叠加"是叠加而非替换，原有 K 线和均线保留 |

---

## 八、验收清单

- [x] §三 公式在通达信手机版"测试公式"通过（实测命中 `IFNONE` 不识别，已切换到降级公式）
- [x] 通达信切日 / 周 / 月线，三个周期分别看到 MA5/10/20/60 + B/S 标记
- [x] §五 抽样指数 D/W/M 周期 B/S 标记与 backtest `run_v9_detail` 输出对应（用户自行 check 通过）
- [x] 触碰日（K 线穿越 MA20 的窄幅震荡区段）确认无 B/S 标记
- [x] 首次进入 UP/DOWN 边界（数据起始第 20 根 K 线左右）确认 B/S 正确触发
- [x] B 显示在 K 线上方（`H * 1.01`），S 在 K 线下方（`L * 0.99`）
- [x] B 黄色 / S 绿色（实测 B 红色与阳线 K 融合，已改黄色）

---

## 九、后续可扩展（不在本次范围）

- 副图指标：成交量、MA20 偏离率、量比突变
- 多周期共振标记：日 + 周线同时 B → 加粗 / 大字号
- 信号通知：导出公式预警条件，通达信触发声音 / 弹窗
- ETF 联动：B/S 信号同时映射到对应 ETF 主图
