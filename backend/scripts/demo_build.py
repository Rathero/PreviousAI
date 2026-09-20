"""Builds everything a demonstration shows, so the day itself waits for nothing.

For each pinned home (app/demo.py) it builds the report, draws the PDF, renders the
narrated briefing and warms what is left on the live path, then files the lot in
`data/demo`. From then on /api/report, /api/report/pdf, /api/locate and /api/briefing
answer from those files, in milliseconds, with values that cannot move between the
rehearsal and the room.

Run it the morning of the demonstration: a pack is a report, and a report of last week
describes last week's alerts and forecast.

    python backend/scripts/demo_build.py
    python backend/scripts/demo_build.py --whole          # a briefing for every variant too
    python backend/scripts/demo_build.py --variants house apartment-4
    python backend/scripts/demo_build.py --extra "house:children,older_adults"
    python backend/scripts/demo_build.py --check          # say what is ready, build nothing

`--variants` get the whole pack, briefing included; `--extra` are the detours a
demonstration may take - the same home on the fourth floor, the plan re-ranked for
children - and get the report and the PDF, which is what those clicks ask for. Their
briefing, if anyone asks for it, is still rendered the slow way; `--whole` renders those
too, which takes about a minute each and is the version to run when the demonstration
may wander.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Explicit UTF-8: the Windows console uses cp1252 and chokes on "→" or "·".
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from app import briefing, demo, dwelling as DW, interpret, pdf_report  # noqa: E402
from app import simulations, video  # noqa: E402
from app import report as R, view  # noqa: E402
from app.providers import cartociudad, fal, streetview  # noqa: E402

# The detours a demonstration takes from the home it opened with: the flat on the ground
# floor and on the fourth (the flood card reads differently on each), and the plan
# re-ranked for each kind of household. Any other combination can be named on the command
# line; what is not built is still answered live, from a warm cache.
EXTRA = ["apartment-0", "apartment-4"] + [f"house:{who}" for who in interpret.PROFILES]


def parse_variant(spec: str) -> tuple[str | None, str | None, list[str]]:
    """"apartment-4:children,older_adults" -> ("apartment", "4", ["children", ...])."""
    home_part, _, who_part = spec.partition(":")
    home, _, floor = home_part.partition("-")
    who = [w for w in who_part.split(",") if w.strip()]
    unknown = [w for w in who if w not in interpret.PROFILES]
    if unknown:
        raise SystemExit(f"unknown household: {', '.join(unknown)}. "
                         f"Pick from {', '.join(interpret.PROFILES)}.")
    if home not in ("house", "apartment", "any"):
        raise SystemExit(f"unknown home: {home!r}. Use house, apartment, "
                         "apartment-<floor> or any.")
    return (None if home == "any" else home), (floor or None), who


async def warm_typing(query: str) -> int:
    """Every prefix of the address, so the dropdown never goes to the network while
    someone types it. The pinned suggestion is added by the API, but the ones beside it
    come from CartoCiudad."""
    warmed = 0
    for size in range(3, len(query) + 1):
        try:
            await cartociudad.candidates(query[:size], limit=6)
            warmed += 1
        except Exception:  # noqa: BLE001 - one prefix short of the set is not a failure
            pass
    return warmed


def check_simulations(place_id: str, app_view: dict) -> list[str]:
    """The four hazards drawn on this street are only shown while the card still says the
    level they were drawn for."""
    scenes = (simulations.manifest()["places"].get(place_id) or {}).get("scenes", {})
    problems = []
    for risk in app_view.get("risks", []):
        rec = scenes.get(risk["key"])
        if not rec:
            problems.append(f"{risk['key']}: no simulation drawn for this street")
        elif rec.get("level") != risk.get("level"):
            problems.append(f"{risk['key']}: drawn for {rec.get('level')}, the card now says "
                            f"{risk.get('level')} - run fal_place.py again")
    return problems


async def build_one(place_id: str, spec: str, *, with_pdf: bool, with_briefing: bool,
                    first: bool) -> bool:
    place = simulations.PLACES[place_id]
    home, floor, who = parse_variant(spec)
    variant = demo.variant(home, floor, who)
    print(f"\n{place['query']}  ·  {variant}")

    started = time.time()
    report = await R.build_report(query=place["query"], profile=who, force_home=True,
                                  dwelling=DW.parse(home, floor))
    app_view = view.app_view(report)
    loc = app_view["location"]
    print(f"  report      {app_view['overall']['score']:>3}/100  "
          + " ".join(f"{r['key']}:{r['score']}" for r in app_view["risks"])
          + f"   {time.time() - started:5.1f}s")

    for line in check_simulations(place_id, app_view):
        print(f"  [warning]   {line}")

    pdf_bytes, pdf_name = None, None
    if with_pdf:
        started = time.time()
        pictures = await pdf_report.pictures(report)
        pdf_bytes = await asyncio.to_thread(pdf_report.render, report, app_view, pictures)
        pdf_name = pdf_report.filename(app_view)
        missing = [k for k in ("street", "aerial") if not pictures.get(k)]
        print(f"  pdf         {len(pdf_bytes) / 1e6:.1f} MB  {pdf_name}"
              + (f"  (no {', '.join(missing)} picture)" if missing else "")
              + f"   {time.time() - started:5.1f}s")

    record = None
    if with_briefing:
        if not video.available():
            print("  [failed]    briefing: ffmpeg not found (pip install imageio-ffmpeg)")
        else:
            started = time.time()
            # Built the way POST /api/briefing builds it, from the point and the label the
            # page sends, so the pack holds the video that request would have produced.
            spoken = await R.build_report(lat=loc["latitude"], lon=loc["longitude"],
                                          label=loc["label"], include_projection=False,
                                          profile=who, dwelling=DW.parse(home, floor))

            # A live line while it encodes, but only on a terminal: redirected to a file,
            # carriage returns pile the steps on top of each other instead of replacing them.
            live = sys.stdout.isatty()

            async def step(text: str) -> None:
                if live:
                    print("\r" + f"  briefing    {text}…".ljust(76)[:76], end="")

            record = await briefing.render(spoken, narrate=True, progress=step)
            if live:
                print("\r" + " " * 76 + "\r", end="")
            voice = (record.get("narration") or {}).get("voice")
            print(f"  briefing    {record['duration_s']:.0f}s  {len(record['scenes'])} scenes  "
                  f"{record['bytes'] / 1e6:.1f} MB  "
                  + (f"voice {voice}" if record["narrated"] else "SILENT (no fal.ai voice)")
                  + f"   {time.time() - started:5.1f}s")
            for note in record.get("notes") or []:
                print(f"  [warning]   {note}")

    # The address box and the picture of the home belong to the place, not to the pack.
    if first:
        if streetview.available():
            try:
                meta = await streetview.metadata(loc["latitude"], loc["longitude"])
                print("  street view " + ("panorama " + str(meta.get("date") or "")
                                          if meta.get("available")
                                          else f"none: {meta.get('reason')}"))
            except streetview.StreetViewUnavailable as exc:
                print(f"  [warning]   street view: {exc}")
        warmed = await warm_typing(place["query"])
        print(f"  typing      {warmed} prefixes of the address answered from the cache")

    demo.write(place_id, variant, report_body=report, view_body=app_view,
               pdf_bytes=pdf_bytes, pdf_filename=pdf_name, briefing_record=record)
    return True


def show_status() -> int:
    status = demo.status()
    if not status["enabled"]:
        print("PREVIOUS_DEMO=0: the pinned homes are switched off and every address goes live.")
    if not status["homes"]:
        print("Nothing built yet. Run this script without --check.")
        return 1
    for home in status["homes"]:
        marks = " ".join(f"{name}{'+' if home[name] else '-'}"
                         for name in ("report", "pdf", "briefing"))
        age = "unknown age" if home["age_hours"] is None else f"{home['age_hours']:.1f} h old"
        print(f"  {home['query']:<28} {home['variant']:<24} {marks}   {age}")
    oldest = status["oldest_hours"]
    if oldest is not None and oldest > 24:
        print(f"\nThe oldest pack is {oldest / 24:.1f} days old: its alerts and forecast are that "
              f"old too. Build it again before showing it.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--places", nargs="*", default=None,
                   help="which pinned homes (default: all). "
                        f"Known: {', '.join(simulations.PLACES)}")
    p.add_argument("--variants", nargs="*", default=["house"],
                   help="home[-floor][:who,who] to build whole, briefing included "
                        "(default: house)")
    p.add_argument("--extra", nargs="*", default=EXTRA,
                   help=f"variants to build without their briefing (default: {' '.join(EXTRA)})")
    p.add_argument("--whole", action="store_true",
                   help="render a briefing for the --extra variants as well")
    p.add_argument("--no-pdf", action="store_true", help="skip the PDF")
    p.add_argument("--no-briefing", action="store_true",
                   help="skip the video briefing (the slow one: voice and encoding)")
    p.add_argument("--check", action="store_true", help="say what is ready and build nothing")
    args = p.parse_args()

    if args.check:
        return show_status()

    places = args.places or list(simulations.PLACES)
    unknown = [pid for pid in places if pid not in simulations.PLACES]
    if unknown:
        print(f"Unknown home(s): {', '.join(unknown)}. Known: {', '.join(simulations.PLACES)}")
        return 2
    if not args.no_briefing and not fal.available():
        print("No FAL_KEY: the briefing will be built silent, with the same captions.\n")

    started, failures = time.time(), 0
    wanted = [(spec, True) for spec in args.variants]
    wanted += [(spec, args.whole) for spec in args.extra if spec not in args.variants]
    for place_id in places:
        for index, (spec, whole) in enumerate(wanted):
            try:
                asyncio.run(build_one(place_id, spec, with_pdf=not args.no_pdf,
                                      with_briefing=whole and not args.no_briefing,
                                      first=index == 0))
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"  [failed]    {place_id} {spec}: {type(exc).__name__}: {exc}")

    print(f"\nBuilt in {time.time() - started:.0f}s. What is ready now:")
    show_status()
    if failures:
        print(f"\n{failures} pack(s) failed. Run it again: what is already built is reused.")
        return 1
    print("\nThe street picture of the home is the one thing still fetched live: Google's terms "
          "do not allow it to be stored. Open the report once and the browser keeps it "
          "for an hour.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
