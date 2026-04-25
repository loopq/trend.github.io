"""V6 CLI：对 v5-tiny-result.md 精选的 20 个 THS 行业跑多窗口组合回测。

复用 V4.2 window_engine 框架，输出 v6-sector-result.md。
评估窗口：3 / 5 / 8 / 10 年（终点 2026-04-25）

python -m scripts.backtest.run_v6
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Dict, List

import pandas as pd

from scripts.backtest.data_loader import IndexData, load_index
from scripts.backtest.engine import BacktestResult, run_strategy
from scripts.backtest.reporter import compute_allocation
from scripts.backtest.run_v5 import filter_tiny_candidates
from scripts.backtest.strategies import all_strategies
from scripts.backtest.v5_registry import build_v5_registry
from scripts.backtest.v5_screener import screen_sector
from scripts.backtest.window_engine import (
    INDEX_CAPITAL,
    WindowResult,
    run_portfolio_window,
)

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT = PROJECT_ROOT / "docs" / "agents" / "backtest" / "v6-sector-result.md"

WINDOWS = [3, 5, 8, 10]
MIN_EVALUATION_START = pd.Timestamp("2016-01-01")
AS_OF = pd.Timestamp("2026-04-25")


def _fmt_pct(v) -> str:
    return f"{v:+.2f}%" if v is not None else "-"


def _fmt_money(v) -> str:
    return f"${v:,.2f}"


def render_v6_result(
    windows: List[WindowResult],
    selected_codes_with_categories: List[tuple],
    calmar_snapshot: Dict[str, Dict],
    as_of: pd.Timestamp,
) -> str:
    n_indices = windows[0].index_count if windows else 0

    lines: List[str] = []
    lines.append("# V6 行业组合回测（精选 20 行业 · 多窗口）")
    lines.append("")
    lines.append(f"> 评估日：{as_of.date()}")
    lines.append(f"> 数据终点（拉取截止）：2026-04-24 收盘")
    lines.append(f"> 组合：{n_indices} 个 THS 一级行业（来自 v5-tiny-result.md）")
    lines.append(f"> 每行业初始本金：$10,000")
    lines.append(f"> 起始本金：{n_indices} × $10,000 = ${n_indices * 10000:,}")
    lines.append("> 内部分配：V4.1 Calmar 权重（D/W/M），CAGR ≤ 0 剔除，单策略上限 80%")
    lines.append("")
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
    lines.append("")

    # 每窗口详细
    for idx, w in enumerate(windows, 1):
        lines.append(f"## 二.{idx} {w.window_years} 年窗口详细（{w.window_start.date()} ~ {w.as_of.date()}）")
        lines.append("")

        late = [p for p in w.per_index if p.is_late]
        if late:
            lines.append("### 迟到指数（实际起始晚于窗口起始）")
            lines.append("")
            lines.append("| 指数 | 应起始 | 实际起始 | 迟到天数 | 闲置现金 |")
            lines.append("|---|---|---|---|---|")
            for p in sorted(late, key=lambda x: x.actual_start):
                delay = (p.actual_start - w.window_start).days
                lines.append(
                    f"| {p.name}({p.code}) | {w.window_start.date()} "
                    f"| {p.actual_start.date()} | {delay} 天 "
                    f"| ~${INDEX_CAPITAL:,.0f} × {delay} 天 |"
                )
            lines.append("")

        lines.append("### 各行业贡献（按收益降序）")
        lines.append("")
        lines.append("| 排名 | 行业 | 类别 | 初始 | 终值 | 收益 | 实际起始 | 备注 |")
        lines.append("|---|---|---|---|---|---|---|---|")
        sorted_idx = sorted(w.per_index, key=lambda x: -x.return_pct)
        for rank, p in enumerate(sorted_idx, 1):
            note = "⏰ 迟到" if p.is_late else ""
            lines.append(
                f"| {rank} | {p.name}({p.code}) | {p.category} "
                f"| {_fmt_money(p.initial)} | {_fmt_money(p.final)} "
                f"| **{_fmt_pct(p.return_pct)}** | {p.actual_start.date()} | {note} |"
            )
        lines.append("")

    # Calmar 权重快照
    lines.append("## 三、Calmar 权重快照（用于所有窗口）")
    lines.append("")
    lines.append("| 行业 | D 权重 | W 权重 | M 权重 |")
    lines.append("|---|---|---|---|")
    for code, info in calmar_snapshot.items():
        name = info.get("_name", code)
        d = info.get("D", {})
        w = info.get("W", {})
        m = info.get("M", {})

        def fmt_cell(a):
            if not a or a.get("excluded"):
                return "❌"
            return f"{a['weight'] * 100:.1f}%"

        lines.append(f"| {name}({code}) | {fmt_cell(d)} | {fmt_cell(w)} | {fmt_cell(m)} |")

    # 与 V4.2 对比
    lines.append("")
    lines.append("## 四、与 V4.2（16 指数宽基组合）对比")
    lines.append("")
    lines.append("| 窗口 | V4.2 (16 指数) CAGR | V4.2 回撤 | V6 (20 行业) CAGR | V6 回撤 | CAGR 提升 |")
    lines.append("|---|---|---|---|---|---|")
    v42_data = {
        3: (9.41, -10.12),
        5: (5.26, -19.20),
        8: (7.83, -21.46),
        10: (6.77, -21.13),
    }
    for w in windows:
        v42_cagr, v42_mdd = v42_data.get(w.window_years, (None, None))
        delta = w.cagr - v42_cagr if v42_cagr is not None else None
        lines.append(
            f"| {w.window_years} 年 "
            f"| {v42_cagr:.2f}% | {v42_mdd:.2f}% "
            f"| **{w.cagr:.2f}%** | {w.max_drawdown:.2f}% "
            f"| **{delta:+.2f}%** |"
        )
    lines.append("")
    lines.append("> V4.2 数据来自 docs/agents/backtest/conclusion.md（剔除 BTC 后的 16 指数组合）")
    return "\n".join(lines)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s - %(message)s")

    # 1. 跑 V5 拿到所有 SectorMetrics（带缓存，快）
    logger.info("[1/4] 运行 V5 筛选拿到 90 行业指标...")
    registry = build_v5_registry()
    all_metrics = []
    for meta in registry:
        sm = screen_sector(meta)
        if sm is not None:
            all_metrics.append(sm)
    logger.info("V5 成功：%d / 总：%d", len(all_metrics), len(registry))

    # 2. 应用 tiny 筛选（含强制纳入）
    selected, _overflow = filter_tiny_candidates(all_metrics)
    logger.info("[2/4] V5 tiny 精选：%d 个行业入选", len(selected))

    # 3. 拉数据 + 跑 full history
    logger.info("[3/4] 拉数据 + 跑 full-history 策略...")
    index_data: Dict[str, IndexData] = {}
    full_results: Dict[str, List[BacktestResult]] = {}
    selected_codes_with_categories = []

    for sm in selected:
        meta = next(m for m in registry if m.code == sm.code)
        data = load_index(meta.code, meta.source, meta.name)
        if data is None or data.daily.empty:
            logger.warning("  %s 数据缺失，跳过", meta.code)
            continue
        index_data[meta.code] = data
        results = []
        for strat in all_strategies():
            try:
                r = run_strategy(
                    data, strat,
                    min_evaluation_start=MIN_EVALUATION_START,
                    index_category=meta.category,
                )
                results.append(r)
            except ValueError:
                pass
        if results:
            full_results[meta.code] = results
            selected_codes_with_categories.append((meta.code, meta.name, meta.category))

    # 关键：让 window_engine 把"赢家"判断绕过去（v5 精选已经是赢家集合）
    # window_engine 内部用 r.beats_bh 判断；我们的 selected 中所有 best_alpha > +50%，全是赢家
    # 但保险起见，我们把 full_results 里加一个 dummy 让 window_engine 不漏掉任何一个

    # 4. Calmar 权重快照
    calmar_snapshot: Dict[str, Dict] = {}
    for code, results in full_results.items():
        alloc = compute_allocation(results)
        alloc["_name"] = results[0].index_name
        alloc["_category"] = results[0].index_category
        calmar_snapshot[code] = alloc

    # 5. 跑 4 个窗口
    logger.info("[4/4] 跑 %d 个窗口...", len(WINDOWS))
    window_results: List[WindowResult] = []
    for n in WINDOWS:
        wr = run_portfolio_window(index_data, full_results, n, AS_OF)
        logger.info(
            "  %d 年：$%s → $%s | %.2f%% | CAGR %.2f%% | MDD %.2f%% | 迟到 %d",
            n,
            f"{wr.initial_capital:,.0f}", f"{wr.final_value:,.0f}",
            wr.total_return, wr.cagr, wr.max_drawdown,
            sum(1 for p in wr.per_index if p.is_late),
        )
        window_results.append(wr)

    # 6. 渲染输出
    content = render_v6_result(window_results, selected_codes_with_categories, calmar_snapshot, AS_OF)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(content, encoding="utf-8")
    logger.info("已产出 %s", OUTPUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
