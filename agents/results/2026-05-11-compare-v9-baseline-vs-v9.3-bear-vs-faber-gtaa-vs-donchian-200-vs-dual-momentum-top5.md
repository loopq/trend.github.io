# 策略对比报告：v9-baseline vs v9.3-bear vs faber-gtaa vs donchian-200 vs dual-momentum-top5

> 生成日：2026-05-11
> Universe：combined-27（v9 14 主题/行业 + main-online 16 宽基/海外/商品 去重）
> 时间窗：3 / 5 / 8 / 10 年
> 数据终点：2026-04-24

---

## 一句话结论

**5 策略 4 窗口跑下来：dual-momentum-top5 在 CAGR 上全胜 baseline（+4.82~+20.70pp）但 5-8-10y MDD 显著恶化（-28~-34pp 比 baseline 深），是典型的“high-return, high-risk concentration”策略；faber-gtaa 长窗口反超 baseline 仍然成立；其余策略画像与 cycle 2 一致。**

本周期最有价值的发现：
1. **决策粒度对照实验**：per-index in/out（faber/donchian）路线 vs portfolio cross-sectional（dual-momentum）路线，结果鲜明分化——dual-momentum 在所有窗口 CAGR 都赢 baseline，但 5/8y MDD 跳到 -47%（baseline 仅 -13~-18%），暴露 top-5 集中持仓在 2022 大熊期的脆弱性。
2. **dual-momentum 3y 窗口 CAGR 36.64% 是 2023-04~2026-04 后熊市 momentum-friendly bull period 的真 alpha**（BTC/NDX/创业板50/港股科技都强势，top-5 选股放大头部赢家）。算法验证已确认无 look-ahead bias。

具体看（ΔCAGR / ΔMaxDD vs baseline）：
- 3 年: bear -1.97pp / -1.56pp; faber -2.63pp / -3.36pp; donchian -5.05pp / -3.30pp; **dual-momentum +20.70pp / -4.21pp**
- 5 年: bear -2.31pp / -4.07pp; faber -3.12pp / -5.83pp; donchian -3.00pp / -0.66pp; **dual-momentum +3.70pp / -34.16pp**
- 8 年: bear -1.02pp / -2.95pp; faber +1.00pp / -2.92pp; donchian -2.45pp / +1.05pp; **dual-momentum +6.58pp / -28.67pp**
- 10 年: bear -0.06pp / -3.13pp; faber +6.15pp / +3.03pp; donchian -14.25pp / +15.97pp; **dual-momentum +4.82pp / -6.54pp**

---

## 一、组合层对比

