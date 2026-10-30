"""首页偏离率折线：增量历史（独立 oracle 对照归档口径）、降级、页面结构、真实配置。"""
import json
import math
import os
import re
from datetime import date

import pandas as pd
import pytest
from bs4 import BeautifulSoup

from scripts import (CHART_SEED_FROM, CHART_START, DEVIATION_HISTORY, HISTORY_DAYS, chart_meta,
                     deviation_frame, history_json, load_config, load_history, update_history)
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
    "000300": make_df(wave(2900, 4000, 300, 7)),
    "BTC": make_df(wave(4100, 60000, 6000, 11), calendar="D"),             # 24 小时市场：含周末
    "SPX": make_df(wave(400, 6000, 400, 9)).drop(index=[350, 380]).reset_index(drop=True),  # 美股休市日
    "932000": make_df(wave(150, 2500, 200, 5)),                              # 上市晚：窗口前段无值
}
ASOF = date(2026, 10, 16)
SEED_DAYS = (date(2026, 10, 17) - CHART_SEED_FROM).days


def test_every_point_equals_archive_as_of_value():
    history = update_history(pd.DataFrame(), FRAMES, ASOF)
    hs300 = FRAMES["000300"]["date"]
    assert list(history.index) == list(hs300[hs300 >= CHART_START])
    for code, df in FRAMES.items():
        for day, value in history[code].items():
            expected = as_of(df, day)
            assert pd.isna(value) == (expected is None), (code, day)
            if expected is not None:
                assert value == pytest.approx(expected, abs=0.0051), (code, day)
    assert pd.isna(history["932000"].iloc[0]) and pd.notna(history["932000"].iloc[-1])


def test_a_share_last_point_equals_table_deviation():
    history = update_history(pd.DataFrame(), FRAMES, ASOF)
    assert "%.2f%%" % history["000300"].iloc[-1] == index_row(FRAMES["000300"])["cells"]["偏离率"]


def test_overlap_fills_gaps_and_preserves_frozen_history():
    dates = pd.to_datetime(["2016-01-04", "2026-10-14", "2026-10-15"])
    history = pd.DataFrame({"000300": [42., None, -99.], "REMOVED": [1., 2., 3.]}, index=dates)
    frame = make_df(range(100, 160))
    merged = update_history(history, {"000300": frame}, ASOF)
    assert merged.at[dates[0], "000300"] == 42.
    for day in pd.to_datetime(["2026-10-14", "2026-10-15", "2026-10-16"]):
        assert merged.at[day, "000300"] == pytest.approx(as_of(frame, day), abs=0.0051)
    pd.testing.assert_series_equal(merged.loc[dates, "REMOVED"], history["REMOVED"])
    assert merged.index.is_unique and merged.index.is_monotonic_increasing


@pytest.mark.parametrize("frame", [None, make_df(range(100, 140), end="2016-06-13"), make_df([100] * 19)])
def test_failed_or_short_frame_does_not_erase_old_values(frame):
    dates = pd.to_datetime(["2016-06-10", "2020-06-01", "2026-10-16"])
    history = pd.DataFrame({"X": [1., 2., 3.]}, index=dates)
    pd.testing.assert_frame_equal(update_history(history, {"X": frame}, ASOF), history)


@pytest.mark.parametrize("hs300", [{}, {"000300": None}])
def test_missing_hs300_updates_existing_dates_only(hs300):
    dates = pd.to_datetime(["2026-10-14", "2026-10-15"])
    history = pd.DataFrame({"X": [None, -99.]}, index=dates)
    frame = make_df(range(100, 140))
    merged = update_history(history, {**hs300, "X": frame}, ASOF)
    pd.testing.assert_index_equal(merged.index, history.index)
    for day in dates:
        assert merged.at[day, "X"] == pytest.approx(as_of(frame, day), abs=0.0051)


def test_new_index_seeds_entire_existing_axis():
    dates = pd.to_datetime(["2016-01-04", "2020-06-01", "2026-10-16"])
    history = pd.DataFrame({"000300": [1., 2., 3.]}, index=dates)
    merged = update_history(history, {"X": FRAMES["000300"]}, ASOF)
    pd.testing.assert_series_equal(merged["000300"], history["000300"])
    for day in dates:
        assert merged.at[day, "X"] == pytest.approx(as_of(FRAMES["000300"], day), abs=0.0051)


