#!/usr/bin/env python3
# 一次性脚本：生成 2026-05-12 winner-filter HTML 报告
# - per-index winner：v9-baseline / faber-gtaa / donchian-200 三个 in/out 策略
# - portfolio 对照：6 策略 + virtual best mix（per-index 自由选最佳 → 等权 24 → 反推 CAGR）

import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List

RESULTS_DIR = Path(__file__).resolve().parent.parent.parent / "agents" / "results"
DETAILED_MD = RESULTS_DIR / "2026-05-11-detailed-5strats-on-combined-24.md"
COMPARE_MD = RESULTS_DIR / "2026-05-11-compare-v9-baseline-vs-faber-gtaa-vs-donchian-200-vs-dual-momentum-top5-vs-dual-momentum-w5w10-vs-dual-momentum-w5w10-stop20.md"
OUT_HTML = RESULTS_DIR / "2026-05-12-winner-filter-with-w5w10-stop20.html"

WINDOWS = ["3 年", "5 年", "8 年", "10 年"]
WINDOWS_YEARS = {"3 年": 3, "5 年": 5, "8 年": 8, "10 年": 10}

IN_OUT_STRATEGIES = ["v9-baseline", "faber-gtaa", "donchian-200"]
ALL_STRATEGIES = [
    "v9-baseline", "faber-gtaa", "donchian-200",
    "dual-momentum-top5", "dual-momentum-w5w10", "dual-momentum-w5w10-stop20",
]

UNIVERSE_GROUPS = {
    "沪深300": "A股宽基", "上证50": "A股宽基", "中证500": "A股宽基",
    "中证1000": "A股宽基", "中证2000": "A股宽基", "科创50": "A股宽基",
    "创业板50": "A股宽基",
    "光伏产业": "A股主题", "中证白酒": "A股主题", "中证医疗": "A股主题",
    "5G通信": "A股主题", "中证新能": "A股主题", "人工智能": "A股主题",
    "CS智汽车": "A股主题", "中证军工": "A股主题", "CS新能车": "A股主题",
    "有色金属": "A股行业", "细分化工": "A股行业",
    "恒生指数": "港股", "恒生科技": "港股",
    "纳指100": "美股", "标普500": "美股",
    "黄金现价": "商品", "白银现价": "商品",
}

UNIVERSE_ORDER = ["A股宽基", "A股主题", "A股行业", "港股", "美股", "商品"]


@dataclass
class PerfRow:
    cagr: float
    mdd: float
    total: float


@dataclass
class IndexPerf:
    name: str
    code: str
    data: Dict[str, Dict[str, PerfRow]] = field(default_factory=dict)


@dataclass
class WinnerEntry:
    index_name: str
    index_code: str
    universe: str
    window: str
    winner_strategy: str
    winner_cagr: float
    winner_mdd: float
    second_strategy: str
    second_cagr: float
    second_mdd: float
    delta_cagr: float
    delta_mdd: float
    tier: str  # 'big' / 'mid' / 'small'


# =============== Parsers ===============
def parse_detailed_md(text: str) -> Dict[str, IndexPerf]:
    indices: Dict[str, IndexPerf] = {}
    sections = re.split(r'^### ', text, flags=re.MULTILINE)
    for sec in sections:
        if not sec.strip():
            continue
        first_line = sec.split('\n', 1)[0].strip()
        if first_line not in IN_OUT_STRATEGIES:
            continue
        strategy = first_line
        for line in sec.split('\n'):
            line = line.strip()
            if not line.startswith('|') or '---' in line:
                continue
            if line.startswith('| 指数 |'):
                continue
            cells = [c.strip() for c in line.strip('|').split('|')]
            if len(cells) < 13:
                continue
            m = re.match(r'^(.+?)\(([^)]+)\)$', cells[0])
            if not m:
                continue
            name, code = m.group(1), m.group(2)
            key = f"{name}({code})"
            if key not in indices:
                indices[key] = IndexPerf(name=name, code=code)
            for i, window in enumerate(WINDOWS):
                cagr = float(cells[1 + i*3].replace('%', '').replace('+', ''))
                mdd = float(cells[2 + i*3].replace('%', '').replace('+', ''))
                total = float(cells[3 + i*3].replace('%', '').replace('+', ''))
                indices[key].data.setdefault(strategy, {})[window] = PerfRow(cagr, mdd, total)
    return indices


def parse_compare_md(text: str) -> Dict[str, Dict[str, PerfRow]]:
    result: Dict[str, Dict[str, PerfRow]] = {}
    in_section = False
    for line in text.split('\n'):
        line = line.strip()
        if line.startswith('## 一、组合层对比'):
            in_section = True
            continue
        if in_section and line.startswith('## '):
            break
        if not in_section:
            continue
        if not line.startswith('|') or '时间窗' in line or '---' in line:
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        if len(cells) < 5:
            continue
        window, strategy = cells[0], cells[1]
        if 'Δ' in strategy or window not in WINDOWS:
            continue
        cagr = float(cells[2].replace('%', '').replace('+', ''))
        mdd = float(cells[3].replace('%', '').replace('+', ''))
        total = float(cells[4].replace('%', '').replace('+', ''))
        result.setdefault(strategy, {})[window] = PerfRow(cagr, mdd, total)
    return result


