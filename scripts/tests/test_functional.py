"""端到端功能测试：合成行情 → 真实主链路 / 回填适配器 → 渲染页面 → 逐格对照独立 oracle。

时间语义（plan B3）：主链路用每个指数的最新 K 线，回填按目标日 T 截断。
个体指标在输入相同时跨路径相等；组内指标（趋势强度 / 强度变化 / 多空比例）各自对本路径整组输入的 oracle。
"""
import math
from datetime import datetime

import pandas as pd
import pytest
from bs4 import BeautifulSoup

import scripts.backfill_archive as backfill_mod
import scripts.main as main_mod
from scripts.generator import Generator
from scripts.tests import oracle
from scripts.tests.conftest import TEMPLATES, StubFetcher, cfg, make_df

T = "2026-10-16"          # 行情日（周五）
NOW = "2026-10-17"        # 主链路运行日 / 桩的「今天」
INDIVIDUAL = ["状态", "涨幅%", "现价", "临界值点", "偏离率", "量比", "状态转变时间", "区间涨幅%", "走势", "周月状态"]


def series(n, f, end=T, calendar="B", band=0.5):
    closes = [f(i) for i in range(n)]
    return make_df(closes, end=end, calendar=calendar,
                   highs=[c + band for c in closes], lows=[c - band for c in closes],
                   volumes=[1000 + 300 * math.sin(i / 3) for i in range(n)])


def jump(base, tail):
    """基础序列末尾替换为 tail（制造今日突破 / 跌破）"""
    df = base.copy()
    df.loc[df.index[-len(tail):], ["close", "open"]] = [[t, t] for t in tail]
    df["high"], df["low"] = df["close"] + 0.5, df["close"] - 0.5
    return df


def discriminating(rule, high_period):
    df = series(520, lambda i: 100 + math.sin(i / 9))
    df.loc[df["date"].dt.to_period(rule) == pd.Period(high_period, rule), "close"] = 1000.0
    df.loc[df.index[-1], "close"] = 104.0
    return df


def month_cliff():
    df = series(520, lambda i: 100.0)
    df.loc[df["date"] >= "2026-10-01", "close"] = 50.0
    return df


FRAMES = {
    "UP": series(520, lambda i: 100 + 0.5 * i + math.sin(i / 7)),                 # 极强
    "DOWN": series(520, lambda i: 400 - 0.5 * i + math.sin(i / 5)),               # 极弱
    "BRKUP": jump(series(520, lambda i: 100 + 2 * math.sin(i / 6)), [92] * 5 + [130]),   # 🔼
    "BRKDN": jump(series(520, lambda i: 100 + 2 * math.sin(i / 6)), [108] * 5 + [70]),   # 🔽
    "BTC": series(900, lambda i: 50000 + 3000 * math.sin(i / 11) + (9000 if i == 899 else 0),
                  end=NOW, calendar="D", band=50),                                 # 24 小时市场，含 T+1
    "LONG": series(700, lambda i: 300 + 20 * math.sin(i / 13)),                   # 超出中证日历窗口
    "SHORT": series(19, lambda i: 100.0),                                          # 数据不足
    "FAIL": None,                                                                  # 取数失败
    "WEEK": discriminating("W-SUN", "2026-06-01"),                                 # 周线判别（倒数第 20 根周线）
    "MONTH": month_cliff(),                                                        # 月线跨月突变
    "S1": series(520, lambda i: 80 + 5 * math.sin(i / 4)),
    "S2": series(520, lambda i: 60 + 0.05 * i + 3 * math.cos(i / 8)),
    "S3": series(520, lambda i: 90 - 0.02 * i + 2 * math.sin(i / 3)),
}
MAJOR = [cfg("UP"), cfg("DOWN", "sina_index"), cfg("BRKUP"), cfg("BRKDN", "hk"), cfg("BTC", "crypto"),
         cfg("LONG"), cfg("SHORT"), cfg("FAIL")]
SECTOR = [cfg(c) for c in ["WEEK", "MONTH", "S1", "S2", "S3"]]
CONFIG = {"lookback_days": 250, "major_indices": MAJOR, "sector_indices": SECTOR}


