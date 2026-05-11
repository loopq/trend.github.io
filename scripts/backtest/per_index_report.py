"""综合 per-strategy × per-index × per-window 详细对比报告生成器。

用法：
    python -m scripts.backtest.per_index_report \\
        --strategies v9-baseline,v9.3-bear,faber-gtaa,donchian-200,dual-momentum-top5 \\
        --universe combined-24 \\
        --windows 3,5,8,10 \\
        --output agents/results/2026-05-11-detailed-5strats-on-combined-24.md

输出 markdown 报告含：
- 组合层汇总表（每策略每窗口 CAGR/MDD/总收益）
- 排名（按各窗口 CAGR）
- per-strategy 详细表（每指数每窗口 CAGR/MDD/总收益）
- 风格倾向分析（按 universe 子集分组）

注意：cross-sectional-topk 策略（如 dual-momentum）无 per-index 数据，仅显示组合层。
"""

import argparse
import logging
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


def _per_index_cagr(initial: float, final: float, years: float) -> float:
    """从 (initial, final, years) 算 CAGR%。"""
    if initial <= 0 or years <= 0 or final <= 0:
        return 0.0
    return ((final / initial) ** (1 / years) - 1) * 100


def _fmt_pct(v: float, signed: bool = False) -> str:
    """格式化百分比："{:+.2f}%" / "{:.2f}%"。"""
    return f"{v:+.2f}%" if signed else f"{v:.2f}%"


def _collect(strategy_names: List[str], universe_name: str, windows: List[int]) -> Dict:
    """跑每个策略，收集 portfolio + per-index 数据。"""
    from scripts.backtest.run import _run_one_strategy

    out: Dict[str, Dict] = {}
    for strat_name in strategy_names:
        logger.info("==== 跑策略 %s on %s ====", strat_name, universe_name)
        strat, registry, _, full_results, window_results = _run_one_strategy(
            strat_name, universe_name, windows,
        )
        out[strat_name] = {
            "registry": registry,
            "is_cross_sectional": not full_results,  # cross-sectional 路径 full_results 为空
            "windows": {},
        }
        for wr in window_results:
            years = (wr.as_of - wr.window_start).days / 365.25
            per_index = []
            for p in wr.per_index:
                cagr = _per_index_cagr(p.initial, p.final, years)
                per_index.append({
                    "code": p.code,
                    "name": p.name,
                    "category": p.category,
                    "cagr": cagr,
                    "mdd": p.max_drawdown,
                    "total_return": p.return_pct,
                })
            out[strat_name]["windows"][wr.window_years] = {
                "portfolio": {
                    "cagr": wr.cagr,
                    "mdd": wr.max_drawdown,
                    "total_return": wr.total_return,
                },
                "per_index": per_index,
            }
    return out


def _render_portfolio_summary(data: Dict, strategy_names: List[str], windows: List[int]) -> str:
    """组合层汇总表：每策略每窗口的 CAGR / MDD / 总收益。"""
    lines = ["| 策略 |"]
    lines[0] += "".join([f" {n} 年 CAGR | {n} 年 MDD | {n} 年 总收益 |" for n in windows])
    lines.append("|---|" + "|".join(["---"] * (3 * len(windows))) + "|")
    for strat in strategy_names:
        row = f"| **{strat}** |"
        for n in windows:
            p = data[strat]["windows"][n]["portfolio"]
            row += f" {_fmt_pct(p['cagr'])} | {_fmt_pct(p['mdd'])} | {_fmt_pct(p['total_return'], signed=True)} |"
        lines.append(row)
    return "\n".join(lines)


def _render_ranking(data: Dict, strategy_names: List[str], windows: List[int]) -> str:
    """排名：每窗口按 CAGR 排序。"""
    lines = []
    for n in windows:
        ranked = sorted(strategy_names, key=lambda s: -data[s]["windows"][n]["portfolio"]["cagr"])
        lines.append(f"\n**{n} 年窗口（按 CAGR 排）：**\n")
        for i, s in enumerate(ranked, 1):
            p = data[s]["windows"][n]["portfolio"]
            lines.append(f"{i}. **{s}** — CAGR {_fmt_pct(p['cagr'])} / MDD {_fmt_pct(p['mdd'])} / 总收益 {_fmt_pct(p['total_return'], signed=True)}")
    return "\n".join(lines)