# =============== Computation ===============
def compute_winners(indices: Dict[str, IndexPerf]) -> List[WinnerEntry]:
    entries: List[WinnerEntry] = []
    for idx in indices.values():
        for window in WINDOWS:
            perfs = []
            for strat in IN_OUT_STRATEGIES:
                if strat in idx.data and window in idx.data[strat]:
                    perfs.append((strat, idx.data[strat][window]))
            if len(perfs) < 2:
                continue
            perfs.sort(key=lambda x: x[1].cagr, reverse=True)
            ws, wp = perfs[0]
            ss, sp = perfs[1]
            dc = wp.cagr - sp.cagr
            dm = wp.mdd - sp.mdd
            if dc >= 5.0:
                tier = 'big'
            elif dc >= 2.0:
                tier = 'mid'
            else:
                tier = 'small'
            entries.append(WinnerEntry(
                index_name=idx.name, index_code=idx.code,
                universe=UNIVERSE_GROUPS.get(idx.name, '其它'),
                window=window,
                winner_strategy=ws, winner_cagr=wp.cagr, winner_mdd=wp.mdd,
                second_strategy=ss, second_cagr=sp.cagr, second_mdd=sp.mdd,
                delta_cagr=dc, delta_mdd=dm, tier=tier,
            ))
    entries.sort(key=lambda e: e.delta_cagr, reverse=True)
    return entries


def compute_virtual_best_mix(indices: Dict[str, IndexPerf]) -> Dict[str, Dict[str, float]]:
    """Returns: { window: {'cagr': %, 'total': %, 'n_indices': int} }"""
    result: Dict[str, Dict[str, float]] = {}
    for window in WINDOWS:
        years = WINDOWS_YEARS[window]
        totals = []
        for idx in indices.values():
            perfs = []
            for strat in IN_OUT_STRATEGIES:
                if strat in idx.data and window in idx.data[strat]:
                    perfs.append(idx.data[strat][window])
            if not perfs:
                continue
            best = max(perfs, key=lambda p: p.cagr)
            totals.append(best.total / 100.0)
        if not totals:
            continue
        mean_total = sum(totals) / len(totals)
        cagr = ((1 + mean_total) ** (1 / years) - 1) * 100
        result[window] = {'cagr': cagr, 'total': mean_total * 100, 'n_indices': len(totals)}
    return result


# =============== HTML Rendering ===============
STRATEGY_TAG_CLASSES = {
    "v9-baseline": "tag-baseline",
    "faber-gtaa": "tag-faber",
    "donchian-200": "tag-donchian",
    "dual-momentum-top5": "tag-dual",
    "dual-momentum-w5w10": "tag-w5w10",
    "dual-momentum-w5w10-stop20": "tag-stop20",
}


def strat_tag(strat: str) -> str:
    cls = STRATEGY_TAG_CLASSES.get(strat, "tag-baseline")
    return f'<span class="tag {cls}">{strat}</span>'


def fmt_pct(v: float) -> str:
    if abs(v) < 1e-9:
        return f'<span class="zero">{v:.2f}%</span>'
    sign = '+' if v > 0 else ''
    cls = 'pos' if v > 0 else 'neg'
    return f'<span class="{cls}">{sign}{v:.2f}%</span>'


def fmt_mdd(v: float) -> str:
    # MDD 永远 <= 0；越浅（接近 0）越好
    abs_v = abs(v)
    if abs_v < 15:
        cls = 'mdd-shallow'
    elif abs_v < 30:
        cls = 'mdd-mid'
    else:
        cls = 'mdd-deep'
    return f'<span class="{cls}">{v:.2f}%</span>'


def fmt_pp(v: float) -> str:
    if abs(v) < 0.01:
        return f'<span class="zero">{v:+.2f}pp</span>'
    sign = '+' if v > 0 else ''
    cls = 'pos' if v > 0 else 'neg'
    return f'<span class="{cls}">{sign}{v:.2f}pp</span>'


