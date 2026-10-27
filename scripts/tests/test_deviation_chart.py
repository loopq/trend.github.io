"""首页偏离率折线：数据（独立 oracle 对照归档口径）、降级、页面结构、真实配置。"""
import json
import math
import os

import pandas as pd
import pytest
from bs4 import BeautifulSoup

from scripts import deviation_charts, load_config
from scripts.main import PROJECT_ROOT
from scripts.tests.conftest import cfg, make_df
from scripts.tests.oracle import index_row


def wave(n, base, amp, period):
    return [base + amp * math.sin(i / period) for i in range(n)]


def as_of(df, day):
    """归档口径：截至 day（含）最后一根 K 线的偏离率 %；不足 20 根为 None"""
    s = df[df["date"] <= day]["close"]
    return None if len(s) < 20 else (s.iloc[-1] / s.iloc[-20:].mean() - 1) * 100


def strict_json(text):
    def reject(value):
        raise AssertionError(f"非 JSON 数值: {value}")
    return json.loads(text, parse_constant=reject)


FRAMES = {
    "000300": make_df(wave(400, 4000, 300, 7)),
    "BTC": make_df(wave(600, 60000, 6000, 11), calendar="D"),               # 24 小时市场：含周末
    "SPX": make_df(wave(400, 6000, 400, 9)).drop(index=[350, 380]).reset_index(drop=True),  # 美股休市日
    "932000": make_df(wave(150, 2500, 200, 5)),                              # 上市晚：窗口前段无值
}
CONFIG = {"major_indices": [cfg("000300"), cfg("BTC", "crypto"), {**cfg("SPX", "us"), "chart_hidden": True}],
          "sector_indices": [cfg("932000")]}


def test_every_point_equals_archive_as_of_value():
    charts = deviation_charts(CONFIG, FRAMES)
    hs300 = FRAMES["000300"]["date"]
    last = hs300.iloc[-1]
    assert charts["dates"] == [d.strftime("%Y-%m-%d") for d in hs300 if d > last - pd.DateOffset(years=1)]
    assert charts["start"] == "2026-07-16"
    codes = {"指数000300": "000300", "指数BTC": "BTC", "指数SPX": "SPX", "指数932000": "932000"}
    for s in charts["major"] + charts["sector"]:
        df = FRAMES[codes[s["name"]]]
        assert len(s["data"]) == len(charts["dates"])
        for day, value in zip(charts["dates"], s["data"]):
            expected = as_of(df, pd.Timestamp(day))
            assert (value is None) == (expected is None), (s["name"], day)
            if expected is not None:
                assert value == pytest.approx(expected, abs=0.0051), (s["name"], day)
    assert charts["sector"][0]["data"][0] is None and charts["sector"][0]["data"][-1] is not None


def test_a_share_last_point_equals_table_deviation():
    charts = deviation_charts(CONFIG, FRAMES)
    assert "%.2f%%" % charts["major"][0]["data"][-1] == index_row(FRAMES["000300"])["cells"]["偏离率"]


def test_order_visible_first_and_failed_kept_as_empty_line():
    config = {"major_indices": [cfg("000300"), {**cfg("A"), "chart_hidden": True}, cfg("B"), cfg("C")]}
    frames = {"000300": FRAMES["000300"], "A": FRAMES["000300"], "B": None, "C": make_df([100] * 10)}
    major = deviation_charts(config, frames)["major"]
    assert [(s["name"], s["hidden"]) for s in major] == [
        ("指数000300", False), ("指数B", False), ("指数C", False), ("指数A", True)]
    assert all(v is None for s in major[1:3] for v in s["data"])


def test_stale_source_is_blank_not_flat_line():
    """回退源断更（如新浪 sh000813 停在 2016-06-13）：不把陈旧值延续成整条平线"""
    frames = {"000300": FRAMES["000300"], "OLD": make_df(wave(200, 3000, 100, 5), end="2016-06-13"),
              "GAP": make_df(wave(400, 3000, 100, 5)).drop(index=range(380, 395)).reset_index(drop=True)}
    config = {"major_indices": [cfg("000300"), cfg("OLD"), cfg("GAP")]}
    _, old, gap = deviation_charts(config, frames)["major"]
    assert all(v is None for v in old["data"])
    dates = deviation_charts(config, frames)["dates"]
    resumed = FRAMES["000300"]["date"].iloc[-5].strftime("%Y-%m-%d")    # 断更 15 个交易日后恢复
    blank = [d for d, v in zip(dates, gap["data"]) if v is None]
    assert blank and max(blank) < resumed and gap["data"][-1] is not None


