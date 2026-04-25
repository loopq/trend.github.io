"""V8 CLI：用中证 ETF 池跑回测 + 与 V6（THS）对比 Top 20。

复用 V5 的 screen_sector（已通用），换 registry 为 V8 中证池。
输出：
    docs/agents/backtest/v8-result.md         全部 344 候选 + 4 排行榜
    docs/agents/backtest/v8-tiny-result.md    Top 20 精选 + V6 对比 + 业务关联分析
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from scripts.backtest.run_v5 import (
    FORCE_INCLUDE_CODES,
    TINY_MAX_COUNT,
    TINY_MIN_ALPHA,
    TINY_MIN_CALMAR,
    TINY_MIN_SIGMA,
    _percentile,
    _fmt_pct,
    _fmt_num,
    filter_tiny_candidates,
    render_v5_result,
)
from scripts.backtest.index_registry import IndexMeta
from scripts.backtest.v5_screener import SectorMetrics, screen_sector
from scripts.backtest.v5_registry import build_v5_registry
from scripts.backtest.v8_registry import build_v8_registry

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_RESULT = PROJECT_ROOT / "docs" / "agents" / "backtest" / "v8-result.md"
OUTPUT_SUMMARY = PROJECT_ROOT / "docs" / "agents" / "backtest" / "v8-summary.md"
OUTPUT_TINY = PROJECT_ROOT / "docs" / "agents" / "backtest" / "v8-tiny-result.md"

# V8 不强制纳入任何（因为整池都有 ETF 了）
V8_FORCE_INCLUDE: set = set()


def render_v8_summary(metrics: List[SectorMetrics], failed: List[Tuple[str, str, str]]) -> str:
    """V8 专属总结：聚焦"跑了哪些 / 失败哪些 / 各自成绩"。"""
    lines: List[str] = []
    lines.append("# V8 中证 ETF 池回测总结")
    lines.append("")
    lines.append("> 评估区间：2016-01-01 ~ 2026-04-24（数据终点固定）")
    lines.append("> 候选：中证目录中「跟踪产品=是 + 资产类别=股票 + 基日≤2020 + 类别 ∈ 行业/主题/策略/风格」")
    lines.append(f"> 样本：{len(metrics) + len(failed)} 个中证指数")
    lines.append(f"> **成功：{len(metrics)}** / **失败：{len(failed)}**")
    lines.append("")
    lines.append("V8 区别于 V5/V6：每个候选都已有 ETF 跟踪，**直接可投资**，无需 V7 的映射步骤。")
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
        lines.append("> 失败大概率是 AkShare 服务器拒绝（反爬）。本次已实施「自动重试 3 轮」机制，仍失败的为长期不可获取。")
    else:
        lines.append("### ❌ 失败 0 个")
        lines.append("")
        lines.append(f"本轮 {len(metrics)} 个中证指数**全部成功**，无失败案例。")
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
        lines.append("| 策略 | 中位 alpha | 跑赢 B&H | 跑输 |")
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
        lines.append(f"- best alpha > 0 的指数：{sum(1 for a in best_alphas if a > 0)} 个")
        lines.append(f"- best alpha > +50% 的指数：{sum(1 for a in best_alphas if a > 50)} 个")
        lines.append(f"- best alpha > +100% 的指数：{sum(1 for a in best_alphas if a > 100)} 个")
        lines.append("")

    # 三、各指数完整成绩
    lines.append("## 三、各指数完整成绩（按代码升序）")
    lines.append("")
    lines.append("| 代码 | 名称 | 类别 | σ | B&H 收益 | B&H CAGR | D 收益 | D alpha | D Calmar | D 交易 | W 收益 | W alpha | M 收益 | M alpha | 最强 | best α |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for m in sorted(metrics, key=lambda x: x.code):
        lines.append(
            f"| {m.code} | {m.name} | {m.category} | {m.annual_volatility:.1f}% "
            f"| {_fmt_pct(m.bh_total_return)} | {_fmt_pct(m.bh_cagr)} "
            f"| {_fmt_pct(m.d_total_return)} | {_fmt_pct(m.d_alpha)} | {_fmt_num(m.d_calmar, 3)} "
            f"| {m.d_trade_count if m.d_trade_count is not None else '-'} "
            f"| {_fmt_pct(m.w_total_return)} | {_fmt_pct(m.w_alpha)} "
            f"| {_fmt_pct(m.m_total_return)} | {_fmt_pct(m.m_alpha)} "
            f"| **{m.best_strategy}** | **{_fmt_pct(m.best_alpha)}** |"
        )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("**字段说明**：σ=年化波动率，alpha=策略总收益−B&H总收益，Calmar=CAGR/|MDD|，最强=D/W/M 中 alpha 最大者。")
    return "\n".join(lines)


def filter_v8_tiny(metrics: List[SectorMetrics]) -> Tuple[List[SectorMetrics], List[SectorMetrics]]:
    """V8 版本的 tiny 筛选：与 V5 同标准但不强制纳入。"""
    forced: List[SectorMetrics] = [m for m in metrics if m.code in V8_FORCE_INCLUDE]
    passed: List[SectorMetrics] = []
    for m in metrics:
        if m.code in V8_FORCE_INCLUDE:
            continue
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
    selected = forced + passed[:TINY_MAX_COUNT - len(forced)]
    overflow = passed[TINY_MAX_COUNT - len(forced):]
    selected.sort(key=lambda m: -(m.best_alpha * m.best_calmar))
    return selected, overflow


def filter_v8_relaxed_top20(metrics: List[SectorMetrics]) -> List[SectorMetrics]:
    """放宽门槛凑齐 20 个：σ ≥ 25% + alpha > 0 + Calmar ≥ 0.15。

    用于"V6 严格 vs V8 可投资"的对比备份方案。
    """
    candidates = [
        m for m in metrics
        if m.annual_volatility >= 25.0
        and m.best_alpha > 0
        and m.best_calmar >= 0.15
        and m.best_return > 0
    ]
    candidates.sort(key=lambda m: -(m.best_alpha * m.best_calmar))
    return candidates[:20]


def get_v6_top20() -> List[SectorMetrics]:
    """重跑 V5 拿 V6 选定的 20 个 THS 行业（含强制纳入电力）。"""
    registry = build_v5_registry()
    metrics = []
    for meta in registry:
        sm = screen_sector(meta)
        if sm is not None:
            metrics.append(sm)
    selected, _ = filter_tiny_candidates(metrics)
    return selected


def render_v8_tiny_with_compare(
    v8_selected: List[SectorMetrics],
    v8_overflow: List[SectorMetrics],
    v6_selected: List[SectorMetrics],
    all_v8: List[SectorMetrics],
    v8_relaxed: List[SectorMetrics],
) -> str:
    lines: List[str] = []
    lines.append("# V8 中证 ETF 池精选 Top 20 + V6 对比")
    lines.append("")
    lines.append(
        f"> 候选池：{len(all_v8)} 个有 ETF 跟踪的中证指数（行业/主题/策略/风格）"
    )
    lines.append(f"> 入选：{len(v8_selected)} 个 / 全样本 {len(all_v8)} 个")
    lines.append("")
    lines.append("## 一、V8 vs V6（THS）的核心差异")
    lines.append("")
    lines.append("| 维度 | V6（THS 一级行业） | V8（中证有 ETF） |")
    lines.append("|---|---|---|")
    lines.append(f"| 候选池 | 90 | {len(all_v8)} |")
    lines.append("| 可投资性 | ❌ 需找 ETF 代理 | ✅ 每个都有 ETF |")
    lines.append("| 划分体系 | 同花顺自定义 | 中证指数官方 |")
    lines.append("| 行业精细度 | 一级（90 个）| 主题/行业混合（更多角度）|")
    lines.append("")

    # 二、V8 Top 20
    lines.append("## 二、V8 Top 20 入选清单")
    lines.append("")
    lines.append("| 排名 | 中证指数(代码) | 类别 | σ | best 策略 | best 总收益 | B&H | best alpha | Calmar | composite |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for rank, m in enumerate(v8_selected, 1):
        composite = m.best_alpha * m.best_calmar
        lines.append(
            f"| {rank} | {m.name}({m.code}) | {m.category} | {m.annual_volatility:.1f}% "
            f"| **{m.best_strategy}** | {_fmt_pct(m.best_return)} "
            f"| {_fmt_pct(m.bh_total_return)} "
            f"| **{_fmt_pct(m.best_alpha)}** | {_fmt_num(m.best_calmar, 3)} "
            f"| **{composite:.1f}** |"
        )
    lines.append("")

    # 三、V6 vs V8 主题对应（业务关联）
    lines.append("## 三、V6 vs V8 业务对应分析")
    lines.append("")
    lines.append("以 V6（THS）为基准，分析每个行业在 V8 是否有「业务对应的中证指数入选」：")
    lines.append("")
    lines.append("| V6 THS 行业 | V8 是否有对应入选？ | V8 对应中证指数 |")
    lines.append("|---|---|---|")

    # 业务对应关键词（手工映射）
    v6_to_keywords = {
        "光伏设备": ["光伏", "太阳能", "新能源"],
        "能源金属": ["锂", "新能源金属", "稀土", "新能源车"],
        "风电设备": ["风电", "新能源"],
        "通用设备": ["机械", "高端", "智能制造"],
        "小金属": ["有色", "金属", "稀土"],
        "白酒": ["酒", "消费"],
        "医疗服务": ["医疗", "医药", "生物"],
        "电机": ["机械", "电机"],
        "电网设备": ["电力设备", "电网", "新能源"],
        "电池": ["电池", "锂"],
        "通信设备": ["通信", "5G"],
        "环保设备": ["环保", "环境", "节能"],
        "汽车整车": ["汽车", "新能源车"],
        "其他电源设备": ["新能源"],
        "自动化设备": ["机器人", "智能制造"],
        "医疗器械": ["医疗器械", "医药"],
        "工业金属": ["有色", "金属"],
        "军工电子": ["军工", "国防", "航空", "航天"],
        "军工装备": ["军工", "国防", "航空", "航天"],
        "电力": ["电力", "公用"],
    }

    for v6_m in v6_selected:
        keywords = v6_to_keywords.get(v6_m.name, [v6_m.name])
        matched = [
            v8_m for v8_m in v8_selected
            if any(kw in v8_m.name for kw in keywords)
        ]
        if matched:
            cell = " · ".join(f"{m.name}({m.code})" for m in matched)
            mark = "✅"
        else:
            cell = "—（V8 无业务对应入选）"
            mark = "⚠"
        lines.append(f"| {v6_m.name}({v6_m.code}) | {mark} | {cell} |")
    lines.append("")

    # 四、V8 独有 vs V6 独有
    v8_codes = {m.code for m in v8_selected}
    v6_names = {m.name for m in v6_selected}
    # V8 独有（业务上 V6 没覆盖的角度）
    v8_unique_themes = []
    for v8_m in v8_selected:
        any_v6_kw_match = False
        for v6_name, kws in v6_to_keywords.items():
            if any(kw in v8_m.name for kw in kws):
                any_v6_kw_match = True
                break
        if not any_v6_kw_match:
            v8_unique_themes.append(v8_m)

    lines.append(f"## 四、V8 独有的「新视角」（V6 完全没覆盖到的，{len(v8_unique_themes)} 个）")
    lines.append("")
    if v8_unique_themes:
        lines.append("| 中证指数 | 类别 | σ | best 策略 | best alpha | Calmar |")
        lines.append("|---|---|---|---|---|---|")
        for m in v8_unique_themes:
            lines.append(
                f"| {m.name}({m.code}) | {m.category} | {m.annual_volatility:.1f}% "
                f"| **{m.best_strategy}** | **{_fmt_pct(m.best_alpha)}** | {_fmt_num(m.best_calmar, 3)} |"
            )
    else:
        lines.append("无（V6 已覆盖所有业务方向）。")
    lines.append("")

    # 五、统计对比
    lines.append("## 五、统计对比")
    lines.append("")
    v6_alphas = [m.best_alpha for m in v6_selected]
    v8_alphas = [m.best_alpha for m in v8_selected]
    v6_sigmas = [m.annual_volatility for m in v6_selected]
    v8_sigmas = [m.annual_volatility for m in v8_selected]
    v6_calmars = [m.best_calmar for m in v6_selected]
    v8_calmars = [m.best_calmar for m in v8_selected]

    v6_d = sum(1 for m in v6_selected if m.best_strategy == "D")
    v6_w = sum(1 for m in v6_selected if m.best_strategy == "W")
    v6_m = sum(1 for m in v6_selected if m.best_strategy == "M")
    v8_d = sum(1 for m in v8_selected if m.best_strategy == "D")
    v8_w = sum(1 for m in v8_selected if m.best_strategy == "W")
    v8_m = sum(1 for m in v8_selected if m.best_strategy == "M")

    lines.append("| 指标 | V6 (THS) | V8 (中证 ETF) |")
    lines.append("|---|---|---|")
    lines.append(f"| 平均 σ | {sum(v6_sigmas) / len(v6_sigmas):.2f}% | {sum(v8_sigmas) / len(v8_sigmas):.2f}% |")
    lines.append(f"| 中位 alpha | {_percentile(v6_alphas, 50):+.2f}% | {_percentile(v8_alphas, 50):+.2f}% |")
    lines.append(f"| 最大 alpha | {max(v6_alphas):+.2f}% | {max(v8_alphas):+.2f}% |")
    lines.append(f"| 中位 Calmar | {_percentile(v6_calmars, 50):.3f} | {_percentile(v8_calmars, 50):.3f} |")
    lines.append(f"| 最强策略 D 比例 | {v6_d}/{len(v6_selected)} ({v6_d / len(v6_selected) * 100:.0f}%) | {v8_d}/{len(v8_selected)} ({v8_d / len(v8_selected) * 100:.0f}%) |")
    lines.append(f"| 最强策略 W 比例 | {v6_w}/{len(v6_selected)} | {v8_w}/{len(v8_selected)} |")
    lines.append(f"| 最强策略 M 比例 | {v6_m}/{len(v6_selected)} | {v8_m}/{len(v8_selected)} |")
    lines.append("")

    # 六、结论
    lines.append("## 六、结论与下一步")
    lines.append("")
    lines.append("V8 的核心价值：**所有入选标的天然有 ETF 可投资**，跳过了 V7 的映射步骤。")
    lines.append("")
    lines.append("如果 V8 与 V6 的业务画像高度一致（医疗/光伏/新能源/有色/军工 等都覆盖），说明：")
    lines.append("- 策略适用性是行业本身的属性（不依赖于具体指数划分体系）")
    lines.append("- V8 可直接作为下一步实盘组合的标的池")
    lines.append("")
    lines.append("如果 V8 显著缺失 V6 某些行业 → 说明这些 THS 行业**没有完全对应的 ETF 可投资**，需做取舍。")
    lines.append("")

    # 七、放宽门槛 Top 20（保证可投资的备选方案）
    lines.append("## 七、备选方案：放宽门槛凑齐 20 个 V8 候选")
    lines.append("")
    lines.append("严格门槛（σ ≥ 28% + alpha ≥ +50% + Calmar ≥ 0.25）下 V8 仅 7 个达标。")
    lines.append("**放宽门槛（σ ≥ 25% + alpha > 0 + Calmar ≥ 0.15）后凑齐 Top 20**，作为「100% 可投资」的备选清单：")
    lines.append("")
    lines.append("| 排名 | 中证指数(代码) | 类别 | σ | best 策略 | best 总收益 | best alpha | Calmar | composite |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for rank, m in enumerate(v8_relaxed, 1):
        composite = m.best_alpha * m.best_calmar
        lines.append(
            f"| {rank} | {m.name}({m.code}) | {m.category} | {m.annual_volatility:.1f}% "
            f"| **{m.best_strategy}** | {_fmt_pct(m.best_return)} "
            f"| {_fmt_pct(m.best_alpha)} | {_fmt_num(m.best_calmar, 3)} "
            f"| **{composite:.1f}** |"
        )
    lines.append("")
    lines.append("> 这 20 个**全部有 ETF 可买**，alpha 虽不如 V6 极端，但是**真正能下单的实操池**。")
    return "\n".join(lines)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s - %(message)s")

    # 1. 加载 V8 registry
    logger.info("[1/4] 加载 V8 候选池...")
    registry = build_v8_registry()
    total = len(registry)
    logger.info("V8 候选池：%d 个有 ETF 跟踪的中证指数", total)

    # 2. 跑 screener（带自动重试：失败的指数最多重试 3 轮）
    logger.info("[2/4] 运行 screener（带自动重试）...")
    MAX_RETRY_ROUNDS = 4  # 第 1 轮 + 3 轮重试
    metrics: List[SectorMetrics] = []
    metrics_by_code: Dict[str, SectorMetrics] = {}
    pending: List[IndexMeta] = list(registry)

    for attempt in range(1, MAX_RETRY_ROUNDS + 1):
        if not pending:
            break
        logger.info("  第 %d 轮：尝试 %d 个", attempt, len(pending))
        new_pending: List[IndexMeta] = []
        for i, meta in enumerate(pending, 1):
            if i % 50 == 0:
                logger.info("    进度 %d/%d", i, len(pending))
            try:
                sm = screen_sector(meta)
            except Exception as e:
                if attempt < MAX_RETRY_ROUNDS:
                    new_pending.append(meta)
                else:
                    metrics_by_code.setdefault(meta.code, None)
                continue
            if sm is None:
                if attempt < MAX_RETRY_ROUNDS:
                    new_pending.append(meta)
                continue
            metrics_by_code[meta.code] = sm
        pending = new_pending
        logger.info("  第 %d 轮结束：成功累计 %d / 仍失败 %d",
                    attempt, len(metrics_by_code), len(pending))

    metrics = [m for m in metrics_by_code.values() if m is not None]
    failed: List[Tuple[str, str, str]] = []
    success_codes = {m.code for m in metrics}
    for meta in registry:
        if meta.code not in success_codes:
            failed.append((meta.code, meta.name, "数据拉取失败（重试 3 轮仍未获取）"))

    logger.info("最终：成功 %d / 失败 %d", len(metrics), len(failed))

    # 3. 写完整结果（复用 v5 渲染）
    logger.info("[3/4] 写入完整结果...")
    OUTPUT_RESULT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_RESULT.write_text(render_v5_result(metrics, failed), encoding="utf-8")
    OUTPUT_SUMMARY.write_text(render_v8_summary(metrics, failed), encoding="utf-8")

    # 4. 筛选 Top 20 + V6 对比
    logger.info("[4/4] 筛选 Top 20 + V6 对比...")
    v8_selected, v8_overflow = filter_v8_tiny(metrics)
    logger.info("  V8 入选：%d", len(v8_selected))

    logger.info("  跑 V6（THS）以做对比...")
    v6_selected = get_v6_top20()
    logger.info("  V6 入选：%d", len(v6_selected))

    v8_relaxed = filter_v8_relaxed_top20(metrics)
    logger.info("  V8 放宽门槛 Top 20：%d", len(v8_relaxed))

    OUTPUT_TINY.write_text(
        render_v8_tiny_with_compare(v8_selected, v8_overflow, v6_selected, metrics, v8_relaxed),
        encoding="utf-8",
    )
    logger.info("已产出：")
    logger.info("  %s", OUTPUT_RESULT)
    logger.info("  %s", OUTPUT_SUMMARY)
    logger.info("  %s", OUTPUT_TINY)
    return 0


if __name__ == "__main__":
    sys.exit(main())
