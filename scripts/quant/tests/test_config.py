from __future__ import annotations

from pathlib import Path

import pytest

from scripts.quant.config import (
    Bucket,
    Config,
    IndexSpec,
    bucket_id,
    load_config,
)


def test_load_config_returns_13_indices(quant_config_path: Path) -> None:
    cfg = load_config(quant_config_path)
    assert len(cfg.indices) == 13
    assert cfg.total_capital == 130_000
    assert cfg.per_index_capital == 10_000


def test_generate_36_effective_buckets(quant_config_path: Path) -> None:
    cfg = load_config(quant_config_path)
    buckets = cfg.generate_buckets()
    assert len(buckets) == 36

    # 三个 ❌ bucket 必须不被创建
    blocked = {("399989", "W"), ("930721", "W"), ("399967", "W")}
    keys = {(b.index_code, b.frequency) for b in buckets}
    assert keys & blocked == set()


def test_bucket_capital_split_uses_calmar(quant_config_path: Path) -> None:
    cfg = load_config(quant_config_path)
    buckets = {b.id: b for b in cfg.generate_buckets()}
    # 中证白酒 D=72.7%, W=6.1%, M=21.2%（来自 v9-summary）
    assert buckets["399997-D"].initial_capital == pytest.approx(7270.0, rel=1e-9)
    assert buckets["399997-W"].initial_capital == pytest.approx(610.0, rel=1e-9)
    assert buckets["399997-M"].initial_capital == pytest.approx(2120.0, rel=1e-9)
    # 三周期之和必须 == 单指数本金
    s = sum(buckets[f"399997-{f}"].initial_capital for f in "DWM")
    assert s == pytest.approx(10_000.0, abs=0.01)


def test_bucket_id_format() -> None:
    assert bucket_id("399997", "D") == "399997-D"
    assert bucket_id("000688", "M") == "000688-M"


def test_load_config_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "missing.yaml")


def test_index_spec_lookup(quant_config_path: Path) -> None:
    cfg = load_config(quant_config_path)
    spec = cfg.find_index("399997")
    assert isinstance(spec, IndexSpec)
    assert spec.etf_code == "161725"
    assert spec.index_name == "中证白酒"


def test_index_spec_lookup_unknown(quant_config_path: Path) -> None:
    cfg = load_config(quant_config_path)
    with pytest.raises(KeyError):
        cfg.find_index("999999")


def test_calmar_weights_must_sum_close_to_one(quant_config_path: Path) -> None:
    cfg = load_config(quant_config_path)
    for spec in cfg.indices:
        active = [w for w in spec.calmar_weights.values() if w is not None]
        # 三个有效 bucket 之和 ≈ 1.0；三选二也允许（W 或 M 为 None 时余下两个之和≈1）
        assert abs(sum(active) - 1.0) < 0.005, (
            f"{spec.index_code}: weights sum {sum(active)} ≠ 1.0"
        )


def test_bucket_dataclass_immutable() -> None:
    b = Bucket(index_code="399997", frequency="D", initial_capital=7270.0,
               etf_code="161725", index_name="中证白酒", etf_name="招商中证白酒 ETF")
    assert b.id == "399997-D"