def _render_per_strategy_detail(data: Dict, strat_name: str, windows: List[int]) -> str:
    """单策略 per-index 详细表（24 行 × 4 窗口 × 3 数字）。"""
    if data[strat_name]["is_cross_sectional"]:
        return f"_（{strat_name} 走横截面 top-K 路径，无 per-index 持仓数据，仅有组合层数字。请见组合层汇总表。）_\n"

    # 收集所有 codes（按 windows[0] 的顺序，假设各窗口同 universe）
    first_win = data[strat_name]["windows"][windows[0]]
    codes_order = [item["code"] for item in first_win["per_index"]]
    by_code: Dict[str, Dict[int, Dict]] = defaultdict(dict)
    name_by_code: Dict[str, str] = {}
    for n in windows:
        for item in data[strat_name]["windows"][n]["per_index"]:
            by_code[item["code"]][n] = item
            name_by_code[item["code"]] = item["name"]

    header = "| 指数 |"
    for n in windows:
        header += f" {n}y CAGR | {n}y MDD | {n}y 总收益 |"
    lines = [header, "|---|" + "|".join(["---"] * (3 * len(windows))) + "|"]
    for code in codes_order:
        row = f"| {name_by_code[code]}({code}) |"
        for n in windows:
            item = by_code[code].get(n)
            if item is None:
                row += " - | - | - |"
            else:
                row += f" {_fmt_pct(item['cagr'])} | {_fmt_pct(item['mdd'])} | {_fmt_pct(item['total_return'], signed=True)} |"
        lines.append(row)
    return "\n".join(lines)


def _render_style_analysis(data: Dict, strategy_names: List[str], windows: List[int], baseline: str) -> str:
    """风格倾向分析：每策略在各 universe 子集上 vs baseline 的平均 ΔCAGR / ΔMDD。"""
    if data[baseline]["is_cross_sectional"]:
        return f"_（baseline {baseline} 是横截面策略，无 per-index 数据可对比，跳过风格分析。）_\n"

    # 按窗口和策略，按 category 聚合
    lines = ["", "下表显示每策略在 5 个 universe 子集上的 **平均 ΔCAGR / ΔMDD vs baseline**（10y 窗口）。正号 = 跑赢 baseline；负号 = 跑输。"]
    lines.append("")

    n = max(windows)  # 用最长窗口（信息最丰富）
    base_per = {item["code"]: item for item in data[baseline]["windows"][n]["per_index"]}

    # 收集所有 categories
    categories = sorted(set(item["category"] for item in data[baseline]["windows"][n]["per_index"]))
    header = "| 策略 |" + "".join([f" {c} |" for c in categories])
    sep = "|---|" + "|".join(["---"] * len(categories)) + "|"
    lines.append(header)
    lines.append(sep)

    for strat in strategy_names:
        if data[strat]["is_cross_sectional"]:
            row = f"| {strat} |" + "|".join([" 横截面无数据 "] * len(categories)) + "|"
            lines.append(row)
            continue
        if strat == baseline:
            continue
        cat_deltas: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
        for item in data[strat]["windows"][n]["per_index"]:
            base_item = base_per.get(item["code"])
            if not base_item:
                continue
            d_cagr = item["cagr"] - base_item["cagr"]
            d_mdd = item["mdd"] - base_item["mdd"]
            cat_deltas[item["category"]].append((d_cagr, d_mdd))
        row = f"| {strat} |"
        for c in categories:
            deltas = cat_deltas.get(c, [])
            if not deltas:
                row += " - |"
            else:
                avg_cagr = sum(d[0] for d in deltas) / len(deltas)
                avg_mdd = sum(d[1] for d in deltas) / len(deltas)
                row += f" ΔCAGR {avg_cagr:+.2f}pp / ΔMDD {avg_mdd:+.2f}pp ({len(deltas)}指数) |"
        lines.append(row)

    lines.append("")
    lines.append("**解读约定**：")
    lines.append("- ΔCAGR 正 = 该策略在该子集上 CAGR 高于 baseline → 风格偏好该子集")
    lines.append("- ΔCAGR 负 = 该策略在该子集上跑输 baseline → 风格回避该子集")
    lines.append("- ΔMDD 正 = MDD 比 baseline 浅（更小回撤）→ 风险控制更好")
    lines.append("- ΔMDD 负 = MDD 比 baseline 深（更大回撤）→ 风险控制更差")
    return "\n".join(lines)


