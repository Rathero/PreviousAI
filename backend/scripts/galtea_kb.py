"""The knowledge base an evaluation platform checks the AI layer's answers against.

An accuracy test case compares an answer with the correct one, so what it needs is not
what the product should do but what the product knows: the hazard record of a place,
card by card, every value with the period it covers, the scale it was measured at and
its source - exactly the evidence `claims.py` puts in front of the AI - and the
hand-written catalogues that `advice.py`, `protection.py` and `grants.py` choose from
and never add to.

    python backend/scripts/galtea_kb.py
    python backend/scripts/galtea_kb.py --places "Sevilla" "El Masnou"
    python backend/scripts/galtea_kb.py --network --gap 20

A place whose climate record is not already in `data/cache` is skipped: ERA5 comes from
Open-Meteo's free tier, where one new point costs a good part of the day's quota (see
prewarm.py). Warm it there first, or pass --network to let this script fetch.

Writes one Markdown file per place and one per catalogue into `data/galtea/`, plus the
zip to upload.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Explicit UTF-8: the Windows console uses cp1252 and chokes on "→" or "·".
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from app import claims, config, dwelling, grants, interpret, narrative, protection  # noqa: E402
from app import report as R  # noqa: E402

OUT = config.DATA_DIR / "galtea"
ZIP = OUT / "previous-ai-knowledge-base.zip"

# Places worth having in the corpus: the four hazards with official data behind them,
# and the extremes a claim is most likely to be wrong about (a flat in a preferential
# flow zone, a town that has burned, a city where the nights never cool down).
PLACES = [
    "Avinguda Garona 10, Vielha",
    "Calle Mayor 10, Paiporta",
    "El Masnou",
    "Sevilla",
    "Phoenix, Arizona",
    "41.985, 2.825",
    "40.725, 0.874",
]

# The order the evidence reads best in: the summary, then the cards, then what was
# ruled out and what the next fortnight holds.
FIRST = ("overall",)
LAST = ("ruled_out", "forecast")


# --------------------------------------------------------------------------- #
# One place
# --------------------------------------------------------------------------- #
def _card_sources(report: dict, key: str) -> list[str]:
    """The sources behind a card, as its own indicators name them."""
    card = next((h for h in report["hazards"] if h["key"] == key), None)
    out: list[str] = []
    for ind in (card or {}).get("indicators", []):
        name = (ind.get("provenance") or {}).get("source")
        if name and name not in out:
            out.append(name)
    return out


def place_document(report: dict) -> str:
    """The report as evidence: the same facts `claims.py` shows the AI, plus their source."""
    loc = report["location"]
    overall = report["overall"]
    built = (report.get("meta") or {}).get("generated_at", "")[:10]
    lines = [f"# Natural hazards at {loc['label']}", ""]
    lines.append(f"The hazard record held for this address: every value with the period it "
                 f"covers, the scale it was measured at and the source it comes from. Built on "
                 f"{built} from the official and scientific open data listed at the end.")
    lines.append("")
    lines.append(f"- Coordinates: {loc['latitude']:.4f}, {loc['longitude']:.4f} "
                 f"({loc.get('precision') or 'point'})")
    if loc.get("elevation_m") is not None:
        lines.append(f"- Elevation: {loc['elevation_m']:.0f} m")
    lines.append(f"- Overall natural hazard risk: {overall['score']:.0f}/100 ({overall['level']})")
    headline = (report.get("narrative") or {}).get("headline")
    if headline:
        lines.append(f"- In one sentence: {headline}")
    lines.append("")

    topics = claims.topics(report)
    order = ([k for k in FIRST if k in topics]
             + [k for k in topics if k not in FIRST + LAST]
             + [k for k in LAST if k in topics])
    for key in order:
        topic = topics[key]
        lines += [f"## {topic['label']}", ""]
        lines += [f"- {fact}" for fact in topic["facts"] if fact]
        sources = _card_sources(report, key)
        if sources:
            lines.append(f"- Source: {'; '.join(sources[:3])}.")
        lines.append("")

    history = report.get("history") or {}
    if history.get("items"):
        lines += ["## What has already happened near here", ""]
        if history.get("note"):
            lines += [history["note"], ""]
        for item in history["items"][:40]:
            detail = f" - {item['detail']}" if item.get("detail") else ""
            lines.append(f"- {item['date']}: {item['title']}{detail} ({item['source']})")
        lines.append("")

    if report.get("sources"):
        lines += ["## Where these numbers come from", ""]
        for src in report["sources"]:
            lines.append(f"- **{src['name']}** - {src['role']}. {src.get('access', '')} "
                         f"Licence: {src.get('licence', 'see source')}. "
                         f"{src.get('url', '')}".strip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def slug(text: str) -> str:
    plain = "".join(c.lower() if c.isalnum() else "-" for c in text)
    return "-".join(p for p in plain.split("-") if p)[:60].strip("-")


# --------------------------------------------------------------------------- #
# The catalogues the AI picks from and never adds to
# --------------------------------------------------------------------------- #
def advice_document() -> str:
    lines = ["# Preparedness advice catalogue", "",
             "Every piece of advice this product can give. Nothing outside this list is ever "
             "shown: the AI ranks these items for the household and the place, and writes none "
             "of them.", ""]
    for title, bank in (("At home", narrative.ADVICE), ("On a trip", narrative.TRAVEL_ADVICE)):
        lines += [f"## {title}", ""]
        for hazard, texts in bank.items():
            lines += [f"### {hazard}", ""]
            lines += [f"- {t}" for t in texts]
            lines.append("")
    lines += ["## Written for who lives there", "",
              "Offered only when the household says one of these applies.", ""]
    for item in narrative.PROFILE_ADVICE:
        who = ", ".join(interpret.PROFILES[p][0] for p in item["profiles"]
                        if p in interpret.PROFILES)
        lines.append(f"- ({who}; {', '.join(item['hazards'])}) {item['text']}")
    lines += ["", "## The household as the product records it", ""]
    for key, (label, meaning) in interpret.PROFILES.items():
        lines.append(f"- **{label}** (`{key}`): {meaning}.")
    return "\n".join(lines).rstrip() + "\n"


def measures_document() -> str:
    lines = ["# Protection measures catalogue", "",
             "What an action plan can propose, what it costs and the standard it has to meet. "
             "Nothing outside this list is ever proposed.", ""]
    kinds = {key: home for key, home, _ in protection.SECTIONS}
    for family in sorted({m["family"] for m in protection.MEASURES}):
        lines += [f"## {family}", ""]
        for measure in protection.MEASURES:
            if measure["family"] != family:
                continue
            bits = [f"**{measure['title']}** ({kinds.get(measure['kind'], measure['kind'])}).",
                    measure["why"],
                    f"Cost: {measure['cost'] or 'free'}."]
            if measure.get("standard"):
                bits.append(f"Standard: {measure['standard']}.")
            bits.append("Who acts: the household." if measure["unit"] == "home"
                        else "Who acts: the owners of the building.")
            lines.append("- " + " ".join(bits))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def grants_document() -> str:
    lines = ["# Public money for protecting a home in Spain", "",
             f"A hand-checked catalogue: every programme read in its primary source on "
             f"{grants.CHECKED}. Amounts and deadlines change and the official page decides. "
             f"Nothing outside this list exists as far as this product is concerned.", ""]
    for programme in grants.PROGRAMMES:
        where = programme.get("where") or {}
        scope = where.get("municipality") or where.get("region") or where.get("country") or "ES"
        lines += [f"## {programme['name']}", ""]
        lines.append(f"- Official name: {programme.get('official_name', programme['name'])}")
        lines.append(f"- Body: {programme['body']} (scope: {scope})")
        lines.append(f"- Who applies: {programme['who']}")
        lines.append(f"- Risks it covers: {', '.join(programme.get('families') or []) or 'any'}")
        lines.append(f"- What it funds: {programme['funds']}")
        lines.append(f"- Amount: {programme['amount']}")
        if programme.get("note"):
            lines.append(f"- Note: {programme['note']}")
        deadline = f", deadline {programme['deadline']}" if programme.get("deadline") else ""
        lines.append(f"- Status: {programme.get('status')}{deadline}")
        lines.append(f"- Legal reference: {programme.get('ref', 'see the official page')}")
        lines.append(f"- Official page: {programme.get('url', '')}")
        lines.append("")
    gaps = getattr(grants, "GAPS", None) or {}
    if gaps:
        lines += ["## What does not exist", "",
                  "Said plainly, so a household hears it instead of finding an empty list.", ""]
        for family, entries in gaps.items():
            for scope, text in entries:
                lines.append(f"- {family} ({scope}): {text}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #
async def build(places: list[str], network: bool, gap: float) -> list[Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    house = dwelling.parse("house", None)
    for index, place in enumerate(places):
        if not R.is_cached(place) and not network:
            print(f"  [skip]   {place[:48]:<48} not in the cache (warm it with prewarm.py)")
            continue
        try:
            report = await R.build_report(query=place, force_home=True, dwelling=house)
        except Exception as exc:  # a place that fails is one document short, not a failed run
            print(f"  [failed] {place[:48]:<48} {type(exc).__name__}: {exc}")
            continue
        path = OUT / f"hazards-{slug(report['location']['label'])}.md"
        path.write_text(place_document(report), encoding="utf-8")
        written.append(path)
        source = "cache" if report["meta"]["from_cache"] else "network"
        print(f"  [ok]     {place[:48]:<48} {report['overall']['score']:>5.0f}/100 ({source})")
        if gap and not report["meta"]["from_cache"] and index < len(places) - 1:
            await asyncio.sleep(gap)
    for name, text in (("advice-catalogue.md", advice_document()),
                       ("protection-measures.md", measures_document()),
                       ("public-money-spain.md", grants_document())):
        path = OUT / name
        path.write_text(text, encoding="utf-8")
        written.append(path)
        print(f"  [ok]     {name}")
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--places", nargs="+", default=PLACES)
    parser.add_argument("--network", action="store_true",
                        help="let a place that is not cached go to Open-Meteo")
    parser.add_argument("--gap", type=float, default=20.0,
                        help="seconds to wait after a place that went to the network")
    args = parser.parse_args()

    written = asyncio.run(build(args.places, args.network, args.gap))
    if not written:
        print("nothing to bundle")
        return 1
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in written:
            bundle.write(path, path.name)
    print(f"\n{len(written)} documents -> {ZIP} ({ZIP.stat().st_size / 1024:.0f} kB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
