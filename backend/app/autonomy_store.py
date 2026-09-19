"""Where the autonomous engineering layer keeps its queue and its run records (data/autonomy/).

The queue is written by the report (`evidence.py`) when a number rests on one source;
the orchestrator (`scripts/devin_run.py`) takes tasks from it and writes one JSON record
per run: the trigger, the Devin session, every attempt with the gate's verdict and the
feedback sent back, and how it ended.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from . import config

QUEUE = config.AUTONOMY_DIR / "queue.json"
RUNS = config.AUTONOMY_DIR / "runs"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def queue() -> list[dict]:
    return _read(QUEUE, [])


def request(task: str, reason: str, place: str | None = None) -> dict:
    """Queues a task once; later requests only add the place that asked."""
    items = queue()
    item = next((i for i in items if i["task"] == task), None)
    if item is None:
        item = {"task": task, "reason": reason, "status": "requested", "requested_at": now(),
                "places": [], "run_id": None}
        items.append(item)
    if place and place not in item["places"]:
        item["places"].append(place)
    _write(QUEUE, items)
    return item


def set_status(task: str, status: str, run_id: str | None = None) -> None:
    items = queue()
    for i in items:
        if i["task"] == task:
            i["status"] = status
            i["run_id"] = run_id or i.get("run_id")
            i["updated_at"] = now()
    _write(QUEUE, items)


def task_status(task: str) -> dict | None:
    return next((i for i in queue() if i["task"] == task), None)


def save_run(run: dict) -> None:
    _write(RUNS / f"{run['run_id']}.json", run)


def load_run(run_id: str) -> dict | None:
    if not run_id.replace("-", "").isalnum():
        return None
    return _read(RUNS / f"{run_id}.json", None)


def runs() -> list[dict]:
    """Newest first, without the bulky per-check details."""
    out = []
    for p in RUNS.glob("*.json"):
        r = _read(p, None)
        if not r:
            continue
        out.append({k: r.get(k) for k in ("run_id", "task", "title", "status", "trigger",
                                          "started_at", "finished_at", "acus", "pr_url")}
                   | {"attempts": len(r.get("attempts") or []),
                      "session_url": (r.get("session") or {}).get("url")})
    return sorted(out, key=lambda r: r.get("started_at") or "", reverse=True)
