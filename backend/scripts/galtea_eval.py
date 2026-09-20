"""Previous AI behind a single text answer, so an evaluation platform can call it.

The product has no chat: the web app takes an address and answers with cards, and the
AI inside it only makes typed decisions (`interpret.py`, `advice.py`, `claims.py`). An
evaluation harness sends one message and reads one string, so this adapter drives the
real pipeline - the AI reads the request, the engine builds the report, the AI ranks the
advice - and writes what the app shows into text. It composes; it never writes a number
or a sentence that is not already in the report or in a hand-written catalogue.

    python backend/scripts/galtea_eval.py --ask "Is the ground floor safe in Paiporta?"
    python backend/scripts/galtea_eval.py                # runs the evaluation
    python backend/scripts/galtea_eval.py --network      # let new places reach Open-Meteo

A message naming a place that is not in `data/cache` is answered from the catalogues
instead of fetching it: ERA5 comes from Open-Meteo's free tier and one new point costs a
good part of the day's quota (see prewarm.py). --network lifts that.

`GALTEA_API_KEY` comes from `.env.local` at the repo root (git-ignored), or from the
environment.

NOTE: this module deliberately does NOT do `from __future__ import annotations`. The SDK
picks the argument shape from the identity of the agent's first annotation, and a
stringified `str` falls through to a chat history, which would crash the agent on every
test case.
"""

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
# Explicit UTF-8: the Windows console uses cp1252 and chokes on "→" or "·".
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from app import grants, interpret, narrative, protection, view  # noqa: E402
from app import report as R  # noqa: E402
from app.providers import geocoding  # noqa: E402

PRODUCT_ID = "product_h92bl1271vvp1o5v1hwvau7c"
VERSION_ID = "version_l0aqugj8ok9kzv9f20dic4wk"

# A place that is not cached is not fetched unless the run says so.
ALLOW_NETWORK = False

MAX_ADVICE = 4
MAX_CATALOGUE = 4
POLL_SECONDS = 10
POLL_LIMIT = 60  # ten minutes: evaluations are scored server-side, and judges queue.


# --------------------------------------------------------------------------- #
# The product, as one answer
# --------------------------------------------------------------------------- #
def _tile_lines(tile: dict) -> list[str]:
    score = f" ({tile['score']}/100)" if tile["score"] is not None else ""
    head = f"- {tile['label']}: {tile['level']}{score}."
    lines = [f"{head} {tile['summary']}".strip() if tile.get("summary") else head]
    if tile.get("fact"):
        lines.append(f"  {tile['fact']}")
    if tile.get("home_note"):
        lines.append(f"  For this home: {tile['home_note']}")
    card = (tile.get("cards") or [None])[0]
    if card and card.get("limitation"):
        lines.append(f"  What this does not tell you: {card['limitation']}")
    if tile.get("source"):
        lines.append(f"  Source: {tile['source']}")
    return lines


def compose(report: dict) -> str:
    """The app's own view, read out: headline, the four risks, the advice, the caveats."""
    page = view.app_view(report)
    overall = report["overall"]
    lines = [f"{report['location']['label']} - overall natural hazard risk "
             f"{overall['score']:.0f}/100 ({overall['level']}).",
             page["headline"]["title"], page["headline"]["text"], ""]

    for tile in page["risks"]:
        if tile["applies"] or tile["ruled_out"]:
            lines += _tile_lines(tile)
    lines.append("")

    advice_items = (report.get("narrative") or {}).get("advice") or []
    if advice_items:
        who = (report.get("personalization") or {}).get("profile") or []
        lines.append("What to do here" + (f", for {', '.join(who).lower()}" if who else "") + ":")
        lines += [f"- {item['text']}" for item in advice_items[:MAX_ADVICE]]
        lines.append("")

    money = (page.get("grants") or {}).get("items") or []
    if money:
        lines.append("Public money that can pay for part of this:")
        for item in money[:3]:
            lines.append(f"- {item['name']} ({item.get('body', 'official programme')}): "
                         f"{item.get('amount', 'see the official page')}")
        lines.append("")

    coverage = report.get("coverage") or {}
    for note in (coverage.get("notes") or [])[:2]:
        lines.append(f"Note: {note}")
    for gap in (coverage.get("not_covered") or [])[:3]:
        lines.append(f"Not covered by this report: {gap['hazard']} - {gap['reason']}")

    lines.append("Every figure above is measured or mapped data with its period and scale, not a "
                 "prediction that an event will reach this address, and it is not legal, "
                 "insurance or valuation advice. During an emergency the official bulletin and "
                 "112 decide, not this report.")
    return "\n".join(line for line in lines if line is not None).strip()


