"""对比报告生成器：组合层 / 分指数差异 / Filter 命中三张表。"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Dict, List, Sequence, Tuple


def _fmt_pct(v: float, signed: bool = False) -> str:
    if v is None:
        return "-"
    fmt = "+.2f" if signed else ".2f"
    return f"{v:{fmt}}%"


def render_portfolio_table(strategies: Sequence[Tuple[str, list]]) -> str:
    """组合层对比表。每窗口 3 行：A / B / Δ。

    strategies: [(name, [WindowResult, ...]), ...]，长度 == 2。
    """
    if len(strategies) != 2:
        raise ValueError("portfolio table requires exactly 2 strategies")
    name_a, win_a = strategies[0]
    name_b, win_b = strategies[1]
    if len(win_a) != len(win_b):
        raise ValueError("two strategies must have same #windows")
    lines = [
        "| 时间窗 | 策略 | 总 CAGR | 最大回撤 | 总收益 |",
        "|---|---|---|---|---|",
    ]
    for wa, wb in zip(win_a, win_b):
        years = wa.window_years
        lines.append(f"| {years} 年 | {name_a} | {_fmt_pct(wa.cagr)} | {_fmt_pct(wa.max_drawdown)} | {_fmt_pct(wa.total_return, signed=True)} |")
        lines.append(f"| {years} 年 | {name_b} | {_fmt_pct(wb.cagr)} | {_fmt_pct(wb.max_drawdown)} | {_fmt_pct(wb.total_return, signed=True)} |")
        lines.append(f"| {years} 年 | Δ | {_fmt_pct(wb.cagr - wa.cagr, signed=True)} | {_fmt_pct(wb.max_drawdown - wa.max_drawdown, signed=True)} | {_fmt_pct(wb.total_return - wa.total_return, signed=True)} |")
    return "\n".join(lines)


def render_per_index_diff_table(
    diffs: List[Dict],
    *,
    threshold_cagr: float = 1.0,
    threshold_dd: float = 2.0,
) -> str:
    """分指数差异表。仅列 |Δ Net CAGR| ≥ threshold_cagr 或 |Δ MaxDD| ≥ threshold_dd 的指数。"""
    significant = [
        d for d in diffs
        if abs(d.get("delta_net_cagr", 0)) >= threshold_cagr
        or abs(d.get("delta_max_dd", 0)) >= threshold_dd
    ]
    if not significant:
        return "（无显著差异指数）"
    lines = [
        "| 指数 | Δ Net CAGR | Δ MaxDD |",
        "|---|---|---|",
    ]
    for d in significant:
        lines.append(
            f"| {d['name']}({d['code']}) "
            f"| {_fmt_pct(d['delta_net_cagr'], signed=True)} "
            f"| {_fmt_pct(d['delta_max_dd'], signed=True)} |"
        )
    return "\n".join(lines)


def render_filter_hit_table(hits: List[Dict]) -> str:
    """Filter 命中统计表。仅 v9.3-bear 类策略才有数据。"""
    if not hits:
        return "（无 Filter 命中数据）"
    lines = [
        "| 指数 | 总 BUY 候选 | 被 suppress | suppress 率 | 若执行的事后 60D 收益均值 |",
        "|---|---|---|---|---|",
    ]
    for h in hits:
        hindsight = h.get("hindsight_60d_avg_return")
        hs = _fmt_pct(hindsight, signed=True) if hindsight is not None else "N/A"
        lines.append(
            f"| {h['name']}({h['code']}) "
            f"| {h['buy_candidates']} "
            f"| {h['suppressed']} "
            f"| {h['suppress_rate']:.1f}% "
            f"| {hs} |"
        )
    return "\n".join(lines)


def write_compare_report(
    results_by_strategy: Dict[str, tuple],
    windows: List[int],
    output_dir: Path,
) -> Path:
    """对比报告主入口。被 run.py 调用。

    results_by_strategy: { strategy_name: (strat, registry, index_data, full_results, window_results) }
    """
    names = list(results_by_strategy.keys())
    if len(names) != 2:
        raise ValueError(f"compare expects 2 strategies, got {names}")
    a_name, b_name = names

    _, _, _, _, a_windows = results_by_strategy[a_name]
    _, registry, _, b_full, b_windows = results_by_strategy[b_name]

    portfolio_md = render_portfolio_table([(a_name, a_windows), (b_name, b_windows)])

    diffs = []
    a_full = results_by_strategy[a_name][3]
    for meta in registry:
        a_r = a_full.get(meta.code)
        b_r = b_full.get(meta.code)
        if not a_r or not b_r:
            continue
        a0, b0 = a_r[0], b_r[0]
        diffs.append({
            "code": meta.code,
            "name": meta.name,
            "delta_net_cagr": (b0.annualized_return - a0.annualized_return),
            "delta_max_dd": (b0.max_drawdown - a0.max_drawdown),
        })
    diff_md = render_per_index_diff_table(diffs)

    # Filter 命中统计需要 BearTrendFilter 在引擎里采集 metadata，本次先空表占位（Task 13 决定是否补全）
    hits: List[Dict] = []
    hits_md = render_filter_hit_table(hits)

    today = date.today().isoformat()
    out = output_dir / f"{today}-compare-{a_name}-vs-{b_name}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    md = "\n\n".join([
        f"# 策略对比报告：{a_name} vs {b_name}",
        f"> 生成日：{today}",
        "## 一、组合层对比",
        portfolio_md,
        "## 二、分指数差异（|ΔCAGR|≥1pp 或 |ΔMaxDD|≥2pp）",
        diff_md,
        "## 三、Filter 命中统计",
        hits_md,
    ])
    out.write_text(md, encoding="utf-8")
    return out
