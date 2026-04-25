"""数据拉取层（实时全量行情 + 历史日线）。

设计：抽象成 `RealtimeFetcher` Protocol，方便 mock。
- 默认实现：调 AkShare 实时全量
- 测试实现：从 fixture JSON 读

mvp-plan §3.5.1 规定本地走通模式必须 mock 实时行情。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class RealtimeQuote:
    code: str           # 指数代码或 ETF 代码
    name: str
    price: float        # 当前实时价
    change_pct: float   # 涨跌幅 %
    timestamp: str      # ISO8601


class RealtimeFetcher(Protocol):
    def fetch_indices(self, codes: list[str]) -> dict[str, RealtimeQuote]: ...
    def fetch_etfs(self, codes: list[str]) -> dict[str, RealtimeQuote]: ...


class FixtureFetcher:
    """从 JSON fixture 读实时报价（测试用）。

    fixture 格式：
        {
            "indices": {"399997": {"name": "中证白酒", "price": 1.234, "change_pct": 1.15, "timestamp": "..."}},
            "etfs":    {"161725": {"name": "招商中证白酒", "price": 1.236, "change_pct": 1.20, "timestamp": "..."}}
        }
    """

    def __init__(self, fixture_path: Path | str) -> None:
        raw = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
        self._raw = raw

    def _build(self, kind: str, codes: list[str]) -> dict[str, RealtimeQuote]:
        out: dict[str, RealtimeQuote] = {}
        section = self._raw.get(kind, {})
        for code in codes:
            entry = section.get(code)
            if entry is None:
                continue
            out[code] = RealtimeQuote(
                code=code,
                name=entry.get("name", code),
                price=float(entry["price"]),
                change_pct=float(entry.get("change_pct", 0.0)),
                timestamp=entry.get("timestamp", ""),
            )
        return out

    def fetch_indices(self, codes: list[str]) -> dict[str, RealtimeQuote]:
        return self._build("indices", codes)

    def fetch_etfs(self, codes: list[str]) -> dict[str, RealtimeQuote]:
        return self._build("etfs", codes)


class AkShareFetcher:  # pragma: no cover -- 联网，本地走通模式不跑
    """生产版（调用 akshare 实时全量行情）。

    由于 akshare 实时接口在测试中不应该被触发，本类的方法体保持精简，
    仅在上线模式被调用，覆盖率不计。
    """

    def fetch_indices(self, codes: list[str]) -> dict[str, RealtimeQuote]:
        import akshare as ak

        df = ak.stock_zh_index_spot_em()
        out: dict[str, RealtimeQuote] = {}
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        for code in codes:
            row = df[df["代码"] == code]
            if row.empty:
                continue
            out[code] = RealtimeQuote(
                code=code,
                name=row["名称"].iloc[0],
                price=float(row["最新价"].iloc[0]),
                change_pct=float(row["涨跌幅"].iloc[0]),
                timestamp=ts,
            )
        return out

    def fetch_etfs(self, codes: list[str]) -> dict[str, RealtimeQuote]:
        import akshare as ak

        df = ak.fund_etf_spot_em()
        out: dict[str, RealtimeQuote] = {}
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        for code in codes:
            row = df[df["代码"] == code]
            if row.empty:
                continue
            out[code] = RealtimeQuote(
                code=code,
                name=row["名称"].iloc[0],
                price=float(row["最新价"].iloc[0]),
                change_pct=float(row["涨跌幅"].iloc[0]),
                timestamp=ts,
            )
        return out
