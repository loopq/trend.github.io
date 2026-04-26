"""配置加载与 bucket 生成。

数据流：config.yaml → Config → 36 个 Bucket（13 指数 × 3 周期 - 3 个 ❌）。
设计参考 mvp-plan.md §7.6 + §10 Phase 1.1。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml


FREQUENCIES = ("D", "W", "M")


def bucket_id(index_code: str, frequency: str) -> str:
    return f"{index_code}-{frequency}"


@dataclass(frozen=True)
class IndexSpec:
    index_code: str
    index_name: str
    data_source: str
    etf_code: str
    etf_name: str
    category: str
    calmar_weights: dict[str, float | None]


@dataclass(frozen=True)
class Bucket:
    index_code: str
    frequency: str
    initial_capital: float
    etf_code: str
    index_name: str
    etf_name: str

    @property
    def id(self) -> str:
        return bucket_id(self.index_code, self.frequency)


@dataclass(frozen=True)
class Config:
    total_capital: float
    per_index_capital: float
    repo: dict
    paths: dict
    trigger: dict
    paper_trading: dict
    slo: dict
    notification: dict
    writer: dict
    indices: list[IndexSpec] = field(default_factory=list)

    def find_index(self, index_code: str) -> IndexSpec:
        for spec in self.indices:
            if spec.index_code == index_code:
                return spec
        raise KeyError(f"index {index_code} not in config")

    def generate_buckets(self) -> list[Bucket]:
        out: list[Bucket] = []
        for spec in self.indices:
            for freq in FREQUENCIES:
                weight = spec.calmar_weights.get(freq)
                if weight is None:
                    continue  # ❌ bucket 跳过
                out.append(
                    Bucket(
                        index_code=spec.index_code,
                        frequency=freq,
                        initial_capital=round(self.per_index_capital * weight, 2),
                        etf_code=spec.etf_code,
                        index_name=spec.index_name,
                        etf_name=spec.etf_name,
                    )
                )
        return out


def _build_index_spec(raw: dict) -> IndexSpec:
    weights = {f: raw["calmar_weights"].get(f) for f in FREQUENCIES}
    return IndexSpec(
        index_code=str(raw["index_code"]),
        index_name=raw["index_name"],
        data_source=raw["data_source"],
        etf_code=str(raw["etf_code"]),
        etf_name=raw["etf_name"],
        category=raw["category"],
        calmar_weights=weights,
    )


def load_config(path: Path | str) -> Config:
    """加载 config.yaml；若设置 QUANT_DATA_ROOT 环境变量，覆盖 paths 里的所有 data 路径。

    设计参考 deployment-plan.md §3.5.1：mock-test 用 QUANT_DATA_ROOT=/tmp/quant-test 完全隔离。
    """
    import os

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"config not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    paths = dict(raw["paths"])
    data_root_override = os.environ.get("QUANT_DATA_ROOT")
    if data_root_override:
        # 把 paths 里所有以 data_root 开头的路径替换
        old_root = paths["data_root"]
        new_root = data_root_override
        for k, v in paths.items():
            if isinstance(v, str) and v.startswith(old_root):
                paths[k] = v.replace(old_root, new_root, 1)

    return Config(
        total_capital=raw["total_capital"],
        per_index_capital=raw["per_index_capital"],
        repo=raw["repo"],
        paths=paths,
        trigger=raw["trigger"],
        paper_trading=raw["paper_trading"],
        slo=raw["slo"],
        notification=raw["notification"],
        writer=raw["writer"],
        indices=[_build_index_spec(it) for it in raw["indices"]],
    )
