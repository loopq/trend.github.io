from __future__ import annotations

import pytest

from scripts.quant.data_fetcher import FixtureFetcher


def test_fixture_fetcher_indices(fixtures_dir):
    f = FixtureFetcher(fixtures_dir / "realtime_2026-04-25.json")
    quotes = f.fetch_indices(["399997", "399989", "931151"])
    assert len(quotes) == 3
    assert quotes["399997"].price == pytest.approx(13567.89)
    assert quotes["399989"].name == "中证医疗"


def test_fixture_fetcher_etfs(fixtures_dir):
    f = FixtureFetcher(fixtures_dir / "realtime_2026-04-25.json")
    quotes = f.fetch_etfs(["161725", "512170"])
    assert quotes["161725"].price == pytest.approx(1.236)


def test_fixture_fetcher_unknown_code_skipped(fixtures_dir):
    f = FixtureFetcher(fixtures_dir / "realtime_2026-04-25.json")
    quotes = f.fetch_indices(["399997", "999999"])
    assert "399997" in quotes
    assert "999999" not in quotes


def test_fixture_fetcher_empty_request(fixtures_dir):
    f = FixtureFetcher(fixtures_dir / "realtime_2026-04-25.json")
    assert f.fetch_indices([]) == {}
