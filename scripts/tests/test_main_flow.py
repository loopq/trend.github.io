"""main() CLI 层流程测试：跳过 / 部署 / 失败率退出 / GITHUB_OUTPUT 契约。
桩替换取数与输出目录，CLI 参数与 main() 行为保持生产原样。"""
import os

from scripts.tests.conftest import cfg, make_df

HS300 = cfg("000300")
OTHER = cfg("000905")


def frames_ending(end):
    return {"000300": make_df(range(100, 140), end=end), "000905": make_df(range(200, 240), end=end)}


def test_skip_when_yesterday_not_trading_day(run_cli):
    code, out, site, fetcher = run_cli(["--mock-date", "2026-10-19"], frames_ending("2026-10-16"), [HS300])
    assert code is None and out == {"should_deploy": "false"}
    assert fetcher.calls == [] and not site.exists()


def test_deploy_when_data_fresh(run_cli):
    code, out, site, fetcher = run_cli(["--mock-date", "2026-10-17"], frames_ending("2026-10-16"), [HS300, OTHER])
    assert code is None and out == {"should_deploy": "true"}
    assert fetcher.calls == [("000300", "cs_index", 800), ("000905", "cs_index", 800)]  # 无重复请求
    assert (site / "index.html").exists() and (site / "archive" / "index.html").exists()
    assert archive_days(site) == ["2026-10-16.html"]


def test_skip_when_a_share_data_stale(run_cli):
    code, out, site, _ = run_cli(["--mock-date", "2026-10-17"], frames_ending("2026-10-15"), [HS300, OTHER])
    assert code is None and out == {"should_deploy": "false"}
    assert not (site / "index.html").exists()


def archive_days(site):
    return sorted(f for f in os.listdir(site / "archive") if f != "index.html")


def test_force_on_non_trading_day_records_latest_a_share_date(run_cli):
    """周一 force：行情日取沪深300 最新 K 线（10-16），不产出周日（10-18）页面"""
    code, out, site, _ = run_cli(["--mock-date", "2026-10-19", "--force"], frames_ending("2026-10-16"), [HS300, OTHER])
    assert code is None and out == {"should_deploy": "true"}
    assert archive_days(site) == ["2026-10-16.html"]
    assert "日期：2026.10.16" in (site / "index.html").read_text(encoding="utf-8")


def test_force_bypasses_trading_day_and_staleness(run_cli):
    code, out, site, _ = run_cli(["--mock-date", "2026-10-19", "--force"], frames_ending("2026-10-15"), [HS300, OTHER])
    assert code is None and out == {"should_deploy": "true"}
    assert (site / "index.html").exists()


def test_exit_1_when_failure_rate_above_one_third(run_cli):
    frames = {"000300": make_df(range(100, 140), end="2026-10-16")}  # 000905 / 000852 取数失败
    code, out, site, _ = run_cli(["--mock-date", "2026-10-17"], frames, [HS300, OTHER, cfg("000852")])
    assert code == 1 and out == {}
    assert not (site / "index.html").exists()


# ---------- B5：数据不足不得让整批崩溃 ----------

def test_short_history_index_becomes_error_row(run_cli):
    frames = frames_ending("2026-10-16")
    frames["000852"] = make_df([100] * 19, end="2026-10-16")
    code, out, site, _ = run_cli(["--mock-date", "2026-10-17"], frames, [HS300, OTHER, cfg("000852")])
    assert code is None and out == {"should_deploy": "true"}
    assert "数据不足" in (site / "index.html").read_text(encoding="utf-8")


def test_short_history_counts_toward_failure_rate(run_cli):
    frames = frames_ending("2026-10-16")
    frames["000852"] = make_df([100] * 19, end="2026-10-16")
    frames["000905"] = make_df([100] * 5, end="2026-10-16")
    code, out, _, _ = run_cli(["--mock-date", "2026-10-17"], frames, [HS300, OTHER, cfg("000852")])
    assert code == 1 and out == {}