def _score_text(text: str, haystack: str) -> int:
    words = {w for w in "".join(c.lower() if c.isalnum() else " " for c in text).split()
             if len(w) > 3}
    hay = "".join(c.lower() if c.isalnum() else " " for c in haystack).split()
    return sum(1 for w in set(hay) if w in words)


def from_catalogues(message: str, reason: str) -> str:
    """No place to report on: answer only from what is written down, and say so."""
    pool = [(text, "advice") for texts in narrative.ADVICE.values() for text in texts]
    pool += [(item["text"], "advice") for item in narrative.PROFILE_ADVICE]
    pool += [(f"{m['title']}. {m['why']} Cost: {m['cost'] or 'free'}.", "measure")
             for m in protection.MEASURES]
    pool += [(f"{p['name']} ({p['body']}): {p['funds']} Amount: {p['amount']}", "public money")
             for p in grants.PROGRAMMES]
    ranked = sorted(pool, key=lambda item: -_score_text(item[0], message))
    best = [item for item in ranked if _score_text(item[0], message) > 0][:MAX_CATALOGUE]
    lines = [reason]
    if best:
        lines += ["", "What this product can say without one, from its written catalogue:"]
        lines += [f"- {text}" for text, _ in best]
    lines.append("")
    lines.append("A score, a level or anything about the hazards at a specific address needs "
                 "that address: the report is built from official and scientific data for the "
                 "point, never guessed from the name of a town.")
    return "\n".join(lines)


async def answer(message: str) -> str:
    """One message in, the product's answer out."""
    if not (message or "").strip():
        return from_catalogues("", "No question was asked.")
    understood = await interpret.run(message)
    try:
        place, used = await interpret.resolve_place(understood)
    except geocoding.GeocodingError:
        return from_catalogues(
            message,
            "No address or place was recognised in that message, so there is no report to "
            "answer from. Give the street, number and town (an address in Spain is where the "
            "official flood, wildfire and avalanche mapping applies).")
    if not ALLOW_NETWORK and not R.is_cached(used):
        return from_catalogues(
            message,
            f"The climate record for {place.get('label', used)} is not on this machine, and "
            f"this evaluation run does not fetch new places, so no report can be built for it.")
    report = await R.build_report(ask=message)
    return compose(report)


def previous_ai(user_message: str) -> str:
    """The agent the platform calls: `str` in, `str` out (the annotation picks the shape)."""
    return asyncio.run(answer(user_message))


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #
def api_key() -> str:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env.local")
    except ImportError:  # python-dotenv is optional: a plain env var works too
        env = ROOT / ".env.local"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.strip() and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip().strip('"'))
    key = os.environ.get("GALTEA_API_KEY", "").strip()
    if not key:
        raise SystemExit("GALTEA_API_KEY is not set: put it in .env.local at the repo root.")
    return key


def report_statuses(galtea, version_id: str) -> int:
    """Poll until nothing is PENDING, then print each evaluation's status and score."""
    for _ in range(POLL_LIMIT):
        pending = galtea.evaluations.list(version_id=version_id, status="PENDING", limit=100)
        if not pending:
            break
        print(f"  {len(pending)} still pending...")
        time.sleep(POLL_SECONDS)

    rows = galtea.evaluations.list(version_id=version_id, limit=200)
    counts: dict[str, int] = {}
    scored = []
    for row in rows:
        status = str(getattr(row, "status", "?"))
        counts[status] = counts.get(status, 0) + 1
        score = getattr(row, "score", None)
        if score is not None:
            scored.append(score)
    print("\nStatuses:", ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    if scored:
        print(f"Scores: {len(scored)} scored, average {sum(scored) / len(scored):.2f}, "
              f"lowest {min(scored):.2f}, highest {max(scored):.2f}")
    return len(rows)


def main() -> int:
    global ALLOW_NETWORK
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ask", help="answer one message locally, without touching Galtea")
    parser.add_argument("--network", action="store_true",
                        help="let a place that is not cached reach Open-Meteo")
    parser.add_argument("--version-id", default=VERSION_ID)
    args = parser.parse_args()
    ALLOW_NETWORK = args.network

    if args.ask:
        print(asyncio.run(answer(args.ask)))
        return 0

    from galtea import Galtea  # noqa: PLC0415 - only the run needs the SDK
    galtea = Galtea(api_key=api_key())
    print(f"Running the evaluation for {args.version_id} ...")
    result = galtea.evaluations.run(version_id=args.version_id, agent=previous_ai)
    print(f"  {result.get('testCaseCount')} test cases across "
          f"{len(result.get('specifications') or [])} specifications")
    report_statuses(galtea, args.version_id)
    print(f"\nResults: https://platform.galtea.ai/products/{PRODUCT_ID}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
