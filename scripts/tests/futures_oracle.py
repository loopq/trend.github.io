"""独立期指 oracle：从原始输入按定义重算，不调用生产分析函数。"""
from collections import defaultdict
import calendar as month_calendar
from datetime import date, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd

ROLES = ["当月", "次月", "当季", "下季"]
SHOWN = (1, 2, 3)  # 当月不展示
PATHS = ["→次月", "→当季", "→下季"]
START = pd.Timestamp("2022-07-22")


def month_targets(code):
    year, month = 2000 + int(code[2:4]), int(code[4:])
    months = [(year + (month + i - 1) // 12, (month + i - 1) % 12 + 1) for i in range(1, 13)]
    selected = [months[0]] + [m for m in months[1:] if m[1] in (3, 6, 9, 12)][:2]
    return [f"{code[:2]}{y % 100:02}{m:02}" for y, m in selected]


def expiry_date(code, holidays=()):
    year, month = 2000 + int(code[2:4]), int(code[4:])
    fridays = [week[4] for week in month_calendar.monthcalendar(year, month) if week[4]]
    day = date(year, month, fridays[2])
    while day.weekday() >= 5 or day.isoformat() in holidays:
        day += timedelta(days=1)
    return pd.Timestamp(day)


@lru_cache(maxsize=8)
def synthetic(symbol="IC", end="2026-10-19"):
    holidays = [f"2026-10-{n:02}" for n in range(1, 9)]
    calendar = pd.bdate_range("2022-01-01", "2027-12-31").difference(pd.to_datetime(holidays))
    expiry = {f"{symbol}{y:02}{m:02}": expiry_date(f"{symbol}{y:02}{m:02}", holidays)
              for y in range(22, 28) for m in range(1, 13)}
    dates = calendar[(calendar >= START) & (calendar <= end)]
    rows, spots = [], []
    for i, day in enumerate(dates):
        c0 = min(c for c, e in expiry.items() if e >= day)
        spot = 6000 + (symbol == "IM") * 800 + i * .31 + np.sin(i / 8) * 30
        spots.append((day, spot))
        for j, code in enumerate([c0] + month_targets(c0)):
            days = (expiry[code] - day).days
            close = spot - days * (.8 + j * .12 + np.sin(i / 9 + j) * .2) - (i % 7)
            rows.append((day, code, close, 10000 + i * 3 + j))
    bars = pd.DataFrame(rows, columns=["date", "contract", "close", "oi"])
    used = set(bars.contract)
    return dict(symbol=symbol, as_of=pd.Timestamp(end), calendar=calendar,
                spot=pd.DataFrame(spots, columns=["date", "close"]), bars=bars,
                expiry={c: expiry[c] for c in used})


def patch_sources(monkeypatch, end="2026-10-19"):
    import akshare as ak
    from scripts.data_fetcher import DataFetcher
    datasets = {s: synthetic(s, end) for s in ("IC", "IM")}
    monkeypatch.setattr(ak, "tool_trade_date_hist_sina", lambda: pd.DataFrame({"trade_date": datasets["IC"]["calendar"]}))

    def official(date):
        t = pd.Timestamp(date)
        return pd.DataFrame([{"合约代码": c, "最后交易日": d["expiry"][c]}
                             for d in datasets.values() for c in d["bars"].loc[d["bars"].date == t, "contract"]])

    def futures(symbol):
        return datasets[symbol[:2]]["bars"].query("contract == @symbol").rename(columns={"oi": "hold"}).copy()

    def spot(self, code, source, **kwargs):
        assert source == "cs_index"
        symbol = "IM" if code == "000852" else "IC"
        return datasets[symbol]["spot"].copy()

    monkeypatch.setattr(ak, "futures_contract_info_cffex", official)
    monkeypatch.setattr(ak, "futures_zh_daily_sina", futures)
    monkeypatch.setattr(DataFetcher, "fetch_index", spot)
    return datasets


def num(value, fmt=".2f"):
    return "-" if value is None else format(value, fmt)


def compute(raw):
    t = raw["as_of"].date()
    expiry = {c: e.date() for c, e in raw["expiry"].items()}
    calendar = [d.date() for d in raw["calendar"]]
    days = [d for d in calendar if date(2022, 7, 22) <= d <= t]
    spots = {d.date(): p for d, p in raw["spot"][["date", "close"]].itertuples(index=False, name=None)}
    quotes = {(d.date(), c): (float(p), float(oi)) for d, c, p, oi in raw["bars"].itertuples(index=False, name=None) if d.date() <= t}
    listed = defaultdict(list)
    for day, code in quotes:
        listed[day].append(code)
    daily, samples, contracts = {}, [[] for _ in ROLES], {}
    for day in days:
        codes = sorted(listed[day], key=expiry.get)
        contracts[day] = codes
        for role, code in enumerate(codes):
            if role not in SHOWN:
                continue
            close, oi = quotes[day, code]
            remaining = (expiry[code] - day).days
            basis = spots[day] - close
            monthly = basis * 30 / remaining
            annual = basis / spots[day] * 36500 / remaining
            daily[day, role] = [ROLES[role], code, str(expiry[code]), remaining, close, basis, monthly, annual, oi]
            samples[role].append(monthly)
    current, quantiles = [], []
    for role in SHOWN:
        row, pool = daily[t, role], samples[role]
        rank = None if row[6] is None else round(100 * sum(v <= row[6] for v in pool) / len(pool))
        current.append([*map(str, row[:4]), *[num(v) for v in row[4:8]], num(rank, ".0f"), num(row[8], ".0f")])
        quantiles.append([ROLES[role], *[num(float(np.percentile(pool, p))) if pool else "-" for p in (10, 25, 50, 75, 90)], str(len(pool))])
    events = []
    for code, e in sorted(expiry.items()):
        if not date(2022, 7, 22) < e <= t:
            continue
        values = {}
        for n in range(1, 21):
            position = calendar.index(e) - n
            if position >= 0 and calendar[position] >= date(2022, 7, 22):
                day = calendar[position]
                values[n] = [spread(quotes, expiry, day, code, target) for target in month_targets(code)]
        events.append(values)
    stats, roll_cells = [], []
    for n in range(1, 21):
        paths = []
        for slot in range(3):
            pairs = [(e.get(n, [None] * 3)[slot], e.get(1, [None] * 3)[slot]) for e in events]
            differences = [v - baseline for v, baseline in pairs if v is not None and baseline is not None]
            paths.append(dict(delta=float(np.mean(differences)) if differences else None,
                              win_rate=100 * sum(d > 0 for d in differences) / len(differences) if differences and n != 1 else None,
                              n=len(differences) or None))
        stats.append(paths)
        roll_cells.append([str(n), *[num(p[k], ".0f" if k == "n" else ".2f") for p in paths for k in ("delta", "win_rate", "n")]])
    chart = dict(dates=[str(d) for d in days], series=[
        dict(name=role, data=[daily[d, i][6] for d in days], contracts=[contracts[d][i] for d in days])
        for i, role in enumerate(ROLES) if i in SHOWN], start=months_ago(t, 3))
    hint = hint_text(dict(as_of=t, expiry=expiry, calendar=calendar), quotes, contracts[t], events, stats)
    return dict(daily=current, percentiles=quantiles, roll=roll_cells, chart=chart, hint=hint)


def spread(quotes, expiry, day, source, target):
    if (day, source) not in quotes or (day, target) not in quotes:
        return None
    return (quotes[day, source][0] - quotes[day, target][0]) * 30 / (expiry[target] - expiry[source]).days


def hint_text(raw, quotes, codes, events, stats):
    t, expiry, calendar = raw["as_of"], raw["expiry"], raw["calendar"]
    source = min((c for c in codes if expiry[c] > t), key=expiry.get)
    estimated = calendar[-1] < expiry[source]
    n = sum((t + timedelta(days=i)).weekday() < 5 for i in range(1, (expiry[source] - t).days + 1)) if estimated else sum(t < d <= expiry[source] for d in calendar)
    remaining = f"约 {n} 个交易日（按工作日估计）" if estimated else f"{n} 个交易日"
    parts = [f"{source} 距到期 {remaining}；"]
    values = [spread(quotes, expiry, t, source, c) for c in month_targets(source)]
    for slot, target in enumerate(month_targets(source)):
        value = values[slot]
        parts.append(f"{PATHS[slot]} {target}：" + ("未上市" if value is None else f"{value:.2f} 点/月"))
        pool = [e[n][slot] for e in events if n in e and e[n][slot] is not None]
        if not estimated and n <= 20 and value is not None:
            rank = round(100 * sum(v <= value for v in pool) / len(pool)) if pool else None
            parts.append(f"（同期（到期前第 {n} 日）历史分位 {num(rank, '.0f')}%，n={len(pool)}）")
        parts.append("；")
    if not estimated and n > 20:
        parts.append("尚未进入统计窗口（≤20 个交易日）；")
    valid = [i for i, v in enumerate(values) if v is not None]
    if valid:
        best = max(valid, key=lambda i: values[i])
        candidates = [i for i in range(20) if stats[i][best]["n"]]
        if candidates:
            k = max(candidates, key=lambda i: stats[i][best]["delta"])
            s = stats[k][best]
            parts.append(f"历史上 {PATHS[best]} 平均最划算：到期前第 {k + 1} 个交易日（较第 1 日 {s['delta']:+.2f} 点/月，胜率 {num(s['win_rate'])}%，{s['n']} 次）")
    return "".join(parts)


def months_ago(day, months):
    month = day.year * 12 + day.month - 1 - months
    year, month = divmod(month, 12)
    month += 1
    return date(year, month, min(day.day, month_calendar.monthrange(year, month)[1])).isoformat()


def compute_slope(raw):
    t = raw["as_of"].date()
    days = [d.date() for d in raw["calendar"] if date(2022, 7, 22) <= d.date() <= t]
    quotes = defaultdict(dict)
    for day, code, close in raw["bars"][["date", "contract", "close"]].itertuples(index=False, name=None):
        quotes[day.date()][code] = float(close)
    values, near, far = [], [], []
    for day in days:
        codes = sorted(quotes[day], key=raw["expiry"].get)
        near.append(codes[2])
        far.append(codes[3])
        p, q = quotes[day][codes[2]], quotes[day][codes[3]]
        values.append((p - q) / 3 * 12 / p * 100)
    dates = [d.isoformat() for d in days]
    year = [v for d, v in zip(dates, values) if d > months_ago(t, 12)]
    half = [(v, d) for d, v in zip(dates, values) if d > months_ago(t, 6)]
    deepest = max(v for v, d in half)
    deepest_date = min(d for v, d in half if v == deepest)
    year_rank = round(sum(v <= values[-1] for v in year) / len(year) * 100)
    rank = round(sum(v <= values[-1] for v in values) / len(values) * 100)
    summary = dict(value=values[-1], near=near[-1], far=far[-1], year_percentile=year_rank,
                   percentile=rank, deepest=deepest, deepest_date=deepest_date)
    payload = dict(dates=dates, values=values, near=near, far=far, summary=summary)
    cells = [raw["symbol"], near[-1], far[-1], num(values[-1]), str(year_rank), str(rank),
             f"{deepest:.2f}%（{deepest_date}）"]
    return dict(payload=payload, cells=cells, start=months_ago(t, 12))
