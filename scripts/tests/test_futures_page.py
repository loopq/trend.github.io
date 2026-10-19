"""从 ak 桩经真实 CLI、分析、模板到 HTML 的独立逐格验证。"""
import json

import pytest
from bs4 import BeautifulSoup

from scripts.futures import __main__ as cli
from scripts.tests.futures_oracle import compute, patch_sources, synthetic


def strict_json(text):
    def reject(value):
        raise AssertionError(f"非 JSON 数值: {value}")
    return json.loads(text, parse_constant=reject)


def assert_page(html, datasets):
    page = BeautifulSoup(html, "html.parser")
    payload = strict_json(page.select_one('script[type="application/json"]').string)
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


@pytest.mark.parametrize("as_of", ["2026-1-1", "2026-02-30", "bad", "2026-10-17"])
def test_invalid_as_of_fails_offline(tmp_path, monkeypatch, as_of):
    patch_sources(monkeypatch)
    assert cli.main(["--out", str(tmp_path), "--as-of", as_of]) != 0
    assert not (tmp_path / "futures/index.html").exists()


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("failure", ["data", "analysis", "template", "write"])
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
