"""Typed AI decisions, whichever service answers them.

The AI is asked three kinds of things (`interpret.py`, `claims.py`, `advice.py`), always
as typed questions: a choice among options written by code, or the probability that a
statement is true. Two services answer them in the same shape:

  - Nebius Token Factory (`nebius.py`): an open-weights LLM whose reply is forced to
    one of our options, with probabilities read from its token log-probabilities.
  - TypeSafe Jev (`jev.py`): a model built to return typed, calibrated answers.

`AI_PROVIDER` picks one; by default the first with a key (Nebius first). If the chosen
one fails (network, rate limit, retired model) the other answers when it has a key.
Neither ever writes a word of the report or produces a number that gets scored.
Without any key every feature falls back to deterministic code.
"""

from __future__ import annotations

from .. import config
from . import jev, nebius

BACKENDS = {"nebius": nebius, "typesafe": jev}
NAMES = {"nebius": "Nebius Token Factory", "typesafe": "TypeSafe Jev"}


class AIUnavailable(RuntimeError):
    pass


# --- Question builders -------------------------------------------------------------
def choice(instructions: str, criteria: dict[str, str | None]) -> dict:
    return {"type": "choice", "instructions": instructions, "criteria": criteria}


def noul(instructions: str, true: str | None = None, false: str | None = None) -> dict:
    """The probability that a statement is true ("noul" in TypeSafe's vocabulary)."""
    q = {"type": "noul", "instructions": instructions}
    if true or false:
        q["criteria"] = {k: v for k, v in (("true", true), ("false", false)) if v}
    return q


# --- Which service -------------------------------------------------------------------
def provider() -> str | None:
    if config.AI_PROVIDER in BACKENDS:
        return config.AI_PROVIDER if BACKENDS[config.AI_PROVIDER].available() else None
    return next((k for k, b in BACKENDS.items() if b.available()), None)


def available() -> bool:
    return provider() is not None


def model() -> str | None:
    p = provider()
    return BACKENDS[p].model() if p else None


def name() -> str | None:
    p = provider()
    return NAMES[p] if p else None


def status() -> dict:
    p = provider()
    return {"configured": p is not None, "provider": p, "name": NAMES.get(p), "model": model(),
            "keys": {k: b.available() for k, b in BACKENDS.items()}}


async def ask(state, questions: dict[str, dict]) -> dict:
    """One call to the service that is on; if it fails, to the other one with a key.

    Raises AIUnavailable when none answers; callers fall back to code.
    """
    first = provider()
    if first is None:
        raise AIUnavailable("no AI key is set (NEBIUS_API_KEY or TYPESAFE_API_KEY)")
    errors = []
    for p in [first] + [k for k, b in BACKENDS.items() if k != first and b.available()]:
        backend = BACKENDS[p]
        try:
            result = await backend.ask(state, questions)
        except backend.Unavailable as exc:
            errors.append(f"{NAMES[p]}: {exc}")
            continue
        return {**result, "provider": p, "fallback_from": errors or None}
    raise AIUnavailable("; ".join(errors))


class Meter:
    """Adds up the calls made for one feature: tokens, cost and latency."""

    def __init__(self) -> None:
        self.calls = self.cached = self.input_tokens = self.output_tokens = 0
        self.elapsed_ms = 0
        self.cost_usd = 0.0
        self.model: str | None = None
        self.provider: str | None = None

    def add(self, result: dict) -> dict:
        usage = result.get("usage") or {}
        self.calls += 1
        self.cached += bool(result.get("cached"))
        self.input_tokens += int(usage.get("input_tokens") or 0)
        self.output_tokens += int(usage.get("output_tokens") or 0)
        self.cost_usd += float(result.get("cost_usd") or 0)
        self.elapsed_ms = max(self.elapsed_ms, result.get("elapsed_ms") or 0)
        self.model = result.get("model") or self.model
        self.provider = result.get("provider") or self.provider
        return result

    def to_dict(self) -> dict:
        p = self.provider or provider()
        return {"provider": NAMES.get(p, p), "model": self.model or model(), "calls": self.calls,
                "cached_calls": self.cached, "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens, "cost_usd": round(self.cost_usd, 6),
                "elapsed_ms": self.elapsed_ms}
