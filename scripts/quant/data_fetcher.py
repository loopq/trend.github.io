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


class DataAvailabilityError(Exception):
    """缺数 ≥ 阈值时抛出（review H-8 降级策略）。"""


class AkShareFetcher:  # pragma: no cover -- 联网，本地走通模式不跑
    """生产版（调用 akshare 实时全量行情 + 主备源 fallback + 缺失阈值检查）。

    降级策略矩阵（mvp-plan §6 / deployment-plan §一.6）：
    - 单个指数缺失：跳过该指数，其他继续
    - 主源（cs_index/stock_zh_index_spot_em）失败 → 切备用 sina（stock_zh_index_daily 拼最新）
    - 主备双源都失败 + 缺失 ≥ 阈值（5/13）→ 抛 DataAvailabilityError
    """

    def __init__(self, missing_threshold_indices: int = 5, missing_threshold_etfs: int = 8) -> None:
        self.missing_threshold_indices = missing_threshold_indices
        self.missing_threshold_etfs = missing_threshold_etfs

    def _ts(self) -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    def fetch_indices(self, codes: list[str]) -> dict[str, RealtimeQuote]:
        out: dict[str, RealtimeQuote] = {}
        # 主源：东财
        try:
            import akshare as ak
            df = ak.stock_zh_index_spot_em()
            for code in codes:
                row = df[df["代码"] == code]
                if row.empty:
                    continue
                out[code] = RealtimeQuote(
                    code=code,
                    name=row["名称"].iloc[0],
                    price=float(row["最新价"].iloc[0]),
                    change_pct=float(row["涨跌幅"].iloc[0]),
                    timestamp=self._ts(),
                )
        except Exception as e:
            print(f"warning: 主源 stock_zh_index_spot_em 失败: {e}", file=__import__("sys").stderr)

        # 备用源：sina（仅对主源缺失的指数）
        missing = [c for c in codes if c not in out]
        if missing:
            try:
                import akshare as ak
                for code in missing:
                    # 新浪需要 sh/sz 前缀（参考 scripts/data_fetcher.py 的 SINA_EXCHANGE_CODES）
                    sina_code = self._to_sina_symbol(code)
                    if not sina_code:
                        continue
                    df = ak.stock_zh_index_daily(symbol=sina_code)
                    if df.empty:
                        continue
                    last = df.iloc[-1]
                    out[code] = RealtimeQuote(
                        code=code,
                        name=code,  # 备用源没拿到名称
                        price=float(last["close"]),
                        change_pct=0.0,
                        timestamp=self._ts(),
                    )
            except Exception as e:
                print(f"warning: 备用源 sina 失败: {e}", file=__import__("sys").stderr)

        # 阈值检查
        missing = [c for c in codes if c not in out]
        if len(missing) >= self.missing_threshold_indices:
            raise DataAvailabilityError(
                f"指数缺失 {len(missing)}/{len(codes)} ≥ 阈值 {self.missing_threshold_indices}: {missing}"
            )
        return out

    def _to_sina_symbol(self, code: str) -> str | None:
        # 简化版：00/30/39 开头 → sz；60 开头 → sh；其他暂略
        if code.startswith(("00", "30", "39")):
            return f"sz{code}"
        if code.startswith("60"):
            return f"sh{code}"
        return None

    def fetch_etfs(self, codes: list[str]) -> dict[str, RealtimeQuote]:
        out: dict[str, RealtimeQuote] = {}
        try:
            import akshare as ak
            df = ak.fund_etf_spot_em()
            for code in codes:
                row = df[df["代码"] == code]
                if row.empty:
                    continue
                out[code] = RealtimeQuote(
                    code=code,
                    name=row["名称"].iloc[0],
                    price=float(row["最新价"].iloc[0]),
                    change_pct=float(row["涨跌幅"].iloc[0]),
                    timestamp=self._ts(),
                )
        except Exception as e:
            print(f"warning: fund_etf_spot_em 失败: {e}", file=__import__("sys").stderr)

        missing = [c for c in codes if c not in out]
        if len(missing) >= self.missing_threshold_etfs:
            raise DataAvailabilityError(
                f"ETF 缺失 {len(missing)}/{len(codes)} ≥ 阈值 {self.missing_threshold_etfs}: {missing}"
            )
        return out
