"""离线输入契约与有界请求；不访问行情服务。"""
import socket
import threading
import time
from copy import deepcopy

import akshare as ak
import pandas as pd
import pytest
import requests

from scripts.futures import data as d
from scripts.tests.futures_oracle import patch_sources, synthetic


def test_contract_enumeration():
    active = {c: None for c in ["IC2612", "IC2701", "IC2703", "IC2706"]}
    result = d.contracts_to_fetch("IC", active)
    assert result[:2] == ["IC2208", "IC2209"]
    assert result[-5:] == ["IC2611", "IC2612", "IC2701", "IC2703", "IC2706"]
    assert "IC2702" not in result and len(result) == len(set(result))


def load(monkeypatch, as_of="2026-10-16", end="2026-10-19"):
    patch_sources(monkeypatch, end)
    cal = d.load_calendar()
    return d.load_variety("IC", pd.Timestamp(as_of), cal)


def test_sources_ahead_are_truncated(monkeypatch):
    data = load(monkeypatch)
    assert data["spot"].date.max() == data["bars"].date.max() == pd.Timestamp("2026-10-16")


def test_sources_behind_main_date_fail(monkeypatch):
    with pytest.raises(d.FuturesDataError):
        load(monkeypatch, end="2026-10-15")


@pytest.mark.parametrize("fault", ["spot_missing", "whole_day", "last_bar", "middle_bar", "duplicate_bar",
                                 "duplicate_spot", "zero", "nan", "inf", "spot_zero", "spot_nan", "spot_inf",
                                 "non_trading", "active", "expiry", "listing"])
def test_input_contracts_reject_corruption(fault):
    data = deepcopy(synthetic(end="2026-10-16"))
    t = data["as_of"]
    active = {c: data["expiry"][c] for c in data["bars"].loc[data["bars"].date == t, "contract"]}
    bars, spot = data["bars"], data["spot"]
    bad_day = pd.Timestamp("2026-09-07")
    if fault == "spot_missing":
        data["spot"] = spot[spot.date != bad_day]
    elif fault == "whole_day":
        data["bars"] = bars[bars.date != bad_day]
    elif fault in ("last_bar", "middle_bar"):
        day = pd.Timestamp("2026-09-18") if fault == "last_bar" else bad_day
        data["bars"] = bars[~((bars.contract == "IC2609") & (bars.date == day))]
    elif fault.startswith("duplicate"):
        key = "spot" if fault == "duplicate_spot" else "bars"
        data[key] = pd.concat([data[key], data[key].iloc[[0]]], ignore_index=True)
    elif fault in ("zero", "nan", "inf", "spot_zero", "spot_nan", "spot_inf"):
        key = "spot" if fault.startswith("spot_") else "bars"
        data[key].loc[0, "close"] = {"zero": 0, "nan": float("nan"), "inf": float("inf")}[fault.split("_")[-1]]
    elif fault == "non_trading":
        data["as_of"] = pd.Timestamp("2026-10-17")
    elif fault == "active":
        active.pop(next(iter(active)))
    elif fault == "expiry":
        data["expiry"]["IC2609"] += pd.Timedelta(days=3)
    elif fault == "listing":
        data["bars"].loc[bars.contract == "IC2609", "contract"] = "IC2610"
    with pytest.raises(d.FuturesDataError):
        d.validate(data, active)


def test_missing_last_bar_even_with_four_replacement_quotes():
    data = deepcopy(synthetic(end="2026-10-16"))
    bars = data["bars"]
    mask = (bars.contract == "IC2609") & (bars.date == "2026-09-18")
    bars.loc[mask, "contract"] = "IC2611"
    active = {c: data["expiry"][c] for c in bars.loc[bars.date == data["as_of"], "contract"]}
    with pytest.raises(d.FuturesDataError):
        d.validate(data, active)


def test_contract_failure_retries_three_times(monkeypatch):
    patch_sources(monkeypatch)
    calls, waits = [], []

    def fail(symbol):
        calls.append(symbol)
        raise ValueError("上游失败")

    monkeypatch.setattr(ak, "futures_zh_daily_sina", fail)
    monkeypatch.setattr(d.time, "sleep", waits.append)
    with pytest.raises(d.FuturesDataError):
        d.load_variety("IC", pd.Timestamp("2026-10-16"), d.load_calendar())
    assert len(calls) == 3 and waits == [1, 2]


def test_request_timeout_is_bounded_and_restored():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(4)
    stop, connections = threading.Event(), []

    def accept():
        server.settimeout(.05)
        while not stop.is_set():
            try:
                connection, _ = server.accept()
                connections.append(connection)
            except socket.timeout:
                pass

    worker = threading.Thread(target=accept, daemon=True)
    worker.start()
    original = requests.Session.request
    start = time.monotonic()
    try:
        with d.request_timeout((.05, .05)):
            with pytest.raises(d.FuturesDataError):
                d.request(requests.get, f"http://127.0.0.1:{server.getsockname()[1]}", delays=(0, 0))
        assert requests.Session.request is original
        assert time.monotonic() - start < 1.5
        assert len(connections) == 3
    finally:
        stop.set()
        worker.join(1)
        for connection in connections:
            connection.close()
        server.close()


@pytest.mark.parametrize("fault", ["date", "close", "column"])
def test_malformed_contract_schema_is_data_error(monkeypatch, fault):
    patch_sources(monkeypatch)
    original = ak.futures_zh_daily_sina

    def malformed(symbol):
        frame = original(symbol)
        if fault == "column":
            return frame.drop(columns="close")
        frame[fault] = "invalid"
        return frame

    monkeypatch.setattr(ak, "futures_zh_daily_sina", malformed)
    with pytest.raises(d.FuturesDataError):
        d.load_variety("IC", pd.Timestamp("2026-10-16"), d.load_calendar())
