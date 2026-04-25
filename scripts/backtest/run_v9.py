"""V9 CLI：手动精选 10 指数完整回测（V6 + V6 磨损 一站式）。

包含：
1. 单指数指标（σ、CAGR、最大回撤、D/W/M alpha、Calmar 权重）
2. 多窗口组合回测（3/5/8/10 年）
3. 万一免五账户磨损扣减（20 万 / 100 万 两档本金）

python -m scripts.backtest.run_v9
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from scripts.backtest.data_loader import IndexData, load_index
from scripts.backtest.engine import BacktestResult, run_strategy
from scripts.backtest.reporter import compute_allocation
from scripts.backtest.run_v6_friction import (
    AS_OF as FRICTION_AS_OF,
    CAPITAL_LEVELS,
    ROUND_TRIP_COST,
    WINDOWS as FRICTION_WINDOWS,
    WindowFrictionResult,
    run_window_with_friction,
)
from scripts.backtest.strategies import all_strategies
from scripts.backtest.v5_screener import SectorMetrics, screen_sector
from scripts.backtest.v9_registry import build_v9_registry
from scripts.backtest.window_engine import (
    INDEX_CAPITAL,
    WindowResult,
    run_portfolio_window,
)

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT = PROJECT_ROOT / "docs" / "agents" / "backtest" / "v9-manual-result.md"

WINDOWS = [3, 5, 8, 10]
AS_OF = pd.Timestamp("2026-04-25")
MIN_EVALUATION_START = pd.Timestamp("2016-01-01")


def _fmt_pct(v) -> str:
    return f"{v:+.2f}%" if v is not None else "-"


def _fmt_pct_unsigned(v) -> str:
    return f"{v:.2f}%" if v is not None else "-"


def _fmt_money(v) -> str:
    return f"${v:,.2f}"


def _fmt_num(v, digits: int = 3) -> str:
    return f"{v:.{digits}f}" if v is not None else "-"


def render_v9_report(
    metrics: List[SectorMetrics],
    window_results: List[WindowResult],
    friction_results: Dict[str, List[WindowFrictionResult]],
    calmar_snapshot: Dict[str, Dict],
) -> str:
    lines: List[str] = []
    lines.append("# V9 手动精选 10 指数完整回测报告")
    lines.append("")
    lines.append(f"> 评估日：{AS_OF.date()}")
    lines.append("> 数据终点：2026-04-24 收盘")
    lines.append(f"> 组合：{len(metrics)} 个手动精选指数（9 中证 + 1 同花顺）")
    lines.append("")

    # 一、指数清单 + 单指数指标
    lines.append("## 一、指数清单 + 单指数指标")
    lines.append("")
    lines.append("| # | 指数(代码) | 类别 | 数据源 | σ | B&H 收益 | B&H CAGR | D 总收益 | D alpha | M 总收益 | M alpha | 最强 | best alpha |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for i, m in enumerate(metrics, 1):
        # 数据源从 registry 拿
        meta = next((reg for reg in build_v9_registry() if reg.code == m.code), None)
        source = meta.source if meta else "-"
        lines.append(
            f"| {i} | {m.name}({m.code}) | {m.category} | {source} | {m.annual_volatility:.1f}% "
            f"| {_fmt_pct(m.bh_total_return)} | {_fmt_pct(m.bh_cagr)} "
            f"| {_fmt_pct(m.d_total_return)} | {_fmt_pct(m.d_alpha)} "
            f"| {_fmt_pct(m.m_total_return)} | {_fmt_pct(m.m_alpha)} "
            f"| **{m.best_strategy}** | **{_fmt_pct(m.best_alpha)}** |"
        )
    lines.append("")

    # 一.B 高波动榜（按 σ 降序，终极诉求）
    lines.append("## 一.B、高波动榜（按 σ 降序，找高波动标的）")
    lines.append("")
    lines.append("| 排名 | 指数(代码) | 类别 | σ | best 策略 | best alpha | best Calmar |")
    lines.append("|---|---|---|---|---|---|---|")
    sorted_by_sigma = sorted(metrics, key=lambda x: -x.annual_volatility)
    for rank, m in enumerate(sorted_by_sigma, 1):
        lines.append(
            f"| {rank} | {m.name}({m.code}) | {m.category} | **{m.annual_volatility:.2f}%** "
            f"| **{m.best_strategy}** | {_fmt_pct(m.best_alpha)} | {_fmt_num(m.best_calmar)} |"
        )
    lines.append("")

    # 二、Calmar 权重快照
    lines.append("## 二、Calmar 权重快照（V4.1 算法）")
    lines.append("")
    lines.append("内部分配：每指数 $10,000 按 Calmar 权重在 D/W/M 间切，CAGR ≤ 0 剔除，单策略上限 80%。")
    lines.append("")
    lines.append("| 指数(代码) | 类别 | D 权重 | W 权重 | M 权重 |")
    lines.append("|---|---|---|---|---|")
    for code, info in calmar_snapshot.items():
        name = info.get("_name", code)
        category = info.get("_category", "")
        d = info.get("D", {})
        w = info.get("W", {})
        m_alloc = info.get("M", {})

        def fmt_cell(a):
            if not a or a.get("excluded"):
                return "❌"
            return f"{a['weight'] * 100:.1f}%"

        lines.append(f"| {name}({code}) | {category} | {fmt_cell(d)} | {fmt_cell(w)} | {fmt_cell(m_alloc)} |")
    lines.append("")

    # 三、多窗口总览（毛收益）
    lines.append("## 三、多窗口组合回测总览（不扣磨损）")
    lines.append("")
    lines.append("| 窗口 | 起始日 | 终止日 | 参与指数 | 初始本金 | 终值 | **总收益** | CAGR | 最大回撤 | 迟到指数 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for w in window_results:
        late_count = sum(1 for p in w.per_index if p.is_late)
        lines.append(
            f"| **{w.window_years} 年** | {w.window_start.date()} | {w.as_of.date()} "
            f"| {w.index_count} | {_fmt_money(w.initial_capital)} | {_fmt_money(w.final_value)} "
            f"| **{_fmt_pct(w.total_return)}** | {_fmt_pct(w.cagr)} "
            f"| {_fmt_pct(w.max_drawdown)} | {late_count} |"
        )
    lines.append("")

    # 四、扣磨损后净收益（万一免五）
    lines.append("## 四、磨损扣减后净收益（万一免五账户）")
    lines.append("")
    lines.append("成本模型：买佣金 0.01% / 卖佣金 0.01% / 印花税 0.10% → 单次往返 0.12%")
    lines.append("")
    lines.append("| 本金 | 窗口 | 初始 | 毛终值 | **净终值** | 毛收益 | **净收益** | 毛 CAGR | **净 CAGR** | 磨损 | 平均交易/指数 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for cap_label, win_results in friction_results.items():
        for w in win_results:
            lines.append(
                f"| {cap_label} | {w.window_years} 年 "
                f"| {_fmt_money(w.initial_capital)} | {_fmt_money(w.gross_final)} | **{_fmt_money(w.net_final)}** "
                f"| {_fmt_pct(w.gross_return)} | **{_fmt_pct(w.net_return)}** "
                f"| {_fmt_pct(w.gross_cagr)} | **{_fmt_pct(w.net_cagr)}** "
                f"| -{_fmt_pct_unsigned(w.friction_pct)} | {w.avg_round_trips_per_index:.1f} 次 |"
            )
    lines.append("")

    # 五、各窗口指数贡献明细
    for idx, w in enumerate(window_results, 1):
        lines.append(f"## 五.{idx} {w.window_years} 年窗口各指数贡献（不扣磨损）")
        lines.append("")
        late = [p for p in w.per_index if p.is_late]
        if late:
            lines.append("**迟到指数**（实际起始晚于窗口起始）：")
            lines.append("")
            for p in sorted(late, key=lambda x: x.actual_start):
                delay = (p.actual_start - w.window_start).days
                lines.append(f"- {p.name}({p.code}): 实际起始 {p.actual_start.date()}（迟到 {delay} 天）")
            lines.append("")
        lines.append("| 排名 | 指数 | 类别 | 初始 | 终值 | 收益 | 实际起始 | 备注 |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for rank, p in enumerate(sorted(w.per_index, key=lambda x: -x.return_pct), 1):
            note = "⏰ 迟到" if p.is_late else ""
            lines.append(
                f"| {rank} | {p.name}({p.code}) | {p.category} "
                f"| {_fmt_money(p.initial)} | {_fmt_money(p.final)} "
                f"| **{_fmt_pct(p.return_pct)}** | {p.actual_start.date()} | {note} |"
            )
        lines.append("")

    # 六、各指数交易频率（用于磨损估算）
    lines.append("## 六、各指数交易频率明细（万一免五本金 20 万）")
    lines.append("")
    lines.append("（数据基于 5 年窗口，3 年类似比例）")
    lines.append("")
    five_year = next((w for w in friction_results.get("20万", []) if w.window_years == 5), None)
    if five_year:
        # 按行业聚合
        by_index: Dict[str, List] = {}
        for b in five_year.bucket_metrics:
            by_index.setdefault(b.code, []).append(b)
        lines.append("| 指数 | D 交易 | W 交易 | M 交易 | 行业总交易 | 行业初始 | 行业毛终 | 行业净终 | 净收益 |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        rows = []
        for code, buckets in by_index.items():
            name = buckets[0].name
            d_t = next((b.trade_count for b in buckets if b.strategy == "D"), 0)
            w_t = next((b.trade_count for b in buckets if b.strategy == "W"), 0)
            m_t = next((b.trade_count for b in buckets if b.strategy == "M"), 0)
            total_t = d_t + w_t + m_t
            init = sum(b.bucket_capital for b in buckets)
            gross = sum(b.gross_final for b in buckets)
            net = sum(b.net_final for b in buckets)
            ret = (net / init - 1) * 100 if init > 0 else 0
            rows.append((code, name, d_t, w_t, m_t, total_t, init, gross, net, ret))
        rows.sort(key=lambda r: -r[9])
        for code, name, d_t, w_t, m_t, total_t, init, gross, net, ret in rows:
            lines.append(
                f"| {name}({code}) | {d_t} | {w_t} | {m_t} | {total_t} "
                f"| {_fmt_money(init)} | {_fmt_money(gross)} | {_fmt_money(net)} "
                f"| **{_fmt_pct(ret)}** |"
            )
    lines.append("")

    # 七、关键观察
    lines.append("## 七、关键观察")
    lines.append("")
    if friction_results.get("20万"):
        for years in WINDOWS:
            r = next((w for w in friction_results["20万"] if w.window_years == years), None)
            if r:
                lines.append(f"- **{years} 年**：20 万本金净 CAGR {r.net_cagr:+.2f}% / 净终值 {_fmt_money(r.net_final)} / 磨损 {r.friction_pct:.2f}%")
    lines.append("")
    lines.append("注意点：")
    lines.append("- 全部 9 个中证指数都有 ETF 跟踪可投资")
    lines.append("- 电力(881145) 是 THS 同花顺一级行业，需找对应 ETF（如电力 ETF / 公用事业 ETF）实操")
    lines.append("- 实际 ETF 对应代码需自行核对（参见 V7 mapping 经验：算法映射不可靠，建议人工核对）")
    return "\n".join(lines)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s - %(message)s")

    # 1. 加载手动池
    logger.info("[1/5] 加载手动池...")
    registry = build_v9_registry()
    logger.info("V9 手动池：%d 个指数", len(registry))

    # 2. 跑 screener 拿单指数指标
    logger.info("[2/5] 运行 screener 拿单指数指标...")
    metrics: List[SectorMetrics] = []
    for meta in registry:
        sm = screen_sector(meta)
        if sm is None:
            logger.error("  %s %s 失败！", meta.code, meta.name)
            continue
        metrics.append(sm)
        logger.info(
            "  %s σ=%.2f%% best=%s α=%+.2f%% Calmar=%.3f",
            meta.name, sm.annual_volatility, sm.best_strategy, sm.best_alpha, sm.best_calmar,
        )

    # 3. 加载数据 + full-history results（供 window_engine 用）
    logger.info("[3/5] 加载数据 + full-history 策略...")
    index_data: Dict[str, IndexData] = {}
    full_results: Dict[str, List[BacktestResult]] = {}
    for meta in registry:
        data = load_index(meta.code, meta.source, meta.name)
        if data is None or data.daily.empty:
            logger.warning("  %s 数据缺失", meta.code)
            continue
        index_data[meta.code] = data
        results: List[BacktestResult] = []
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

    # 4. Calmar 权重快照
    calmar_snapshot: Dict[str, Dict] = {}
    for code, results in full_results.items():
        alloc = compute_allocation(results)
        alloc["_name"] = results[0].index_name
        alloc["_category"] = results[0].index_category
        calmar_snapshot[code] = alloc

    # 5. 跑多窗口 + 磨损
    logger.info("[4/5] 多窗口组合回测 + 磨损扣减...")
    window_results: List[WindowResult] = []
    for n in WINDOWS:
        wr = run_portfolio_window(index_data, full_results, n, AS_OF)
        logger.info(
            "  %d 年 毛：$%s → $%s | %.2f%% / CAGR %.2f%% / MDD %.2f%%",
            n,
            f"{wr.initial_capital:,.0f}", f"{wr.final_value:,.0f}",
            wr.total_return, wr.cagr, wr.max_drawdown,
        )
        window_results.append(wr)

    # 统一用 $10k × N indices = $基准本金 算 CAGR（与毛收益对齐）
    # 20 万 / 100 万 仅作为"实操金额示意"，按比例线性放大终值
    base_capital = INDEX_CAPITAL * len(registry)
    friction_results: Dict[str, List[WindowFrictionResult]] = {}
    # 用 base_capital 跑一遍 friction 拿净 CAGR（与本金无关）
    base_friction: List[WindowFrictionResult] = []
    for n in WINDOWS:
        fr = run_window_with_friction(
            index_data, full_results, n, AS_OF, base_capital, f"基准${int(base_capital):,}",
        )
        logger.info(
            "  基准 / %d 年 净 CAGR %.2f%% / 磨损 %.2f%%",
            n, fr.net_cagr, fr.friction_pct,
        )
        base_friction.append(fr)

    # 按本金档位线性放大终值（万一免五下 CAGR 与本金无关）
    for cap_label, cap_total in CAPITAL_LEVELS:
        scale = cap_total / base_capital
        friction_results[cap_label] = []
        for fr_base in base_friction:
            scaled = WindowFrictionResult(
                window_years=fr_base.window_years,
                window_start=fr_base.window_start,
                as_of=fr_base.as_of,
                capital_label=cap_label,
                capital_total=cap_total,
                n_indices=fr_base.n_indices,
                initial_capital=fr_base.initial_capital * scale,
                gross_final=fr_base.gross_final * scale,
                gross_return=fr_base.gross_return,
                gross_cagr=fr_base.gross_cagr,
                net_final=fr_base.net_final * scale,
                net_return=fr_base.net_return,
                net_cagr=fr_base.net_cagr,
                total_friction=fr_base.total_friction * scale,
                friction_pct=fr_base.friction_pct,
                avg_round_trips_per_index=fr_base.avg_round_trips_per_index,
                bucket_metrics=fr_base.bucket_metrics,
            )
            friction_results[cap_label].append(scaled)

    # 6. 渲染输出
    logger.info("[5/5] 渲染 v9-manual-result.md...")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        render_v9_report(metrics, window_results, friction_results, calmar_snapshot),
        encoding="utf-8",
    )
    logger.info("已产出 %s", OUTPUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