def test_stale_source_is_blank_not_flat_line():
    """新鲜 frame 中间断更 15 个交易日：缺口不延续成平线，恢复后继续有值"""
    frame = make_df(wave(400, 3000, 100, 5))
    gap = frame.drop(index=range(380, 395)).reset_index(drop=True)
    history = update_history(pd.DataFrame(), {"000300": frame, "GAP": gap}, ASOF)
    assert pd.notna(history.at[frame["date"].iloc[380], "GAP"])   # 仍在 10 天容忍窗口内
    assert history.loc[frame["date"].iloc[390]:frame["date"].iloc[394], "GAP"].isna().all()
    assert history.loc[frame["date"].iloc[395]:, "GAP"].notna().all()


def test_stopped_frame_does_not_rewrite_frozen_values():
    dates = pd.to_datetime(["2016-06-10", "2016-06-13", "2020-06-01", "2026-10-16"])
    history = pd.DataFrame({"OLD": [42., 43., 44., 45.]}, index=dates)
    old = make_df(wave(200, 3000, 100, 5), end="2016-06-13")
    pd.testing.assert_frame_equal(update_history(history, {"OLD": old}, ASOF), history)


def test_stopped_frame_does_not_complete_seed_and_fresh_retry_does():
    dates = pd.to_datetime(["2016-06-10", "2020-06-01", "2026-10-16"])
    history = pd.DataFrame({"000300": [1., 2., 3.]}, index=dates)
    old = make_df(wave(200, 3000, 100, 5), end="2016-06-13")
    merged = update_history(history, {"OLD": old}, ASOF)
    pd.testing.assert_frame_equal(merged, history)
    merged = update_history(merged, {"OLD": FRAMES["000300"]}, ASOF)
    for day in dates:
        assert merged.at[day, "OLD"] == pytest.approx(as_of(FRAMES["000300"], day), abs=0.0051)


@pytest.mark.parametrize("closes", [[100] * 20 + [0] * 20, [-1] * 20 + [19]])
def test_non_finite_point_and_following_holiday_stay_blank(closes):
    # x/0 用额外一根 -1 预热，保证无效点的前一天有有限值可对照
    frame = make_df(closes, end="2026-10-15")
    dates = pd.date_range("2026-10-14", "2026-10-16")
    result = deviation_frame({"X": frame, "000300": make_df(range(100, 140))}, dates)
    assert pd.notna(result["X"].iloc[0])
    assert result["X"].iloc[1:].isna().all()
    assert result["000300"].notna().all()
    assert strict_json(history_json(result))["series"]["X"][1:] == [None, None]


def test_history_json_round_trip(tmp_path):
    history = pd.DataFrame({"000300": [1.23, None], "X": [None, -2.34]},
                           index=pd.to_datetime(["2016-01-04", "2026-10-16"]))
    path = tmp_path / "deviation.json"
    text = history_json(history)
    assert strict_json(text) == {"dates": ["2016-01-04", "2026-10-16"],
                                 "series": {"000300": [1.23, None], "X": [None, -2.34]}}
    path.write_text(text, encoding="utf-8")
    pd.testing.assert_frame_equal(load_history(path), history)


@pytest.mark.parametrize("value", [float("inf"), float("-inf")])
def test_history_json_rejects_infinity(value):
    history = pd.DataFrame({"X": [value]}, index=pd.to_datetime(["2026-10-16"]))
    with pytest.raises(ValueError):
        history_json(history)


@pytest.mark.parametrize("text", [
    "{", "null", "[]", '{}',
    '{"dates":[],"series":[]}',
    '{"dates":"2026-10-16","series":{}}',
    *[json.dumps({"dates": dates, "series": {}}) for dates in [
        [None], ["2026-13-01"], [20260101], ["2026/01/05"],
        ["2026-10-16", "2026-10-16"], ["2026-10-16", "2026-10-15"], ["2015-12-31"]]],
    *[json.dumps({"dates": ["2026-10-15", "2026-10-16"], "series": {"X": values}}) for values in [
        [], [1.], [1., 2., 3.], 1., [None, float("inf")], [None, float("nan")], [None, "1"], [None, True]]],
])
def test_invalid_history_is_logged_and_rebuilt(tmp_path, caplog, text):
    path = tmp_path / "deviation.json"
    path.write_text(text, encoding="utf-8")
    history = load_history(path)
    assert history.empty and list(history.columns) == []
    assert "偏离率历史损坏" in caplog.text


def test_missing_history_is_empty(tmp_path):
    history = load_history(tmp_path / "missing.json")
    assert history.empty and list(history.columns) == []


def test_empty_history_and_all_null_columns_are_dropped(tmp_path):
    path = tmp_path / "deviation.json"
    path.write_text('{"dates":[],"series":{"X":[],"Y":[]}}', encoding="utf-8")
    history = load_history(path)
    assert history.empty and list(history.columns) == []
    path.write_text('{"dates":["2026-10-16"],"series":{"X":[null],"Y":[1]}}', encoding="utf-8")
    history = load_history(path)
    assert list(history.columns) == ["Y"] and history["Y"].tolist() == [1.]


