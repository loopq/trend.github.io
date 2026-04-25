"""现金不足一手判定 + suggested_shares 计算（§3.2 + §10 Phase 1.5）。

A 股一手 = 100 股；bucket 现金不足以买一手时不忽略信号，标记 affordable=False + warning。
"""
from __future__ import annotations

from dataclasses import dataclass


LOT_SIZE = 100


@dataclass(frozen=True)
class Affordability:
    affordable: bool
    suggested_shares: int
    expected_cost: float
    min_lot_cost: float
    warning: str | None


def compute_affordability(bucket_cash: float, etf_price: float) -> Affordability:
    if etf_price <= 0:
        raise ValueError(f"etf_price must be > 0, got {etf_price}")

    min_lot_cost = etf_price * LOT_SIZE
    if bucket_cash < min_lot_cost:
        return Affordability(
            affordable=False,
            suggested_shares=0,
            expected_cost=0.0,
            min_lot_cost=round(min_lot_cost, 4),
            warning=(
                f"bucket 现金 ¥{bucket_cash:.2f} 不足一手 ¥{min_lot_cost:.2f}，"
                "建议跳过；如外部补充资金后下单，请勾选「外部补充资金」"
            ),
        )

    # 浮点精度：用 epsilon 容忍，避免 1234/123.4 = 9.9999... 被截断成 9
    full_lots = int((bucket_cash + 1e-6) // min_lot_cost)
    suggested = full_lots * LOT_SIZE
    expected_cost = suggested * etf_price
    return Affordability(
        affordable=True,
        suggested_shares=suggested,
        expected_cost=round(expected_cost, 4),
        min_lot_cost=round(min_lot_cost, 4),
        warning=None,
    )
