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
    """N 策略对比，每窗口 N+(N-1) 行：N 个策略各一行 + (N-1) 个 Δ 行（每个非 base 策略对 base）。"""
    if len(strategies) < 2:
        raise ValueError("portfolio table requires ≥ 2 strategies")
    base_name, base_windows = strategies[0]
    n_windows = len(base_windows)
    for name, win in strategies[1:]:
        if len(win) != n_windows:
            raise ValueError(f"strategy {name} has {len(win)} windows, expected {n_windows}")

    lines = [
        "| 时间窗 | 策略 | 总 CAGR | 最大回撤 | 总收益 |",
        "|---|---|---|---|---|",
    ]
    for w_idx in range(n_windows):
        years = base_windows[w_idx].window_years
        # N 行各策略
        lines.append(f"| {years} 年 | {base_name} | {_fmt_pct(base_windows[w_idx].cagr)} | {_fmt_pct(base_windows[w_idx].max_drawdown)} | {_fmt_pct(base_windows[w_idx].total_return, signed=True)} |")
        for name, windows in strategies[1:]:
            wr = windows[w_idx]
            lines.append(f"| {years} 年 | {name} | {_fmt_pct(wr.cagr)} | {_fmt_pct(wr.max_drawdown)} | {_fmt_pct(wr.total_return, signed=True)} |")
        # (N-1) 行 Δ
        for name, windows in strategies[1:]:
            wr = windows[w_idx]
            lines.append(
                f"| {years} 年 | Δ ({name} − {base_name}) "
                f"| {_fmt_pct(wr.cagr - base_windows[w_idx].cagr, signed=True)} "
                f"| {_fmt_pct(wr.max_drawdown - base_windows[w_idx].max_drawdown, signed=True)} "
                f"| {_fmt_pct(wr.total_return - base_windows[w_idx].total_return, signed=True)} |"
            )
    return "\n".join(lines)


def render_per_index_diff_table(
    diffs: List[Dict],
    *,
    threshold_cagr: float = 1.0,
    threshold_dd: float = 2.0,
) -> str:
    """分指数差异表。仅列 |Δ Net CAGR| ≥ threshold_cagr 或 |Δ MaxDD| ≥ threshold_dd 的指数。

    单策略 diff（diffs 是同一个非 base 策略 vs base 的差值列表）。
    多策略时由 write_compare_report 按 base 策略循环调用 N-1 次。
    """
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
    """对比报告主入口。N≥2 策略，第一个作为对照基线。

    results_by_strategy: { strategy_name: (strat, registry, index_data, full_results, window_results) }
    """
    names = list(results_by_strategy.keys())
    if len(names) < 2:
        raise ValueError(f"compare expects ≥ 2 strategies, got {names}")
    base_name = names[0]
    other_names = names[1:]

    # 收集每策略的 window_results
    per_strategy_windows = []
    for n in names:
        _, _, _, _, w = results_by_strategy[n]
        per_strategy_windows.append((n, w))
    portfolio_md = render_portfolio_table(per_strategy_windows)

    # registry 与 base full_results
    _, registry, _, base_full, _ = results_by_strategy[base_name]

    # 每个非 base 策略一份分指数 diff 子表
    diff_sections = []
    for other in other_names:
        _, _, _, other_full, _ = results_by_strategy[other]
        if not other_full:
            # 横截面策略（cross-sectional-topk）无 per-index full_results
            diff_sections.append(
                f"### Δ ({other} − {base_name})\n\n"
                f"（{other} 走横截面 top-K 路径，无 per-index 持仓数据，不可逐指数对比 baseline。"
                f"组合层数据见上方“组合层对比”段。）"
            )
            continue
        diffs = []
        for meta in registry:
            base_r = base_full.get(meta.code)
            other_r = other_full.get(meta.code)
            if not base_r or not other_r:
                continue
            base0, other0 = base_r[0], other_r[0]
            diffs.append({
                "code": meta.code,
                "name": meta.name,
                "delta_net_cagr": (other0.annualized_return - base0.annualized_return),
                "delta_max_dd": (other0.max_drawdown - base0.max_drawdown),
            })
        diff_md = render_per_index_diff_table(diffs)
        diff_sections.append(f"### Δ ({other} − {base_name})\n\n{diff_md}")

    diff_full_md = "\n\n".join(diff_sections) if diff_sections else "（无）"

    # Filter 命中表占位
    hits: List[Dict] = []
    hits_md = render_filter_hit_table(hits)

    today = date.today().isoformat()
    suffix = "-vs-".join([base_name] + list(other_names))
    out = output_dir / f"{today}-compare-{suffix}.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    md = "\n\n".join([
        f"# 策略对比报告：{base_name} vs " + " vs ".join(other_names),
        f"> 生成日：{today}",
        "## 一、组合层对比",
        portfolio_md,
        "## 二、分指数差异（|ΔCAGR|≥1pp 或 |ΔMaxDD|≥2pp）",
        diff_full_md,
        "## 三、Filter 命中统计",
        hits_md,
    ])
    out.write_text(md, encoding="utf-8")
    return out
