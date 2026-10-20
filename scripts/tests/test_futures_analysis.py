"""公式与换月边界：手算反例优先，页面另由独立 oracle 验证。"""
import json
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from scripts.futures import analysis as a
from scripts.tests.futures_oracle import synthetic


@pytest.mark.parametrize("code, expected", [
    ("IC2610", ["IC2611", "IC2612", "IC2703"]),
    ("IM2609", ["IM2610", "IM2612", "IM2703"]),
    ("IC2612", ["IC2701", "IC2703", "IC2706"]),
])
def test_targets(code, expected):
    assert a.targets(code) == expected


def test_rule_expiry():
    cal = pd.bdate_range("2026-01-01", "2026-12-31")
    assert a.rule_expiry("IC2610", cal) == pd.Timestamp("2026-10-16")
    assert a.rule_expiry("IC2610", cal.drop(pd.Timestamp("2026-10-16"))) == pd.Timestamp("2026-10-19")
    assert a.rule_expiry("IC2703", cal) is None


def test_daily_formula_and_current_month_hidden():
    data = deepcopy(synthetic(end="2026-10-09"))
    data["spot"].loc[data["spot"].date == data["as_of"], "close"] = 6000
    data["bars"].loc[data["bars"].date == data["as_of"], "close"] = 5930
    row = a.daily_table(data)[0]
    assert (row["role"], row["contract"], row["days"], row["basis"]) == ("次月", "IC2611", 42, 70)
    assert row["monthly"] == pytest.approx(50)
    assert row["annual"] == pytest.approx(70 / 6000 * 365 / 42 * 100)
    # 当月交割日（IC2610）当天：当月不展示，其余角色剩余天数都远离小分母
    table = a.daily_table(synthetic(end="2026-10-16"))
    assert [(r["role"], r["contract"]) for r in table] == [("次月", "IC2611"), ("当季", "IC2612"), ("下季", "IC2703")]
    assert min(r["days"] for r in table) >= 24
    assert [r["role"] for r in a.percentile_table(data)] == [s["name"] for s in a.chart_series(data)["series"]] == ["次月", "当季", "下季"]


def test_percentiles_include_equal_and_numpy():
    data = synthetic(end="2022-07-22")
    rows = a.daily_table(data)
    assert all(r["percentile"] == 100 for r in rows)
    data = synthetic(end="2022-08-18")
    series = a.chart_series(data)["series"]
    for row, s in zip(a.percentile_table(data), series):
        values = [v for v in s["data"] if v is not None]
        assert row["quantiles"] == pytest.approx(np.percentile(values, [10, 25, 50, 75, 90]))
        assert row["n"] == len(values)


def test_events_use_calendar_and_fixed_targets():
    data = synthetic()
    event = next(e for e in a.roll_events(data) if e["contract"] == "IC2610")
    # 国庆长假不计交易日：10-16 前第 6 日为 9-30。
    assert event["dates"][6] == "2026-09-30"
    early = next(e for e in a.roll_events(data) if e["contract"] == "IC2208")
    assert all(d >= "2022-07-22" for d in early["dates"].values())
    september = next(e for e in a.roll_events(data) if e["contract"] == "IC2209")
    assert september["dates"][20] == "2022-08-19"
    assert september["values"][20][0] is None


def test_pairing_empty_and_ties():
    events = [{"values": {1: [1, None, 2], 2: [2, None, 2], 3: [2, None, 1]}},
              {"values": {1: [1, None, 2], 2: [None, None, 2], 3: [None, None, 1]}}]
    stats = a.roll_stats(events)
    assert stats[1]["paths"][0] == dict(delta=1, win_rate=100, n=1)
    assert stats[0]["paths"][0] == dict(delta=0, win_rate=None, n=2)
    assert stats[1]["paths"][1] == dict(delta=None, win_rate=None, n=None)
    assert a.best_roll(stats, 0)["day"] == 2
    assert a.best_roll(stats, 1) is None
    assert a.best_roll(stats, 2)["day"] == 1


@pytest.mark.parametrize("end, source, targets", [
    ("2026-10-15", "IC2610", ["IC2611", "IC2612", "IC2703"]),
    ("2026-10-16", "IC2611", ["IC2612", "IC2703", "IC2706"]),
    ("2026-09-18", "IC2610", ["IC2611", "IC2612", "IC2703"]),
    ("2026-09-21", "IC2610", ["IC2611", "IC2612", "IC2703"]),
    ("2026-10-19", "IC2611", ["IC2612", "IC2703", "IC2706"]),
])
def test_hint_contract_slots(end, source, targets):
    data = synthetic(end=end)
    hint = a.today_hint(data)
    assert hint["contract"] == source
    assert [p["contract"] for p in hint["paths"]] == targets
    missing = {"2026-09-18": 0, "2026-10-16": 2}.get(end)
    if missing is not None:
        assert hint["paths"][missing]["value"] is None
    table = a.daily_table(data)
    assert [r["expiry"] for r in table] == sorted(r["expiry"] for r in table)
    if end == "2026-09-21":
        assert [r["contract"] for r in table] == ["IC2611", "IC2612", "IC2703"]