def test_no_hs300_degrades_to_none():
    assert deviation_charts({"major_indices": [cfg("SPX", "us")]}, {"SPX": FRAMES["SPX"]}) is None
    assert deviation_charts(CONFIG, {**FRAMES, "000300": None}) is None


def test_non_finite_value_degrades_to_none(caplog):
    frames = {"000300": make_df(range(100, 140)), "X": make_df([-1] * 19 + [19])}   # MA20 = 0 → inf
    assert deviation_charts({"major_indices": [cfg("000300"), cfg("X")]}, frames) is None
    assert "偏离率折线计算失败" in caplog.text


def test_real_config_default_visible_set():
    config = load_config(os.path.join(PROJECT_ROOT, "scripts", "config.yaml"))
    visible = {c["name"] for c in config["major_indices"] if not c.get("chart_hidden")}
    assert visible == {"标普500", "纳指100", "沪深300", "中证500", "创业板50", "黄金现价", "恒生科技", "科创50"}
    assert len(config["major_indices"]) == 16
    assert not any(c.get("chart_hidden") for c in config["sector_indices"])


# ---------- 经真实 main() 链路的页面结构 ----------

def soup(path):
    return BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")


def archive_page(site):
    [name] = [f for f in os.listdir(site / "archive") if f != "index.html"]
    return site / "archive" / name


def test_index_renders_two_charts_and_archive_has_none(run_cli):
    major = [cfg("000300"), {**cfg("000905"), "chart_hidden": True}]
    frames = {"000300": make_df(range(100, 160)), "000905": make_df(range(200, 260)),
              "000819": make_df(range(300, 360))}
    code, out, site, fetcher = run_cli(["--mock-date", "2026-10-17"], frames, major, [cfg("000819")])
    assert code is None and out == {"record_date": "2026-10-16", "should_deploy": "true"}
    assert len(fetcher.calls) == len(set(fetcher.calls)) == 3          # 折线复用首次取数
    page = soup(site / "index.html")
    assert [d["id"] for d in page.select(".trend-chart")] == ["chart-major", "chart-sector"]
    payload = strict_json(page.select_one("#trend-chart-data").string)
    assert payload["dates"][-1] == "2026-10-16"
    assert [(s["name"], s["hidden"]) for s in payload["major"]] == [("指数000300", False), ("指数000905", True)]
    assert all(len(s["data"]) == len(payload["dates"]) for s in payload["major"] + payload["sector"])
    assert page.select_one('script[src$="echarts.min.js"]')["src"] == "futures/echarts.min.js"
    script = page.select_one("#trend-chart-init").string
    for snippet in ["title: '全选'", "title: '反选'", "data: [{yAxis: 0}]", "onZero: false",
                    "type: 'slider'", "startValue: charts.start", "'dashed'", "emphasis: {focus: 'series'}"]:
        assert snippet in script
    assert page.select_one("#columnHelpModal")                           # super() 保留列说明弹窗
    archive = soup(archive_page(site))
    assert not archive.select(".trend-chart") and not archive.select_one("#trend-chart-data")
    assert not archive.select_one('script[src$="echarts.min.js"]')


def test_missing_hs300_keeps_tables_without_chart(run_cli):
    major = [cfg("000300"), cfg("000905"), cfg("000852")]
    frames = {"000300": None, "000905": make_df(range(200, 260)), "000852": make_df(range(300, 360))}
    code, out, site, _ = run_cli(["--mock-date", "2026-10-17"], frames, major)
    assert code is None and out["should_deploy"] == "true"
    page = soup(site / "index.html")
    assert page.select(".table-wrapper table") and not page.select(".trend-chart")
    assert not page.select_one('script[src$="echarts.min.js"]')
