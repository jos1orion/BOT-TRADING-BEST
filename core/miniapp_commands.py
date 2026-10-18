"""Small, local command inbox shared by the Mini App API and live bot.

The HTTP server only writes requests.  MT5 is touched exclusively by the
live-trading loop when it drains this inbox.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone

_lock = threading.Lock()


def enqueue(path: str, action: str, user_id: str) -> None:
    record = {
        "action": action,
        "user_id": str(user_id),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with _lock:
        with open(path, "a", encoding="utf-8") as output:
            output.write(json.dumps(record, separators=(",", ":")) + "\n")


def drain(path: str) -> list[dict]:
    """Atomically take pending valid Mini App actions from the local inbox."""
    with _lock:
        if not os.path.exists(path):
            return []
        processing = path + ".processing"
        try:
            os.replace(path, processing)
        except FileNotFoundError:
            return []
    try:
        with open(processing, encoding="utf-8") as source:
            rows = [json.loads(line) for line in source if line.strip()]
    finally:
        try:
            os.remove(processing)
        except FileNotFoundError:
            pass
    return [row for row in rows if isinstance(row, dict)]