def render_tier_table(entries: List[WinnerEntry], tier: str) -> str:
    rows = [e for e in entries if e.tier == tier]
    if not rows:
        return '<p class="meta">（本档无数据）</p>'
    html = ['<table><thead><tr><th>子集</th><th>指数</th><th>窗口</th><th>Winner</th><th>Winner CAGR</th><th>Winner MDD</th><th>2nd 策略</th><th>2nd CAGR</th><th>ΔCAGR</th><th>ΔMDD</th></tr></thead><tbody>']
    for e in rows:
        html.append(
            f'<tr><td>{e.universe}</td>'
            f'<td><strong>{e.index_name}</strong> ({e.index_code})</td>'
            f'<td>{e.window}</td>'
            f'<td>{strat_tag(e.winner_strategy)}</td>'
            f'<td>{fmt_pct(e.winner_cagr)}</td>'
            f'<td>{fmt_mdd(e.winner_mdd)}</td>'
            f'<td>{strat_tag(e.second_strategy)}</td>'
            f'<td>{fmt_pct(e.second_cagr)}</td>'
            f'<td><strong>{fmt_pp(e.delta_cagr)}</strong></td>'
            f'<td>{fmt_pp(e.delta_mdd)}</td></tr>'
        )
    html.append('</tbody></table>')
    return '\n'.join(html)


def render_portfolio_table(portfolio: Dict[str, Dict[str, PerfRow]], vbest: Dict[str, Dict[str, float]]) -> str:
    cols = ALL_STRATEGIES + ['virtual best mix']
    th = ''.join(f'<th>{strat_tag(s) if s in STRATEGY_TAG_CLASSES else "🟣 " + s}</th>' for s in cols)
    html = [f'<table><thead><tr><th>窗口</th>{th}</tr></thead><tbody>']
    for window in WINDOWS:
        row = [f'<tr><td><strong>{window}</strong></td>']
        for s in ALL_STRATEGIES:
            p = portfolio.get(s, {}).get(window)
            if p is None:
                row.append('<td>-</td>')
            else:
                row.append(
                    f'<td>CAGR {fmt_pct(p.cagr)}<br>MDD {fmt_mdd(p.mdd)}<br>总 {fmt_pct(p.total)}</td>'
                )
        v = vbest.get(window)
        if v is None:
            row.append('<td>-</td>')
        else:
            row.append(f'<td>CAGR {fmt_pct(v["cagr"])}<br>总 {fmt_pct(v["total"])}<br><small>({int(v["n_indices"])} 指数)</small></td>')
        row.append('</tr>')
        html.append(''.join(row))
    html.append('</tbody></table>')
    return '\n'.join(html)


def render_alpha_table(portfolio: Dict[str, Dict[str, PerfRow]], vbest: Dict[str, Dict[str, float]]) -> str:
    """对比 3 个 dual-momentum 策略 vs virtual best mix"""
    dm_strats = ["dual-momentum-top5", "dual-momentum-w5w10", "dual-momentum-w5w10-stop20"]
    html = ['<table><thead><tr><th>窗口</th><th>策略</th><th>Portfolio CAGR</th><th>virtual best CAGR</th><th>Δ</th><th>解读</th></tr></thead><tbody>']
    for window in WINDOWS:
        v = vbest.get(window)
        if not v:
            continue
        vc = v['cagr']
        for s in dm_strats:
            p = portfolio.get(s, {}).get(window)
            if not p:
                continue
            d = p.cagr - vc
            if d >= 5:
                interp = '🚀 横截面 alpha 强力溢出（超越事后上限）'
            elif d >= 1:
                interp = '✅ 跑赢事后上限（横截面 alpha 真实）'
            elif d >= -2:
                interp = '≈ 接近持平（dual 已贴近 per-index 最优）'
            else:
                interp = '⚠️ 跑输事后上限（per-index 自由选更优）'
            html.append(
                f'<tr><td><strong>{window}</strong></td>'
                f'<td>{strat_tag(s)}</td>'
                f'<td>{fmt_pct(p.cagr)}</td>'
                f'<td>{fmt_pct(vc)}</td>'
                f'<td><strong>{fmt_pp(d)}</strong></td>'
                f'<td>{interp}</td></tr>'
            )
    html.append('</tbody></table>')
    return '\n'.join(html)


def render_winner_count_table(entries: List[WinnerEntry]) -> str:
    counts: Dict[str, Dict[str, int]] = {s: {'big': 0, 'mid': 0, 'small': 0} for s in IN_OUT_STRATEGIES}
    for e in entries:
        counts[e.winner_strategy][e.tier] += 1
    total_pts = len(entries)
    html = ['<table><thead><tr><th>策略</th><th>🏆 大幅（≥5pp）</th><th>🥈 中等（2-5pp）</th><th>📉 小幅（&lt;2pp）</th><th>合计 winner</th><th>占比</th></tr></thead><tbody>']
    for s in IN_OUT_STRATEGIES:
        c = counts[s]
        total = c['big'] + c['mid'] + c['small']
        pct = total / total_pts * 100 if total_pts else 0
        html.append(
            f'<tr><td>{strat_tag(s)}</td>'
            f'<td>{c["big"]}</td><td>{c["mid"]}</td><td>{c["small"]}</td>'
            f'<td><strong>{total}</strong></td><td>{pct:.1f}%</td></tr>'
        )
    html.append('</tbody></table>')
    return '\n'.join(html)


