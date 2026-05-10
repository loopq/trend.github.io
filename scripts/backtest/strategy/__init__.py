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

__all__ = ["Decider", "Filter", "FilterContext", "Signal", "Strategy"]
