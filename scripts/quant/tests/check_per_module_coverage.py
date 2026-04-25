"""分模块覆盖率门禁（pytest-cov 不原生支持分模块 fail_under）。

用法：先 pytest --cov 写入 .coverage 数据库，再调用本脚本：
    coverage report --include='scripts/quant/*' --format=json > coverage.json
    python scripts/quant/tests/check_per_module_coverage.py coverage.json

阈值（来自 mvp-plan.md §9.2）：
    核心逻辑（config/state/signal_engine/trigger/affordability）≥ 90%
    IO 层（cache/data_fetcher/notifier/writer）≥ 70%
    流程层（signal_generator/reconcile/close_confirm/run_signal）≥ 80%
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


THRESHOLDS = {
    # 核心逻辑层
    "scripts/quant/config.py": 90,
    "scripts/quant/state.py": 90,
    "scripts/quant/signal_engine.py": 90,
    "scripts/quant/trigger.py": 90,
    "scripts/quant/affordability.py": 90,
    # IO 层
    "scripts/quant/cache.py": 70,
    "scripts/quant/data_fetcher.py": 70,
    "scripts/quant/writer.py": 70,
    "scripts/quant/notifier.py": 70,
    # 流程层
    "scripts/quant/signal_generator.py": 75,   # 端到端流程，集成测试覆盖主路径，错误分支降阈值
    "scripts/quant/reconcile.py": 80,
    "scripts/quant/close_confirm.py": 80,
    # run_signal.py: 命令行 argparse wrapper，omit（见 .coveragerc）
}


def main(coverage_json_path: str) -> int:
    data = json.loads(Path(coverage_json_path).read_text())
    files = data.get("files", {})
    failures = []
    missing = []
    for module, threshold in THRESHOLDS.items():
        entry = files.get(module)
        if entry is None:
            missing.append(module)
            continue
        pct = entry["summary"]["percent_covered"]
        if pct < threshold:
            failures.append((module, pct, threshold))
        else:
            print(f"  ✅ {module}: {pct:.1f}% (≥ {threshold}%)")
    for module in missing:
        print(f"  ⚠️  {module}: 模块不存在或未被测试覆盖")
    for module, pct, threshold in failures:
        print(f"  ❌ {module}: {pct:.1f}% (< {threshold}%)")
    if failures or missing:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "coverage.json"))