def test_order_visible_first_and_failed_kept_as_empty_line():
    config = {"major_indices": [cfg("000300"), {**cfg("A"), "chart_hidden": True}, cfg("B"), cfg("C")]}
    frames = {"000300": FRAMES["000300"], "A": FRAMES["000300"], "B": None, "C": make_df([100] * 10)}
    meta = chart_meta(config)
    assert meta == {"major": [
        {"code": "000300", "name": "指数000300", "hidden": False},
        {"code": "B", "name": "指数B", "hidden": False},
        {"code": "C", "name": "指数C", "hidden": False},
        {"code": "A", "name": "指数A", "hidden": True}], "sector": []}
    assert set(update_history(pd.DataFrame(), frames, ASOF).columns) == {"000300", "A"}


def test_real_config_default_visible_set():
    config = load_config(os.path.join(PROJECT_ROOT, "scripts", "config.yaml"))
    visible = {c["name"] for c in config["major_indices"] if not c.get("chart_hidden")}
    assert visible == {"标普500", "纳指100", "沪深300", "中证500", "创业板50", "黄金现价", "恒生科技", "科创50"}
    assert len(config["major_indices"]) == 16
    assert not any(c.get("chart_hidden") for c in config["sector_indices"])


# ---------- 经真实 main() 链路的历史与页面结构 ----------

def soup(path):
    return BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")


