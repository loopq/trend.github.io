"""DataFetcher.fetch_index 契约测试（quant run_signal / backtest data_loader 依赖此接口）。"""
import inspect

import pytest
import requests

from scripts.data_fetcher import DataFetcher
from scripts.tests.conftest import make_df

ROUTES = {
    "cs_index": "_fetch_cs_index",
    "sina_index": "_fetch_sina_index",
    "spot_price": "_fetch_spot_price",
    "hk": "_fetch_hk_index",
    "us": "_fetch_us_index",
    "crypto": "_fetch_crypto_hist",
}


@pytest.fixture
def fetcher(monkeypatch):
    f = DataFetcher()
    calls = []
    for source, method in ROUTES.items():
        monkeypatch.setattr(f, method, lambda code, days, _s=source: calls.append((_s, code, days)) or make_df([1] * 25))
    f.calls = calls
    return f


@pytest.mark.parametrize("source", sorted(ROUTES))
def test_each_source_routes_to_its_fetcher(fetcher, source):
    df = fetcher.fetch_index("X", source, name="名", days=30)
    assert fetcher.calls == [(source, "X", 30)] and len(df) == 25


def test_unknown_source_returns_none(fetcher):
    assert fetcher.fetch_index("X", "nope") is None and fetcher.calls == []


def test_cache_hit_returns_independent_copy(fetcher):
    first = fetcher.fetch_index("X", "hk", days=30)
    first.loc[0, "close"] = -1
    second = fetcher.fetch_index("X", "hk", days=30)
    assert len(fetcher.calls) == 1 and second.loc[0, "close"] == 1


def test_network_error_returns_none(monkeypatch):
    f = DataFetcher()
    monkeypatch.setattr(f, "_fetch_hk_index", lambda code, days: (_ for _ in ()).throw(requests.exceptions.Timeout()))
    assert f.fetch_index("HSI", "hk") is None


def test_unexpected_error_propagates(monkeypatch):
    f = DataFetcher()
    monkeypatch.setattr(f, "_fetch_hk_index", lambda code, days: (_ for _ in ()).throw(RuntimeError("bug")))
    with pytest.raises(RuntimeError):
        f.fetch_index("HSI", "hk")


def test_public_signature_unchanged():
    params = inspect.signature(DataFetcher.fetch_index).parameters
    assert list(params) == ["self", "code", "source", "name", "days"]
    assert params["name"].default is None and params["days"].default == 300
