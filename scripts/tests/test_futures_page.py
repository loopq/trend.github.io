"""从 ak 桩经真实 CLI、分析、模板到 HTML 的独立逐格验证。"""
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
import re

import pytest
from bs4 import BeautifulSoup

from scripts.futures import __main__ as cli
from scripts.tests.futures_oracle import compute, compute_slope, patch_sources, synthetic


def strict_json(text):
    def reject(value):
        raise AssertionError(f"非 JSON 数值: {value}")
    return json.loads(text, parse_constant=reject)


def assert_page(html, datasets):
    page = BeautifulSoup(html, "html.parser")
    payload = strict_json(page.select_one('#futures-data').string)
    for symbol, raw in datasets.items():
        expected = compute(raw)
        section = page.select_one(f"#{symbol}")
        for name in ("daily", "percentiles", "roll"):
            cells = [[td.get_text(strip=True) for td in row.select("td")]
                     for row in section.select(f'table[data-table="{name}"] tbody tr')]
            assert cells == expected[name], (symbol, name)
        actual = payload[symbol]
        assert actual["dates"] == expected["chart"]["dates"]
        assert actual["start"] == expected["chart"]["start"]
        for series, oracle in zip(actual["series"], expected["chart"]["series"]):
            assert series["name"] == oracle["name"] and series["contracts"] == oracle["contracts"]
            assert series["data"] == pytest.approx(oracle["data"], nan_ok=False)
        assert section.select_one(".futures-hint").get_text("", strip=True) == expected["hint"]
    slope = strict_json(page.select_one('#slope-data').string)
    expected_slope = {symbol: compute_slope(raw) for symbol, raw in datasets.items()}
    assert slope == {symbol: expected["payload"] for symbol, expected in expected_slope.items()}
    cells = [[td.get_text(strip=True) for td in row.select("td")]
             for row in page.select('#slope table tbody tr')]
    assert cells == [expected["cells"] for expected in expected_slope.values()]
    return page, payload


@pytest.mark.parametrize("ga", [None, "G-FUTURES"])
def test_real_pipeline_matches_independent_oracle(tmp_path, monkeypatch, ga):
    datasets = patch_sources(monkeypatch)
    if ga:
        monkeypatch.setenv("GA_MEASUREMENT_ID", ga)
    else:
        monkeypatch.delenv("GA_MEASUREMENT_ID", raising=False)
    assert cli.main(["--out", str(tmp_path), "--as-of", "2026-10-19"]) == 0
    html = (tmp_path / "futures/index.html").read_text()
    page, payload = assert_page(html, datasets)
    assert page.select_one(".site-nav a")["href"] == "../index.html"
    assert page.select_one('link[rel="stylesheet"]')["href"] == "../css/style.css"
    assert page.select_one('script[src$="echarts.min.js"]')["src"] == "echarts.min.js"
    assert ("googletagmanager" in html) == bool(ga)
    assert all(v is not None for s in payload["IC"]["series"] + payload["IM"]["series"] for v in s["data"])
    assert 'selected: {"次月": true, "当季": false, "下季": true}' in html
    assert "startValue: data.start" in html and "type: 'inside'" in html and "type: 'slider'" in html
    # 起点可能落在周末：时间轴接受任意日期，类目轴会静默退回全历史。
    assert "xAxis: {type: 'time'" in html
    assert "chart.resize()" in html
    assert "contracts[param.dataIndex]" in html
    assert [section["id"] for section in page.select("section")] == ["slope", "IC", "IM"]
    assert page.select_one('.nav-links a[href="#slope"]')
    assert page.select_one(".container > .disclaimer").text == (
        "多头吃贴水视角，数值越大表示贴水越深；历史统计不代表未来，不提供投资建议。")
    assert page.select_one("#slope h2").text == "IM / IC 年化贴水（当季 − 下季，季月斜率）"
    assert [th.text for th in page.select("#slope th")] == [
        "品种", "当季", "下季", "年化贴水%", "近 1 年分位%", "全样本分位%", "近半年最深"]
    description = page.select_one("#slope .disclaimer").text
    assert all(text in description for text in ["当季", "下季", "÷ 3 × 12", "越大越深", "原图以负值绘制", "收盘价"])
    chart = page.select_one("#chart-slope")
    assert chart["data-start"] == "2025-10-19" == compute_slope(datasets["IC"])["start"]
    assert chart["role"] == "img" and "年化贴水" in chart["aria-label"]
    script = page.select_one("#slope-chart-init").string
    assert "legend: {top: 0, data: ['IC', 'IM']}" in script
    assert "['--color-bull-primary', '--color-bear-primary'].map(color)" in script
    assert "name: '年化贴水 %'" in script and "formatter: '{value}%'" in script
    assert "xAxis: {type: 'time', boundaryGap: false, axisLabel: {hideOverlap: true}}" in script
    assert "const slopeStart = slopeElement.dataset.start" in script
    assert "{type: 'inside', startValue: slopeStart" in script
    assert "{type: 'slider', startValue: slopeStart" in script
    assert "type: 'line'" in script and "window.addEventListener('resize', () => slopeChart.resize())" in script
    assert all(text in script for text in ["data.dates[param.dataIndex]", "data.values[param.dataIndex].toFixed(2)",
                                           "data.near[param.dataIndex]", "data.far[param.dataIndex]", "当季", "下季"])


