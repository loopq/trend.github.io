"""纯计算：贴水、固定换月路径和按到期交易日配对的历史统计。"""
import numpy as np
import pandas as pd

from scripts.futures import PATHS, ROLES, SHOWN_ROLES, START, WINDOW


def rule_expiry(contract, calendar):
    month = pd.Timestamp(2000 + int(contract[2:4]), int(contract[4:]), 1)
    friday = month + pd.Timedelta(days=(4 - month.weekday()) % 7 + 14)
    if calendar.empty or friday < calendar[0] or friday > calendar[-1]:
        return None
    return calendar[calendar.searchsorted(friday)]


def targets(contract):
    month = pd.Period("20" + contract[2:], freq="M") + 1
    quarters = [month + i for i in range(1, 7) if (month + i).month % 3 == 0]
    return [contract[:2] + m.strftime("%y%m") for m in [month, *quarters[:2]]]


def _role_bars(data):
    bars = data["bars"]
    bars = bars[bars.date.between(START, data["as_of"])].copy()
    bars["expiry"] = bars.contract.map(data["expiry"])
    bars = bars.sort_values(["date", "expiry"])
    bars["role"] = bars.groupby("date").cumcount().map(dict(enumerate(ROLES)))
    return bars


def _history(data):
    bars = _role_bars(data)
    bars = bars[bars.role.isin(SHOWN_ROLES)]
    spots = data["spot"].set_index("date").close
    return [_basis_row(row, float(spots[row.date])) for row in bars.itertuples(index=False)]


def _basis_row(row, spot):
    days = (row.expiry - row.date).days
    basis = spot - float(row.close)
    return dict(date=row.date.strftime("%Y-%m-%d"), role=row.role, contract=row.contract,
                expiry=row.expiry.strftime("%Y-%m-%d"), days=days, close=float(row.close),
                basis=basis, monthly=basis / days * 30, annual=basis / spot * 365 / days * 100, oi=float(row.oi))


def _samples(history, role):
    return [r["monthly"] for r in history if r["role"] == role]


def _rank(value, samples):
    if value is None or not samples:
        return None
    return round(sum(x <= value for x in samples) / len(samples) * 100)


def daily_table(data):
    history = _history(data)
    today = data["as_of"].strftime("%Y-%m-%d")
    return [{**r, "percentile": _rank(r["monthly"], _samples(history, r["role"]))}
            for r in history if r["date"] == today]


def percentile_table(data):
    history = _history(data)
    rows = []
    for role in SHOWN_ROLES:
        samples = _samples(history, role)
        rows.append(dict(role=role, quantiles=np.percentile(samples, [10, 25, 50, 75, 90]).tolist(), n=len(samples)))
    return rows


def chart_series(data):
    history = _history(data)
    series = []
    for role in SHOWN_ROLES:
        rows = [r for r in history if r["role"] == role]
        series.append(dict(name=role, data=[r["monthly"] for r in rows], contracts=[r["contract"] for r in rows]))
    return dict(dates=sorted({r["date"] for r in history}), series=series,
                start=(data["as_of"] - pd.DateOffset(months=3)).strftime("%Y-%m-%d"))


def slope_series(data):
    bars = _role_bars(data).set_index(["date", "role"])
    close, contracts = bars.close.unstack("role"), bars.contract.unstack("role")
    # 相邻季月固定相隔三个月；贴水为正，不按到期自然日折算。
    values = (close["当季"] - close["下季"]) / 3 * 12 / close["当季"] * 100
    return dict(dates=close.index.strftime("%Y-%m-%d").tolist(), values=values.tolist(),
                near=contracts["当季"].tolist(), far=contracts["下季"].tolist())