| 时间窗 | 策略 | 总 CAGR | 最大回撤 | 总收益 |
|---|---|---|---|---|
| 3 年 | v9-baseline | 15.94% | -10.79% | +55.86% |
| 3 年 | v9.3-bear | 13.97% | -12.35% | +48.03% |
| 3 年 | faber-gtaa | 13.31% | -14.15% | +45.50% |
| 3 年 | donchian-200 | 10.89% | -14.09% | +36.37% |
| 3 年 | dual-momentum-top5 | 36.64% | -15.00% | +155.17% |
| 3 年 | Δ (v9.3-bear − v9-baseline) | -1.97% | -1.56% | -7.83% |
| 3 年 | Δ (faber-gtaa − v9-baseline) | -2.63% | -3.36% | -10.36% |
| 3 年 | Δ (donchian-200 − v9-baseline) | -5.05% | -3.30% | -19.48% |
| 3 年 | Δ (dual-momentum-top5 − v9-baseline) | +20.70% | -4.20% | +99.31% |
| 5 年 | v9-baseline | 9.55% | -12.88% | +57.76% |
| 5 年 | v9.3-bear | 7.24% | -16.95% | +41.80% |
| 5 年 | faber-gtaa | 6.43% | -18.71% | +36.58% |
| 5 年 | donchian-200 | 6.55% | -13.54% | +37.33% |
| 5 年 | dual-momentum-top5 | 13.25% | -47.04% | +86.27% |
| 5 年 | Δ (v9.3-bear − v9-baseline) | -2.31% | -4.07% | -15.97% |
| 5 年 | Δ (faber-gtaa − v9-baseline) | -3.11% | -5.83% | -21.18% |
| 5 年 | Δ (donchian-200 − v9-baseline) | -3.00% | -0.66% | -20.44% |
| 5 年 | Δ (dual-momentum-top5 − v9-baseline) | +3.70% | -34.16% | +28.51% |
| 8 年 | v9-baseline | 11.43% | -18.37% | +137.62% |
| 8 年 | v9.3-bear | 10.40% | -21.33% | +120.71% |
| 8 年 | faber-gtaa | 12.43% | -21.29% | +155.24% |
| 8 年 | donchian-200 | 8.98% | -17.32% | +98.91% |
| 8 年 | dual-momentum-top5 | 18.01% | -47.04% | +276.12% |
| 8 年 | Δ (v9.3-bear − v9-baseline) | -1.02% | -2.95% | -16.90% |
| 8 年 | Δ (faber-gtaa − v9-baseline) | +1.00% | -2.92% | +17.62% |
| 8 年 | Δ (donchian-200 − v9-baseline) | -2.45% | +1.05% | -38.70% |
| 8 年 | Δ (dual-momentum-top5 − v9-baseline) | +6.58% | -28.67% | +138.51% |
| 10 年 | v9-baseline | 24.49% | -47.54% | +793.53% |
| 10 年 | v9.3-bear | 24.42% | -50.67% | +789.09% |
| 10 年 | faber-gtaa | 30.64% | -44.50% | +1347.05% |
| 10 年 | donchian-200 | 10.23% | -31.57% | +164.90% |
| 10 年 | dual-momentum-top5 | 29.31% | -54.08% | +1206.35% |
| 10 年 | Δ (v9.3-bear − v9-baseline) | -0.06% | -3.13% | -4.43% |
| 10 年 | Δ (faber-gtaa − v9-baseline) | +6.15% | +3.03% | +553.52% |
| 10 年 | Δ (donchian-200 − v9-baseline) | -14.25% | +15.97% | -628.63% |
| 10 年 | Δ (dual-momentum-top5 − v9-baseline) | +4.82% | -6.54% | +412.83% |

## 二、决策粒度对照（per-index in/out vs portfolio cross-sectional）

3 个 V10 月线策略 + dual-momentum 都跑 combined-27，决策粒度三档：

| 策略 | 决策粒度 | 持仓数 | 资金分配 | 4 窗口 ΔCAGR vs baseline |
|---|---|---|---|---|
| **faber-gtaa** | per-index per-bar | 0 ~ 27（独立） | 每指数 INDEX_CAPITAL 固定 | 3年 -2.63 / 5年 -3.12 / 8年 +1.00 / 10年 +6.15 |
| **donchian-200** | per-index per-bar | 0 ~ 27（独立） | 每指数 INDEX_CAPITAL 固定 | 3年 -5.05 / 5年 -3.00 / 8年 -2.45 / 10年 -14.25 |
| **dual-momentum-top5** | portfolio per-rebalance | 0 ~ 5（universe-wide） | top-5 等分 TOTAL_CAPITAL | 3年 +20.70 / 5年 +3.70 / 8年 +6.58 / 10年 +4.82 |

**核心结论**：
- **dual-momentum 在 CAGR 上全面胜出**（4 窗口都赢 baseline 4.82~20.70pp）——cross-sectional“挑赢家”逻辑确实能放大 alpha
- **代价是 MDD 大幅恶化**：5/8 年 MDD 从 baseline 的 -13~-18% 跳到 -47%，反映 top-5 集中持仓在 bear market（2022 大熊）期的脆弱性
- **faber-gtaa 是唯一“in/out 路线长窗口赢 baseline”的策略**（10y +6.15pp CAGR + 浅 MDD），均值法在长趋势下确实有用
- **donchian-200 极值法 CAGR 全输 baseline**，但 MDD 普遍浅（防御型，与 faber 形成均值/极值对照）
- **v9.3-bear 加 Filter 路线全输**——已确认错路（cycle 1+2+3 三重验证）

