"""主站测试公共夹具：确定性合成行情 + 生产链路桩（纯离线，不触网）"""
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd
import pytest
import yaml

import scripts.main as main_mod
from scripts.data_fetcher import DataFetcher

T = "2026-10-16"  # 默认截至日（周五）


def make_df(closes: List[float], end: str = T, volumes=None, highs=None, lows=None,
            calendar: str = "B") -> pd.DataFrame:
    """以 end 为最后一根，按日历倒推生成日线；calendar="B" 工作日，"D" 自然日（24 小时市场）。
    high/low 缺省等于 close，volume 缺省 100。"""
    n = len(closes)
    dates = pd.bdate_range(end=end, periods=n) if calendar == "B" else pd.date_range(end=end, periods=n)
    closes = [float(c) for c in closes]
    return pd.DataFrame({
        "date": dates,
        "close": closes,
        "open": closes,
        "high": [float(h) for h in highs] if highs is not None else closes,
        "low": [float(x) for x in lows] if lows is not None else closes,
        "volume": [float(v) for v in volumes] if volumes is not None else [100.0] * n,
    })


class StubFetcher(DataFetcher):
    """按 source 模拟生产取数窗口：cs_index = 距 today 的 days+30 个自然日起点再 tail(days) 行；
    其余 source = 全量 tail(days) 行。frames[code] 为 None 表示取数失败。"""

    def __init__(self, frames: Dict[str, Optional[pd.DataFrame]], today: str = "2026-10-17"):
        super().__init__()
        self.frames = frames
        self.now = datetime.strptime(today, "%Y-%m-%d")
        self.calls = []

    def fetch_index(self, code, source, name=None, days=300):
        self.calls.append((code, source, days))
        df = self.frames.get(code)
        if df is None:
            return None
        df = df[df["date"] <= self.now]
        if source == "cs_index":
            df = df[df["date"] >= self.now - timedelta(days=days + 30)]
        return df.tail(days).reset_index(drop=True).copy()


def cfg(code: str, source: str = "cs_index", name: Optional[str] = None) -> Dict:
    return {"code": code, "name": name or f"指数{code}", "source": source}


TEMPLATES = os.path.join(main_mod.PROJECT_ROOT, "templates")


@pytest.fixture
def run_cli(tmp_path, monkeypatch):
    """run_cli(argv, frames, major, sector) -> (exit_code, outputs, out_dir, fetcher)"""
    real_gen = main_mod.Generator

    def _run(argv, frames, major, sector=(), ga=None):
        out = tmp_path / "site"
        conf = tmp_path / "config.yaml"
        conf.write_text(yaml.safe_dump({"major_indices": list(major), "sector_indices": list(sector)},
                                       allow_unicode=True), encoding="utf-8")
        gh_out = tmp_path / "gh_output"
        gh_out.write_text("")
        monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))
        if ga:
            monkeypatch.setenv("GA_MEASUREMENT_ID", ga)
        else:
            monkeypatch.delenv("GA_MEASUREMENT_ID", raising=False)

        fetcher = StubFetcher(frames)
        monkeypatch.setattr(main_mod, "DataFetcher", lambda: fetcher)
        monkeypatch.setattr(main_mod, "Generator", lambda **kw: real_gen(
            **{**kw, "template_dir": TEMPLATES, "output_dir": str(out)}))
        monkeypatch.setattr(sys, "argv", ["main.py", "--config", str(conf), *argv])

        code = None
        try:
            main_mod.main()
        except SystemExit as e:
            code = e.code
        outputs = dict(l.split("=", 1) for l in gh_out.read_text().splitlines() if "=" in l)
        return code, outputs, out, fetcher

    return _run
