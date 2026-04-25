"""CLI：按 V4.1 Calmar 权重在 3/5/8/10 年窗口内回测组合，产出 conclusion.md。

python -m scripts.backtest.run_windows
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Dict, List

import pandas as pd

from scripts.backtest.data_loader import IndexData, load_index
from scripts.backtest.engine import BacktestResult, run_strategy
from scripts.backtest.index_registry import build_index_registry
from scripts.backtest.reporter import compute_allocation
from scripts.backtest.strategies import all_strategies
from scripts.backtest.window_engine import (
    INDEX_CAPITAL,
    WindowResult,
    run_portfolio_window,
)

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT = PROJECT_ROOT / "docs" / "agents" / "backtest" / "conclusion.md"

WINDOWS = [3, 5, 8, 10]
MIN_EVALUATION_START = pd.Timestamp("2016-01-01")

# 从窗口组合中整体剔除的代码（不参与聚合、不出现在 Calmar 快照、不出现在详细表格）
# 理由：BTC 过去 10 年 +18,367% 属极端异常值，会完全扭曲组合 CAGR，建议单独评估
EXCLUDE_FROM_WINDOWS = {"BTC"}


def _fmt_pct(v) -> str:
    return f"{v:+.2f}%" if v is not None else "-"


def _fmt_money(v) -> str:
    return f"${v:,.2f}"


def render_conclusion(
    windows: List[WindowResult],
    as_of: pd.Timestamp,
    calmar_snapshot: Dict[str, Dict[str, Dict[str, float]]],
    excluded_codes: set,
) -> str:
    # 所有窗口的参与指数数应一致（从任一窗口取）
    n_indices = windows[0].index_count if windows else 0

    lines: List[str] = []
    lines.append(f"# 组合回测结论（V4.1 Calmar 权重 · 多窗口）")
    lines.append("")
    lines.append(f"> 评估日：{as_of.date()}")
    lines.append(f"> 组合：{n_indices} 个赢家指数，每个 $10,000 固定初始本金")
    lines.append("> 内部分配：按 V4.1 Calmar 比率在 D/W/M 间切，CAGR≤0 策略剔除，单策略上限 80%")
    lines.append(f"> 起始本金：{n_indices} × $10,000 = ${n_indices * 10000:,}")
    if excluded_codes:
        lines.append(f"> **已剔除**：{', '.join(sorted(excluded_codes))}（极端异常值，单独评估更合适）")
    lines.append("")

    # 总览
    lines.append("## 一、窗口总览")
    lines.append("")
    lines.append("| 窗口 | 起始日 | 终止日 | 参与指数 | 初始本金 | 终值 | **总收益** | CAGR | 最大回撤 | 迟到指数数 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for w in windows:
        late_count = sum(1 for p in w.per_index if p.is_late)
        lines.append(
            f"| **{w.window_years} 年** | {w.window_start.date()} | {w.as_of.date()} "
            f"| {w.index_count} | {_fmt_money(w.initial_capital)} | {_fmt_money(w.final_value)} "
            f"| **{_fmt_pct(w.total_return)}** | {_fmt_pct(w.cagr)} "
            f"| {_fmt_pct(w.max_drawdown)} | {late_count} |"
        )

    # 每窗口详细
    for w in windows:
        lines.append("")
        lines.append(f"## 二.{WINDOWS.index(w.window_years) + 1} {w.window_years} 年窗口详细（{w.window_start.date()} ~ {w.as_of.date()}）")
        lines.append("")

        late = [p for p in w.per_index if p.is_late]
        if late:
            lines.append("### 迟到指数（实际起始晚于窗口起始）")
            lines.append("")
            lines.append("| 指数 | 应起始 | 实际起始 | 迟到天数 | 闲置现金期 |")
            lines.append("|---|---|---|---|---|")
            for p in sorted(late, key=lambda x: x.actual_start):
                delay = (p.actual_start - w.window_start).days
                lines.append(
                    f"| {p.name}({p.code}) | {w.window_start.date()} "
                    f"| {p.actual_start.date()} | {delay} 天 "
                    f"| ~${INDEX_CAPITAL:,.0f} × {delay} 天 |"
                )
            lines.append("")

        lines.append("### 各指数贡献（按收益降序）")
        lines.append("")
        lines.append("| 排名 | 指数 | 类别 | 初始 | 终值 | 收益 | 实际起始 | 备注 |")
        lines.append("|---|---|---|---|---|---|---|---|")
        sorted_index = sorted(w.per_index, key=lambda x: -x.return_pct)
        for rank, p in enumerate(sorted_index, 1):
            note = "⏰ 迟到" if p.is_late else ""
            lines.append(
                f"| {rank} | {p.name}({p.code}) | {p.category} "
                f"| {_fmt_money(p.initial)} | {_fmt_money(p.final)} "
                f"| **{_fmt_pct(p.return_pct)}** | {p.actual_start.date()} | {note} |"
            )

    # Calmar 权重快照（参考）
    lines.append("")
    lines.append("## 三、Calmar 权重快照（V4.1 全历史计算，用于所有窗口）")
    lines.append("")
    lines.append("| 指数 | 类别 | D 权重 | W 权重 | M 权重 |")
    lines.append("|---|---|---|---|---|")
    for code, info in calmar_snapshot.items():
        cat = info.get("_category", "")
        name = info.get("_name", code)
        d = info.get("D", {})
        ww = info.get("W", {})
        m = info.get("M", {})

        def fmt_cell(a):
            if not a or a.get("excluded"):
                return "❌"
            return f"{a['weight'] * 100:.1f}%"

        lines.append(
            f"| {name}({code}) | {cat} | {fmt_cell(d)} | {fmt_cell(ww)} | {fmt_cell(m)} |"
        )

    return "\n".join(lines)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s - %(message)s")

    as_of = pd.Timestamp("2026-04-25")  # 评估日
    logger.info("评估日：%s", as_of.date())

    # 1. 加载 registry + 数据
    registry = build_index_registry()
    registry = [m for m in registry if m.code not in EXCLUDE_FROM_WINDOWS]
    if EXCLUDE_FROM_WINDOWS:
        logger.info("已剔除指数：%s", sorted(EXCLUDE_FROM_WINDOWS))
    logger.info("样本池：%d 个指数", len(registry))

    index_data: Dict[str, IndexData] = {}
    for meta in registry:
        logger.info("加载 %s %s", meta.code, meta.name)
        try:
            data = load_index(meta.code, meta.source, meta.name)
        except Exception as e:
            logger.error("  拉取异常：%s", e)
            continue
        if data is None or data.daily.empty:
            logger.error("  数据为空")
            continue
        index_data[meta.code] = data

    logger.info("成功加载 %d 个指数", len(index_data))

    # 2. 跑完整历史 baseline（获取 Calmar 权重）
    logger.info("跑完整历史基线...")
    full_results: Dict[str, List[BacktestResult]] = {}
    for code, data in index_data.items():
        meta = next(m for m in registry if m.code == code)
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
                logger.warning("  [%s/%s] skip: %s", code, strat.name, e)
        if results:
            full_results[code] = results

    # 3. Calmar 权重快照（供输出参考）
    calmar_snapshot: Dict[str, Dict] = {}
    for code, results in full_results.items():
        if not any(r.beats_bh for r in results):
            continue
        alloc = compute_allocation(results)
        alloc["_category"] = results[0].index_category
        alloc["_name"] = results[0].index_name
        calmar_snapshot[code] = alloc

    # 4. 跑 4 个窗口
    window_results: List[WindowResult] = []
    for n in WINDOWS:
        logger.info("窗口 %d 年 ...", n)
        wr = run_portfolio_window(index_data, full_results, n, as_of)
        logger.info(
            "  初始 $%s → 终值 $%s | 收益 %.2f%% | CAGR %.2f%% | 回撤 %.2f%% | 迟到 %d",
            f"{wr.initial_capital:,.0f}", f"{wr.final_value:,.0f}",
            wr.total_return, wr.cagr, wr.max_drawdown,
            sum(1 for p in wr.per_index if p.is_late)
        )
        window_results.append(wr)

    # 5. 渲染 conclusion.md
    content = render_conclusion(window_results, as_of, calmar_snapshot, EXCLUDE_FROM_WINDOWS)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(content, encoding="utf-8")
    logger.info("已产出 %s", OUTPUT)

    return 0


if __name__ == "__main__":
    sys.exit(main())
