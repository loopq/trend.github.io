"""现金不足一手判定 + suggested_shares 计算。"""
from __future__ import annotations

import pytest

from scripts.quant.affordability import compute_affordability


def test_affordable_buy_normal_case() -> None:
    # cash 1234，单价 1.234，一手 100 股 = 123.4 元
    aff = compute_affordability(bucket_cash=1234.0, etf_price=1.234)
    assert aff.affordable is True
    assert aff.min_lot_cost == pytest.approx(123.40)
    assert aff.suggested_shares == 1000  # 1234/123.4 = 10 手 = 1000 股
    assert aff.expected_cost == pytest.approx(1234.0)
    assert aff.warning is None


def test_affordable_with_round_down_to_full_lots() -> None:
    # cash 1300，单价 1.234，10.5 手 → 取整 10 手
    aff = compute_affordability(bucket_cash=1300.0, etf_price=1.234)
    assert aff.suggested_shares == 1000
    assert aff.expected_cost == pytest.approx(1234.0)


def test_not_affordable_when_cash_below_one_lot() -> None:
    # cash 80 < 一手 123.4
    aff = compute_affordability(bucket_cash=80.0, etf_price=1.234)
    assert aff.affordable is False
    assert aff.suggested_shares == 0
    assert aff.warning is not None
    assert "不足" in aff.warning or "不够" in aff.warning


def test_affordable_at_exactly_one_lot() -> None:
    aff = compute_affordability(bucket_cash=123.4, etf_price=1.234)
    assert aff.affordable is True
    assert aff.suggested_shares == 100


def test_affordable_zero_cash() -> None:
    aff = compute_affordability(bucket_cash=0.0, etf_price=1.234)
    assert aff.affordable is False
    assert aff.suggested_shares == 0


def test_affordable_zero_price_raises() -> None:
    with pytest.raises(ValueError):
        compute_affordability(bucket_cash=1000.0, etf_price=0.0)


def test_affordable_negative_price_raises() -> None:
    with pytest.raises(ValueError):
        compute_affordability(bucket_cash=1000.0, etf_price=-1.0)