def oracle_groups(until=None):
    """各组 oracle；until 为回填截至日（None = 主链路，用桩可见的全部数据）"""
    def df_of(code):
        df = FRAMES[code]
        if df is None:
            return None
        df = df[df["date"] <= (until or NOW)]
        return df
    return [oracle.group([(c["code"], c["name"], df_of(c["code"])) for c in grp]) for grp in (MAJOR, SECTOR)]


def page(path):
    s = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    groups = []
    for t in s.select(".table-wrapper table"):
        heads = [th.get_text(strip=True) for th in t.select("thead th")]
        rows = {}
        for tr in t.select("tbody tr"):
            tds = [" ".join(td.get_text(" ", strip=True).split()) for td in tr.find_all("td")]
            rows[tds[1]] = dict(zip(heads, tds))
        groups.append(rows)
    ratio = (int(s.select_one(".bear-label").get_text().strip("空头 %")),
             int(s.select_one(".bull-label").get_text().strip("% 多头")))
    return groups, ratio


def assert_matches_oracle(path, until=None):
    groups, ratio = page(path)
    expected = oracle_groups(until)
    for got, (want, _) in zip(groups, expected):
        assert got == want
    assert ratio == expected[0][1]


@pytest.fixture(scope="module")
def main_site(tmp_path_factory):
    out = tmp_path_factory.mktemp("main")
    gen = Generator(TEMPLATES, str(out))
    assert main_mod.run(CONFIG, datetime.strptime(NOW, "%Y-%m-%d").date(), StubFetcher(FRAMES, NOW), gen)
    return out


@pytest.fixture(scope="module")
def backfill_site(tmp_path_factory):
    out = tmp_path_factory.mktemp("backfill")
    frames = {**FRAMES, "000300": FRAMES["UP"]}     # 回填以 000300 的 K 线确定交易日
    n = backfill_mod.backfill(CONFIG, datetime(2026, 10, 14), datetime(2026, 10, 16),
                              StubFetcher(frames, NOW), Generator(TEMPLATES, str(out)))
    assert n == 3
    return out


def test_main_pages_match_oracle_cell_by_cell(main_site):
    assert_matches_oracle(main_site / "index.html")
    assert_matches_oracle(main_site / "archive" / f"{T}.html")


def test_scenarios_are_actually_exercised(main_site):
    (major, _), _ = page(main_site / "index.html")
    assert "极强" in major["UP"]["趋势强度"] and "极弱" in major["DOWN"]["趋势强度"]
    assert major["BRKUP"]["状态"] == "YES 🔼" and major["BRKDN"]["状态"] == "NO 🔽"
    assert major["SHORT"]["状态"] == "数据不足" and major["FAIL"]["状态"] == "数据异常"
    _, sector = page(main_site / "index.html")[0]
    assert sector["WEEK"]["周月状态"].startswith("NO")       # B2：倒数第 20 根周线 1000 → 跌破
    assert sector["MONTH"]["周月状态"] == "NO - NO"


def test_backfill_days_match_oracle(backfill_site):
    for day in ["2026-10-14", "2026-10-15", T]:
        assert_matches_oracle(backfill_site / "archive" / f"{day}.html", until=day)


def test_individual_metrics_equal_across_paths_when_inputs_equal(main_site, backfill_site):
    (m_major, m_sector), _ = page(main_site / "archive" / f"{T}.html")
    (b_major, b_sector), _ = page(backfill_site / "archive" / f"{T}.html")
    for code in ["UP", "DOWN", "BRKUP", "BRKDN", "LONG"]:          # 最新 K 线 = T
        assert {k: m_major[code][k] for k in INDIVIDUAL} == {k: b_major[code][k] for k in INDIVIDUAL}
    assert m_major["BTC"]["现价"] != b_major["BTC"]["现价"]          # 24 小时市场：按设计不同
    assert m_sector == b_sector                                      # 全组输入相同 → 组内指标也相同


def test_backfill_archive_list_lists_all_days(backfill_site):
    links = [a["href"] for a in BeautifulSoup((backfill_site / "archive" / "index.html").read_text(encoding="utf-8"),
                                              "html.parser").select(".archive-month a")]
    assert links == ["2026-10-16.html", "2026-10-15.html", "2026-10-14.html"]
