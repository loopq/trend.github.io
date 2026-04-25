"""V5 CLI：跑 90 个 THS 一级行业 + 输出 v5-result.md。

python -m scripts.backtest.run_v5
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import List, Tuple

import pandas as pd

from scripts.backtest.v5_registry import build_v5_registry
from scripts.backtest.v5_screener import SectorMetrics, screen_sector

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT = PROJECT_ROOT / "docs" / "agents" / "backtest" / "v5-result.md"
SUMMARY_OUTPUT = PROJECT_ROOT / "docs" / "agents" / "backtest" / "v5-summary.md"
TINY_OUTPUT = PROJECT_ROOT / "docs" / "agents" / "backtest" / "v5-tiny-result.md"

# Tiny 筛选标准（精选 ≤ 20 个用于后续详细验证）
TINY_MIN_SIGMA = 28.0
TINY_MIN_ALPHA = 50.0
TINY_MIN_CALMAR = 0.25
TINY_MAX_COUNT = 20

# 强制纳入的行业代码（用户特别要求，绕过硬门槛）
FORCE_INCLUDE_CODES = {
    "881145",  # 电力（用户特别要求；σ=23.6% 低于门槛，但 alpha +54.75% / Calmar 0.313 表现尚可）
}


def _fmt_pct(v) -> str:
    if v is None:
        return "-"
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.2f}%"


def _fmt_num(v, digits: int = 2) -> str:
    if v is None:
        return "-"
    return f"{v:.{digits}f}"


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    return float(pd.Series(values).quantile(pct / 100))


def render_v5_result(metrics: List[SectorMetrics], failed: List[Tuple[str, str, str]]) -> str:
    """渲染 V5 结果 md。"""
    lines: List[str] = []
    lines.append("# V5 同花顺一级行业回测结果")
    lines.append("")
    lines.append("> 评估区间：2016-01-01 ~ 2026-04-24（数据终点固定）")
    lines.append(f"> 样本：{len(metrics) + len(failed)} 个 THS 一级行业（成功 {len(metrics)} / 失败 {len(failed)}）")
    lines.append("> 算法：V4.1 Calmar 权重 + D/W/M 三策略")
    lines.append("")

    # 一、采集情况
    lines.append("## 一、数据采集情况")
    lines.append("")
    lines.append(f"- 总数：{len(metrics) + len(failed)}")
    lines.append(f"- 成功：{len(metrics)}")
    lines.append(f"- 失败：{len(failed)}（详见末尾）")
    lines.append("")

    # 二、波动率分布
    sigmas = [m.annual_volatility for m in metrics]
    lines.append("## 二、年化波动率分布")
    lines.append("")
    if sigmas:
        lines.append(f"- 最小：{min(sigmas):.2f}%")
        lines.append(f"- p25：{_percentile(sigmas, 25):.2f}%")
        lines.append(f"- 中位数：{_percentile(sigmas, 50):.2f}%")
        lines.append(f"- p75：{_percentile(sigmas, 75):.2f}%")
        lines.append(f"- 最大：{max(sigmas):.2f}%")
    lines.append("")

    # 三、波动率排行 Top 30
    lines.append("## 三、波动率排行（Top 30）")
    lines.append("")
    lines.append("| 排名 | 行业 | 代码 | 年化σ | B&H总收益 | D总收益 | D alpha |")
    lines.append("|---|---|---|---|---|---|---|")
    by_sigma = sorted(metrics, key=lambda m: -m.annual_volatility)[:30]
    for rank, m in enumerate(by_sigma, 1):
        lines.append(
            f"| {rank} | {m.name} | {m.code} | {m.annual_volatility:.2f}% "
            f"| {_fmt_pct(m.bh_total_return)} | {_fmt_pct(m.d_total_return)} | {_fmt_pct(m.d_alpha)} |"
        )
    lines.append("")

    # 四、策略 alpha 排行 Top 30
    lines.append("## 四、策略 alpha 排行（按 best alpha 降序，Top 30）")
    lines.append("")
    lines.append("| 排名 | 行业 | 代码 | σ | 最强策略 | best总收益 | B&H | best alpha | best Calmar |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    by_alpha = sorted(metrics, key=lambda m: -m.best_alpha)[:30]
    for rank, m in enumerate(by_alpha, 1):
        lines.append(
            f"| {rank} | {m.name} | {m.code} | {m.annual_volatility:.2f}% "
            f"| **{m.best_strategy}** | {_fmt_pct(m.best_return)} "
            f"| {_fmt_pct(m.bh_total_return)} | **{_fmt_pct(m.best_alpha)}** "
            f"| {_fmt_num(m.best_calmar, 3)} |"
        )
    lines.append("")

    # 五、综合甜点榜：高波动 + 高 alpha
    # 综合分 = best_alpha × σ / 100（惩罚低波动指数）
    # 仅取波动率 > p50 的指数
    sigma_p50 = _percentile(sigmas, 50) if sigmas else 0
    eligible = [m for m in metrics if m.annual_volatility >= sigma_p50 and m.best_alpha > 0]
    eligible.sort(key=lambda m: -(m.best_alpha * m.annual_volatility / 100))

    lines.append(f"## 五、综合甜点榜（σ ≥ p50 = {sigma_p50:.2f}% 且 best_alpha > 0，Top 25）")
    lines.append("")
    lines.append("| 排名 | 行业 | σ | 最强策略 | best alpha | Calmar | D 权重 | W 权重 | M 权重 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for rank, m in enumerate(eligible[:25], 1):
        d_w = m.calmar_weights.get("D", 0)
        w_w = m.calmar_weights.get("W", 0)
        m_w = m.calmar_weights.get("M", 0)

        def fmt_w(x):
            return f"{x * 100:.1f}%" if x > 0 else "❌"

        lines.append(
            f"| {rank} | {m.name}({m.code}) | {m.annual_volatility:.2f}% "
            f"| **{m.best_strategy}** | **{_fmt_pct(m.best_alpha)}** "
            f"| {_fmt_num(m.best_calmar, 3)} "
            f"| {fmt_w(d_w)} | {fmt_w(w_w)} | {fmt_w(m_w)} |"
        )
    lines.append("")

    # 六、推荐 V5 组合：精选 Top 15（去重前）
    lines.append("## 六、推荐 V5 组合（Top 15）")
    lines.append("")
    lines.append("从综合甜点榜取前 15 个，每个 $10k 起始，按 Calmar 权重在 D/W/M 间分配。")
    lines.append("（如组合内有相关性高的板块，可在 V6 阶段做相关性聚类去重。）")
    lines.append("")
    lines.append("| # | 行业 | σ | best alpha | best 总收益 | 推荐主策略 |")
    lines.append("|---|---|---|---|---|---|")
    for i, m in enumerate(eligible[:15], 1):
        lines.append(
            f"| {i} | {m.name}({m.code}) | {m.annual_volatility:.2f}% "
            f"| **{_fmt_pct(m.best_alpha)}** | {_fmt_pct(m.best_return)} | **{m.best_strategy}** |"
        )
    lines.append("")

    # 七、与 V4.1 对比
    lines.append("## 七、与 V4.1（20 指数组合）的差异")
    lines.append("")
    lines.append("- V4.1：宽基 7 + 港股 2 + 海外 1 + 加密 1 + 板块 9 = 20 指数")
    lines.append("- V4.1 三年组合 CAGR：9.41%（剔除 BTC 后）")
    lines.append("- V4.1 八年组合 CAGR：7.83%（剔除 BTC 后）")
    lines.append("")
    lines.append("V5 假设 Top 15 行业等权组合（每个 $10k = $150k 总本金）的简单粗算：")
    if len(eligible) >= 15:
        avg_best_return = sum(m.best_return for m in eligible[:15]) / 15
        avg_bh = sum(m.bh_total_return for m in eligible[:15]) / 15
        # 估算 10 年 CAGR
        # 注意：各行业评估期不一定都是 10 年，这只是粗算
        lines.append(f"- 平均 best 总收益：**{avg_best_return:.2f}%**")
        lines.append(f"- 平均 B&H 总收益：{avg_bh:.2f}%")
        lines.append(f"- 平均 alpha：**{avg_best_return - avg_bh:+.2f}%**")
        lines.append("")
        lines.append("> 该粗算未考虑组合相关性、不同评估期长度。精细的组合回测见 V6（待开发）。")
    lines.append("")

    # 八、失败行业清单
    if failed:
        lines.append(f"## 八、失败行业清单（{len(failed)}）")
        lines.append("")
        lines.append("| 代码 | 名称 | 失败原因 |")
        lines.append("|---|---|---|")
        for code, name, reason in failed:
            lines.append(f"| {code} | {name} | {reason} |")
        lines.append("")
        lines.append("> 失败可能是 AkShare 服务器拒绝（反爬）。重跑 `python -m scripts.backtest.run_v5` 通常能补救（已成功的走缓存）。")
    lines.append("")

    # 九、附录：90 行业全表
    lines.append("## 九、附录：所有行业全表（按代码升序）")
    lines.append("")
    lines.append("| 代码 | 行业 | σ | B&H收益 | D 总收益 | W 总收益 | M 总收益 | best | best alpha |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for m in sorted(metrics, key=lambda x: x.code):
        lines.append(
            f"| {m.code} | {m.name} | {m.annual_volatility:.2f}% "
            f"| {_fmt_pct(m.bh_total_return)} | {_fmt_pct(m.d_total_return)} "
            f"| {_fmt_pct(m.w_total_return)} | {_fmt_pct(m.m_total_return)} "
            f"| **{m.best_strategy}** | {_fmt_pct(m.best_alpha)} |"
        )

    return "\n".join(lines)


def render_v5_summary(metrics: List[SectorMetrics], failed: List[Tuple[str, str, str]]) -> str:
    """V5 总结文档：聚焦"跑了哪些 / 失败哪些 / 各自成绩"，便于回顾。"""
    lines: List[str] = []
    lines.append("# V5 同花顺一级行业回测总结")
    lines.append("")
    lines.append("> 评估区间：2016-01-01 ~ 2026-04-24（数据终点固定）")
    lines.append(f"> 样本：{len(metrics) + len(failed)} 个 THS 一级行业")
    lines.append(f"> **成功：{len(metrics)}** / **失败：{len(failed)}**")
    lines.append("")

    # 一、运行清单
    lines.append("## 一、运行清单")
    lines.append("")
    lines.append(f"### 成功 {len(metrics)} 个")
    lines.append("")
    cols_per_row = 5
    success_codes = sorted(metrics, key=lambda m: m.code)
    for i in range(0, len(success_codes), cols_per_row):
        chunk = success_codes[i:i + cols_per_row]
        lines.append("- " + " · ".join(f"{m.name}({m.code})" for m in chunk))
    lines.append("")

    if failed:
        lines.append(f"### ❌ 失败 {len(failed)} 个")
        lines.append("")
        lines.append("| 代码 | 名称 | 失败原因 |")
        lines.append("|---|---|---|")
        for code, name, reason in failed:
            lines.append(f"| {code} | {name} | {reason} |")
        lines.append("")
        lines.append("> 失败大概率是 AkShare 服务器拒绝（反爬），重跑通常能补救（已成功的走缓存）。")
    else:
        lines.append("### ❌ 失败 0 个")
        lines.append("")
        lines.append("本轮 90 个 THS 一级行业**全部成功**，无失败案例。")
    lines.append("")

    # 二、关键统计
    if metrics:
        sigmas = [m.annual_volatility for m in metrics]
        d_alphas = [m.d_alpha for m in metrics if m.d_alpha is not None]
        w_alphas = [m.w_alpha for m in metrics if m.w_alpha is not None]
        m_alphas = [m.m_alpha for m in metrics if m.m_alpha is not None]
        best_alphas = [m.best_alpha for m in metrics]

        d_winners = sum(1 for m in metrics if m.best_strategy == "D")
        w_winners = sum(1 for m in metrics if m.best_strategy == "W")
        m_winners = sum(1 for m in metrics if m.best_strategy == "M")

        positive_d = sum(1 for a in d_alphas if a > 0)
        positive_w = sum(1 for a in w_alphas if a > 0)
        positive_m = sum(1 for a in m_alphas if a > 0)

        lines.append("## 二、关键统计")
        lines.append("")
        lines.append("### 波动率分布")
        lines.append("")
        lines.append(f"- 最小：{min(sigmas):.2f}%")
        lines.append(f"- p25：{_percentile(sigmas, 25):.2f}%")
        lines.append(f"- 中位数：{_percentile(sigmas, 50):.2f}%")
        lines.append(f"- p75：{_percentile(sigmas, 75):.2f}%")
        lines.append(f"- 最大：{max(sigmas):.2f}%")
        lines.append("")
        lines.append("### 各策略 alpha 分布（与 B&H 对比）")
        lines.append("")
        lines.append("| 策略 | 中位 alpha | 跑赢 B&H 数量 | 跑输 B&H 数量 |")
        lines.append("|---|---|---|---|")
        if d_alphas:
            lines.append(f"| D | {_percentile(d_alphas, 50):+.2f}% | {positive_d} | {len(d_alphas) - positive_d} |")
        if w_alphas:
            lines.append(f"| W | {_percentile(w_alphas, 50):+.2f}% | {positive_w} | {len(w_alphas) - positive_w} |")
        if m_alphas:
            lines.append(f"| M | {_percentile(m_alphas, 50):+.2f}% | {positive_m} | {len(m_alphas) - positive_m} |")
        lines.append("")
        lines.append("### 最强策略分布")
        lines.append("")
        total_best = d_winners + w_winners + m_winners
        if total_best > 0:
            lines.append(f"- D 是最强：{d_winners} 个（{d_winners / total_best * 100:.1f}%）")
            lines.append(f"- W 是最强：{w_winners} 个（{w_winners / total_best * 100:.1f}%）")
            lines.append(f"- M 是最强：{m_winners} 个（{m_winners / total_best * 100:.1f}%）")
        lines.append("")
        lines.append("### 综合 alpha")
        lines.append("")
        lines.append(f"- 最大 best alpha：{max(best_alphas):+.2f}%")
        lines.append(f"- 中位：{_percentile(best_alphas, 50):+.2f}%")
        lines.append(f"- 最小：{min(best_alphas):+.2f}%")
        lines.append(f"- best alpha > 0 的行业：{sum(1 for a in best_alphas if a > 0)} 个")
        lines.append(f"- best alpha > +50% 的行业：{sum(1 for a in best_alphas if a > 50)} 个")
        lines.append(f"- best alpha > +100% 的行业：{sum(1 for a in best_alphas if a > 100)} 个")
        lines.append("")

    # 三、各行业完整成绩（按代码升序）
    lines.append("## 三、各行业完整成绩（按代码升序）")
    lines.append("")
    lines.append("| 代码 | 行业 | σ | B&H 收益 | B&H CAGR | D 收益 | D alpha | D Calmar | D 交易 | W 收益 | W alpha | M 收益 | M alpha | 最强 | best α | Calmar 权重 D/W/M |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for m in sorted(metrics, key=lambda x: x.code):
        d_w = m.calmar_weights.get("D", 0)
        w_w = m.calmar_weights.get("W", 0)
        m_w = m.calmar_weights.get("M", 0)

        def fw(x):
            return f"{x * 100:.0f}%" if x > 0 else "0"

        weights_str = f"{fw(d_w)}/{fw(w_w)}/{fw(m_w)}"

        lines.append(
            f"| {m.code} | {m.name} | {m.annual_volatility:.1f}% "
            f"| {_fmt_pct(m.bh_total_return)} | {_fmt_pct(m.bh_cagr)} "
            f"| {_fmt_pct(m.d_total_return)} | {_fmt_pct(m.d_alpha)} | {_fmt_num(m.d_calmar, 3)} "
            f"| {m.d_trade_count if m.d_trade_count is not None else '-'} "
            f"| {_fmt_pct(m.w_total_return)} | {_fmt_pct(m.w_alpha)} "
            f"| {_fmt_pct(m.m_total_return)} | {_fmt_pct(m.m_alpha)} "
            f"| **{m.best_strategy}** | **{_fmt_pct(m.best_alpha)}** | {weights_str} |"
        )

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("**字段说明**：")
    lines.append("- σ：年化波动率（基于评估区间日 log 收益率，× √252）")
    lines.append("- alpha：策略总收益 − B&H 总收益")
    lines.append("- Calmar：CAGR / |最大回撤|")
    lines.append("- 最强：D/W/M 中 alpha 最大的策略")
    lines.append("- Calmar 权重：V4.1 算法计算的 D/W/M 之间分配比例（用于实战时把单指数 $10k 切给三策略）")
    return "\n".join(lines)


def filter_tiny_candidates(metrics: List[SectorMetrics]) -> Tuple[List[SectorMetrics], List[SectorMetrics]]:
    """筛选精选候选行业。返回 (selected, overflow)。

    规则（同时满足）：
        σ ≥ TINY_MIN_SIGMA
        best alpha ≥ TINY_MIN_ALPHA
        best Calmar ≥ TINY_MIN_CALMAR
        best 总收益 > 0

    强制纳入：FORCE_INCLUDE_CODES（绕过硬门槛）

    排序：按 composite = best_alpha × best_calmar 降序，取前 TINY_MAX_COUNT 个。
    强制纳入的优先占位。
    """
    forced: List[SectorMetrics] = [m for m in metrics if m.code in FORCE_INCLUDE_CODES]

    passed: List[SectorMetrics] = []
    for m in metrics:
        if m.code in FORCE_INCLUDE_CODES:
            continue  # 已在 forced 列表里
        if m.annual_volatility < TINY_MIN_SIGMA:
            continue
        if m.best_alpha < TINY_MIN_ALPHA:
            continue
        if m.best_calmar < TINY_MIN_CALMAR:
            continue
        if m.best_return <= 0:
            continue
        passed.append(m)

    passed.sort(key=lambda m: -(m.best_alpha * m.best_calmar))

    # 强制纳入优先占位
    available_slots = max(0, TINY_MAX_COUNT - len(forced))
    selected = forced + passed[:available_slots]
    overflow = passed[available_slots:]

    # 最终展示按 composite 排序（强制纳入项也参与排序，方便阅读）
    selected.sort(key=lambda m: -(m.best_alpha * m.best_calmar))
    return selected, overflow


def render_v5_tiny_result(
    selected: List[SectorMetrics],
    overflow: List[SectorMetrics],
    all_metrics: List[SectorMetrics],
) -> str:
    """渲染精选 ≤ 20 个候选行业的结果文档。"""
    lines: List[str] = []
    lines.append("# V5 精选行业（Tiny Result · 用于后续详细验证）")
    lines.append("")
    lines.append("> 从 90 个 THS 一级行业中按硬指标筛选，按 composite = best_alpha × best_calmar 排序")
    lines.append(f"> 入选：**{len(selected)}** 个 / 候选总数：{len(selected) + len(overflow)} 个 / 全样本 {len(all_metrics)} 个")
    lines.append("")

    # 一、筛选标准
    lines.append("## 一、筛选标准")
    lines.append("")
    lines.append("**硬门槛（同时满足）**：")
    lines.append("")
    lines.append(f"| 维度 | 门槛 | 含义 |")
    lines.append(f"|---|---|---|")
    lines.append(f"| 年化波动率 σ | ≥ {TINY_MIN_SIGMA}% | 高于全样本中位数（28.85%），保证策略有信号空间 |")
    lines.append(f"| best alpha | ≥ +{TINY_MIN_ALPHA}% | 策略显著跑赢 B&H，不是边际优势 |")
    lines.append(f"| best Calmar | ≥ {TINY_MIN_CALMAR} | 风险调整后收益有效，避免高 alpha 但高回撤的伪强 |")
    lines.append("| best 总收益 | > 0 | 绝对值不能亏（避免「垃圾里挑最不烂的」） |")
    lines.append("")
    lines.append(f"**排序**：composite = best_alpha × best_calmar 降序")
    lines.append("")
    lines.append(f"**容量**：最多 {TINY_MAX_COUNT} 个")
    lines.append("")

    # 二、入选行业（核心表）
    forced_codes = FORCE_INCLUDE_CODES
    forced_in_selected = [m for m in selected if m.code in forced_codes]
    lines.append(f"## 二、入选行业（Top {len(selected)}）")
    lines.append("")
    if forced_in_selected:
        lines.append(
            f"> ⚠ 含 {len(forced_in_selected)} 个**强制纳入**项："
            f"{' / '.join(f'{m.name}({m.code})' for m in forced_in_selected)}"
            f"（绕过硬门槛，详见下文标记）"
        )
        lines.append("")
    lines.append("| 排名 | 行业(代码) | σ | best 策略 | best 总收益 | B&H | best alpha | Calmar | composite | Calmar 权重 D/W/M | 备注 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for rank, m in enumerate(selected, 1):
        composite = m.best_alpha * m.best_calmar
        d_w = m.calmar_weights.get("D", 0)
        w_w = m.calmar_weights.get("W", 0)
        m_w = m.calmar_weights.get("M", 0)

        def fw(x):
            return f"{x * 100:.0f}%" if x > 0 else "0"

        note = "🔧 强制纳入" if m.code in forced_codes else ""

        lines.append(
            f"| {rank} | {m.name}({m.code}) | {m.annual_volatility:.1f}% "
            f"| **{m.best_strategy}** | {_fmt_pct(m.best_return)} "
            f"| {_fmt_pct(m.bh_total_return)} "
            f"| **{_fmt_pct(m.best_alpha)}** | {_fmt_num(m.best_calmar, 3)} "
            f"| **{composite:.1f}** | {fw(d_w)}/{fw(w_w)}/{fw(m_w)} | {note} |"
        )
    lines.append("")

    # 三、入选行业类别分布
    lines.append("## 三、入选行业的类别分布")
    lines.append("")
    # 简单语义聚类（基于行业名）
    clusters = {
        "新能源链（光伏/风电/电池/电源）": ["光伏设备", "风电设备", "电池", "其他电源设备", "电网设备", "电机"],
        "金属资源（小金属/能源金属/有色）": ["能源金属", "小金属", "贵金属", "工业金属", "金属新材料"],
        "医疗（医疗服务/器械/中药）": ["医疗服务", "医疗器械", "化学制药", "生物制品", "中药"],
        "消费（白酒/饮料/家电）": ["白酒", "饮料制造", "小家电", "家居用品", "服装家纺"],
        "军工": ["军工电子", "军工装备"],
        "通信/科技": ["通信设备", "通信服务", "软件开发", "IT服务", "半导体", "元件"],
        "汽车": ["汽车整车", "汽车零部件"],
        "机械装备": ["通用设备", "专用设备", "自动化设备", "工程机械"],
        "周期（油气/煤炭/化工）": ["油气开采及服务", "煤炭开采加工", "化学制品", "化学原料", "农化制品"],
    }
    cluster_count = {}
    cluster_members = {}
    for c_name in clusters:
        cluster_members[c_name] = []
    cluster_members["其他"] = []
    for m in selected:
        matched = False
        for c_name, c_keywords in clusters.items():
            if m.name in c_keywords:
                cluster_members[c_name].append(m.name)
                matched = True
                break
        if not matched:
            cluster_members["其他"].append(m.name)

    lines.append("| 类别 | 入选数 | 入选行业 |")
    lines.append("|---|---|---|")
    for c_name, members in cluster_members.items():
        if members:
            lines.append(f"| {c_name} | {len(members)} | {' · '.join(members)} |")
    lines.append("")
    lines.append("> **观察**：入选行业明显集中在**新能源链 + 金属资源 + 医疗 + 消费**四大主题，符合「高波动 + 趋势分明」的策略适用画像。银行/证券/保险/红利/煤炭等低波动板块全部出局。")
    lines.append("")

    # 四、最强策略统计
    d_count = sum(1 for m in selected if m.best_strategy == "D")
    w_count = sum(1 for m in selected if m.best_strategy == "W")
    m_count = sum(1 for m in selected if m.best_strategy == "M")
    lines.append("## 四、入选行业的最强策略分布")
    lines.append("")
    lines.append(f"- D（日线）：{d_count} 个（{d_count / len(selected) * 100:.1f}%）")
    lines.append(f"- W（周线）：{w_count} 个（{w_count / len(selected) * 100:.1f}%）")
    lines.append(f"- M（月线）：{m_count} 个（{m_count / len(selected) * 100:.1f}%）")
    lines.append("")
    lines.append("> 与全样本（D 81% / W 1% / M 18%）相比，精选行业的最强策略分布**更偏向 D**，说明「高波动 + 趋势剧烈反转」的板块特别适合日线信号。")
    lines.append("")

    # 五、被淘汰但接近门槛的"边缘候选"（如有 overflow 或排名 21-30）
    lines.append(f"## 五、未入选但通过硬门槛的候选")
    lines.append("")
    if overflow:
        lines.append(f"共 {len(overflow)} 个，按 composite 降序。如果未来想扩展容量，可从这里依次纳入：")
        lines.append("")
        lines.append("| 行业(代码) | σ | best 策略 | best alpha | Calmar | composite |")
        lines.append("|---|---|---|---|---|---|")
        for m in overflow:
            composite = m.best_alpha * m.best_calmar
            lines.append(
                f"| {m.name}({m.code}) | {m.annual_volatility:.1f}% "
                f"| {m.best_strategy} | {_fmt_pct(m.best_alpha)} "
                f"| {_fmt_num(m.best_calmar, 3)} | {composite:.1f} |"
            )
        lines.append("")
    else:
        lines.append("**无**——所有通过硬门槛的候选均已入选（候选总数 ≤ 上限 20）。")
        lines.append("")

    # 六、近门槛被剔除（仅展示典型）
    near_misses: List[Tuple[str, SectorMetrics]] = []
    for m in all_metrics:
        if m in selected or m in overflow:
            continue
        # 仅 1 项不达标（视为接近）
        fails = []
        if m.annual_volatility < TINY_MIN_SIGMA:
            fails.append(f"σ {m.annual_volatility:.1f}% < {TINY_MIN_SIGMA}%")
        if m.best_alpha < TINY_MIN_ALPHA:
            fails.append(f"alpha {m.best_alpha:+.1f}% < +{TINY_MIN_ALPHA}%")
        if m.best_calmar < TINY_MIN_CALMAR:
            fails.append(f"Calmar {m.best_calmar:.2f} < {TINY_MIN_CALMAR}")
        if m.best_return <= 0:
            fails.append(f"best 总收益 {m.best_return:.1f}% ≤ 0")
        if len(fails) == 1:
            near_misses.append((fails[0], m))

    if near_misses:
        # 按 composite 降序取 Top 10
        near_misses.sort(key=lambda x: -(x[1].best_alpha * x[1].best_calmar))
        lines.append("## 六、近门槛被剔除（Top 10，仅 1 项不达标）")
        lines.append("")
        lines.append("| 行业(代码) | σ | best alpha | Calmar | 不达标原因 |")
        lines.append("|---|---|---|---|---|")
        for reason, m in near_misses[:10]:
            lines.append(
                f"| {m.name}({m.code}) | {m.annual_volatility:.1f}% "
                f"| {_fmt_pct(m.best_alpha)} | {_fmt_num(m.best_calmar, 3)} | {reason} |"
            )
        lines.append("")
        lines.append("> 这些行业其它指标 OK 但卡在某 1 项门槛上。如果未来发现门槛设置过严，可松动重新筛选。")
        lines.append("")

    # 七、后续建议
    lines.append("## 七、后续详细验证方向（V6 候选）")
    lines.append("")
    lines.append("基于本轮选定行业，下一步可以做：")
    lines.append("")
    lines.append("1. **多窗口组合回测**（参考 V4.2 框架）：跑 3/5/8/10 年这 ~20 个行业的组合表现")
    lines.append("2. **相关性聚类去重**：光伏/风电/电池/能源金属高度相关，可能需要每簇保留 1 个代表")
    lines.append("3. **交易成本仿真**：按真实佣金/印花税扣减，看净收益是否仍能维持 alpha")
    lines.append("4. **晚熊验证**：单独跑 2021-2023 大熊市这段，看策略在熊市中是否真能压低回撤")
    return "\n".join(lines)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s - %(message)s")

    registry = build_v5_registry()
    total = len(registry)
    logger.info("V5 样本池：%d 个 THS 一级行业", total)

    metrics: List[SectorMetrics] = []
    failed: List[Tuple[str, str, str]] = []

    for i, meta in enumerate(registry, start=1):
        logger.info("[%d/%d] %s %s", i, total, meta.code, meta.name)
        try:
            sm = screen_sector(meta)
        except Exception as e:
            logger.error("  异常：%s", e)
            failed.append((meta.code, meta.name, f"异常：{str(e)[:80]}"))
            continue
        if sm is None:
            failed.append((meta.code, meta.name, "数据为空或回测失败"))
            continue
        metrics.append(sm)
        logger.info(
            "  σ=%.2f%% best=%s α=%+.2f%% Calmar=%.3f",
            sm.annual_volatility, sm.best_strategy, sm.best_alpha, sm.best_calmar,
        )

    logger.info("成功 %d / 失败 %d", len(metrics), len(failed))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render_v5_result(metrics, failed), encoding="utf-8")
    logger.info("已产出 %s", OUTPUT)

    SUMMARY_OUTPUT.write_text(render_v5_summary(metrics, failed), encoding="utf-8")
    logger.info("已产出 %s", SUMMARY_OUTPUT)

    selected, overflow = filter_tiny_candidates(metrics)
    TINY_OUTPUT.write_text(render_v5_tiny_result(selected, overflow, metrics), encoding="utf-8")
    logger.info("已产出 %s（入选 %d / 候选 %d）", TINY_OUTPUT, len(selected), len(selected) + len(overflow))
    return 0


if __name__ == "__main__":
    sys.exit(main())
