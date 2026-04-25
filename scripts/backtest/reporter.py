"""纯渲染：BacktestResult → Markdown。

V3：赢家/败者二分逻辑。
- 单指数详细 md：仅对"至少一个策略跑赢 B&H"的指数生成
- summary：赢家榜 + 败者榜 + 类别聚合

V4 新增：每指数 $10k 按 Calmar 比率在 D/W/M 间分配，80% 上限。
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from scripts.backtest.engine import BacktestResult

INDEX_CAPITAL = 10000.0  # 每指数初始本金
MAX_SINGLE_WEIGHT = 0.80  # 单策略权重上限（多策略时）
MDD_FLOOR = 0.1  # 最大回撤下限（避免除零，单位 %）


def _fmt_pct(value) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}%"


def _fmt_money(value: float) -> str:
    return f"${value:,.2f}"


def _fmt_diff(value) -> str:
    """带符号的超额百分比展示。"""
    if value is None:
        return "-"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


# ---------- Calmar 分配算法 ----------

def compute_allocation(results: List[BacktestResult]) -> Dict[str, Dict[str, float]]:
    """基于 Calmar 比率计算每策略权重和金额。

    规则：
        1. CAGR <= 0 的策略剔除
        2. Calmar = CAGR / max(|MDD|, MDD_FLOOR)
        3. 按 Calmar 正比归一化
        4. 多策略时，任一权重 > MAX_SINGLE_WEIGHT 则封顶并按其他 Calmar 比例再分

    返回：{strategy_name: {"weight": float, "amount": float, "calmar": float, "excluded": bool}}
    """
    candidates = [r for r in results if r.annualized_return > 0]

    result: Dict[str, Dict[str, float]] = {}
    for r in results:
        result[r.strategy_name] = {
            "weight": 0.0,
            "amount": 0.0,
            "calmar": 0.0,
            "excluded": r.annualized_return <= 0,
        }

    if not candidates:
        return result

    calmars: Dict[str, float] = {}
    for r in candidates:
        mdd = max(abs(r.max_drawdown), MDD_FLOOR)
        calmars[r.strategy_name] = r.annualized_return / mdd

    total_calmar = sum(calmars.values())
    weights: Dict[str, float] = {n: c / total_calmar for n, c in calmars.items()}

    # 80% 上限（仅多策略时）
    if len(candidates) > 1:
        for _ in range(5):  # 最多迭代 5 次以稳定
            over = {n: w for n, w in weights.items() if w > MAX_SINGLE_WEIGHT + 1e-9}
            if not over:
                break
            for over_name in over:
                excess = weights[over_name] - MAX_SINGLE_WEIGHT
                weights[over_name] = MAX_SINGLE_WEIGHT
                others = {n: calmars[n] for n in calmars if n not in over}
                others_total = sum(others.values())
                if others_total > 0:
                    for other_name, other_calmar in others.items():
                        weights[other_name] += excess * (other_calmar / others_total)

    for name, w in weights.items():
        result[name]["weight"] = w
        result[name]["amount"] = w * INDEX_CAPITAL
        result[name]["calmar"] = calmars[name]

    return result


# ---------- 单指数详细 md ----------

def _all_years(results: List[BacktestResult]) -> List[int]:
    years = set()
    for r in results:
        years.update(r.yearly_returns.keys())
        years.update(r.bh_yearly_returns.keys())
    return sorted(years)


def _year_row(year: int, results: List[BacktestResult]) -> str:
    cells = [str(year)]
    for r in results:
        cells.append(_fmt_pct(r.yearly_returns.get(year)))
    bh = results[0].bh_yearly_returns.get(year) if results else None
    cells.append(_fmt_pct(bh))
    return "| " + " | ".join(cells) + " |"


def _total_row(results: List[BacktestResult]) -> str:
    cells = ["**总收益**"]
    for r in results:
        cells.append(f"**{_fmt_pct(r.total_return)}**")
    cells.append(f"**{_fmt_pct(results[0].bh_total_return)}**" if results else "-")
    return "| " + " | ".join(cells) + " |"


def _metrics_table(results: List[BacktestResult]) -> str:
    strat_names = [r.strategy_name for r in results]
    header = "|  | " + " | ".join(strat_names) + " | B&H |"
    sep = "|---" + "|---" * (len(strat_names) + 1) + "|"

    rows = [header, sep]

    def add(label: str, values: List[str]):
        rows.append(f"| {label} | " + " | ".join(values) + " |")

    add("终值 ($)",
        [_fmt_money(r.equity_curve.iloc[-1] if not r.equity_curve.empty else 0) for r in results]
        + [_fmt_money(results[0].bh_equity_curve.iloc[-1] if not results[0].bh_equity_curve.empty else 0)])
    add("年化收益 CAGR (%)",
        [_fmt_pct(r.annualized_return) for r in results]
        + [_fmt_pct(results[0].bh_annualized_return)])
    add("最大回撤 (%)",
        [_fmt_pct(r.max_drawdown) for r in results]
        + [_fmt_pct(results[0].bh_max_drawdown)])
    add("交易次数（完整对）", [str(r.trade_count) for r in results] + ["-"])
    add("胜率 (%)",
        [_fmt_pct(r.win_rate) for r in results] + ["-"])
    add("未实现盈亏 ($)",
        [_fmt_money(r.unrealized_pnl) for r in results] + ["-"])

    return "\n".join(rows)


def _trade_log_full(result: BacktestResult) -> str:
    lines = [
        f"### 策略 {result.strategy_name}（{result.strategy_name.lower()} 周期，共 {len(result.trades)} 笔交易）",
        "",
        "| 日期 | 动作 | 价格 | 份额 | 桶内现金 | K 线 High | K 线 Low | MA20 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for t in result.trades:
        lines.append(
            f"| {t.date.date()} | {t.action} | {t.price:.4f} | {t.shares:.4f} "
            f"| {t.cash_after:.2f} | {t.bar_high:.4f} | {t.bar_low:.4f} | {t.bar_ma20:.4f} |"
        )
    return "\n".join(lines)


def render_index_report(results: List[BacktestResult]) -> str:
    if not results:
        return "# 空回测结果\n"
    first = results[0]

    winner_marks = [
        r.strategy_name for r in results if r.beats_bh
    ]
    winner_line = (
        f"- **跑赢 B&H 的策略**：{', '.join(winner_marks) if winner_marks else '无'}"
    )

    years = _all_years(results)
    year_rows = "\n".join(_year_row(y, results) for y in years)

    strat_names = [r.strategy_name for r in results]
    year_header = "| 年份 | " + " | ".join(strat_names) + " | 指数B&H |"
    year_sep = "|---" + "|---" * (len(strat_names) + 1) + "|"

    first_buy_verification = ""
    for r in results:
        buys = [t for t in r.trades if t.action == "BUY"]
        if buys:
            b = buys[0]
            clean_ok = "✓" if b.bar_low > b.bar_ma20 else "✗"
            first_buy_verification += (
                f"- **策略 {r.strategy_name}** 首笔 BUY：{b.date.date()} 价 {b.price:.2f}，"
                f"K 线 [{b.bar_low:.2f}, {b.bar_high:.2f}] vs MA20 {b.bar_ma20:.2f} → {clean_ok}\n"
            )

    trade_logs = "\n\n".join(_trade_log_full(r) for r in results)

    allocation_block = _render_allocation_block(results)

    content = f"""# {first.index_name} ({first.index_code}) 回测报告

