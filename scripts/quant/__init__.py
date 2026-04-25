"""量化信号系统（基于 V9.2 13 指数 / 36 bucket 半自动）。

子模块：
- config / state / signal_engine / trigger / affordability：纯逻辑层
- cache / data_fetcher / writer / notifier：IO 层
- signal_generator / reconcile / close_confirm / run_signal：流程层

详细设计见 `docs/agents/quant/mvp-plan.md`。
"""
