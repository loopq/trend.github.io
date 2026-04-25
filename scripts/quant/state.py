"""positions.json / transactions.json 状态机 + 严格不变量校验。

设计参考 mvp-plan.md §3.2 + §7.1 + §7.3 + §8.4。

核心原则（来自 §3.2）：
- BUY 前提：actual_state == CASH（且 shares == 0）
- SELL 前提：actual_state == HOLD（且必须全卖）
- 任一违反 → StateInvariantError（生产可被 -O 去除的 assert 不能用）
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .config import Config


SCHEMA_VERSION = 1


class StateInvariantError(Exception):
    """状态机不变量违反；bucket 级隔离，单 bucket 报错不影响其他 bucket。"""

    def __init__(self, bucket_id: str, reason: str) -> None:
        self.bucket_id = bucket_id
        self.reason = reason
        super().__init__(f"[{bucket_id}] {reason}")


@dataclass
class BucketPosition:
    index_code: str
    index_name: str
    etf_code: str
    etf_name: str
    calmar_weight: float
    initial_capital: float
    actual_state: str = "CASH"        # CASH | HOLD
    policy_state: str = "CASH"        # CASH | HOLD
    shares: int = 0
    avg_cost: float = 0.0
    cash: float = 0.0
    last_action_date: str | None = None
    last_action_type: str | None = None  # BUY | SELL


@dataclass
class PositionsBook:
    version: int = SCHEMA_VERSION
    updated_at: str = ""
    paper_trading: bool = True
    buckets: dict[str, BucketPosition] = field(default_factory=dict)


@dataclass
class Transaction:
    tx_id: str
    date: str
    bucket_id: str
    signal_id: str
    action: str          # BUY | SELL
    shares: int
    price: float
    amount: float
    fee: float
    external_funded: bool
    paper: bool
    note: str
    confirmed_at: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def init_positions(cfg: Config) -> PositionsBook:
    book = PositionsBook(updated_at=_now_iso(), paper_trading=True)
    for bucket in cfg.generate_buckets():
        spec = cfg.find_index(bucket.index_code)
        weight = spec.calmar_weights[bucket.frequency] or 0.0
        book.buckets[bucket.id] = BucketPosition(
            index_code=bucket.index_code,
            index_name=bucket.index_name,
            etf_code=bucket.etf_code,
            etf_name=bucket.etf_name,
            calmar_weight=weight,
            initial_capital=bucket.initial_capital,
            cash=bucket.initial_capital,
        )
    return book


def save_positions(book: PositionsBook, path: Path | str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": book.version,
        "updated_at": book.updated_at,
        "paper_trading": book.paper_trading,
        "buckets": {bid: asdict(b) for bid, b in book.buckets.items()},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def load_positions(path: Path | str) -> PositionsBook:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return PositionsBook(
        version=raw.get("version", SCHEMA_VERSION),
        updated_at=raw.get("updated_at", ""),
        paper_trading=raw.get("paper_trading", True),
        buckets={bid: BucketPosition(**v) for bid, v in raw.get("buckets", {}).items()},
    )


def save_transactions(txs: Iterable[Transaction], path: Path | str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"transactions": [asdict(t) for t in txs]}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def load_transactions(path: Path | str) -> list[Transaction]:
    p = Path(path)
    if not p.exists():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    return [Transaction(**t) for t in raw.get("transactions", [])]


def append_transaction(path: Path | str, tx: Transaction) -> None:
    txs = load_transactions(path)
    txs.append(tx)
    save_transactions(txs, path)


def apply_buy(
    book: PositionsBook,
    bucket_id: str,
    shares: int,
    price: float,
    fee: float,
    *,
    external_funded: bool = False,
    when: str | None = None,
) -> None:
    if shares <= 0:
        raise ValueError(f"shares must be positive, got {shares}")
    if bucket_id not in book.buckets:
        raise KeyError(bucket_id)
    b = book.buckets[bucket_id]
    if b.actual_state != "CASH":
        raise StateInvariantError(bucket_id, f"BUY 前 actual_state 必须 CASH, 当前 {b.actual_state}")
    cost = shares * price + fee
    if not external_funded and cost > b.cash + 1e-6:
        raise StateInvariantError(
            bucket_id, f"现金 {b.cash} 不足以买入成本 {cost}（external_funded=False）"
        )
    b.actual_state = "HOLD"
    b.shares = shares
    b.avg_cost = price
    b.cash -= cost
    b.last_action_date = when or _now_iso()[:10]
    b.last_action_type = "BUY"
    book.updated_at = _now_iso()


def apply_sell(
    book: PositionsBook,
    bucket_id: str,
    shares: int,
    price: float,
    fee: float,
    *,
    when: str | None = None,
) -> None:
    if shares <= 0:
        raise ValueError(f"shares must be positive, got {shares}")
    if bucket_id not in book.buckets:
        raise KeyError(bucket_id)
    b = book.buckets[bucket_id]
    if b.actual_state != "HOLD":
        raise StateInvariantError(bucket_id, f"SELL 前 actual_state 必须 HOLD, 当前 {b.actual_state}")
    if shares != b.shares:
        raise StateInvariantError(
            bucket_id, f"V9.2 全仓策略：SELL 必须卖光 {b.shares} 股，传入 {shares}"
        )
    proceeds = shares * price - fee
    b.actual_state = "CASH"
    b.shares = 0
    b.avg_cost = 0.0
    b.cash += proceeds
    b.last_action_date = when or _now_iso()[:10]
    b.last_action_type = "SELL"
    book.updated_at = _now_iso()


def validate_invariants(book: PositionsBook) -> list[str]:
    errors: list[str] = []
    for bid, b in book.buckets.items():
        if b.actual_state == "HOLD" and b.shares == 0:
            errors.append(f"[{bid}] actual_state=HOLD 但 shares=0")
        if b.actual_state == "CASH" and b.shares > 0:
            errors.append(f"[{bid}] actual_state=CASH 但 shares={b.shares}")
        if b.actual_state not in ("CASH", "HOLD"):
            errors.append(f"[{bid}] actual_state 非法值 {b.actual_state}")
        if b.policy_state not in ("CASH", "HOLD"):
            errors.append(f"[{bid}] policy_state 非法值 {b.policy_state}")
    return errors
