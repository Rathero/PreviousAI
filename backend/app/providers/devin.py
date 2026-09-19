"""Devin (Cognition) API v3: the hands of the autonomous engineering layer.

Devin writes code on a branch of the repository and opens a pull request. It never
produces, changes or scores a number in a report: whether its work is accepted is
decided by the gate (`backend/autonomy/gate.py`), which is deterministic code, not a
person and not a model saying it looks good.

Only the endpoints the orchestrator needs are wrapped: create a session, read it, send
it a message (which also resumes a suspended session) and terminate it. See
https://docs.devin.ai/api-reference/overview. The key is a service-user token and never
leaves this module: errors are reported without it.
"""

from __future__ import annotations

import time

import httpx

from .. import config

TIMEOUT_S = 60.0
RETRIES = 3


class DevinUnavailable(RuntimeError):
    pass


def available() -> bool:
    return bool(config.DEVIN_API_KEY and config.DEVIN_ORG_ID)


def _url(path: str) -> str:
    return f"{config.DEVIN_API_URL}/organizations/{config.DEVIN_ORG_ID}{path}"


def _request(method: str, path: str, *, json: dict | None = None,
             params: dict | None = None) -> dict:
    if not available():
        raise DevinUnavailable("DEVIN_API_KEY and DEVIN_ORG_ID are not set in .env")
    headers = {"Authorization": f"Bearer {config.DEVIN_API_KEY}", "User-Agent": config.USER_AGENT}
    last = None
    for attempt in range(RETRIES):
        try:
            r = httpx.request(method, _url(path), json=json, params=params,
                              headers=headers, timeout=TIMEOUT_S)
        except httpx.HTTPError as exc:
            last = f"{type(exc).__name__}: {exc}"
        else:
            if r.status_code == 429 or r.status_code >= 500:
                last = f"HTTP {r.status_code}"
            elif r.status_code >= 400:
                raise DevinUnavailable(f"Devin API {method} {path}: HTTP {r.status_code} "
                                       f"{r.text[:300]}")
            else:
                return r.json() if r.content else {}
        time.sleep(2 ** attempt * 2)
    raise DevinUnavailable(f"Devin API {method} {path} failed after {RETRIES} tries: {last}")


def create_session(prompt: str, *, title: str, repos: list[str] | None = None,
                   structured_output_schema: dict | None = None,
                   max_acu_limit: int | None = None, tags: list[str] | None = None) -> dict:
    body = {"prompt": prompt, "title": title, "repos": repos or [config.DEVIN_REPO],
            "tags": tags or ["previous-ai", "autonomous-layer"]}
    if structured_output_schema:
        body["structured_output_schema"] = structured_output_schema
        body["structured_output_required"] = True
    if max_acu_limit:
        body["max_acu_limit"] = int(max_acu_limit)
    return _request("POST", "/sessions", json=body)


def get_session(session_id: str) -> dict:
    return _request("GET", f"/sessions/{session_id}")


def send_message(session_id: str, message: str) -> dict:
    """Also resumes the session if it was suspended."""
    return _request("POST", f"/sessions/{session_id}/messages", json={"message": message})


def terminate(session_id: str) -> dict:
    return _request("DELETE", f"/sessions/{session_id}")


def list_sessions(limit: int = 10) -> dict:
    return _request("GET", "/sessions", params={"first": limit})