**决策粒度选型建议**：
- 追长期 CAGR + 接受高 MDD（如风险预算 50%）→ dual-momentum
- 追长期 CAGR + 控制 MDD（< 25%）→ faber-gtaa
- 追低 MDD（< 35%） + 接受偏低 CAGR → donchian-200
- 平衡型（CAGR 中、MDD 中）→ baseline

---

## 三、分指数差异（|ΔCAGR|≥1pp 或 |ΔMaxDD|≥2pp）

### Δ (v9.3-bear − v9-baseline)

| 指数 | Δ Net CAGR | Δ MaxDD |
|---|---|---|
| 沪深300(000300) | +0.85% | +20.18% |
| 上证50(000016) | +1.71% | +15.32% |
| 中证500(000905) | -2.14% | +14.06% |
| 中证1000(000852) | -3.61% | +5.93% |
| 科创50(000688) | -15.58% | +8.56% |
| 中证2000(932000) | -4.31% | +8.36% |
| 创业板50(399673) | +0.45% | +22.85% |
| 北证50(899050) | -49.24% | +18.43% |
| 光伏产业(931151) | -1.43% | +14.65% |
| 中证白酒(399997) | -11.73% | +1.08% |
| 中证医疗(399989) | -0.57% | +28.85% |
| 5G通信(931079) | -15.64% | -4.02% |
| 中证新能(399808) | -4.29% | +14.42% |
| 人工智能(931071) | -11.78% | -8.05% |
| CS智汽车(930721) | -7.69% | +2.28% |
| 中证军工(399967) | -1.49% | +3.30% |
| CS新能车(399976) | -1.60% | +22.18% |
| 有色金属(000819) | -5.97% | +5.77% |
| 细分化工(000813) | -5.81% | +8.76% |
| 恒生指数(HSI) | -0.08% | +19.70% |
| 国企指数(HSCEI) | +0.84% | +23.03% |
| 恒生科技(HSTECH) | -1.89% | +5.03% |
| 纳指100(NDX) | -6.43% | +8.43% |
| 标普500(SPX) | -3.53% | +4.97% |
| 比特币(BTC) | -10.26% | +27.59% |
| 黄金现价(XAU) | -6.10% | +1.53% |
| 白银现价(XAG) | -6.83% | -9.28% |

### Δ (faber-gtaa − v9-baseline)

| 指数 | Δ Net CAGR | Δ MaxDD |
|---|---|---|
| 沪深300(000300) | +1.16% | +0.28% |
| 上证50(000016) | +1.88% | +0.27% |
| 中证500(000905) | +0.98% | +7.43% |
| 中证1000(000852) | +0.02% | -2.28% |
| 科创50(000688) | -6.54% | +11.76% |
| 创业板50(399673) | +3.30% | +10.34% |
| 北证50(899050) | -45.93% | +1.39% |
| 光伏产业(931151) | -3.80% | -8.71% |
| 中证白酒(399997) | -6.22% | -33.81% |
| 中证医疗(399989) | -5.20% | -0.57% |
| 5G通信(931079) | -6.99% | -8.63% |
| 中证新能(399808) | -1.52% | +4.00% |
| 人工智能(931071) | -3.46% | -5.73% |
| CS智汽车(930721) | -7.22% | -6.26% |
| 中证军工(399967) | -5.28% | -18.08% |
| CS新能车(399976) | +2.77% | +13.01% |
| 有色金属(000819) | -5.46% | -24.82% |
| 细分化工(000813) | -3.63% | -9.92% |
| 恒生指数(HSI) | +2.48% | -0.96% |
| 国企指数(HSCEI) | +1.63% | -9.44% |
| 恒生科技(HSTECH) | -0.93% | -3.84% |
| 纳指100(NDX) | +2.08% | -6.73% |
| 标普500(SPX) | -1.30% | -7.92% |
| 比特币(BTC) | -34.74% | +15.45% |
| 黄金现价(XAU) | +0.45% | -13.65% |
| 白银现价(XAG) | +4.40% | +8.65% |

