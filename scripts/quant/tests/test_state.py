from __future__ import annotations

from pathlib import Path

import pytest

from scripts.quant.state import (
    PositionsBook,
    StateInvariantError,
    Transaction,
    apply_buy,
    apply_sell,
    init_positions,
    load_positions,
    load_transactions,
    save_positions,
    save_transactions,
    validate_invariants,
)
from scripts.quant.config import load_config


@pytest.fixture
def cfg(quant_config_path):
    return load_config(quant_config_path)


def test_init_positions_creates_36_buckets_all_cash(cfg) -> None:
    book = init_positions(cfg)
    assert len(book.buckets) == 36
    for bucket_id, b in book.buckets.items():
        assert b.actual_state == "CASH"
        assert b.policy_state == "CASH"
        assert b.shares == 0
        assert b.avg_cost == 0.0
        assert b.cash > 0  # 起始资金 > 0


def test_init_positions_capital_sum_equals_total(cfg) -> None:
    book = init_positions(cfg)
    total = sum(b.cash for b in book.buckets.values())
    # 总和 ≈ 13 × 10000 = 130000（部分 ❌ bucket 不入账，但权重在剩余里 ≈ 1.0）
    assert total == pytest.approx(130_000.0, rel=0.005)


def test_save_load_positions_roundtrip(cfg, tmp_data_dir) -> None:
    book = init_positions(cfg)
    path = tmp_data_dir / "positions.json"
    save_positions(book, path)
    book2 = load_positions(path)
    assert book.buckets.keys() == book2.buckets.keys()
    for bid in book.buckets:
        a, b = book.buckets[bid], book2.buckets[bid]
        assert a.actual_state == b.actual_state
        assert a.cash == b.cash


def test_apply_buy_cash_to_hold(cfg) -> None:
    book = init_positions(cfg)
    bucket = book.buckets["399997-D"]
    initial_cash = bucket.cash
    apply_buy(book, bucket_id="399997-D", shares=200, price=1.234, fee=0.025)
    b = book.buckets["399997-D"]
    assert b.actual_state == "HOLD"
    assert b.shares == 200
    assert b.avg_cost == 1.234
    assert b.cash == pytest.approx(initial_cash - 200 * 1.234 - 0.025, rel=1e-9)
    assert b.last_action_type == "BUY"


def test_apply_buy_when_already_hold_raises(cfg) -> None:
    book = init_positions(cfg)
    apply_buy(book, "399997-D", shares=200, price=1.234, fee=0.025)
    with pytest.raises(StateInvariantError):
        apply_buy(book, "399997-D", shares=100, price=1.5, fee=0.01)


def test_apply_sell_hold_to_cash(cfg) -> None:
    book = init_positions(cfg)
    apply_buy(book, "399997-D", shares=200, price=1.234, fee=0.025)
    cash_after_buy = book.buckets["399997-D"].cash
    apply_sell(book, bucket_id="399997-D", shares=200, price=1.300, fee=0.052)
    b = book.buckets["399997-D"]
    assert b.actual_state == "CASH"
    assert b.shares == 0
    assert b.avg_cost == 0.0
    assert b.cash == pytest.approx(cash_after_buy + 200 * 1.300 - 0.052, rel=1e-9)
    assert b.last_action_type == "SELL"


def test_apply_sell_when_cash_raises(cfg) -> None:
    book = init_positions(cfg)
    with pytest.raises(StateInvariantError):
        apply_sell(book, "399997-D", shares=200, price=1.234, fee=0.025)


def test_apply_sell_partial_shares_raises(cfg) -> None:
    """V9.2 全仓策略：SELL 必须卖光，部分卖出违反语义。"""
    book = init_positions(cfg)
    apply_buy(book, "399997-D", shares=200, price=1.234, fee=0.025)
    with pytest.raises(StateInvariantError):
        apply_sell(book, "399997-D", shares=100, price=1.300, fee=0.025)


def test_validate_invariants_detects_hold_with_zero_shares(cfg) -> None:
    book = init_positions(cfg)
    book.buckets["399997-D"].actual_state = "HOLD"
    book.buckets["399997-D"].shares = 0
    errors = validate_invariants(book)
    assert any("399997-D" in e for e in errors)


def test_validate_invariants_detects_cash_with_shares(cfg) -> None:
    book = init_positions(cfg)
    book.buckets["399997-D"].shares = 100  # actual_state 仍 CASH
    errors = validate_invariants(book)
    assert any("399997-D" in e for e in errors)


def test_validate_invariants_clean_book(cfg) -> None:
    book = init_positions(cfg)
    assert validate_invariants(book) == []


def test_save_load_transactions_roundtrip(tmp_data_dir) -> None:
    txs = [
        Transaction(
            tx_id="tx-2026-04-25-399997-D-001",
            date="2026-04-25",
            bucket_id="399997-D",
            signal_id="2026-04-25-399997-D",
            action="BUY",
            shares=200,
            price=1.236,
            amount=247.20,
            fee=0.025,
            external_funded=False,
            paper=True,
            note="",
            confirmed_at="2026-04-25T14:53:21+08:00",
        )
    ]
    path = tmp_data_dir / "transactions.json"
    save_transactions(txs, path)
    loaded = load_transactions(path)
    assert len(loaded) == 1
    assert loaded[0].tx_id == "tx-2026-04-25-399997-D-001"
    assert loaded[0].paper is True


def test_load_transactions_missing_returns_empty(tmp_data_dir) -> None:
    assert load_transactions(tmp_data_dir / "absent.json") == []


def test_apply_buy_unknown_bucket_raises(cfg) -> None:
    book = init_positions(cfg)
    with pytest.raises(KeyError):
        apply_buy(book, "999999-D", shares=100, price=1.0, fee=0.01)


def test_apply_buy_negative_shares_raises(cfg) -> None:
    book = init_positions(cfg)
    with pytest.raises(ValueError):
        apply_buy(book, "399997-D", shares=-100, price=1.234, fee=0.01)


def test_apply_buy_insufficient_cash_raises(cfg) -> None:
    book = init_positions(cfg)
    # 中证白酒 D 起始 7270；买 100 股 @ 100 元远超
    with pytest.raises(StateInvariantError):
        apply_buy(book, "399997-D", shares=100, price=100.0, fee=0.01)


def test_apply_buy_external_funded_bypasses_cash_check(cfg) -> None:
    """external_funded=True 允许 cash 转负（用户外部补充）。"""
    book = init_positions(cfg)
    apply_buy(book, "399997-D", shares=100, price=100.0, fee=0.01, external_funded=True)
    b = book.buckets["399997-D"]
    assert b.actual_state == "HOLD"
    assert b.cash < 0  # 外部资金补足
