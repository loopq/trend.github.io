"""09:00 reconcile：跨日 pending 信号 → expired（§8.5）。

单 commit 多文件原子提交（更新所有 signals/{date}.json + index.json）。
循环外一次 commit（Round 2 Issue 8 修订）。
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .config import Config
from .signal_generator import _ts_iso
from .writer import FileChange, LocalWriter


def reconcile_pending_signals(
    *,
    cfg: Config,
    today: date,
    repo_root: Path,
    writer: LocalWriter,
) -> dict:
    """把 today 之前所有 pending 信号 → expired。

    返回汇总：{ "expired_count": N, "files_changed": [...] }。
    """
    today_str = today.strftime("%Y-%m-%d")
    index_path = repo_root / cfg.paths["signals_index"]
    if not index_path.exists():
        return {"expired_count": 0, "files_changed": []}

    index_payload = json.loads(index_path.read_text(encoding="utf-8"))
    entries = index_payload.get("entries", [])

    changes: list[FileChange] = []
    expired_total = 0
    affected_dates: list[str] = []

    new_entries = []
    for entry in entries:
        if entry["date"] >= today_str or entry.get("pending_count", 0) == 0:
            new_entries.append(entry)
            continue

        # entry["file"] 是相对 data_root 的路径（如 "signals/2026-04-24.json"）
        signals_path = repo_root / cfg.paths["data_root"] / entry["file"]
        if not signals_path.exists():
            new_entries.append(entry)
            continue

        payload = json.loads(signals_path.read_text(encoding="utf-8"))
        any_changed = False
        for sig in payload.get("signals", []):
            if sig.get("status") == "pending":
                sig["status"] = "expired"
                sig["expired_at"] = _ts_iso()
                sig["expired_reason"] = "not_confirmed_within_window"
                expired_total += 1
                any_changed = True

        if any_changed:
            # 重新统计
            sigs = payload.get("signals", [])
            entry["pending_count"] = sum(1 for s in sigs if s["status"] == "pending")
            entry["expired_count"] = sum(1 for s in sigs if s["status"] == "expired")
            changes.append(FileChange(
                path=signals_path,
                content=json.dumps(payload, ensure_ascii=False, indent=2),
            ))
            affected_dates.append(entry["date"])
        new_entries.append(entry)

    if not changes:
        return {"expired_count": 0, "files_changed": []}

    index_payload["entries"] = new_entries
    index_payload["updated_at"] = _ts_iso()
    changes.append(FileChange(
        path=index_path,
        content=json.dumps(index_payload, ensure_ascii=False, indent=2),
    ))

    writer.commit_atomic(changes, message=f"[quant] reconcile pending → expired {today_str}")
    return {
        "expired_count": expired_total,
        "files_changed": [str(c.path) for c in changes],
        "affected_dates": affected_dates,
    }
