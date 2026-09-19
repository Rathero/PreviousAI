"""Disk cache with a time to live.

Every external answer is kept on disk: repeated places are instant, public services
are not hammered, and with OFFLINE_FALLBACK an expired answer is served when a
source is unreachable instead of failing the report.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from . import config


def _path(namespace: str, key: str):
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
    folder = config.CACHE_DIR / namespace
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{digest}.json"


def get(namespace: str, key: str, *, allow_stale: bool = False,
        ttl: float | None = None) -> Any | None:
    """`ttl` in seconds overrides the global one: live alerts expire in half an hour,
    climatology in weeks."""
    path = _path(namespace, key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    limit = config.CACHE_TTL_SECONDS if ttl is None else ttl
    fresh = time.time() - payload.get("stored_at", 0) < limit
    if fresh or allow_stale:
        return payload.get("value")
    return None


def set(namespace: str, key: str, value: Any) -> None:  # noqa: A001
    path = _path(namespace, key)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"stored_at": time.time(), "key": key, "value": value}),
        encoding="utf-8",
    )
    tmp.replace(path)


def stats() -> dict:
    entries = list(config.CACHE_DIR.rglob("*.json"))
    return {
        "entries": len(entries),
        "bytes": sum(p.stat().st_size for p in entries),
        "namespaces": sorted({p.parent.name for p in entries}),
    }
