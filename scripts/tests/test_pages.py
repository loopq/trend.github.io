"""页面结构测试：经真实 main() 链路渲染，bs4 解析。"""
import os

import pytest
from bs4 import BeautifulSoup

from scripts.tests.conftest import cfg, make_df

MAJOR = [cfg("000300"), cfg("000905"), cfg("000852")]
SECTOR = [cfg("000819"), cfg("399986")]


def soup(path):
    return BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")


def archive_page(site):
    [name] = [f for f in os.listdir(site / "archive") if f != "index.html"]
    return site / "archive" / name


@pytest.fixture
def site(run_cli):
    frames = {c["code"]: make_df(range(100 + i, 140 + i), end="2026-10-16")
              for i, c in enumerate(MAJOR + SECTOR)}
    code, out, site, _ = run_cli(["--mock-date", "2026-10-17"], frames, MAJOR, SECTOR)
    assert code is None and out == {"should_deploy": "true"}
    return site


def headers(page):
    return [[th.get_text(strip=True) for th in t.select("thead th")] for t in soup(page).select(".table-wrapper table")]


# ---------- D3：归档页与首页同一份列定义 ----------

def test_archive_columns_match_index_including_volume_ratio(site):
    index_heads, archive_heads = headers(site / "index.html"), headers(archive_page(site))
    assert len(index_heads[0]) == 14 and "量比" in index_heads[0]
    assert archive_heads == index_heads


def test_every_data_row_fills_all_columns(site):
    for page in (site / "index.html", archive_page(site)):
        for table in soup(page).select(".table-wrapper table"):
            width = len(table.select("thead th"))
            for tr in table.select("tbody tr"):
                assert len(tr.find_all("td")) == width


# ---------- 模板统一：列说明单一来源、相对路径、入口槽、GA ----------

def test_help_modal_terms_equal_table_headers(site):
    for page in (site / "index.html", archive_page(site)):
        terms = [dt.get_text(strip=True) for dt in soup(page).select("#columnHelpModal .help-list dt")]
        assert terms == headers(page)[0]


def test_relative_paths(site):
    s = soup(site / "index.html")
    assert s.select_one('link[rel="stylesheet"]')["href"] == "css/style.css"
    assert [a["href"] for a in s.select(".nav-links a")] == ["archive/index.html"]
    a = soup(archive_page(site))
    assert a.select_one('link[rel="stylesheet"]')["href"] == "../css/style.css"
    assert [x["href"] for x in a.select(".nav-links a")] == ["../index.html", "../archive/index.html"]


def test_site_nav_slot_present_and_empty(site):
    for page in (site / "index.html", archive_page(site), site / "archive" / "index.html"):
        nav = soup(page).select_one(".header > nav.site-nav")
        assert nav is not None and nav.decode_contents() == ""


def test_ga_rendered_only_with_measurement_id(run_cli, monkeypatch):
    frames = {"000300": make_df(range(100, 140), end="2026-10-16")}
    _, _, site, _ = run_cli(["--mock-date", "2026-10-17"], frames, [cfg("000300")], ga="G-TEST123")
    for page in (site / "index.html", archive_page(site), site / "archive" / "index.html"):
        assert "gtag/js?id=G-TEST123" in page.read_text(encoding="utf-8")
    _, _, site, _ = run_cli(["--mock-date", "2026-10-17"], frames, [cfg("000300")])
    assert "googletagmanager" not in (site / "index.html").read_text(encoding="utf-8")


def test_error_row_spans_remaining_columns(run_cli):
    frames = {c["code"]: make_df(range(100, 140), end="2026-10-16") for c in MAJOR}
    frames["000852"] = None   # 取数失败，失败率 1/3 不超限
    _, _, site, _ = run_cli(["--mock-date", "2026-10-17"], frames, MAJOR)
    for page in (site / "index.html", archive_page(site)):
        [td] = soup(page).select("td.status-error")
        assert td.get_text(strip=True) == "数据异常" and td["colspan"] == "11"