def render_style_tables(entries: List[WinnerEntry]) -> str:
    """风格倾向：universe × 窗口（仅 ≥2pp 领先）"""
    sig_entries = [e for e in entries if e.tier in ('big', 'mid')]
    # universe x strategy
    uni_count: Dict[str, Dict[str, int]] = {s: {u: 0 for u in UNIVERSE_ORDER} for s in IN_OUT_STRATEGIES}
    for e in sig_entries:
        if e.universe in UNIVERSE_ORDER:
            uni_count[e.winner_strategy][e.universe] += 1
    html = ['<h3>按 universe 子集（仅含 ≥ 2pp 领先组合）</h3>']
    html.append('<table><thead><tr><th>策略</th>' + ''.join(f'<th>{u}</th>' for u in UNIVERSE_ORDER) + '<th>合计</th></tr></thead><tbody>')
    for s in IN_OUT_STRATEGIES:
        cells = []
        total = 0
        for u in UNIVERSE_ORDER:
            c = uni_count[s][u]
            cells.append(f'<td>{c if c else "-"}</td>')
            total += c
        html.append(f'<tr><td>{strat_tag(s)}</td>' + ''.join(cells) + f'<td><strong>{total}</strong></td></tr>')
    html.append('</tbody></table>')

    # window x strategy
    win_count: Dict[str, Dict[str, int]] = {s: {w: 0 for w in WINDOWS} for s in IN_OUT_STRATEGIES}
    for e in sig_entries:
        win_count[e.winner_strategy][e.window] += 1
    html.append('<h3>按窗口（仅含 ≥ 2pp 领先组合）</h3>')
    html.append('<table><thead><tr><th>策略</th>' + ''.join(f'<th>{w}</th>' for w in WINDOWS) + '<th>合计</th></tr></thead><tbody>')
    for s in IN_OUT_STRATEGIES:
        cells = []
        total = 0
        for w in WINDOWS:
            c = win_count[s][w]
            cells.append(f'<td>{c if c else "-"}</td>')
            total += c
        html.append(f'<tr><td>{strat_tag(s)}</td>' + ''.join(cells) + f'<td><strong>{total}</strong></td></tr>')
    html.append('</tbody></table>')
    return '\n'.join(html)


def render_per_index_recommend(entries: List[WinnerEntry], indices: Dict[str, IndexPerf]) -> str:
    """每指数 × 4 窗口 winner + 主要风格"""
    # 按 universe 排序后按指数排
    by_index: Dict[str, Dict[str, WinnerEntry]] = {}
    for e in entries:
        key = f"{e.index_name}({e.index_code})"
        by_index.setdefault(key, {})[e.window] = e

    html = ['<table><thead><tr><th>子集</th><th>指数</th><th>3 年 Winner</th><th>5 年 Winner</th><th>8 年 Winner</th><th>10 年 Winner</th><th>主要风格</th></tr></thead><tbody>']
    # 按 universe 组排序
    keys_sorted = sorted(by_index.keys(), key=lambda k: (
        UNIVERSE_ORDER.index(UNIVERSE_GROUPS.get(k.split('(')[0], '其它'))
        if UNIVERSE_GROUPS.get(k.split('(')[0]) in UNIVERSE_ORDER else 99,
        k,
    ))
    for key in keys_sorted:
        wins = by_index[key]
        sample = next(iter(wins.values()))
        uni = sample.universe
        cells = []
        strat_count: Dict[str, int] = {}
        for w in WINDOWS:
            e = wins.get(w)
            if e is None:
                cells.append('<td>-</td>')
                continue
            icon = {'big': '🏆', 'mid': '🥈', 'small': '≈'}[e.tier]
            cells.append(f'<td>{icon} {strat_tag(e.winner_strategy)} <small>+{e.delta_cagr:.1f}pp</small></td>')
            # 仅 ≥ 2pp 算"明显胜出"
            if e.tier in ('big', 'mid'):
                strat_count[e.winner_strategy] = strat_count.get(e.winner_strategy, 0) + 1
        if not strat_count:
            style = '<span class="zero">无策略明显胜出 → baseline 即可</span>'
        else:
            best_strat = max(strat_count, key=lambda s: strat_count[s])
            n = strat_count[best_strat]
            if n == 4:
                style = f'全程 {strat_tag(best_strat)}'
            elif n >= 2:
                style = f'{strat_tag(best_strat)} × {n} 窗口'
            else:
                style = f'混合：{strat_tag(best_strat)}'
        name, code = key.split('(')
        code = code.rstrip(')')
        html.append(f'<tr><td>{uni}</td><td><strong>{name}</strong>({code})</td>' + ''.join(cells) + f'<td>{style}</td></tr>')
    html.append('</tbody></table>')
    return '\n'.join(html)