def archive_page(site):
    [name] = [f for f in os.listdir(site / "archive") if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.html", f)]
    return site / "archive" / name


def save_history(site, history):
    path = site / DEVIATION_HISTORY
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(history_json(history), encoding="utf-8")
    return path


def test_index_renders_two_charts_and_archive_has_none(run_cli):
    major = [cfg("000300"), {**cfg("000905"), "chart_hidden": True}]
    frames = {"000300": FRAMES["000300"], "000905": make_df(range(200, 260)),
              "000819": make_df(range(300, 360))}
    code, out, site, fetcher = run_cli(["--mock-date", "2026-10-17"], frames, major, [cfg("000819")])
    assert code is None and out == {"record_date": "2026-10-16", "should_deploy": "true"}
    assert len(fetcher.calls) == len(set(fetcher.calls)) == 3          # 折线复用首次取数
    assert all(days == SEED_DAYS for _, _, days in fetcher.calls)
    history = strict_json((site / DEVIATION_HISTORY).read_text(encoding="utf-8"))
    assert history["dates"][0] >= "2016-01-01" and history["dates"][-1] == "2026-10-16"
    assert set(history["series"]) == set(frames)
    assert all(len(values) == len(history["dates"]) for values in history["series"].values())
    page = soup(site / "index.html")
    assert [d["id"] for d in page.select(".trend-chart")] == ["chart-major", "chart-sector"]
    payload = strict_json(page.select_one("#trend-chart-meta").string)
    assert payload == {"major": [{"code": "000300", "name": "指数000300", "hidden": False},
                                  {"code": "000905", "name": "指数000905", "hidden": True}],
                       "sector": [{"code": "000819", "name": "指数000819", "hidden": False}]}
    assert not page.select_one("#trend-chart-data")
    assert page.select_one('script[src$="echarts.min.js"]')["src"] == "futures/echarts.min.js"
    script = page.select_one("#trend-chart-init").string
    for snippet in ["title: '全选'", "title: '反选'", "data: [{yAxis: 0}]", "onZero: false",
                    "type: 'slider'", "startValue: +start", "'dashed'", "emphasis: {focus: 'series'}",
                    "archive/deviation.json?v=2026.10.16", "smooth: true", "ZOOM_MONTHS = 6",
                    "params[0].value[0]", "history.series[s.code] || blank",
                    "偏离率走势暂时无法加载，请稍后刷新"]:
        assert snippet in script
    assert page.select_one("#columnHelpModal")                           # super() 保留列说明弹窗
    archive = soup(archive_page(site))
    assert not archive.select(".trend-chart") and not archive.select_one("#trend-chart-meta")
    assert not archive.select_one("#trend-chart-data")
    assert not archive.select_one('script[src$="echarts.min.js"]')


def test_second_run_uses_short_window_and_seeds_new_index(run_cli, tmp_path):
    history = pd.DataFrame({"000300": [42., 43.]}, index=pd.to_datetime(["2016-01-04", "2026-10-15"]))
    save_history(tmp_path / "site", history)
    frames = {"000300": FRAMES["000300"], "Y": FRAMES["000300"]}
    code, out, site, fetcher = run_cli(["--mock-date", "2026-10-17"], frames, [cfg("000300"), cfg("Y")])
    assert code is None and out["should_deploy"] == "true"
    assert fetcher.calls == [("000300", "cs_index", HISTORY_DAYS), ("Y", "cs_index", SEED_DAYS)]
    merged = load_history(site / DEVIATION_HISTORY)
    assert merged.at[pd.Timestamp("2016-01-04"), "000300"] == 42.
    assert merged["Y"].notna().all()
    assert merged.at[pd.Timestamp("2016-01-04"), "Y"] == pytest.approx(as_of(frames["Y"], history.index[0]), abs=0.0051)


@pytest.mark.parametrize("with_history", [False, True])
def test_missing_hs300_keeps_tables_and_chart_slots(run_cli, tmp_path, with_history):
    major = [cfg("000300"), cfg("000905"), cfg("000852")]
    frames = {"000300": None, "000905": make_df(range(200, 260)), "000852": make_df(range(300, 360))}
    dates = pd.to_datetime(["2026-10-14", "2026-10-15"])
    if with_history:
        save_history(tmp_path / "site", pd.DataFrame({"000300": [1., 2.]}, index=dates))
    code, out, site, _ = run_cli(["--mock-date", "2026-10-17"], frames, major)
    assert code is None and out == {"record_date": "2026-10-16", "should_deploy": "true"}
    page = soup(site / "index.html")
    assert page.select(".table-wrapper table") and len(page.select(".trend-chart")) == 2
    assert page.select_one('script[src$="echarts.min.js"]')
    if with_history:
        pd.testing.assert_index_equal(load_history(site / DEVIATION_HISTORY).index, dates)
    else:
        assert not (site / DEVIATION_HISTORY).exists()


@pytest.mark.parametrize("function", ["update_history", "history_json"])
def test_history_update_failure_preserves_file_and_tables(run_cli, tmp_path, monkeypatch, caplog, function):
    path = save_history(tmp_path / "site", pd.DataFrame({"000300": [42.]}, index=pd.to_datetime(["2016-01-04"])))
    original = path.read_bytes()
    def fail(*args):
        raise RuntimeError("history failed")
    monkeypatch.setattr("scripts.main." + function, fail)
    code, out, site, _ = run_cli(["--mock-date", "2026-10-17"], {"000300": FRAMES["000300"]}, [cfg("000300")])
    assert code is None and out["should_deploy"] == "true"
    assert path.read_bytes() == original
    assert soup(site / "index.html").select(".table-wrapper table")
    assert "偏离率历史更新失败，保留旧文件" in caplog.text


def test_corrupt_history_reseeds_without_breaking_tables(run_cli, tmp_path):
    path = tmp_path / "site" / DEVIATION_HISTORY
    path.parent.mkdir(parents=True)
    path.write_text('{"dates":["2026-10-16"],"series":[]}', encoding="utf-8")
    frames = {"000300": FRAMES["000300"], "X": make_df(range(100, 140))}
    code, out, site, fetcher = run_cli(["--mock-date", "2026-10-17"], frames, [cfg("000300"), cfg("X")])
    assert code is None and out["should_deploy"] == "true"
    assert fetcher.calls == [("000300", "cs_index", SEED_DAYS), ("X", "cs_index", SEED_DAYS)]
    assert soup(site / "index.html").select(".table-wrapper table")
    assert set(strict_json(path.read_text(encoding="utf-8"))["series"]) == set(frames)
    assert not load_history(path).empty


def test_stopped_seed_is_retried_on_next_run(run_cli):
    major = [cfg("000300"), cfg("OLD", "sina_index")]
    frames = {"000300": FRAMES["000300"], "OLD": make_df(range(100, 140), end="2016-06-13")}
    code, out, site, first = run_cli(["--mock-date", "2026-10-17"], frames, major)
    assert code is None and out["should_deploy"] == "true"
    assert first.calls == [("000300", "cs_index", SEED_DAYS), ("OLD", "sina_index", SEED_DAYS)]
    history = load_history(site / DEVIATION_HISTORY)
    assert list(history.columns) == ["000300"]
    frames["OLD"] = FRAMES["000300"]
    code, out, site, second = run_cli(["--mock-date", "2026-10-17"], frames, major)
    assert code is None and out["should_deploy"] == "true"
    assert second.calls == [("000300", "cs_index", HISTORY_DAYS), ("OLD", "sina_index", SEED_DAYS)]
    merged = load_history(site / DEVIATION_HISTORY)
    pd.testing.assert_index_equal(merged.index, history.index)
    assert merged["OLD"].notna().all()
    assert merged.at[pd.Timestamp("2020-06-01"), "OLD"] == pytest.approx(as_of(frames["OLD"], pd.Timestamp("2020-06-01")), abs=0.0051)
