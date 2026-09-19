"""TypeSafe Jev: typed, calibrated decisions instead of generated text.

Jev never writes a word of the report and never produces a number that gets scored. It
answers the same typed questions as Nebius (`ai.py` picks between them) for three
judgements code cannot make on its own:

  1. `interpret.py`: reading a free-text request into place, dates and who is going.
  2. `claims.py`: checking sentence by sentence whether a text about the place is
     supported by the report.
  3. `advice.py`: ranking the hand-written advice by relevance to the household.

Every answer carries its probability, and every call reports its tokens and cost. The
HTTP API is called directly with httpx (https://docs.typesafe.ai/api). Answers are
cached by request, so a repeated question costs nothing.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time

import httpx

from .. import cache, config

PRICE_PER_MTOK_USD = 0.042  # input tokens; output tokens are free (docs.typesafe.ai/models)
TIMEOUT_S = 20.0
RETRIES = 3


class JevUnavailable(RuntimeError):
    pass


Unavailable = JevUnavailable


def available() -> bool:
    return bool(config.TYPESAFE_KEY)


def model() -> str:
    return config.TYPESAFE_MODEL


def _cost(usage: dict | None) -> float:
    return int((usage or {}).get("input_tokens") or 0) * PRICE_PER_MTOK_USD / 1e6


def _key(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


async def ask(state, questions: dict[str, dict], *, client: httpx.AsyncClient | None = None) -> dict:
    """One call: every question is evaluated against the same state, in parallel.

    Returns {"answers", "model", "usage", "elapsed_ms", "cached"}. Raises JevUnavailable
    with a readable reason on any failure; callers fall back.
    """
    if not available():
        raise JevUnavailable("TYPESAFE_API_KEY is not set")
    body = {"state": state, "model": config.TYPESAFE_MODEL, "questions": questions}
    key = _key(body)
    hit = cache.get("jev", key)
    if hit is not None:
        return {**hit, "cost_usd": _cost(hit.get("usage")), "elapsed_ms": 0, "cached": True}

    started = time.perf_counter()
    owns = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT_S)
    try:
        for attempt in range(RETRIES):
            try:
                resp = await client.post(
                    config.TYPESAFE_URL, json=body,
                    headers={"Authorization": f"Bearer {config.TYPESAFE_KEY}",
                             "User-Agent": config.USER_AGENT})
            except httpx.HTTPError as exc:
                if attempt == RETRIES - 1:
                    raise JevUnavailable(f"TypeSafe is not responding: {exc}") from exc
                await asyncio.sleep(0.5 * 2 ** attempt)
                continue
            if resp.status_code in (429, 529) and attempt < RETRIES - 1:
                wait = resp.headers.get("retry-after")
                await asyncio.sleep(float(wait) if wait and wait.replace(".", "").isdigit()
                                    else 0.5 * 2 ** attempt)
                continue
            if resp.status_code == 401:
                raise JevUnavailable("TypeSafe rejected the API key (401)")
            if resp.status_code >= 400:
                raise JevUnavailable(f"TypeSafe error {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            break
    finally:
        if owns:
            await client.aclose()

    usage = data.get("usage", {})
    out = {"answers": data.get("answers", {}), "model": data.get("model"), "usage": usage,
           "cost_usd": _cost(usage)}
    cache.set("jev", key, out)
    return {**out, "elapsed_ms": round((time.perf_counter() - started) * 1000), "cached": False}
