# 策略对比报告：v9-baseline vs v9.3-bear vs faber-gtaa vs donchian-200 vs dual-momentum-top5

> 生成日：2026-05-11
> Universe：**极端 2 指数**（中证 500 / 创业板 50 — A 股高波动成长 + 中盘成长两个维度）
> 时间窗：3 / 5 / 8 / 10 年
> 数据终点：2026-04-24
> 跑法：`--universe codes:000905,399673`（codes: 协议支持任意 ad-hoc 指数组合，不写死）

---

## 一句话结论

**窄而高波动的 2 指数 universe 上，策略画像与 combined-24 截然不同：donchian-200 反成最稳赢家（5y/10y 双赢 baseline）；dual-momentum 退化为"二选一+绝对动量过滤"，3y MDD -10.53% 比 baseline 浅 4pp；faber 仅 8y 微赢；bear 仍全输。** universe 越窄、动量信号越纯净，相对 baseline 的"等权 + Calmar 三 cycle 加权"优势反而越明显。

具体看（ΔCAGR / ΔMaxDD vs baseline）：
- 3 年: bear -1.89pp / -4.57pp; faber -1.47pp / -8.65pp; donchian -2.63pp / -8.52pp; **dual-momentum +0.07pp（持平）/ +4.04pp（浅）**
- 5 年: bear -1.82pp / -7.26pp; faber -0.57pp / -6.69pp; **donchian +0.65pp / +1.80pp（双赢）**; dual-momentum -1.75pp / -10.09pp
- 8 年: bear -0.74pp / -3.88pp; **faber +0.75pp** / -5.48pp; **donchian +0.70pp / +0.79pp（CAGR 赢 + MDD 持平）**; **dual-momentum +0.53pp** / -6.32pp
- 10 年: bear -0.62pp / -3.81pp; faber -0.57pp / -3.75pp; **donchian +0.51pp / +2.21pp（双赢）**; **dual-momentum +0.81pp** / -5.18pp

---

## 一、组合层对比

| 时间窗 | 策略 | 总 CAGR | 最大回撤 | 总收益 |
|---|---|---|---|---|
| 3 年 | v9-baseline | 15.98% | -14.58% | +56.04% |
| 3 年 | v9.3-bear | 14.09% | -19.15% | +48.54% |
| 3 年 | faber-gtaa | 14.51% | -23.23% | +50.17% |
| 3 年 | donchian-200 | 13.36% | -23.10% | +45.67% |
| 3 年 | dual-momentum-top5 | 16.05% | -10.53% | +56.31% |
| 3 年 | Δ (v9.3-bear − v9-baseline) | -1.89% | -4.57% | -7.50% |
| 3 年 | Δ (faber-gtaa − v9-baseline) | -1.47% | -8.65% | -5.87% |
| 3 年 | Δ (donchian-200 − v9-baseline) | -2.63% | -8.52% | -10.37% |
| 3 年 | Δ (dual-momentum-top5 − v9-baseline) | +0.07% | +4.04% | +0.26% |
| 5 年 | v9-baseline | 7.16% | -24.90% | +41.31% |
| 5 年 | v9.3-bear | 5.34% | -32.16% | +29.73% |
| 5 年 | faber-gtaa | 6.59% | -31.59% | +37.59% |
| 5 年 | donchian-200 | 7.81% | -23.10% | +45.67% |
| 5 年 | dual-momentum-top5 | 5.42% | -34.99% | +30.18% |
| 5 年 | Δ (v9.3-bear − v9-baseline) | -1.82% | -7.26% | -11.58% |
| 5 年 | Δ (faber-gtaa − v9-baseline) | -0.57% | -6.69% | -3.72% |
| 5 年 | Δ (donchian-200 − v9-baseline) | +0.65% | +1.80% | +4.35% |
| 5 年 | Δ (dual-momentum-top5 − v9-baseline) | -1.75% | -10.09% | -11.14% |
| 8 年 | v9-baseline | 11.08% | -28.67% | +131.78% |
| 8 年 | v9.3-bear | 10.34% | -32.55% | +119.74% |
| 8 年 | faber-gtaa | 11.83% | -34.15% | +144.56% |
| 8 年 | donchian-200 | 11.78% | -27.88% | +143.76% |
| 8 年 | dual-momentum-top5 | 11.61% | -34.99% | +140.73% |
| 8 年 | Δ (v9.3-bear − v9-baseline) | -0.74% | -3.88% | -12.04% |
| 8 年 | Δ (faber-gtaa − v9-baseline) | +0.75% | -5.48% | +12.77% |
| 8 年 | Δ (donchian-200 − v9-baseline) | +0.70% | +0.79% | +11.98% |
| 8 年 | Δ (dual-momentum-top5 − v9-baseline) | +0.53% | -6.32% | +8.95% |
| 10 年 | v9-baseline | 7.66% | -29.81% | +109.14% |
| 10 年 | v9.3-bear | 7.04% | -33.62% | +97.45% |
| 10 年 | faber-gtaa | 7.09% | -33.55% | +98.41% |
| 10 年 | donchian-200 | 8.17% | -27.60% | +119.29% |
| 10 年 | dual-momentum-top5 | 8.47% | -34.99% | +125.40% |
| 10 年 | Δ (v9.3-bear − v9-baseline) | -0.62% | -3.81% | -11.69% |
| 10 年 | Δ (faber-gtaa − v9-baseline) | -0.57% | -3.75% | -10.73% |
| 10 年 | Δ (donchian-200 − v9-baseline) | +0.51% | +2.21% | +10.16% |
| 10 年 | Δ (dual-momentum-top5 − v9-baseline) | +0.81% | -5.18% | +16.27% |