> 类别：{first.index_category}

## 回测口径声明

- **评估起算日**：{first.evaluation_start.date()}
- **评估终止日**：{first.evaluation_end.date()}
- **起始资金**：$10,000（指数内部按 Calmar 权重在 D/W/M 间分配）
- **交易摩擦**：0
- **前置条件**：BUY 要求 shares==0，SELL 要求 shares>0
{winner_line}

## 开仓点核对

{first_buy_verification}

## 年度收益率对比（单位 %）

{year_header}
{year_sep}
{year_rows}
{_total_row(results)}

## 关键指标

{_metrics_table(results)}

## 推荐仓位分配（Calmar 权重 · $10k 本金）

{allocation_block}

## 完整交易日志

{trade_logs}
"""
    return content


def _render_allocation_block(results: List[BacktestResult]) -> str:
    """渲染单指数的仓位分配表。"""
    alloc = compute_allocation(results)

    lines = [
        "Calmar = CAGR / |最大回撤|；CAGR ≤ 0 的策略剔除；单策略上限 80%。",
        "",
        "| 策略 | CAGR | 最大回撤 | Calmar | 权重 | 分配金额 | 状态 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        a = alloc[r.strategy_name]
        if a["excluded"]:
            status = "❌ 剔除（CAGR ≤ 0）"
            weight_str = "-"
            amount_str = "$0"
            calmar_str = "-"
        else:
            status = "✓"
            weight_str = f"{a['weight'] * 100:.1f}%"
            amount_str = f"${a['amount']:,.2f}"
            calmar_str = f"{a['calmar']:.3f}"

        lines.append(
            f"| {r.strategy_name} | {_fmt_pct(r.annualized_return)} "
            f"| {_fmt_pct(r.max_drawdown)} | {calmar_str} "
            f"| {weight_str} | {amount_str} | {status} |"
        )

    active = [r.strategy_name for r in results if not alloc[r.strategy_name]["excluded"]]
    if not active:
        lines.append("")
        lines.append("> ⚠️ **所有策略 CAGR ≤ 0，不建议配置此指数。**")
    return "\n".join(lines)


# ---------- summary.md ----------

def _winners_of(results: List[BacktestResult]) -> List[str]:
    return [r.strategy_name for r in results if r.beats_bh]


def _min_gap(results: List[BacktestResult]) -> float:
    """败者的最小差距（最接近 B&H 的策略的负超额）。"""
    if not results:
        return 0.0
    return max(r.total_return - r.bh_total_return for r in results)


def render_cross_summary(all_results: Dict[str, List[BacktestResult]]) -> str:
    """赢家榜 + 败者榜 + 类别聚合。"""
    winners_entries: List[Tuple[str, List[BacktestResult]]] = []
    losers_entries: List[Tuple[str, List[BacktestResult]]] = []

    for code, results in all_results.items():
        if not results:
            continue
        if any(r.beats_bh for r in results):
            winners_entries.append((code, results))
        else:
            losers_entries.append((code, results))

    # 按最大超额收益排序赢家
    def winner_max_excess(entry):
        _, results = entry
        return max((r.total_return - r.bh_total_return) for r in results)

    winners_entries.sort(key=winner_max_excess, reverse=True)
    # 按最小差距排序败者（最接近跑赢的排前面）
    losers_entries.sort(key=lambda e: _min_gap(e[1]), reverse=True)

    lines: List[str] = []
    lines.append(f"# 全量指数回测汇总")
    lines.append("")
    lines.append(f"- 样本池：{len(all_results)} 个指数")
    lines.append(f"- 赢家（至少 1 策略跑赢 B&H）：{len(winners_entries)} 个")
    lines.append(f"- 败者（D/W/M 全部跑输 B&H）：{len(losers_entries)} 个")
    lines.append(f"- 评估起点：最晚 2016-01-01（新兴指数按实际基日）")
    lines.append(f"- 策略：D / W / M（单周期独立，各 $10k）")
    lines.append("")

    # 赢家榜
    lines.append(f"## 赢家榜（{len(winners_entries)}）")
    lines.append("")
    lines.append("| 指数名(代码) | 类别 | 评估区间 | D | W | M | B&H | 赢家策略 | 详细 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for code, results in winners_entries:
        first = results[0]
        by_n = {r.strategy_name: r for r in results}
        d, w, m = by_n.get("D"), by_n.get("W"), by_n.get("M")
        winners_str = "+".join(_winners_of(results))
        lines.append(
            f"| {first.index_name}({code}) | {first.index_category} "
            f"| {first.evaluation_start.date()}~{first.evaluation_end.date()} "
            f"| {_fmt_pct(d.total_return) if d else '-'} "
            f"| {_fmt_pct(w.total_return) if w else '-'} "
            f"| {_fmt_pct(m.total_return) if m else '-'} "
            f"| {_fmt_pct(first.bh_total_return)} "
            f"| {winners_str} "
            f"| [查看]({code}.md) |"
        )

    # 败者榜
    lines.append("")
    lines.append(f"## 败者榜（{len(losers_entries)}，不生成详细 md）")
    lines.append("")
    lines.append("| 指数名(代码) | 类别 | 评估区间 | D | W | M | B&H | 最小差距 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for code, results in losers_entries:
        first = results[0]
        by_n = {r.strategy_name: r for r in results}
        d, w, m = by_n.get("D"), by_n.get("W"), by_n.get("M")
        gap = _min_gap(results)
        lines.append(
            f"| {first.index_name}({code}) | {first.index_category} "
            f"| {first.evaluation_start.date()}~{first.evaluation_end.date()} "
            f"| {_fmt_pct(d.total_return) if d else '-'} "
            f"| {_fmt_pct(w.total_return) if w else '-'} "
            f"| {_fmt_pct(m.total_return) if m else '-'} "
            f"| {_fmt_pct(first.bh_total_return)} "
            f"| {_fmt_diff(gap)} |"
        )

    # 类别聚合
    by_cat: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "winner": 0})
    for code, results in all_results.items():
        if not results:
            continue
        cat = results[0].index_category
        by_cat[cat]["total"] += 1
        if any(r.beats_bh for r in results):
            by_cat[cat]["winner"] += 1

    lines.append("")
    lines.append("## 按类别聚合")
    lines.append("")
    lines.append("| 类别 | 样本数 | 赢家数 | 赢家比例 |")
    lines.append("|---|---|---|---|")
    for cat, stats in sorted(by_cat.items(), key=lambda x: -x[1]["winner"]):
        total = stats["total"]
        winner = stats["winner"]
        pct = f"{winner / total * 100:.1f}%" if total else "-"
        lines.append(f"| {cat} | {total} | {winner} | {pct} |")

    # 推荐仓位分配表（仅赢家）
    lines.append("")
    lines.append("## 推荐仓位分配表（赢家指数，Calmar 权重，每指数 $10k）")
    lines.append("")
    lines.append("| 指数(代码) | 类别 | D 权重 | D 金额 | W 权重 | W 金额 | M 权重 | M 金额 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for code, results in winners_entries:
        first = results[0]
        by_n = {r.strategy_name: r for r in results}
        alloc = compute_allocation(results)

        def cell(name: str) -> Tuple[str, str]:
            if name not in by_n:
                return "-", "-"
            a = alloc[name]
            if a["excluded"]:
                return "❌", "$0"
            return f"{a['weight'] * 100:.1f}%", f"${a['amount']:,.0f}"

        d_w, d_a = cell("D")
        w_w, w_a = cell("W")
        m_w, m_a = cell("M")
        lines.append(
            f"| {first.index_name}({code}) | {first.index_category} "
            f"| {d_w} | {d_a} | {w_w} | {w_a} | {m_w} | {m_a} |"
        )

    lines.append("")
    lines.append(
        f"_分配算法：CAGR ≤ 0 剔除 → Calmar = CAGR/|MDD| 正比归一化 → 单策略上限 {int(MAX_SINGLE_WEIGHT * 100)}%。_"
    )
    lines.append("_详细交易日志见各赢家的单指数 md。_")
    return "\n".join(lines)


# ---------- 写入 ----------

def write_reports(
    all_results: Dict[str, List[BacktestResult]],
    output_dir: Path,
) -> Tuple[int, int]:
    """写入报告。返回 (赢家数, 败者数)。"""
    output_dir.mkdir(parents=True, exist_ok=True)

    winners = 0
    losers = 0
    for code, results in all_results.items():
        if not results:
            continue
        if any(r.beats_bh for r in results):
            (output_dir / f"{code}.md").write_text(render_index_report(results), encoding="utf-8")
            winners += 1
        else:
            losers += 1

    (output_dir / "summary.md").write_text(render_cross_summary(all_results), encoding="utf-8")
    return winners, losers
