"""组件化策略框架。

用法：
    from scripts.backtest.strategy import Strategy, get
    strat = get("v9-baseline")
"""
from scripts.backtest.strategy.protocol import (
    Decider,
    Filter,
    FilterContext,
    Signal,
    Strategy,
)
from scripts.backtest.strategy.registry import (
    register,
    get,
    list_all,
)

__all__ = [
    "Decider", "Filter", "FilterContext", "Signal", "Strategy",
    "register", "get", "list_all",
]