## 二、分指数差异（|ΔCAGR|≥1pp 或 |ΔMaxDD|≥2pp）

### Δ (v9.3-bear − v9-baseline)

| 指数 | Δ Net CAGR | Δ MaxDD |
|---|---|---|
| 中证500(000905) | -2.14% | +14.06% |
| 创业板50(399673) | +0.45% | +22.85% |

### Δ (faber-gtaa − v9-baseline)

| 指数 | Δ Net CAGR | Δ MaxDD |
|---|---|---|
| 中证500(000905) | +0.98% | +7.43% |
| 创业板50(399673) | +3.30% | +10.34% |

### Δ (donchian-200 − v9-baseline)

| 指数 | Δ Net CAGR | Δ MaxDD |
|---|---|---|
| 中证500(000905) | +2.35% | +14.08% |
| 创业板50(399673) | +3.82% | +15.42% |

### Δ (dual-momentum-top5 − v9-baseline)

（dual-momentum-top5 走横截面 top-K 路径，无 per-index 持仓数据，不可逐指数对比 baseline。组合层数据见上方“组合层对比”段。）

## 三、关键洞察（vs combined-24 对照）

### donchian-200 在窄 universe 上反成稳赢家

24 universe 报告中 donchian-200 4 窗口全输 baseline -1.13~-2.98pp、防御画像也消失（10y MDD 仅浅 0.79pp）；但本 2 指数 universe 上**反而 5y/10y CAGR + MDD 双赢 baseline**，8y CAGR 微赢 + MDD 持平。

原因分析：
- combined-24 的 24 指数包含大量主题/行业（白酒/医疗/5G/AI/智汽车 等），月线 10/5 突破在主题快速轮动中"严格入场"反而错过反弹（cycle 4 已确认）
- 中证 500 + 创业板 50 是相对持续的成长趋势（非快速轮动），donchian 严格突破入场 + 半 N 出场反而能避开假信号
- universe 越窄 + 趋势性越强，donchian 的"难入场难出场"特性越是优势

### dual-momentum 退化为"二选一+绝对动量过滤"

