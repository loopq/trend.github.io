"""飞书推送通知器（§6.16 通知失败硬失败 + 单卡片汇总）。

两种模式：
- DryRunNotifier：写 `notify-outbox/{ts}.json` 模拟"已发送"（本地走通用）
- FeishuWebhookNotifier：真发到 webhook（上线用）

失败重试：3 次指数退避（5s / 15s / 45s）；耗尽抛 NotifierUnrecoverableError 让 workflow exit 1。
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Protocol


class NotifierUnrecoverableError(Exception):
    """3 次重试后仍失败 → 工作流应 exit 1 → GitHub Actions 默认发邮件兜底。"""


@dataclass(frozen=True)
class NotificationCard:
    """飞书 interactive 卡片，单卡汇总当日所有信号。"""
    title: str
    summary: str
    items: list[dict]   # 每项 = {"text": "...", "url": "..."}
    detail_url: str

    def to_feishu_payload(self) -> dict:
        elements = [{"tag": "div", "text": {"tag": "lark_md", "content": self.summary}}]
        for it in self.items:
            content = it.get("text", "")
            if "url" in it:
                content = f"[{content}]({it['url']})"
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": content}})
        elements.append({
            "tag": "action",
            "actions": [{
                "tag": "button",
                "text": {"tag": "plain_text", "content": "→ 打开量化控制台"},
                "url": self.detail_url,
                "type": "default",
            }],
        })
        return {
            "msg_type": "interactive",
            "card": {
                "header": {"title": {"tag": "plain_text", "content": self.title}},
                "elements": elements,
            },
        }


class Notifier(Protocol):
    def send(self, card: NotificationCard) -> None: ...


class DryRunNotifier:
    """写 notify-outbox/{ts}.json，不发外部网络请求。"""

    def __init__(self, outbox_dir: Path | str) -> None:
        self.outbox_dir = Path(outbox_dir)

    def send(self, card: NotificationCard) -> None:
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S-%f")
        path = self.outbox_dir / f"{ts}.json"
        payload = {
            "sent_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "card": asdict(card),
            "feishu_payload": card.to_feishu_payload(),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


class FeishuWebhookNotifier:  # pragma: no cover -- 联网，本地走通不跑
    """真发到飞书 webhook + 3 次指数退避重试 + 失败抛 NotifierUnrecoverableError。"""

    def __init__(
        self,
        webhook_url: str,
        retry_count: int = 3,
        backoff_seconds: tuple[float, ...] = (5, 15, 45),
    ) -> None:
        if not webhook_url:
            raise ValueError("webhook_url is empty")
        self.webhook_url = webhook_url
        self.retry_count = retry_count
        self.backoff_seconds = backoff_seconds

    def send(self, card: NotificationCard) -> None:
        import requests

        payload = card.to_feishu_payload()
        last_err: Exception | None = None
        for attempt in range(self.retry_count + 1):
            try:
                resp = requests.post(self.webhook_url, json=payload, timeout=10)
                resp.raise_for_status()
                body = resp.json()
                # 飞书成功响应：{"code": 0, ...}；非 0 视为失败
                if body.get("code", 0) != 0:
                    raise RuntimeError(f"feishu code={body.get('code')} msg={body.get('msg')}")
                return
            except Exception as e:
                last_err = e
                if attempt < self.retry_count:
                    backoff = self.backoff_seconds[min(attempt, len(self.backoff_seconds) - 1)]
                    time.sleep(backoff)
        raise NotifierUnrecoverableError(
            f"飞书推送失败 {self.retry_count} 次：{last_err}"
        )