def render_full_winner_table(entries: List[WinnerEntry]) -> str:
    html = ['<table><thead><tr><th>排序</th><th>子集</th><th>指数</th><th>窗口</th><th>Winner</th><th>Winner CAGR</th><th>2nd</th><th>2nd CAGR</th><th>ΔCAGR</th><th>分级</th></tr></thead><tbody>']
    tier_tag = {'big': '<span class="tag tag-big">🏆 大幅</span>',
                'mid': '<span class="tag tag-mid">🥈 中等</span>',
                'small': '<span class="tag tag-small">📉 差距小</span>'}
    for i, e in enumerate(entries, 1):
        html.append(
            f'<tr><td>{i}</td><td>{e.universe}</td>'
            f'<td>{e.index_name}({e.index_code})</td>'
            f'<td>{e.window}</td>'
            f'<td>{strat_tag(e.winner_strategy)}</td>'
            f'<td>{fmt_pct(e.winner_cagr)}</td>'
            f'<td>{strat_tag(e.second_strategy)}</td>'
            f'<td>{fmt_pct(e.second_cagr)}</td>'
            f'<td>{fmt_pp(e.delta_cagr)}</td>'
            f'<td>{tier_tag[e.tier]}</td></tr>'
        )
    html.append('</tbody></table>')
    return '\n'.join(html)


def render_top_winners(entries: List[WinnerEntry], n: int = 10) -> str:
    """前 N 个大幅领先组合"""
    big = [e for e in entries if e.tier == 'big'][:n]
    html = ['<ol>']
    for e in big:
        html.append(
            f'<li><strong>{e.index_name}</strong>({e.index_code}) {e.window} → 用 {strat_tag(e.winner_strategy)} '
            f'CAGR {fmt_pct(e.winner_cagr)} / MDD {fmt_mdd(e.winner_mdd)}，'
            f'<strong>领先 {e.second_strategy}（{fmt_pct(e.second_cagr)}）{fmt_pp(e.delta_cagr)}</strong></li>'
        )
    html.append('</ol>')
    return '\n'.join(html)


# =============== Main HTML ===============
CSS = """:root {
  --c-bg: #fafbfc; --c-text: #1f2328; --c-muted: #656d76; --c-accent: #0969da;
  --c-border: #d0d7de; --c-code-bg: #f6f8fa; --c-warn: #bf8700; --c-warn-bg: #fff8c5;
  --c-success: #1a7f37; --c-success-bg: #dafbe1; --c-danger: #d1242f; --c-danger-bg: #ffebe9;
  --c-info-bg: #ddf4ff; --c-pos: #1a7f37; --c-neg: #d1242f;
}
* { box-sizing: border-box; }
body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
  font-size: 15px; line-height: 1.65; color: var(--c-text); background: var(--c-bg);
  max-width: 1280px; margin: 0 auto; padding: 28px 40px 80px; }
h1 { font-size: 26px; border-bottom: 2px solid var(--c-border); padding-bottom: 10px; margin-bottom: 8px; }
h2 { font-size: 21px; margin-top: 40px; padding-top: 12px; border-top: 1px solid var(--c-border); }
h3 { font-size: 17px; color: var(--c-accent); margin-top: 28px; margin-bottom: 6px; }
table { border-collapse: collapse; margin: 14px 0; font-size: 13px; width: 100%; }
th, td { border: 1px solid var(--c-border); padding: 7px 11px; text-align: left; vertical-align: top; white-space: nowrap; }
th { background: var(--c-code-bg); font-weight: 600; font-size: 12.5px; }
table tbody tr:hover { background: var(--c-info-bg); }
.meta { color: var(--c-muted); font-size: 13.5px; margin-top: 0; }
.pos { color: var(--c-pos); font-weight: 600; }
.neg { color: var(--c-neg); font-weight: 600; }
.zero { color: var(--c-muted); }
.mdd-shallow { color: var(--c-success); font-weight: 600; }
.mdd-mid { color: var(--c-warn); font-weight: 600; }
.mdd-deep { color: var(--c-neg); font-weight: 600; }
.tag { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 500; margin-right: 4px; white-space: nowrap; }
.tag-baseline { background: #e7f5ff; color: #1971c2; }
.tag-faber { background: #ffe3e3; color: #c92a2a; }
.tag-donchian { background: #d3f9d8; color: #2b8a3e; }
.tag-dual { background: #fff3bf; color: #b08800; }
.tag-w5w10 { background: #f3d9fa; color: #862e9c; font-weight: 600; }
.tag-stop20 { background: #ffd8a8; color: #d9480f; font-weight: 700; }
.tag-big { background: var(--c-success-bg); color: var(--c-success); font-weight: 600; }
.tag-mid { background: var(--c-info-bg); color: var(--c-accent); }
.tag-small { background: var(--c-code-bg); color: var(--c-muted); }
.callout { border-left: 4px solid var(--c-accent); background: var(--c-info-bg); padding: 12px 16px; margin: 14px 0; border-radius: 0 6px 6px 0; }
.callout-warn { border-left-color: var(--c-warn); background: var(--c-warn-bg); }
.callout-success { border-left-color: var(--c-success); background: var(--c-success-bg); }
.callout-danger { border-left-color: var(--c-danger); background: var(--c-danger-bg); }
nav.toc { background: var(--c-code-bg); padding: 14px 22px; border-radius: 6px; margin: 18px 0 24px; border: 1px solid var(--c-border); }
nav.toc h4 { margin: 0 0 6px; font-size: 13px; }
nav.toc ul { margin: 0; padding-left: 18px; columns: 2; column-gap: 28px; }
nav.toc li { margin: 2px 0; font-size: 13.5px; }
nav.toc a { color: var(--c-accent); text-decoration: none; }
nav.toc a:hover { text-decoration: underline; }
@media (max-width: 720px) {
  body { padding: 18px 16px 60px; font-size: 14px; }
  nav.toc ul { columns: 1; }
  table { font-size: 11.5px; } th, td { padding: 4px 6px; }
}
"""


