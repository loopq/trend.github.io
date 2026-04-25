"""V9.2 详细报告：仿照 summary.md 出总览 + 每个指数单独 md。

输出：
    docs/agents/backtest/v9-summary.md    总览（14 指数排行 + 推荐组合）
    docs/agents/backtest/v9-{code}.md     × 14（每指数年度+Calmar+交易日志）

不覆盖之前的 v9-manual-result.md（V9 多窗口报告保留）。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Dict, List

import pandas as pd

from scripts.backtest.data_loader import load_index
from scripts.backtest.engine import BacktestResult, run_strategy
from scripts.backtest.reporter import compute_allocation, render_index_report
from scripts.backtest.strategies import all_strategies
from scripts.backtest.v9_registry import build_v9_registry

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = PROJECT_ROOT / "docs" / "agents" / "backtest"
SUMMARY_OUTPUT = OUTPUT_DIR / "v9-summary.md"

MIN_EVALUATION_START = pd.Timestamp("2016-01-01")


def _fmt_pct(v) -> str:
    if v is None:
        return "-"
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.2f}%"


def _fmt_money(v) -> str:
    return f"${v:,.2f}"


def _fmt_num(v, digits: int = 3) -> str:
    if v is None:
        return "-"
    return f"{v:.{digits}f}"


def render_v9_summary(
    full_results_by_code: Dict[str, List[BacktestResult]],
    calmar_by_code: Dict[str, Dict],
    sigma_by_code: Dict[str, float],
) -> str:
    """仿照 V4 summary.md 出 V9.2 总览。"""
    lines: List[str] = []
    lines.append("# V9.2 手动精选 14 指数完整总结")
    lines.append("")
    lines.append("> 14 个手动精选指数（V9.2 版，已移除 中证500/中证1000/电力 三个低波动腰部）")
    lines.append("> 评估区间：2016-01-01 ~ 2026-04-24")
    lines.append("> 数据终点：2026-04-24 收盘 · 缓存机制保证可重现")
    lines.append("")

    # 一、样本概览
    lines.append("## 一、样本概览")
    lines.append("")
    lines.append(f"- 候选池：14 个指数（用户手动精选）")
    lines.append(f"- 数据成功：{len(full_results_by_code)} / 14")
    lines.append(f"- 策略：D / W / M（单周期独立，各 $10k 起步，按 V4.1 Calmar 权重内部分配）")
    lines.append(f"- 数据源：cs_index（中证）/ sina_index（深交所国证）/ ths_industry（同花顺）")
    lines.append("")

    # 二、单指数成绩榜（按 best alpha 降序）
    lines.append("## 二、单指数成绩榜（按 best alpha 降序）")
    lines.append("")
    lines.append("| 排名 | 指数(代码) | 类别 | σ | best 策略 | best 总收益 | B&H 收益 | **best alpha** | best Calmar | 详细 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")

    rows = []
    for code, results in full_results_by_code.items():
        first = results[0]
        # 算各指标
        by_n = {r.strategy_name: r for r in results}
        d = by_n.get("D")
        w = by_n.get("W")
        m = by_n.get("M")

        bh_total = first.bh_total_return
        d_alpha = (d.total_return - bh_total) if d else None
        w_alpha = (w.total_return - bh_total) if w else None
        m_alpha = (m.total_return - bh_total) if m else None

        candidates = [(n, a, by_n[n]) for n, a in [("D", d_alpha), ("W", w_alpha), ("M", m_alpha)] if a is not None]
        if not candidates:
            continue
        best_name, best_alpha_val, best_r = max(candidates, key=lambda x: x[1])
        best_calmar = (best_r.annualized_return / max(abs(best_r.max_drawdown), 0.1)) if best_r.max_drawdown else 0

        sigma = sigma_by_code.get(code)
        rows.append((code, first.index_name, first.index_category, sigma,
                     best_name, best_r.total_return, bh_total, best_alpha_val, best_calmar))

    rows.sort(key=lambda r: -r[7])  # 按 alpha 降序
    for rank, (code, name, cat, sigma, bn, br_total, bh_total, alpha, calmar) in enumerate(rows, 1):
        sigma_str = f"{sigma:.2f}%" if sigma is not None else "-"
        lines.append(
            f"| {rank} | {name}({code}) | {cat} | {sigma_str} "
            f"| **{bn}** | {_fmt_pct(br_total)} | {_fmt_pct(bh_total)} "
            f"| **{_fmt_pct(alpha)}** | {_fmt_num(calmar)} | [v9-{code}.md](v9-{code}.md) |"
        )
    lines.append("")

    # 三、Calmar 权重快照
    lines.append("## 三、Calmar 权重快照（V4.1 算法）")
    lines.append("")
    lines.append("内部分配：每指数 $10,000 按 Calmar 比率在 D/W/M 间切，CAGR ≤ 0 剔除，单策略上限 80%。")
    lines.append("")
    lines.append("| 指数(代码) | 类别 | D 权重 | W 权重 | M 权重 |")
    lines.append("|---|---|---|---|---|")
    for code, info in calmar_by_code.items():
        first = full_results_by_code[code][0]
        d_a = info.get("D", {})
        w_a = info.get("W", {})
        m_a = info.get("M", {})

        def fmt_cell(a):
            if not a or a.get("excluded"):
                return "❌"
            return f"{a['weight'] * 100:.1f}%"

        lines.append(
            f"| {first.index_name}({code}) | {first.index_category} "
            f"| {fmt_cell(d_a)} | {fmt_cell(w_a)} | {fmt_cell(m_a)} |"
        )
    lines.append("")

    # 四、按类别聚合
    by_cat: Dict[str, List[str]] = {}
    for code, results in full_results_by_code.items():
        cat = results[0].index_category
        by_cat.setdefault(cat, []).append(results[0].index_name)
    lines.append("## 四、按类别聚合")
    lines.append("")
    lines.append("| 类别 | 数量 | 指数 |")
    lines.append("|---|---|---|")
    for cat, names in sorted(by_cat.items(), key=lambda x: -len(x[1])):
        lines.append(f"| {cat} | {len(names)} | {' · '.join(names)} |")
    lines.append("")

    # 五、与 V9.1 / V9 / V6 净 CAGR 对比
    lines.append("## 五、版本对比（净 CAGR · 万一免五）")
    lines.append("")
    lines.append("| 窗口 | V6（20 行业·THS）| V9（10 指数）| V9.1（17 指数）| **V9.2（14 指数）** | V9.2 提升（vs V9.1）|")
    lines.append("|---|---|---|---|---|---|")
    # V9.2 修正后（细分化工 cache 截断 bug 修复）
    v9_2_data = {3: 14.81, 5: 10.44, 8: 11.04, 10: 8.76}
    v9_1_data = {3: 13.69, 5: 9.83, 8: 9.85, 10: 7.70}
    v9_data = {3: 15.15, 5: 11.84, 8: 11.15, 10: 9.08}
    v6_data = {3: 18.08, 5: 18.95, 8: None, 10: None}
    for years in [3, 5, 8, 10]:
        v6_v = v6_data.get(years)
        v9_v = v9_data.get(years)
        v9_1_v = v9_1_data.get(years)
        v9_2_v = v9_2_data.get(years)
        delta = v9_2_v - v9_1_v if v9_2_v and v9_1_v else None
        lines.append(
            f"| {years} 年 | {_fmt_pct(v6_v)} | {_fmt_pct(v9_v)} "
            f"| {_fmt_pct(v9_1_v)} | **{_fmt_pct(v9_2_v)}** "
            f"| {_fmt_pct(delta)} |"
        )
    lines.append("")
    lines.append("> V9 < V9.2 < V9.1：V9 (10) 指数最精，CAGR 最高；V9.2 (14) 是合理折中；V9.1 (17) 含 3 个低波动拖累。")
    lines.append("")

    # 六、20 万 / 100 万实操终值（V9.2 修正后）
    lines.append("## 六、不同本金的实操终值（净，万一免五）")
    lines.append("")
    lines.append("| 本金 | 3 年 | 5 年 | 8 年 | 10 年 |")
    lines.append("|---|---|---|---|---|")
    lines.append("| **20 万** | $30.3 万 | $32.9 万 | $46.5 万 | $46.7 万 |")
    lines.append("| **100 万** | $151.4 万 | $164.4 万 | $232.6 万 | $233.7 万 |")
    lines.append("")

    # 七、使用注意事项
    lines.append("## 七、使用注意事项")
    lines.append("")
    lines.append("1. **可投资性**：13 个为中证/国证指数（除细分化工外都有 ETF 跟踪），细分化工 D/W/M 全失败 → 实际 $10k 闲置")
    lines.append("2. **磨损率**：3 年 ~2% / 5 年 ~4% / 8 年 ~8% / 10 年 ~10%（万一免五账户，长期累积）")
    lines.append("3. **回撤**：组合最大回撤约 -11% ~ -21%，3 年窗口最低 -11%（最好），10 年窗口 -21%")
    lines.append("4. **历史不代表未来**：所有数字基于 2016-2026 数据，未来若市场结构改变（牛熊切换、风格漂移）效果可能下降")
    lines.append("")

    # 八、链接到各指数详细 md
    lines.append("## 八、各指数详细 md 索引")
    lines.append("")
    lines.append("| 指数 | 文件 |")
    lines.append("|---|---|")
    for code, results in full_results_by_code.items():
        first = results[0]
        lines.append(f"| {first.index_name}({code}) | [v9-{code}.md](v9-{code}.md) |")
    return "\n".join(lines)


def _compute_sigma(daily_close: pd.Series) -> float:
    """年化波动率（%）= 日 log 收益率标准差 × √252 × 100"""
    import numpy as np
    import math
    log_ret = np.log(daily_close).diff().dropna()
    if log_ret.empty:
        return 0.0
    return float(log_ret.std() * math.sqrt(252) * 100)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s - %(message)s")

    registry = build_v9_registry()
    logger.info("V9.2 池：%d 个指数", len(registry))

    full_results_by_code: Dict[str, List[BacktestResult]] = {}
    calmar_by_code: Dict[str, Dict] = {}
    sigma_by_code: Dict[str, float] = {}

    for meta in registry:
        logger.info("[%s] %s", meta.code, meta.name)
        try:
            data = load_index(meta.code, meta.source, meta.name)
        except Exception as e:
            logger.error("  数据失败：%s", e)
            continue
        if data is None or data.daily.empty:
            logger.error("  数据为空")
            continue

        results: List[BacktestResult] = []
        for strat in all_strategies():
            try:
                r = run_strategy(
                    data, strat,
                    min_evaluation_start=MIN_EVALUATION_START,
                    index_category=meta.category,
                )
                results.append(r)
            except ValueError as e:
                logger.warning("  [%s] 策略跳过：%s", strat.name, e)
        if not results:
            logger.error("  无有效策略结果")
            continue

        full_results_by_code[meta.code] = results
        calmar_by_code[meta.code] = compute_allocation(results)

        # 计算 σ（评估区间内）
        eval_daily = data.daily[data.daily.index >= MIN_EVALUATION_START]
        if not eval_daily.empty:
            sigma_by_code[meta.code] = _compute_sigma(eval_daily["close"])

        # 渲染该指数的单独 md
        content = render_index_report(results)
        out = OUTPUT_DIR / f"v9-{meta.code}.md"
        out.write_text(content, encoding="utf-8")
        logger.info("  已产出 %s", out.name)

    # 渲染总览
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_OUTPUT.write_text(
        render_v9_summary(full_results_by_code, calmar_by_code, sigma_by_code),
        encoding="utf-8",
    )
    logger.info("已产出 %s", SUMMARY_OUTPUT.name)
    logger.info("总计 %d 份单指数 md + 1 份 v9-summary.md", len(full_results_by_code))
    return 0


if __name__ == "__main__":
    sys.exit(main())
