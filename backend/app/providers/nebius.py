"""Nebius Token Factory: typed AI decisions answered by an open-weights LLM.

It answers exactly the questions TypeSafe Jev answers (`ai.choice`, `ai.noul`), in the
same shape, so the callers do not know which service replied. The model never writes
free text for the report:

  - All the questions of one call go in ONE chat completion. The reply is forced to a
    JSON object whose every value is one of the options we listed (JSON schema with an
    `enum` per question), so there is nothing to parse or repair.
  - Probabilities are not the model's opinion of itself: they are read from the
    log-probabilities of the tokens it chose, and of the alternatives it did not
    choose, at every token of each answer (`_distribution`).
  - Temperature 0, and answers cached per request, so results are reproducible and a
    repeated question costs nothing.

The HTTP API is OpenAI-compatible and called directly with httpx.
See https://docs.tokenfactory.nebius.com/.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time

import httpx

from .. import cache, config

TIMEOUT_S = 60.0
RETRIES = 3
TOP_LOGPROBS = 20  # the API's maximum
CONCURRENCY = 6  # a claim check sends one call per sentence; the base limit is 60 a minute
PRICES_TTL_S = 24 * 3600
# Bump when the prompt changes: cached answers were given to the old one.
PROMPT_VERSION = 2  # Recommended by Norma — fixed with Claude Opus 5 via Claude Code

# Recommended by Norma — fixed with Claude Opus 5 via Claude Code
# On the suggested "unknown" value / error object: the reply is already pinned to the
# listed options by the strict JSON schema `_prompt` builds, and `_answers` refuses
# anything else, so neither would ever reach a caller. Uncertainty has its own channel
# here: `_distribution` reads it from the token log-probabilities. So the prompt says
# what to do with a thin STATE (answer anyway, from the evidence there is) instead of
# offering a way out of the schema, and says it in the positive.
SYSTEM = (
    "You answer questions about a STATE, a JSON object describing a situation. Answer "
    "strictly from what the STATE says plus ordinary common sense. Each question has an "
    "id.\n"
    "- A choice question lists its options: answer with the exact option, copied "
    "character for character.\n"
    "- A yes/no question states something: answer \"yes\" if it is true of the STATE, "
    "\"no\" if it is not.\n"
    "- Answer every question, including the ones the STATE leaves open: pick the listed "
    "option its evidence best supports. How sure you are is read from your own token "
    "probabilities, so a close call needs no hedging. When a field is missing or "
    "unreadable, treat it as absent and answer from what remains.\n"
    "- Every value is one short string, an option or \"yes\"/\"no\": no explanation, no "
    "units, no other text. Keep a flat, machine-readable register.\n"
    "Reply with exactly one JSON object that has every question id as a key, in the "
    "order given, and the answer as its value.\n"
    "\n"
    "Worked example, in the shape every call arrives in. For the STATE\n"
    "{\"room\": {\"windows\": 0, \"lamps\": 2}}\n"
    "and the questions\n"
    "[light] choice: how the room is lit\n"
    "  Options:\n"
    "  - \"daylight\"\n"
    "  - \"artificial\"\n"
    "  - \"mixed\"\n"
    "[is_dark] yes/no: the room has no light at all\n"
    "the whole reply is\n"
    "{\"light\": \"artificial\", \"is_dark\": \"no\"}"
)

_semaphore: asyncio.Semaphore | None = None


class NebiusUnavailable(RuntimeError):
    pass


Unavailable = NebiusUnavailable


def available() -> bool:
    return bool(config.NEBIUS_KEY)


def model() -> str:
    return config.NEBIUS_MODEL


# --- Prompt and schema -------------------------------------------------------------
def _options(q: dict) -> dict[str, str | None]:
    if q["type"] == "choice":
        return q["criteria"]
    if q["type"] == "noul":
        crit = q.get("criteria") or {}
        return {"yes": crit.get("true"), "no": crit.get("false")}
    raise NebiusUnavailable(f"question type '{q['type']}' is not supported")


def _prompt(state, questions: dict[str, dict]) -> tuple[str, dict, dict[str, str]]:
    """The user message, the JSON schema, and the id each question is answered under.

    The ids are the caller's own names ("month_7", "who_children") when they are plain
    identifiers: numbered ids mislead the model ("q07" is easily read as July).
    """
    plain = all(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,40}", n) for n in questions)
    ids = {name: name if plain else f"q_{chr(97 + i // 26)}{chr(97 + i % 26)}"
           for i, name in enumerate(questions)}
    lines = ["STATE:", json.dumps(state, ensure_ascii=False, indent=1), "", "QUESTIONS:"]
    props = {}
    for name, q in questions.items():
        qid, opts = ids[name], _options(q)
        if q["type"] == "noul":
            lines.append(f"[{qid}] yes/no: {q['instructions']}")
            for opt, desc in opts.items():
                if desc:
                    lines.append(f"  {opt} = {desc}")
        else:
            lines.append(f"[{qid}] choice: {q['instructions']}")
            lines.append("  Options:")
            for opt, desc in opts.items():
                lines.append(f"  - {json.dumps(opt, ensure_ascii=False)}" + (f": {desc}" if desc else ""))
        props[qid] = {"type": "string", "enum": list(opts)}
    schema = {"type": "object", "properties": props, "required": list(props),
              "additionalProperties": False}
    return "\n".join(lines), schema, ids


# --- Probabilities from the tokens ---------------------------------------------------
def _token_bytes(entry: dict) -> bytes:
    raw = entry.get("bytes")
    return bytes(raw) if raw is not None else str(entry.get("token", "")).encode("utf-8")


def _literals(option: str) -> list[bytes]:
    """How the option can appear inside the JSON string, closing quote included."""
    out = []
    for ascii_only in (False, True):
        lit = json.dumps(option, ensure_ascii=ascii_only).encode("utf-8")[1:]
        if lit not in out:
            out.append(lit)
    return out


def _distribution(options: list[str], chosen: str, content: bytes, tokens: list[dict],
                  starts: list[int], vs: int, ve: int) -> dict[str, float]:
    """P(option) for the answer whose text runs from byte `vs` to its closing quote `ve`.

    Walks the tokens the model generated for this answer. At each one, the alternatives
    it had (top log-probabilities) are sorted by the options they are still compatible
    with; alternatives compatible with none were not allowed by the schema and are
    dropped, so the rest are renormalised. The chosen path keeps its share, and each
    road not taken hands its share to the option it leads to (the most complete one
    when it leads to several: the prompts ask for that).
    """
    encs = [(o, lit) for o in options for lit in _literals(o)]
    order = {o: i for i, o in enumerate(options)}
    probs: dict[str, float] = {}
    path = 1.0  # probability of the road actually taken, so far
    for tok, ts in zip(tokens, starts):
        tb = _token_bytes(tok)
        if ts + len(tb) <= vs:
            continue
        if ts > ve:  # past the closing quote: the answer is complete
            break
        lead = content[ts:vs] if ts < vs else b""  # the opening quote, if the token carries it
        done = content[vs:ts] if ts > vs else b""
        alts = list(tok.get("top_logprobs") or [])
        if not any(_token_bytes(a) == tb for a in alts):
            alts.append(tok)
        branches = []
        for alt in alts:
            ab = _token_bytes(alt)
            if not ab.startswith(lead):
                continue
            prefix = done + ab[len(lead):]
            compatible = {o for o, lit in encs if lit.startswith(prefix) or prefix.startswith(lit)}
            if compatible:
                branches.append((math.exp(alt.get("logprob", -1e4)), ab, compatible))
        total = sum(p for p, _, _ in branches)
        if total <= 0:
            continue
        for p, ab, compatible in branches:
            if ab == tb:
                continue
            others = compatible - {chosen}
            # A road that only leads back to the chosen option is another spelling of it.
            target = max(others, key=lambda o: (len(o), -order[o])) if others else chosen
            probs[target] = probs.get(target, 0.0) + path * p / total
        path *= sum(p for p, ab, _ in branches if ab == tb) / total
    probs[chosen] = probs.get(chosen, 0.0) + path
    return probs


def _answers(content: str, logprobs: list[dict] | None, questions: dict[str, dict],
             ids: dict[str, str]) -> dict:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise NebiusUnavailable(f"the model did not return valid JSON: {content[:200]}") from exc
    raw = content.encode("utf-8")
    tokens = logprobs or []
    starts, pos, joined = [], 0, []
    for tok in tokens:
        starts.append(pos)
        tb = _token_bytes(tok)
        pos += len(tb)
        joined.append(tb)
    # The tokens must spell the text (the end-of-turn token may follow it). If they do
    # not, there is no honest probability to give: rather no AI than a made-up one.
    if not (tokens and b"".join(joined).startswith(raw)):
        raise NebiusUnavailable(f"{config.NEBIUS_MODEL} returned no usable log-probabilities")

    out = {}
    for name, q in questions.items():
        qid, opts = ids[name], list(_options(q))
        value = parsed.get(qid)
        if value not in opts:
            raise NebiusUnavailable(f"the model answered '{value}' to {name}, not one of its options")
        m = re.search(rb'(?<!\\)"' + qid.encode() + rb'"\s*:\s*"', raw)
        if not m:
            raise NebiusUnavailable(f"cannot find the answer to {name} in: {content[:200]}")
        vs = ve = m.end()
        while ve < len(raw) and not (raw[ve:ve + 1] == b'"' and raw[ve - 1:ve] != b"\\"):
            ve += 1
        probs = _distribution(opts, value, raw, tokens, starts, vs, ve)
        total = sum(probs.values()) or 1.0
        probs = {k: round(v / total, 4) for k, v in sorted(probs.items(), key=lambda kv: -kv[1])}
        if q["type"] == "noul":
            out[name] = {"type": "noul", "noul": probs.get("yes", 0.0)}
        else:
            out[name] = {"type": "choice", "choice": value, "confidence": probs[value],
                         "probabilities": probs}
    return out


# --- Prices (for the meter) -----------------------------------------------------------
async def prices(client: httpx.AsyncClient | None = None) -> dict[str, dict]:
    """USD per token, per model, from the verbose model list (cached for a day)."""
    hit = cache.get("nebius_models", "verbose", ttl=PRICES_TTL_S)
    if hit is not None:
        return hit
    owns = client is None
    client = client or httpx.AsyncClient(timeout=20)
    try:
        resp = await client.get(f"{config.NEBIUS_URL}/models", params={"verbose": "true"},
                                headers=_headers())
        resp.raise_for_status()
        out = {m["id"]: {"prompt": float((m.get("pricing") or {}).get("prompt") or 0),
                         "completion": float((m.get("pricing") or {}).get("completion") or 0),
                         "modality": (m.get("architecture") or {}).get("modality"),
                         "context_length": m.get("context_length")}
               for m in resp.json().get("data", [])}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return {}
    finally:
        if owns:
            await client.aclose()
    cache.set("nebius_models", "verbose", out)
    return out


def cost(usage: dict, price: dict | None) -> float:
    if not price:
        return 0.0
    return (int(usage.get("prompt_tokens") or 0) * price["prompt"]
            + int(usage.get("completion_tokens") or 0) * price["completion"])


# --- Calls ----------------------------------------------------------------------------
def _headers() -> dict:
    return {"Authorization": f"Bearer {config.NEBIUS_KEY}", "User-Agent": config.USER_AGENT}


def _key(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _body(state, questions: dict[str, dict]) -> tuple[dict, dict[str, str]]:
    text, schema, ids = _prompt(state, questions)
    return {
        "model": config.NEBIUS_MODEL,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}],
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "answers", "schema": schema, "strict": True}},
        "temperature": 0,
        "max_tokens": 64 + sum(12 + max(len(o) for o in _options(q)) for q in questions.values()),
        "logprobs": True,
        "top_logprobs": TOP_LOGPROBS,
    }, ids


def cache_key(state, questions: dict[str, dict]) -> str:
    return _key({**_body(state, questions)[0], "prompt_version": PROMPT_VERSION})


async def _post(client: httpx.AsyncClient, body: dict) -> dict:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(CONCURRENCY)
    async with _semaphore:
        for attempt in range(RETRIES):
            try:
                resp = await client.post(f"{config.NEBIUS_URL}/chat/completions", json=body,
                                         headers=_headers())
            except httpx.HTTPError as exc:
                if attempt == RETRIES - 1:
                    raise NebiusUnavailable(f"Nebius is not responding: {exc}") from exc
                await asyncio.sleep(0.5 * 2 ** attempt)
                continue
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < RETRIES - 1:
                wait = resp.headers.get("retry-after")
                await asyncio.sleep(float(wait) if wait and wait.replace(".", "").isdigit()
                                    else 1.0 * 2 ** attempt)
                continue
            if resp.status_code == 401:
                raise NebiusUnavailable("Nebius rejected the API key (401)")
            if resp.status_code in (403, 404):  # a retired or unknown model, not a bad key
                raise NebiusUnavailable(f"Nebius has no model {config.NEBIUS_MODEL} for this key "
                                        f"({resp.status_code}): {resp.text[:200]}")
            if resp.status_code >= 400:
                raise NebiusUnavailable(f"Nebius error {resp.status_code}: {resp.text[:300]}")
            return resp.json()
    raise NebiusUnavailable("Nebius did not answer")


async def ask(state, questions: dict[str, dict], *, client: httpx.AsyncClient | None = None) -> dict:
    """One call: every question answered against the same state.

    Returns {"answers", "model", "usage", "cost_usd", "elapsed_ms", "cached"}, the
    answers shaped like Jev's. Raises NebiusUnavailable with a readable reason on any
    failure; callers fall back.
    """
    if not available():
        raise NebiusUnavailable("NEBIUS_API_KEY is not set")
    body, ids = _body(state, questions)
    hit = cache.get("nebius", _key({**body, "prompt_version": PROMPT_VERSION}))
    if hit is not None:
        return {**hit, "elapsed_ms": 0, "cached": True}

    started = time.perf_counter()
    owns = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT_S)
    try:
        data = await _post(client, body)
        price = (await prices(client)).get(config.NEBIUS_MODEL)
    finally:
        if owns:
            await client.aclose()
    try:
        choice = data["choices"][0]
        content = choice["message"]["content"] or ""
        logprobs = (choice.get("logprobs") or {}).get("content")
    except (KeyError, IndexError, TypeError) as exc:
        raise NebiusUnavailable(f"unexpected Nebius reply: {json.dumps(data)[:300]}") from exc
    usage = data.get("usage") or {}
    out = {"answers": _answers(content, logprobs, questions, ids),
           "model": data.get("model") or config.NEBIUS_MODEL,
           "usage": {"input_tokens": int(usage.get("prompt_tokens") or 0),
                     "output_tokens": int(usage.get("completion_tokens") or 0)},
           "cost_usd": cost(usage, price)}
    cache.set("nebius", _key({**body, "prompt_version": PROMPT_VERSION}), out)
    return {**out, "elapsed_ms": round((time.perf_counter() - started) * 1000), "cached": False}
