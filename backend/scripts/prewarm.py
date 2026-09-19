"""Warms the cache for a list of homes, so their reports open instantly.

Open-Meteo limits by VOLUME (days x variables), per minute, hour and day: one new point
costs roughly 1,800 of the 5,000 hourly calls. Warming places ahead of time, with a pause
after each one that went to the network, keeps the app responsive and the quota safe.
Every warmed report also fetches its Street View metadata and, with Deepfire configured,
today's fire-spread what-if.

    python backend/scripts/prewarm.py
    python backend/scripts/prewarm.py --places "Carrer de la Força 5, Girona" "Vielha"
    python backend/scripts/prewarm.py --gap 20 --no-spread
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

from app import cache, dwelling  # noqa: E402
from app.providers import streetview  # noqa: E402
from app.report import build_report  # noqa: E402

# Addresses that show the four hazards with official data behind them.
EXAMPLES = [
    "El Masnou",
    "Passeig Prat de la Riba 10, El Masnou",
    "Vielha",
    "Carrer Sarriulera 10, Vielha",
    "Avinguda Castiero 17, Vielha",
    "Carrer de la Força 5, Girona",
    "Barcelona",
]


async def warm(places: list[str], gap: float) -> tuple[int, list[tuple[float, float]]]:
    failures, points = 0, []
    for index, place in enumerate(places):
        started = time.time()
        try:
            report = await build_report(query=place, force_home=True,
                                        dwelling=dwelling.parse("house", None))
            loc = report["location"]
            points.append((loc["latitude"], loc["longitude"]))
            if streetview.available():
                try:
                    await streetview.metadata(loc["latitude"], loc["longitude"])
                except streetview.StreetViewUnavailable:
                    pass
            source = "cache" if report["meta"]["from_cache"] else "network"
            print(f"  [ok]     {place[:50]:<50} {report['overall']['score']:>5}/100 "
                  f"{time.time() - started:5.1f}s ({source})")
            if gap and not report["meta"]["from_cache"] and index < len(places) - 1:
                await asyncio.sleep(gap)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  [failed] {place[:50]:<50} {exc}")
    return failures, points


async def warm_spread(points: list[tuple[float, float]]) -> int:
    """Today's fire-spread what-if for each point (Deepfire ELMFIRE, about a minute each),
    one at a time: the API allows two runs in flight per client."""
    from app import fire_spread

    failures = 0
    for lat, lon in points:
        started = time.time()
        try:
            run = await fire_spread.start(lat, lon)
            while run.get("status") == "QUEUED" and time.time() - started < 600:
                await asyncio.sleep(10)
                run = await fire_spread.status(run["id"], lat, lon)
            area, hours = run.get("final_area_ha"), len(run.get("hours") or [])
            burnt = f", {area:.2f} ha in {hours} h" if area is not None else ""
            print(f"  [{run.get('status')}] {lat:.4f}, {lon:.4f}{burnt}  {time.time() - started:5.1f}s")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  [failed] {lat:.4f}, {lon:.4f}  {exc}")
    return failures


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--places", nargs="*", default=None, help="addresses to warm (default: the examples)")
    p.add_argument("--gap", type=float, default=12.0,
                   help="seconds to wait after each place that went to the network")
    p.add_argument("--no-spread", action="store_true",
                   help="skip today's fire-spread what-ifs (Deepfire, about a minute per point)")
    args = p.parse_args()

    places = args.places or EXAMPLES
    print(f"Warming {len(places)} reports. A new point fetches the ERA5 record since 1979, two "
          f"CMIP6 windows and the terrain; an address within 1 km and 50 m of height of a saved "
          f"point reuses its series.\n")
    failures, points = asyncio.run(warm(places, args.gap))

    from app.providers import deepfire
    points = list(dict.fromkeys(points))
    if points and deepfire.available() and not args.no_spread:
        print(f"\nFire-spread what-ifs for today ({len(points)} points, Deepfire ELMFIRE):")
        failures += asyncio.run(warm_spread(points))

    stats = cache.stats()
    print(f"\nCache: {stats['entries']} entries, {stats['bytes'] / 1e6:.1f} MB")
    if failures:
        print(f"{failures} step(s) failed. Run it again: whatever is cached is not requested again.")
        return 1
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