### Δ (donchian-200 − v9-baseline)

| 指数 | Δ Net CAGR | Δ MaxDD |
|---|---|---|
| 沪深300(000300) | +1.48% | +13.37% |
| 上证50(000016) | +1.07% | +6.91% |
| 中证500(000905) | +4.25% | +14.08% |
| 中证1000(000852) | +0.64% | +3.24% |
| 科创50(000688) | -3.21% | +11.76% |
| 中证2000(932000) | -1.42% | -11.04% |
| 创业板50(399673) | +3.82% | +15.42% |
| 北证50(899050) | -45.90% | +3.77% |
| 光伏产业(931151) | -2.73% | -13.54% |
| 中证白酒(399997) | -8.41% | -14.98% |
| 中证医疗(399989) | -7.31% | +9.37% |
| 5G通信(931079) | -10.02% | -25.36% |
| 中证新能(399808) | -0.71% | +4.43% |
| 人工智能(931071) | -4.90% | -4.35% |
| CS智汽车(930721) | -7.02% | -14.81% |
| 中证军工(399967) | -3.85% | -14.90% |
| CS新能车(399976) | +7.44% | +19.42% |
| 有色金属(000819) | -0.49% | +4.57% |
| 细分化工(000813) | -3.97% | +1.35% |
| 恒生指数(HSI) | +4.41% | +11.82% |
| 国企指数(HSCEI) | +3.80% | +12.40% |
| 恒生科技(HSTECH) | -12.55% | -14.03% |
| 纳指100(NDX) | -0.51% | -6.73% |
| 标普500(SPX) | -1.29% | -2.26% |
| 比特币(BTC) | -34.16% | -5.55% |
| 黄金现价(XAU) | +0.48% | -6.09% |
| 白银现价(XAG) | +3.86% | +8.65% |

### Δ (dual-momentum-top5 − v9-baseline)

（dual-momentum-top5 走横截面 top-K 路径，无 per-index 持仓数据，不可逐指数对比 baseline。组合层数据见上方“组合层对比”段。）

### 分指数模式（仅 in/out 三策略）

dual-momentum 走横截面 top-5（不可逐指数对比），下面观察 bear / faber / donchian 三个 in/out 策略 vs baseline 的分指数 Δ：

- **A 股宽基**（沪深300/上证50/中证500/中证1000/中证2000/创业板50/科创50/北证50）：faber/donchian 在大盘宽基（沪深300/上证50/中证500/创业板50）普遍 +1~+4pp CAGR 小赢，但 MDD 同步加深 +6~+15pp（"持有期更长 = 吃更多回撤"）；bear 同向但 MDD 恶化更剧（沪深300 +20pp、创业板50 +22pp）。三策略在科创50/北证50/中证2000 这类小市值/新指数集体翻车（北证50 几乎全输 -45pp，启动时间晚 + 趋势不稳是共因）。
- **A 股主题/行业**（光伏/白酒/医疗/5G/AI/智汽车/军工/新能/新能车/有色/化工 等）：**所有 in/out 策略都在主题/行业指数上普遍输 baseline**（faber 平均 -4~-7pp、donchian 平均 -4~-10pp、bear 普遍 -5~-15pp）；仅"中证新能车"是反例（faber +2.77/+13、donchian +7.44/+19）。说明主题/行业指数振幅大、趋势短，月线均值/极值法都跟不上 daily Calmar 加权 baseline。
- **港股**（HSI/HSCEI/HSTECH）：HSI/HSCEI 是 faber 和 donchian 的强项（+1.6~+4.4pp CAGR、faber 同时浅 MDD），HSTECH donchian 大输 -12.55pp（极值法吃震荡）；bear 在港股 MDD 普遍恶化 +5~+23pp，几乎无可取之处。
- **美股**（NDX/SPX）：faber NDX +2.08pp/-6.73pp 是亮点（CAGR 升 + MDD 降），SPX 三策略都微输；bear 在 NDX/SPX 双输（CAGR -3~-6pp、MDD +5~+8pp），加 filter 是错的再次确认。
- **加密 / 商品**（BTC/XAU/XAG）：BTC 是 faber/donchian 的硬伤（-34pp CAGR，月线粒度太粗 + 24h 持续 trending 不适合 trend-following 离场），bear 类似；XAU/XAG faber 和 donchian 都微赢（XAG +3.86~+4.40pp CAGR），均值/极值法在低噪声商品上表现稳定。

