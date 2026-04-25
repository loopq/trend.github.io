"""pytest fixtures shared across quant tests.

约定：
- 所有 fixture 写入 tmp_path，不污染真仓库
- 时间相关 fixture 全部固定到 2026-04-25 14:48 UTC+8
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture
def quant_config_path() -> Path:
    return PROJECT_ROOT / "scripts" / "quant" / "config.yaml"


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """临时 data/quant 根目录，含三个标准子目录。"""
    root = tmp_path / "data" / "quant"
    for sub in ("cache", "signals", "notify-outbox"):
        (root / sub).mkdir(parents=True)
    return root


@pytest.fixture
def write_json():
    """方便测试用例写入 fixture json。"""
    def _w(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return _w
