from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.quant.notifier import DryRunNotifier, NotificationCard


def _card() -> NotificationCard:
    return NotificationCard(
        title="量化信号 2026-04-25",
        summary="今日 3 条信号（D-BUY ×2 / D-SELL ×1）",
        items=[
            {"text": "[D-BUY] 中证白酒(161725) 1000 股 @¥1.236", "url": "https://x/quant/index/399997.html"},
            {"text": "[D-SELL] 创业板 50(159949) 全部 300 股", "url": "https://x/quant/index/399673.html"},
        ],
        detail_url="https://loopq.github.io/trend.github.io/quant/",
    )


def test_dry_run_notifier_writes_outbox(tmp_data_dir):
    notifier = DryRunNotifier(tmp_data_dir / "notify-outbox")
    notifier.send(_card())
    files = list((tmp_data_dir / "notify-outbox").iterdir())
    assert len(files) == 1
    payload = json.loads(files[0].read_text())
    assert payload["card"]["title"] == "量化信号 2026-04-25"
    assert "feishu_payload" in payload


def test_dry_run_notifier_payload_is_feishu_interactive(tmp_data_dir):
    notifier = DryRunNotifier(tmp_data_dir / "notify-outbox")
    notifier.send(_card())
    files = list((tmp_data_dir / "notify-outbox").iterdir())
    payload = json.loads(files[0].read_text())
    fp = payload["feishu_payload"]
    assert fp["msg_type"] == "interactive"
    assert fp["card"]["header"]["title"]["content"] == "量化信号 2026-04-25"
    # 含 action button
    actions = [e for e in fp["card"]["elements"] if e.get("tag") == "action"]
    assert len(actions) == 1
    assert actions[0]["actions"][0]["url"] == "https://loopq.github.io/trend.github.io/quant/"


def test_card_payload_lark_md_formatting():
    fp = _card().to_feishu_payload()
    # 摘要和每条信号都应用 lark_md
    md_elements = [e for e in fp["card"]["elements"] if e.get("text", {}).get("tag") == "lark_md"]
    assert len(md_elements) >= 3  # 1 summary + 2 items


def test_dry_run_notifier_multiple_cards_dont_collide(tmp_data_dir):
    """多次 send 不会因为时间戳相同而覆盖文件。"""
    notifier = DryRunNotifier(tmp_data_dir / "notify-outbox")
    for _ in range(3):
        notifier.send(_card())
    files = list((tmp_data_dir / "notify-outbox").iterdir())
    assert len(files) == 3