def render_html(indices, portfolio, entries, vbest) -> str:
    # 统计
    n_total = len(entries)
    n_big = sum(1 for e in entries if e.tier == 'big')
    n_mid = sum(1 for e in entries if e.tier == 'mid')
    n_small = sum(1 for e in entries if e.tier == 'small')

    # stop20 vs w5w10 portfolio alpha 高亮
    stop20_vs_w5w10 = []
    for w in WINDOWS:
        p1 = portfolio.get('dual-momentum-w5w10', {}).get(w)
        p2 = portfolio.get('dual-momentum-w5w10-stop20', {}).get(w)
        if p1 and p2:
            stop20_vs_w5w10.append((w, p1, p2))

    html = []
    html.append('<!DOCTYPE html>')
    html.append('<html lang="zh-CN">')
    html.append('<head>')
    html.append('<meta charset="UTF-8">')
    html.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    html.append('<title>Winner 筛选 + Portfolio 对照 — 含 dual-momentum-w5w10-stop20</title>')
    html.append(f'<style>{CSS}</style>')
    html.append('</head>')
    html.append('<body>')
    html.append('<h1>Winner 筛选 + Portfolio 对照 — 含 dual-momentum-w5w10-stop20</h1>')
    html.append('<p class="meta"><strong>生成日</strong>: 2026-05-12 · <strong>per-index winner</strong>: v9-baseline / faber-gtaa / donchian-200（3 个 in/out 策略） · <strong>portfolio 对照</strong>: 6 策略 + virtual best mix · <strong>Universe</strong>: combined-24</p>')

    html.append('<div class="callout callout-success">')
    html.append('<strong>📌 本期更新</strong>：新增 <span class="tag tag-stop20">dual-momentum-w5w10-stop20</span>（w5w10 + portfolio -20% 止损 + peak reset），结束本轮 dual-momentum 调优。')
    html.append('<ul>')
    if stop20_vs_w5w10:
        for w, p1, p2 in stop20_vs_w5w10:
            d_cagr = p2.cagr - p1.cagr
            d_mdd = p2.mdd - p1.mdd
            html.append(f'<li><strong>{w}</strong>：CAGR {fmt_pct(p1.cagr)} → {fmt_pct(p2.cagr)}（<strong>{fmt_pp(d_cagr)}</strong>），MDD {fmt_mdd(p1.mdd)} → {fmt_mdd(p2.mdd)}（<strong>{fmt_pp(d_mdd)}</strong>）</li>')
    html.append('</ul>')
    html.append('</div>')

    html.append('<div class="callout callout-warn">')
    html.append('<strong>📋 报告范围</strong>：')
    html.append('<ul>')
    html.append('<li><strong>per-index winner 筛选</strong>：仅 3 个 in/out 策略参与（v9-baseline / faber-gtaa / donchian-200）。dual-momentum 系列是横截面 top-K 策略，无 per-index 持仓数据，不参与 per-index winner。</li>')
    html.append('<li><strong>portfolio 对照</strong>：6 策略全 + virtual best mix（per-index 自由选最佳的事后上限）。</li>')
    html.append('<li><strong>剔除</strong>：v9.3-bear（六重确认无效）已弃用。</li>')
    html.append('</ul>')
    html.append('</div>')

    # TOC
    html.append('<nav class="toc"><h4>目录</h4><ul>')
    html.append('<li><a href="#summary">一、筛选概览（lead 分级）</a></li>')
    html.append('<li><a href="#portfolio">二、Portfolio 对照（6 策略 + best mix）</a></li>')
    html.append('<li><a href="#big-lead">三、🏆 大幅领先（≥ 5pp）</a></li>')
    html.append('<li><a href="#mid-lead">四、🥈 中等领先（2-5pp）</a></li>')
    html.append('<li><a href="#strategy-summary">五、策略 winner 次数统计</a></li>')
    html.append('<li><a href="#strategy-style">六、策略风格倾向</a></li>')
    html.append('<li><a href="#index-best">七、每指数最佳策略推荐</a></li>')
    html.append('<li><a href="#full-table">八、全 (指数 × 窗口) 完整 winner 表</a></li>')
    html.append('<li><a href="#insights">九、关键洞察 + 实操建议</a></li>')
    html.append('</ul></nav>')

    # 一、筛选概览
    html.append('<h2 id="summary">一、筛选概览</h2>')
    html.append(f'<div class="callout"><strong>共 {n_total} 个 (指数 × 窗口) 数据点</strong>（24 指数 × 4 窗口 = 96，少数指数早期数据缺失）：<br>')
    html.append(f'• <span class="tag tag-big">🏆 大幅领先 ≥ 5pp</span> {n_big} 个（{n_big/n_total*100:.0f}%）<br>')
    html.append(f'• <span class="tag tag-mid">🥈 中等领先 2-5pp</span> {n_mid} 个（{n_mid/n_total*100:.0f}%）<br>')
    html.append(f'• <span class="tag tag-small">📉 差距小 &lt; 2pp</span> {n_small} 个（{n_small/n_total*100:.0f}%）</div>')

    # 二、Portfolio 对照
    html.append('<h2 id="portfolio">二、Portfolio 层对照（dual-momentum 真正发光的地方）</h2>')
    html.append('<div class="callout-warn callout">')
    html.append('<strong>⚠️ dual-momentum 系列在 per-index 维度下"看似全输"是误读</strong><br>')
    html.append('dual-momentum 是<strong>集中持仓 top-K 等分总资金</strong>策略——未被选中的月份 = cash idle = 0% CAGR，所以 per-index 维度从不胜出。')
    html.append('<br><strong>真正的 alpha 在 portfolio 层</strong>——下表对比 6 策略 portfolio CAGR/MDD 和"事后最优 per-index 组合 (virtual best mix)"。')
    html.append('</div>')

    html.append('<h3>6 策略 Portfolio CAGR / MDD / 总收益 × 4 窗口（vs virtual best mix）</h3>')
    html.append(render_portfolio_table(portfolio, vbest))

    html.append('<h3>🚀 dual-momentum 系列 vs virtual best mix（横截面 alpha 是否真实）</h3>')
    html.append(render_alpha_table(portfolio, vbest))

    # callout 总结
    html.append('<div class="callout-success callout">')
    html.append('<strong>📌 dual-momentum 系列 portfolio 层结论</strong>')
    html.append('<ul>')
    # 自动算
    for w in WINDOWS:
        v = vbest.get(w)
        if not v:
            continue
        vc = v['cagr']
        p_top5 = portfolio.get('dual-momentum-top5', {}).get(w)
        p_w5w10 = portfolio.get('dual-momentum-w5w10', {}).get(w)
        p_stop20 = portfolio.get('dual-momentum-w5w10-stop20', {}).get(w)
        parts = []
        if p_top5:
            parts.append(f'top5 {fmt_pp(p_top5.cagr - vc)}')
        if p_w5w10:
            parts.append(f'w5w10 {fmt_pp(p_w5w10.cagr - vc)}')
        if p_stop20:
            parts.append(f'w5w10-stop20 {fmt_pp(p_stop20.cagr - vc)}')
        html.append(f'<li><strong>{w}</strong>（best mix {fmt_pct(vc)}）：{"，".join(parts)}</li>')
    html.append('</ul>')
    html.append('</div>')

    # 三、大幅领先
    html.append('<h2 id="big-lead">三、🏆 大幅领先（ΔCAGR ≥ 5pp）</h2>')
    html.append(render_tier_table(entries, 'big'))

    # 四、中等领先
    html.append('<h2 id="mid-lead">四、🥈 中等领先（2-5pp）</h2>')
    html.append(render_tier_table(entries, 'mid'))

    # 五、winner 次数
    html.append('<h2 id="strategy-summary">五、策略 winner 次数统计</h2>')
    html.append(render_winner_count_table(entries))

    # 六、风格倾向
    html.append('<h2 id="strategy-style">六、策略风格倾向</h2>')
    html.append(render_style_tables(entries))

    # 七、每指数推荐
    html.append('<h2 id="index-best">七、每指数最佳策略推荐（综合 4 窗口）</h2>')
    html.append(render_per_index_recommend(entries, indices))

    # 八、完整表
    html.append('<h2 id="full-table">八、全 (指数 × 窗口) 完整 winner 表</h2>')
    html.append(render_full_winner_table(entries))

    # 九、insights
    html.append('<h2 id="insights">九、关键洞察 + 实操建议</h2>')
    html.append('<h3>核心结论</h3>')
    html.append('<ol>')
    pct_actionable = (n_big + n_mid) / n_total * 100
    counts_by_strat = {s: 0 for s in IN_OUT_STRATEGIES}
    for e in entries:
        if e.tier in ('big', 'mid'):
            counts_by_strat[e.winner_strategy] += 1
    sorted_strats = sorted(counts_by_strat.items(), key=lambda x: x[1], reverse=True)
    rank_str = ' → '.join(f'{strat_tag(s)} ({n})' for s, n in sorted_strats)
    html.append(f'<li><strong>{n_big + n_mid} / {n_total} = {pct_actionable:.0f}% 的数据点有可优化空间</strong>（≥ 2pp 领先）。</li>')
    html.append(f'<li><strong>winner 次数排名（≥ 2pp）</strong>：{rank_str}</li>')

    # dual-momentum 系列 portfolio alpha 一段话
    html.append('<li><strong>dual-momentum 系列 portfolio alpha（相对 virtual best mix）</strong>：')
    html.append('<ul>')
    for w in WINDOWS:
        v = vbest.get(w)
        if not v:
            continue
        vc = v['cagr']
        p_stop20 = portfolio.get('dual-momentum-w5w10-stop20', {}).get(w)
        if p_stop20:
            d = p_stop20.cagr - vc
            if d >= 5:
                tone = '🚀 大幅超越事后上限'
            elif d >= 1:
                tone = '✅ 跑赢事后上限'
            elif d >= -2:
                tone = '≈ 接近持平'
            else:
                tone = '⚠️ 跑输'
            html.append(f'<li>{w}：w5w10-stop20 {fmt_pp(d)} → {tone}</li>')
    html.append('</ul></li>')

    # stop20 的 MDD 改善
    html.append('<li><strong>dual-momentum-w5w10-stop20 vs w5w10 增量</strong>（止损 V2 效果）：')
    html.append('<ul>')
    for w, p1, p2 in stop20_vs_w5w10:
        d_cagr = p2.cagr - p1.cagr
        d_mdd = p2.mdd - p1.mdd
        html.append(f'<li>{w}：CAGR {fmt_pp(d_cagr)}，MDD {fmt_pp(d_mdd)}</li>')
    html.append('</ul></li>')
    html.append('</ol>')

    html.append('<h3>🏆 最值得记住的 winner 组合（top 10）</h3>')
    html.append(render_top_winners(entries, 10))

    html.append('<h3>实操建议</h3>')
    html.append('<div class="callout-success callout">')
    html.append('<strong>分级使用策略（per-index 维度）</strong>：')
    html.append('<ul>')
    html.append('<li>📌 <strong>大幅领先组合（🏆）</strong>：直接切到 winner 策略</li>')
    html.append('<li>📌 <strong>中等领先组合（🥈）</strong>：看 ΔMDD 决定切换</li>')
    html.append('<li>📌 <strong>差距小组合（📉）</strong>：保留 baseline 即可</li>')
    html.append('</ul>')
    html.append('</div>')

    html.append('<div class="callout callout-warn">')
    html.append('<strong>portfolio 维度选择</strong>：')
    html.append('<ul>')
    html.append('<li>📌 <strong>追求短期超额</strong>：dual-momentum-w5w10-stop20（3y CAGR +36%，MDD -11.4%，已是顶配）</li>')
    html.append('<li>📌 <strong>追求中长期稳健</strong>：dual-momentum-w5w10-stop20（5/8/10y MDD -28.8% 比 w5w10 -33.5% 浅 5pp，CAGR 还涨 1-1.6pp）</li>')
    html.append('<li>📌 <strong>追求绝对低回撤</strong>：v9-baseline（MDD 全窗口 -11~-15%），但牺牲 6-21pp CAGR</li>')
    html.append('</ul>')
    html.append('</div>')

    html.append('</body></html>')
    return '\n'.join(html)


# =============== Main ===============
def main():
    detailed_text = DETAILED_MD.read_text()
    compare_text = COMPARE_MD.read_text()

    indices = parse_detailed_md(detailed_text)
    portfolio = parse_compare_md(compare_text)
    entries = compute_winners(indices)
    vbest = compute_virtual_best_mix(indices)

    print(f"[parse] indices: {len(indices)}")
    print(f"[parse] portfolio strategies: {list(portfolio.keys())}")
    print(f"[compute] winner entries: {len(entries)}")
    print(f"[compute] virtual best mix: {vbest}")

    html = render_html(indices, portfolio, entries, vbest)
    OUT_HTML.write_text(html)
    print(f"[write] {OUT_HTML} ({len(html)} bytes)")


if __name__ == '__main__':
    main()