def slope_summary(series, as_of):
    t = pd.Timestamp(as_of)
    rows = [(d, v, n, f) for d, v, n, f in zip(series["dates"], series["values"], series["near"], series["far"])
            if START <= d <= t.strftime("%Y-%m-%d")]
    year = (t - pd.DateOffset(years=1)).strftime("%Y-%m-%d")
    half = (t - pd.DateOffset(months=6)).strftime("%Y-%m-%d")
    current = rows[-1]
    # 序列按日期升序，max 遇到并列保留最早一日。
    deepest = max((r for r in rows if r[0] > half), key=lambda r: r[1])
    return dict(value=current[1], near=current[2], far=current[3],
                year_percentile=_rank(current[1], [r[1] for r in rows if r[0] > year]),
                percentile=_rank(current[1], [r[1] for r in rows]),
                deepest=deepest[1], deepest_date=deepest[0])


def _prices(data):
    return data["bars"].set_index(["date", "contract"]).close.to_dict()


def _spread(prices, expiry, day, source, target):
    near, far = prices.get((day, source)), prices.get((day, target))
    if near is None or far is None:
        return None
    return float((near - far) / (expiry[target] - expiry[source]).days * 30)


def roll_events(data):
    calendar, expiry, prices = data["calendar"], data["expiry"], _prices(data)
    events = []
    for source, end in sorted(expiry.items()):
        if not pd.Timestamp(START) < end <= data["as_of"]:
            continue
        position = calendar.get_loc(end)
        days = {n: calendar[position - n] for n in range(1, min(WINDOW, position) + 1)
                if calendar[position - n] >= pd.Timestamp(START)}
        values = {n: [_spread(prices, expiry, day, source, target) for target in targets(source)]
                  for n, day in days.items()}
        events.append(dict(contract=source, expiry=end.strftime("%Y-%m-%d"), values=values,
                           dates={n: d.strftime("%Y-%m-%d") for n, d in days.items()}))
    return events


def _paired_stats(events, day, slot):
    pairs = [(e["values"].get(day, [None] * 3)[slot], e["values"].get(1, [None] * 3)[slot]) for e in events]
    differences = [v - base for v, base in pairs if v is not None and base is not None]
    if not differences:
        return dict(delta=None, win_rate=None, n=None)
    win = sum(d > 0 for d in differences) / len(differences) * 100 if day != 1 else None
    return dict(delta=float(np.mean(differences)), win_rate=win, n=len(differences))


def roll_stats(events):
    return [dict(day=n, paths=[_paired_stats(events, n, i) for i in range(3)]) for n in range(1, WINDOW + 1)]


def best_roll(stats, slot):
    candidates = [{"day": r["day"], **r["paths"][slot]} for r in stats if r["paths"][slot]["n"]]
    return max(candidates, key=lambda r: (r["delta"], -r["day"])) if candidates else None


def _hint_path(source, target, slot, data, prices, events, n, estimated):
    value = _spread(prices, data["expiry"], data["as_of"], source, target)
    samples = [e["values"][n][slot] for e in events if n in e["values"] and e["values"][n][slot] is not None]
    comparable = not estimated and n <= WINDOW and value is not None
    return dict(path=PATHS[slot], contract=target, value=value,
                percentile=_rank(value, samples) if comparable else None, n=len(samples) if comparable else None)


def today_hint(data, events=None, stats=None):
    events = roll_events(data) if events is None else events
    stats = roll_stats(events) if stats is None else stats
    t, expiry, calendar = data["as_of"], data["expiry"], data["calendar"]
    active = data["bars"].loc[data["bars"].date == t, "contract"]
    source = min((c for c in active if expiry[c] > t), key=expiry.get)
    estimated = expiry[source] > calendar[-1]
    n = len(pd.bdate_range(t + pd.Timedelta(days=1), expiry[source])) if estimated else int(((calendar > t) & (calendar <= expiry[source])).sum())
    prices = _prices(data)
    paths = [_hint_path(source, target, i, data, prices, events, n, estimated) for i, target in enumerate(targets(source))]
    valid = [i for i, p in enumerate(paths) if p["value"] is not None]
    best = max(valid, key=lambda i: paths[i]["value"]) if valid else None
    return dict(contract=source, n=n, estimated=estimated, paths=paths, best_path=best,
                outside_window=not estimated and n > WINDOW, history=best_roll(stats, best) if best is not None else None)
