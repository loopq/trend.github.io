"""workflow 结构断言：主站定时入口保留、quant 入口下线、gh-pages 双写入方的发布归属与有界重试。
真实并发竞争只能在 CI 中发生；这里守护配置层面的条件闭合。"""
import os

import yaml

WF = os.path.join(os.path.dirname(__file__), "..", "..", ".github", "workflows")
GH_PAGES = "peaceiris/actions-gh-pages"


def load(name):
    with open(os.path.join(WF, name), encoding="utf-8") as f:
        wf = yaml.safe_load(f)
    return wf, wf.get("on", wf.get(True))   # PyYAML 把 on 解析为 True


def steps(wf):
    [job] = wf["jobs"].values()
    return job["steps"]


def find(wf, pred):
    return [i for i, s in enumerate(steps(wf)) if pred(s)]


def runs(s, text):
    return text in (s.get("run") or "")


def deploys(wf):
    return [s for s in steps(wf) if GH_PAGES in s.get("uses", "")]


def assert_bounded_retry(wf, gate=""):
    first, retry = deploys(wf)
    assert first["id"] == "deploy" and first.get("continue-on-error") is True
    assert "steps.deploy.outcome == 'failure'" in retry["if"] and gate in retry["if"]
    assert "continue-on-error" not in retry                      # 重试耗尽 → job 失败
    assert first["with"] == retry["with"]
    for d in (first, retry):
        assert d["with"]["keep_files"] is True and "force_orphan" not in d["with"]
        assert "exclude_assets" not in d["with"]                 # exclude 会删除目标端匹配文件
    return first, retry


# ---------- update.yml ----------

def test_update_keeps_schedule_entrypoints():
    wf, on = load("update.yml")
    assert on["repository_dispatch"]["types"] == ["morning"] and "workflow_dispatch" in on
    assert wf["concurrency"]["group"] == "trend-update"


def test_update_has_no_quant_steps():
    wf, _ = load("update.yml")
    for s in steps(wf):
        assert "quant" not in s.get("run", "").lower()           # 不再执行任何 quant 命令
        assert "git push" not in s.get("run", "")                # 主站不再推 main


def test_update_restores_archives_before_generating_and_publishes_staging_only():
    wf, _ = load("update.yml")
    [restore] = find(wf, lambda s: runs(s, "scripts.site_publish restore origin/gh-pages docs"))
    [gen] = find(wf, lambda s: runs(s, "scripts/main.py"))
    [stage] = find(wf, lambda s: runs(s, "scripts.site_publish stage docs /tmp/site-publish"))
    first_deploy = min(find(wf, lambda s: GH_PAGES in s.get("uses", "")))
    assert restore < gen < stage < first_deploy
    assert "continue-on-error" not in steps(wf)[restore]          # 恢复失败即中止，不部署
    assert "should_deploy == 'true'" in steps(wf)[stage]["if"]


def test_update_deploy_retry_and_notification_gate():
    wf, _ = load("update.yml")
    gate = "steps.run_script.outputs.should_deploy == 'true'"
    first, _ = assert_bounded_retry(wf, gate)
    assert gate in first["if"] and first["with"]["publish_dir"] == "/tmp/site-publish"
    [mail] = [s for s in steps(wf) if "send-mail" in s.get("uses", "")]
    assert gate in mail["if"]
    assert "steps.deploy.outcome == 'success'" in mail["if"] and "steps.deploy_retry.outcome == 'success'" in mail["if"]
    assert [s["id"] for s in deploys(wf)] == ["deploy", "deploy_retry"]


# ---------- backtest.yml ----------

def test_backtest_publish_has_bounded_retry():
    wf, _ = load("backtest.yml")
    first, _ = assert_bounded_retry(wf)
    assert first["with"]["publish_dir"] == "/tmp/quant-publish"
    assert find(wf, lambda s: runs(s, "git push origin main"))  # main 的提交推送段保留


# ---------- 入口清单 ----------

def test_quant_scheduler_removed_and_keepalive_kept():
    assert not os.path.exists(os.path.join(WF, "quant.yml"))
    _, on = load("keepalive.yml")
    assert on["schedule"]


def test_trend_tests_workflow_covers_site_and_publish_config():
    wf, on = load("trend-test.yml")
    for trigger in ("push", "pull_request"):
        paths = on[trigger]["paths"]
        for p in ("scripts/*.py", "scripts/tests/**", "templates/**", "docs/css/**",
                  ".github/workflows/update.yml", ".github/workflows/backtest.yml",
                  ".github/workflows/trend-test.yml"):
            assert p in paths
    assert find(wf, lambda s: runs(s, "pytest scripts/tests scripts/backtest"))