def test_existing_sections_json_and_chart_script_match_frozen_before(tmp_path, monkeypatch):
    class FrozenTime(datetime):
        @classmethod
        def now(cls):
            return cls(2026, 10, 20, 12)

    datasets = patch_sources(monkeypatch)
    # 固定到分，隔离不同平台 sin 实现的末位误差；不修改缓存的 synthetic 输入。
    for symbol, raw in datasets.items():
        datasets[symbol] = deepcopy(raw)
        for field in ("bars", "spot"):
            datasets[symbol][field]["close"] = raw[field]["close"].round(2)
    monkeypatch.setattr(cli, "datetime", FrozenTime)
    monkeypatch.delenv("GA_MEASUREMENT_ID", raising=False)
    assert cli.main(["--out", str(tmp_path), "--as-of", "2026-10-19"]) == 0
    html = (tmp_path / "futures/index.html").read_text()
    # 基线来自改动前的分析函数及模板，同一份冻结输入；摘要不经过 DOM 规范化。
    snapshots = [
        (r'<section id="IC".*?</section>', "b29a2cdcf4588c87b04a1c98d7277c96045c8514758286f3e690ec29ae239714"),
        (r'<section id="IM".*?</section>', "325974dd95f4ed691345aa74d59d0e65255dfa9c636839f8a8b97022f2fca962"),
        (r'<script id="futures-data".*?</script>', "764a411aab1704208e7ae413df29693909abaeb32d26155e1adb19b8d26868ef"),
        (r'<script>\s*const futuresData.*?</script>', "073e0dcc9c4eb6ee9a1529587fbcdec30bd2a41a4ce3708a346d82b61dee914b"),
    ]
    for pattern, expected in snapshots:
        assert sha256(re.search(pattern, html, re.S)[0].encode()).hexdigest() == expected


@pytest.mark.parametrize("as_of", ["2026-1-1", "2026-02-30", "bad", "2026-10-17"])
def test_invalid_as_of_fails_offline(tmp_path, monkeypatch, as_of):
    patch_sources(monkeypatch)
    assert cli.main(["--out", str(tmp_path), "--as-of", as_of]) != 0
    assert not (tmp_path / "futures/index.html").exists()


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("failure", ["data", "analysis", "slope", "slope-json", "template", "write"])
def test_failure_preserves_formal_page(tmp_path, monkeypatch, existing, failure):
    patch_sources(monkeypatch, end="2022-08-19")
    target = tmp_path / "futures/index.html"
    if existing:
        target.parent.mkdir()
        target.write_bytes(b"old page\x00\xff")

    def fail(*args, **kwargs):
        raise RuntimeError("模拟失败")

    if failure == "data":
        monkeypatch.setattr(cli, "load_variety", fail)
    elif failure == "analysis":
        monkeypatch.setattr(cli, "daily_table", fail)
    elif failure == "slope":
        monkeypatch.setattr(cli, "slope_series", fail)
    elif failure == "slope-json":
        monkeypatch.setattr(cli, "slope_summary", lambda *args: {"value": float("nan")})
    elif failure == "template":
        monkeypatch.setattr("jinja2.environment.Template.render", fail)
    else:
        from scripts.tests.test_generator import interrupt_write
        interrupt_write(monkeypatch)
    assert cli.main(["--out", str(tmp_path), "--as-of", "2022-08-19"]) != 0
    assert target.read_bytes() == b"old page\x00\xff" if existing else not target.exists()
    assert not list((tmp_path / ".tmp").glob("*"))


def test_main_date_mismatch_and_future_truncation(tmp_path, monkeypatch):
    patch_sources(monkeypatch, end="2026-10-15")
    assert cli.main(["--out", str(tmp_path), "--as-of", "2026-10-16"]) != 0
    patch_sources(monkeypatch, end="2026-10-19")
    assert cli.main(["--out", str(tmp_path), "--as-of", "2026-10-16"]) == 0
    datasets = {symbol: synthetic(symbol, "2026-10-16") for symbol in ("IC", "IM")}
    assert_page((tmp_path / "futures/index.html").read_text(), datasets)


def test_estimated_calendar_omits_window_and_percentiles(tmp_path, monkeypatch):
    patch_sources(monkeypatch, end="2026-12-21")
    raw_load = cli.load_calendar
    monkeypatch.setattr(cli, "load_calendar", lambda: raw_load()[raw_load() <= "2026-12-31"])
    assert cli.main(["--out", str(tmp_path), "--as-of", "2026-12-21"]) == 0
    page = BeautifulSoup((tmp_path / "futures/index.html").read_text(), "html.parser")
    for hint in page.select(".futures-hint"):
        assert "按工作日估计" in hint.text
        assert "同期" not in hint.text and "尚未进入" not in hint.text
