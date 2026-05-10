"""策略注册表。@register 装饰器 + get / list_all。"""
from __future__ import annotations

from typing import Callable, Dict, List

from scripts.backtest.strategy.protocol import Strategy

_FACTORIES: Dict[str, Callable[[], Strategy]] = {}


def register(name: str) -> Callable[[Callable[[], Strategy]], Callable[[], Strategy]]:
    def deco(factory: Callable[[], Strategy]) -> Callable[[], Strategy]:
        if name in _FACTORIES:
            raise ValueError(f"strategy {name!r} already registered")
        _FACTORIES[name] = factory
        return factory
    return deco


def get(name: str) -> Strategy:
    if name not in _FACTORIES:
        raise KeyError(f"unknown strategy: {name!r} (known: {sorted(_FACTORIES)})")
    return _FACTORIES[name]()


def list_all() -> List[str]:
    return sorted(_FACTORIES)


def _reset_for_test() -> None:
    """仅供测试夹具用。"""
    _FACTORIES.clear()