def _render_summary_text(data: Dict, strategy_names: List[str], windows: List[int]) -> str:
    """文字总结：每策略最强/最弱窗口 + 总分。"""
    lines = ["## 文字总结", ""]

    # 每策略综合分（4 窗口 CAGR 平均 - MDD 绝对值平均，简单评分）
    scores = []
    for s in strategy_names:
        cagrs = [data[s]["windows"][n]["portfolio"]["cagr"] for n in windows]
        mdds = [data[s]["windows"][n]["portfolio"]["mdd"] for n in windows]
        avg_cagr = sum(cagrs) / len(cagrs)
        avg_mdd = sum(mdds) / len(mdds)  # negative
        # 综合分：越高越好
        score = avg_cagr + avg_mdd  # avg_mdd 是负数，浅 MDD 加分多
        scores.append((s, avg_cagr, avg_mdd, score, cagrs, mdds))
    scores.sort(key=lambda x: -x[3])

    lines.append("**综合评分（4 窗口平均 CAGR + 平均 MDD，越高越好；MDD 负数所以浅 MDD 加分多）：**\n")
    for i, (s, ac, am, sc, _, _) in enumerate(scores, 1):
        lines.append(f"{i}. **{s}**: 综合分 {sc:.2f} = 平均 CAGR {ac:.2f}% + 平均 MDD {am:.2f}%")
    lines.append("")

    # 每策略每窗口胜率
    lines.append("**每策略各窗口排名（按 CAGR）：**\n")
    rank_table = ["| 策略 |" + "".join([f" {n} 年 |" for n in windows]) + " 平均排名 |"]
    rank_table.append("|---|" + "|".join(["---"] * (len(windows) + 1)) + "|")
    rank_per_strat: Dict[str, List[int]] = defaultdict(list)
    for n in windows:
        ranked = sorted(strategy_names, key=lambda s: -data[s]["windows"][n]["portfolio"]["cagr"])
        for i, s in enumerate(ranked, 1):
            rank_per_strat[s].append(i)
    for s in strategy_names:
        ranks = rank_per_strat[s]
        avg_rank = sum(ranks) / len(ranks)
        row = f"| **{s}** |" + "".join([f" 第 {r} |" for r in ranks]) + f" **{avg_rank:.2f}** |"
        rank_table.append(row)
    lines.extend(rank_table)
    return "\n".join(lines)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(description="生成 per-strategy × per-index × per-window 详细对比报告")
    parser.add_argument("--strategies", required=True, help="逗号分隔策略名（如 v9-baseline,faber-gtaa）")
    parser.add_argument("--universe", required=True, help="universe 名（如 combined-24 或 codes:000300,000016）")
    parser.add_argument("--windows", default="3,5,8,10", help="逗号分隔窗口年数（默认 3,5,8,10）")
    parser.add_argument("--output", required=True, help="输出 markdown 报告路径")
    parser.add_argument("--baseline", default="v9-baseline", help="baseline 策略名（用于风格分析对比，默认 v9-baseline）")
    args = parser.parse_args()

    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    windows = [int(w) for w in args.windows.split(",") if w.strip()]

    data = _collect(strategies, args.universe, windows)

    # 渲染各部分
    portfolio = _render_portfolio_summary(data, strategies, windows)
    ranking = _render_ranking(data, strategies, windows)
    summary_text = _render_summary_text(data, strategies, windows)
    style = _render_style_analysis(data, strategies, windows, args.baseline)

    detail_sections = []
    for s in strategies:
        detail_sections.append(f"\n### {s}\n\n{_render_per_strategy_detail(data, s, windows)}")
    detail_full = "\n".join(detail_sections)

    md = "\n\n".join([
        f"# 详细对比报告：{', '.join(strategies)}",
        f"> 生成日：{__import__('datetime').date.today().isoformat()}",
        f"> Universe：**{args.universe}**",
        f"> 时间窗：{' / '.join(str(n) for n in windows)} 年",
        "## 一、组合层汇总（每策略每窗口）",
        portfolio,
        "## 二、各窗口 CAGR 排名",
        ranking,
        summary_text,
        f"## 三、风格倾向分析（vs baseline {args.baseline}）",
        style,
        "## 四、各策略 per-index 详细表",
        detail_full,
    ])

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    logger.info("报告写入：%s", out)


if __name__ == "__main__":
    main()
