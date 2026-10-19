"""独立 oracle：按业务定义直接用 pandas 计算页面每一格应显示的文本。
刻意不调用 Calculator / Generator，用于端到端校验「页面展示的数据是对的」。"""
from typing import Dict, List, Optional, Tuple

import pandas as pd

LOOKBACK = 250  # 状态转变回溯根数（config.yaml lookback_days）


def _period_status(close: pd.Series, rule: str) -> str:
    bars = close.resample(rule).last().dropna()
    if len(bars) < 20:
        return "-"
    return "YES" if bars.iloc[-1] >= bars.iloc[-20:].mean() else "NO"


def _pct(x: float, signed: bool = False) -> str:
    return ("%+.2f%%" if signed else "%.2f%%") % (x * 100)


def index_row(df: Optional[pd.DataFrame]) -> Dict:
    """单指数个体指标。返回 {"cells": {列名: 文本}, "dev", "prev_dev", "status", "extreme", "error"}"""
    if df is None or len(df) == 0:
        return {"error": "数据异常"}
    if len(df) < 20:
        return {"error": "数据不足"}
    s = df.sort_values("date").set_index("date")
    close, ma = s["close"], s["close"].rolling(20).mean()
    above = close >= ma
    n, c, m = len(close), close.iloc[-1], ma.iloc[-1]

    status = "YES" if above.iloc[-1] else "NO"
    arrow = ""
    if n >= 21 and above.iloc[-2] != above.iloc[-1]:
        arrow = " 🔼" if above.iloc[-1] else " 🔽"

    # 最近一次状态转变：回溯窗口内最后一个状态不同的交易日的下一交易日
    flips = [i for i in range(max(n - LOOKBACK, 20), n - 1) if above.iloc[i] != above.iloc[-1]]
    if flips:
        j = flips[-1] + 1
        change_date, interval = close.index[j].strftime("%y.%m.%d"), _pct(c / ma.iloc[j] - 1)
    else:
        change_date, interval = "未查询到", "-"

    vol = s["volume"]
    avg5 = vol.iloc[-6:-1].mean()
    vr = vol.iloc[-1] / avg5 if avg5 else None

    extreme = None
    if n >= 22:
        last3 = range(n - 3, n)
        if all(close.iloc[i] >= ma.iloc[i] and s["low"].iloc[i] > ma.iloc[i] for i in last3):
            extreme = "极强"
        elif all(close.iloc[i] < ma.iloc[i] and s["high"].iloc[i] < ma.iloc[i] for i in last3):
            extreme = "极弱"

    weekly, monthly = _period_status(close, "W-SUN"), _period_status(close, "ME")
    cells = {
        "状态": status + arrow,
        "涨幅%": _pct(c / close.iloc[-2] - 1, signed=True),
        "现价": "%.2f" % c,
        "临界值点": "%.2f" % m,
        "偏离率": _pct(c / m - 1),
        "量比": "%.2f" % vr if vr else "-",
        "状态转变时间": change_date,
        "区间涨幅%": interval,
        "走势": "",
        "周月状态": f"{weekly} - {monthly}",
    }
    prev_dev = close.iloc[-2] / ma.iloc[-2] - 1 if n >= 21 else None
    return {"cells": cells, "dev": c / m - 1, "prev_dev": prev_dev, "status": status,
            "extreme": extreme, "error": None}


def group(members: List[Tuple[str, str, Optional[pd.DataFrame]]]) -> Tuple[Dict[str, Dict], Tuple[int, int]]:
    """同组指数（配置顺序）→ ({代码: {列名: 文本}}, (空头%, 多头%))；组内指标依赖整组输入"""
    rows = [(i, code, name, index_row(df)) for i, (code, name, df) in enumerate(members)]
    valid = [r for r in rows if not r[3]["error"]]
    ranked = sorted(valid, key=lambda r: (-r[3]["dev"], r[0])) + [r for r in rows if r[3]["error"]]
    rank = {r[1]: k for k, r in enumerate(ranked, 1)}
    with_prev = sorted((r for r in valid if r[3]["prev_dev"] is not None), key=lambda r: (-r[3]["prev_dev"], r[0]))
    prev_rank = {r[1]: k for k, r in enumerate(with_prev, 1)}

    out = {}
    for _, code, name, row in rows:
        head = {"趋势强度": f"{rank[code]} {row['extreme']}" if row.get("extreme") else str(rank[code]),
                "代码": code, "名称": name}
        if row["error"]:
            out[code] = {**head, "状态": row["error"]}
            continue
        change = prev_rank[code] - rank[code] if code in prev_rank else None
        change_s = "-" if change is None else (f"+{change}" if change > 0 else str(change))
        out[code] = {**head, **row["cells"], "强度变化": change_s}

    bull = sum(1 for r in valid if r[3]["status"] == "YES")
    bull_ratio = round(bull / len(valid) * 100) if valid else 50
    return out, (100 - bull_ratio, bull_ratio)
