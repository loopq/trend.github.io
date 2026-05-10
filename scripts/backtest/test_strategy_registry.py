"""注册表测试。运行：pytest scripts/backtest/test_strategy_registry.py -v"""
from __future__ import annotations

import pytest

from scripts.backtest.strategy import Strategy
from scripts.backtest.strategy.registry import register, get, list_all, _reset_for_test


class _DummyDecider:
    name = "dummy"
    def decide(self, *, cycle, bar, position_shares):
        return None


@pytest.fixture(autouse=True)
def _clean_registry():
    _reset_for_test()
    yield
    _reset_for_test()


def test_register_and_get():
    @register("foo")
    def _f():
        return Strategy(name="foo", decider=_DummyDecider())
    s = get("foo")
    assert s.name == "foo"


def test_register_duplicate_raises():
    @register("dup")
    def _f1():
        return Strategy(name="dup", decider=_DummyDecider())
    with pytest.raises(ValueError, match="dup"):
        @register("dup")
        def _f2():
            return Strategy(name="dup", decider=_DummyDecider())


def test_get_unknown_raises():
    with pytest.raises(KeyError, match="unknown"):
        get("unknown")


def test_list_all_returns_sorted_names():
    @register("b")
    def _b():
        return Strategy(name="b", decider=_DummyDecider())
    @register("a")
    def _a():
        return Strategy(name="a", decider=_DummyDecider())
    assert list_all() == ["a", "b"]