def test_hint_outside_window_and_estimated_calendar():
    data = deepcopy(synthetic(end="2026-07-20"))
    assert a.today_hint(data)["outside_window"]
    data["calendar"] = data["calendar"][data["calendar"] <= data["as_of"]]
    hint = a.today_hint(data)
    assert hint["estimated"] and not hint["outside_window"]
    assert all(p["percentile"] is None for p in hint["paths"])
    json.dumps([hint, a.daily_table(data), a.chart_series(data), a.roll_stats(a.roll_events(data))], allow_nan=False)


def test_event_window_excludes_days_before_start(monkeypatch):
    monkeypatch.setattr(a, "START", "2022-08-18")
    [event] = a.roll_events(synthetic(end="2022-08-19"))
    assert event["dates"] == {1: "2022-08-18"}


def test_no_expired_events_has_no_history():
    hint = a.today_hint(synthetic(end="2022-07-22"))
    assert hint["history"] is None


@pytest.mark.parametrize("far_close, expected", [(97, 12), (100, 0), (103, -12)])
def test_slope_formula_and_input_unchanged(far_close, expected):
    data = deepcopy(synthetic(end="2022-07-22"))
    data["bars"]["close"] = [80, 110, 100, far_close]
    data["bars"] = data["bars"].sample(frac=1, random_state=7)
    before = deepcopy(data)
    series = a.slope_series(data)
    assert series == dict(dates=["2022-07-22"], values=[expected], near=["IC2212"], far=["IC2303"])
    json.dumps([series, a.slope_summary(series, data["as_of"])], allow_nan=False)
    pd.testing.assert_frame_equal(data["bars"], before["bars"])
    pd.testing.assert_frame_equal(data["spot"], before["spot"])
    pd.testing.assert_index_equal(data["calendar"], before["calendar"])
    assert data["expiry"] == before["expiry"]


@pytest.mark.parametrize("day, near, far", [
    ("2026-10-16", "IC2612", "IC2703"),
    ("2026-10-19", "IC2703", "IC2706"),
    ("2026-12-31", "IC2703", "IC2706"),
    ("2027-01-18", "IC2706", "IC2709"),
])
def test_slope_uses_daily_roles_across_roll_and_year(day, near, far):
    series = a.slope_series(synthetic(end=day))
    assert (series["dates"][-1], series["near"][-1], series["far"][-1]) == (day, near, far)
    summary = a.slope_summary(series, pd.Timestamp(day))
    assert (summary["near"], summary["far"]) == (near, far)


def test_slope_series_only_uses_start_through_as_of():
    data = deepcopy(synthetic(end="2022-07-26"))
    early = data["bars"].iloc[:4].assign(date=pd.Timestamp("2022-07-21"))
    data["bars"] = pd.concat([early, data["bars"]], ignore_index=True)
    data["as_of"] = pd.Timestamp("2022-07-25")
    assert a.slope_series(data)["dates"] == ["2022-07-22", "2022-07-25"]


def slope_fixture(dates, values):
    return dict(dates=dates, values=values, near=["IC2703"] * len(dates), far=["IC2706"] * len(dates))


def test_slope_summary_windows_equal_rank_and_earliest_maximum():
    series = slope_fixture([
        "2022-07-21", "2022-07-22", "2025-10-19", "2025-10-20", "2026-04-19",
        "2026-04-20", "2026-09-11", "2026-10-19", "2026-10-20",
    ], [0, 4, -20, 2, 90, 9, 9, 9, 1000])
    before = deepcopy(series)
    assert a.slope_summary(series, pd.Timestamp("2026-10-19")) == dict(
        value=9, near="IC2703", far="IC2706", year_percentile=80, percentile=86,
        deepest=9, deepest_date="2026-04-20")
    assert series == before


@pytest.mark.parametrize("day, year_edge, half_edge", [
    ("2024-02-29", "2023-02-28", "2023-08-29"),
    ("2026-08-31", "2025-08-31", "2026-02-28"),
])
def test_slope_calendar_windows_leap_day_and_month_end(day, year_edge, half_edge):
    after_year, after_half = [(pd.Timestamp(d) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
                              for d in (year_edge, half_edge)]
    series = slope_fixture([year_edge, after_year, half_edge, after_half, day], [0, 2, 90, 9, 9])
    summary = a.slope_summary(series, pd.Timestamp(day))
    assert summary == dict(value=9, near="IC2703", far="IC2706", year_percentile=75, percentile=80,
                           deepest=9, deepest_date=after_half)


@pytest.mark.parametrize("dates, values, rank, deepest", [
    (["2022-07-22"], [2], 100, 2),
    (["2022-07-22", "2022-07-25"], [3, 2], 50, 3),
])
def test_slope_short_history(dates, values, rank, deepest):
    summary = a.slope_summary(slope_fixture(dates, values), pd.Timestamp(dates[-1]))
    assert summary == dict(value=values[-1], near="IC2703", far="IC2706", year_percentile=rank,
                           percentile=rank, deepest=deepest, deepest_date="2022-07-22")