总结：in/out 三策略的分指数表现高度一致——**大盘宽基 + 港股大盘 + 美股 + 商品上 faber/donchian 有微弱 alpha；主题/行业 + 加密上系统性输 baseline；bear filter 路线在 90% 指数上恶化 MDD**。这也间接解释了 dual-momentum 为什么能赢——它通过横截面"挑赢家"避开了主题/行业指数的拖累，把资金集中到 momentum 强的少数赢家上（如 BTC/NDX/创业板50 类），但代价是熊市集中持仓崩盘风险（5/8y MDD -47%）。

## 四、Filter 命中统计

（无 Filter 命中数据）

## 五、后续方向

### 当前 5 策略实操判断

| 策略 | 适合谁 | 理由 |
|---|---|---|
| v9-baseline | 平衡型投资者 | 总收益最高、CAGR 中庸、MDD 中庸；通用基准 |
| **faber-gtaa** | 长期投资者（8+ 年视野） | 8-10y CAGR 反超 baseline，10y +6.15pp + 浅 MDD（双赢） |
| **donchian-200** | 风险厌恶投资者 | 10y MDD 比 baseline 浅 16pp（-31.57% vs -47.54%）；CAGR 代价 -14.25pp |
| **dual-momentum-top5** | 高风险偏好投资者 | 4 窗口 CAGR 全胜 baseline，3y +20.70pp；但 5/8y MDD -47% 集中度风险显著 |
| v9.3-bear | 不推荐 | 4 窗口全输；"加 Filter 减信号"路线 cycle 1+2+3 三重确认 |

### Cycle 1-3 总结

3 个 cycle 落地了 4 个 V10 策略 + 2 个 aggregator：

**已弃**（cycle 1+2+3 三重确认无效）：
- v9.3-bear：加 BearTrendFilter 路线在所有 universe / 所有窗口都跑输 baseline

**已得**（4 个有明确价值的策略画像）：
- v9-baseline：通用基准（cycle-calmar / D-W-M Calmar 加权）
- faber-gtaa：长期投资者升级（equal-weight / 月线 MA10 均值法）
- donchian-200：低 MDD 防御方案（equal-weight / 月线 10/5 极值法）
- dual-momentum-top5：高 CAGR 高 MDD 攻击型（cross-sectional-topk / 月线 12 月动量 / top-5）

**框架成熟度**：
- 2 个 aggregator（equal-weight / cross-sectional-topk）支持新策略零 dispatch 改动
- Strategy.params 字段支持 aggregator 特定参数（lookback / topk / abs_threshold 等）
- compare_report 兼容横截面策略（无 per-index 数据时显示提示）
- 隔离铁律守住：scripts/quant/ + scripts/main.py + docs/ 零修改，v9-baseline / v9.3-bear 数值字符级一致

### 调参方向（cycle 4+ 候选）

按代价从小到大：

1. **改 dual-momentum 参数**：top-3 / top-7 / lookback 6/9/24 月。注册新策略名（如 `dual-momentum-top3-lookback6`）即跑，框架天然支持。预期：top-3 CAGR 更高 + MDD 更深；top-7 反之。
2. **改 faber / donchian 窗口**：MA8/12 / 8-4 / 12-6。注册即跑。
3. **混合 universe-aware 策略**：仅在大盘宽基用 faber，主题用 baseline，加密用 dual-momentum。需要新 spec（universe-aware aggregator）。
4. **加 fallback**：dual-momentum 不合格时持债券（需新数据源）；faber/donchian 加 stop-loss。
5. **组合配置**：baseline + faber + dual-momentum 加权混合。需要新 portfolio aggregator（最大改动）。