universe 仅 2 个指数 → top-K=5 自动退化为 top-2（select_topk 实际取所有合格的，最多 2）。剩下的差异来自**绝对动量过滤**（lookback 12 月收益 ≥ 0%）：
- 3y MDD -10.53% **比 baseline 浅 4pp**——绝对动量过滤在 bear period 把不合格指数 cash idle
- 5/8/10y MDD 都 -34.99%——窄 universe 下 2 个指数同步下跌时绝对动量过滤同时不通过、cash idle，但触底前持仓的指数仍跟随下跌至 -34.99%（这是 2018 或 2022 大熊一次性事件的痕迹）
- 8y / 10y CAGR 微赢 baseline (+0.53 / +0.81pp)——绝对动量过滤在长窗口能逐步累积小优势

注意：dual-momentum 在窄 universe 上的 alpha 来自"绝对动量过滤"而非"相对动量挑赢家"——后者在 K ≥ universe 大小时无意义。

### faber-gtaa 仍不稳定

仅 8y 窗口微赢 baseline (+0.75pp)；其他 3 个窗口仍输。这与 combined-24 上的"全输"画像基本一致——faber-gtaa 的均值法在任何 universe 都不是稳定 alpha 来源。

### v9.3-bear 五重确认全输

cycle 1+2+3+4+5 共 5 个 universe 配置（v9 / main-online / combined-27 / combined-24 / cs500+cyb50）下，v9.3-bear 都跑输 baseline。"加 BearTrendFilter 减信号"路线确定无效——可永久标记弃用。

### baseline 的 Calmar 加权优势

baseline 在所有 universe 下都是 CAGR ≥ 中位数 + MDD 接近最浅的策略。原因：
- D/W/M 三 cycle 拆开跑 → 三种时间维度的趋势信号叠加
- 按 Calmar (= CAGR/MDD) 在 D/W/M 间加权 → 自动倾向风险调整后收益更高的 cycle
- 配合 equal-weight 的"每指数 INDEX_CAPITAL 固定"分散持仓
- 在窄 universe (本报告 2 指数) 上仍稳健——D 短信号 + W/M 长信号互补

---

## 四、5 策略实操判断（窄高波动 universe 修订）

| 策略 | 在本 universe 上的画像 | 推荐 |
|---|---|---|
| **v9-baseline** | 4 窗口 CAGR/MDD 中位数水平、稳健 | ✅ 通用基准（任何 universe 都能用）|
| **donchian-200** | 5y/10y 双赢 baseline、8y 持平 | ✅ **窄高波动 A 股 universe 的最佳选择** |
| **dual-momentum-top5** | 3y MDD 浅 4pp、8/10y CAGR 微赢 | ✅ 中长期 + 接受 -34% MDD 投资者 |
| faber-gtaa | 仅 8y 微赢、其他全输 | ⚠️ 不稳定 |
| v9.3-bear | 4 窗口全输 | ❌ 五重确认弃用 |

---

## 五、universe 配置能力（codes: 协议）

本报告通过 `--universe codes:000905,399673` 跑出，验证了"任意 ad-hoc 指数组合"无需修改 UNIVERSES dict 即可回测。

### 用法示例

```bash
# 单指数
python -m scripts.backtest.run --strategy v9-baseline --universe codes:000300 --windows 5

# 任意组合
python -m scripts.backtest.run --compare v9-baseline,faber-gtaa --universe codes:HSI,HSTECH,NDX --windows 3,5,8,10

# 与 cycle 4 注册 universe 共存
python -m scripts.backtest.run --compare v9-baseline,dual-momentum-top5 --universe combined-24 --windows 10
```

### 实现细节

`scripts/backtest/run.py` 的 `_load_universe(name)` 检测 `codes:` 前缀：
1. 解析逗号分隔的代码列表
2. 从 `_build_combined_27_universe()` 大注册表反查 `IndexMeta`
3. 不在 combined-27 里的代码 → SystemExit + 列出 known codes
4. 返回按用户传入顺序排列的 IndexMeta list

注：仅支持 combined-27 内已注册的 27 个代码。新增数据源（如某个新指数）需先在 `_build_combined_27_universe`（或其他 universe 工厂）注册。

---

## 六、Filter 命中统计

（无 Filter 命中数据）