"""Batch download from the Copernicus Climate Data Store.

This is the SLOW LAYER. It runs by hand, outside the server, and can take from minutes to
hours because the CDS is a queue shared by the whole scientific community. It is never
called from the API.

    # See the exact request without using up the queue
    python backend/scripts/cds_download.py --preset valencia --dry-run

    # Download for real (blocks until the queue serves it)
    python backend/scripts/cds_download.py --preset valencia

    # Any point
    python backend/scripts/cds_download.py --lat 41.39 --lon 2.17 \
        --name barcelona --years 2000-2024 --variable 2m_temperature

Before the first run:
 1. An account on https://cds.climate.copernicus.eu and its Personal Access Token.
 2. The token in CDS_API_KEY (.env) or in ~/.cdsapirc.
 3. The dataset's terms of use accepted on its web page, or the retrieve fails with a 403.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Explicit UTF-8: the Windows console uses cp1252 and chokes on "→" or "·".
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from app import config  # noqa: E402
from app.providers import cds  # noqa: E402

PRESETS = {
    "valencia": dict(lat=39.47, lon=-0.38, name="valencia"),
    "madrid": dict(lat=40.42, lon=-3.70, name="madrid"),
    "barcelona": dict(lat=41.39, lon=2.17, name="barcelona"),
    "seville": dict(lat=37.39, lon=-5.98, name="seville"),
}

# Useful variables and their natural daily statistic.
VARIABLE_STATISTIC = {
    "2m_temperature": ["daily_maximum", "daily_minimum"],
    "total_precipitation": ["daily_sum"],
    "10m_wind_speed": ["daily_maximum"],
}


def parse_years(spec: str) -> list[int]:
    if "-" in spec:
        a, b = spec.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(y) for y in spec.split(",")]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--preset", choices=sorted(PRESETS))
    p.add_argument("--lat", type=float)
    p.add_argument("--lon", type=float)
    p.add_argument("--name", default=None)
    p.add_argument("--years", default="2015-2024", help="e.g. 2000-2024 or 2020,2021")
    p.add_argument("--variable", default="2m_temperature", choices=sorted(VARIABLE_STATISTIC))
    p.add_argument("--daily-statistic", default=None,
                   help="by default, all the variable's natural ones")
    p.add_argument("--half-deg", type=float, default=0.75,
                   help="half side of the box, in degrees")
    p.add_argument("--fire", action="store_true",
                   help="request CEMS's Fire Weather Index (EWDS) instead")
    p.add_argument("--years-per-request", type=int, default=1,
                   help="years per request. Raise it carefully: the CDS rejects "
                        "large requests with 'cost limits exceeded'")
    p.add_argument("--max-in-flight", type=int, default=2,
                   help="jobs queued at once. The CDS limits how many it accepts "
                        "per dataset and returns 'rejected' if you go over")
    p.add_argument("--max-wait-minutes", type=float, default=90.0,
                   help="how long to wait in total before giving up; the jobs "
                        "stay alive in the CDS")
    p.add_argument("--dry-run", action="store_true", help="show the request and exit")
    args = p.parse_args()

    if args.preset:
        spot = PRESETS[args.preset]
        lat, lon, name = spot["lat"], spot["lon"], args.name or spot["name"]
    elif args.lat is not None and args.lon is not None:
        lat, lon, name = args.lat, args.lon, args.name or f"{args.lat:.2f}_{args.lon:.2f}"
    else:
        p.error("give --preset or both --lat and --lon")
        return 2

    years = parse_years(args.years)
    area = cds.bbox_around(lat, lon, args.half_deg)
    store: cds.Store = "ewds" if args.fire else "cds"

    # Split by years. The CDS rejects large requests with
    #   403 {"title": "cost limits exceeded", "detail": "Your request is too large"}
    # and ten consecutive years of daily statistics already exceed it. One chunk
    # per year is accepted without trouble, and since we send them all at once
    # the CDS processes them in parallel, so splitting does not cost time: it
    # saves it.
    chunks = [years[i:i + args.years_per_request]
              for i in range(0, len(years), args.years_per_request)]

    jobs = []
    if args.fire:
        for chunk in chunks:
            jobs.append((
                cds.DATASET_FIRE_HISTORICAL,
                cds.build_fire_request(years=chunk, area=area),
                config.CDS_DIR / f"{name}_fwi_{chunk[0]}_{chunk[-1]}.nc",
            ))
    else:
        stats = ([args.daily_statistic] if args.daily_statistic
                 else VARIABLE_STATISTIC[args.variable])
        for stat in stats:
            for chunk in chunks:
                jobs.append((
                    cds.DATASET_DAILY_STATS,
                    cds.build_daily_stats_request(
                        variable=args.variable, years=chunk,
                        daily_statistic=stat, area=area,
                    ),
                    config.CDS_DIR / f"{name}_{args.variable}_{stat}_{chunk[0]}_{chunk[-1]}.nc",
                ))

    url, key = cds.credentials(store)
    print(f"Store    : {store}  ->  {url}")
    print(f"Token    : {'configured' if key else 'NOT CONFIGURED'}")
    print(f"Point    : {lat}, {lon}   box [N,W,S,E] = {area}")
    print(f"Years    : {years[0]}-{years[-1]}  ({len(years)} years)")
    print(f"Jobs     : {len(jobs)}  ({args.years_per_request} year(s) per request)")
    print()

    print(f"--- example request ({jobs[0][2].name}) ---")
    print(f"dataset = {jobs[0][0]!r}")
    print(f"request = {json.dumps(jobs[0][1], indent=2)[:900]}")
    print()

    if args.dry_run:
        print(f"(--dry-run: nothing was sent. It would be {len(jobs)} requests)")
        return 0

    if not key:
        print("ERROR: the token is missing. Put it in .env, in ~/.cdsapirc or in the "
              f"{store.upper()}_API_KEY variable.", file=sys.stderr)
        return 1

    print("Queueing everything at once: the CDS processes several jobs in parallel.")
    started = time.time()
    results = cds.retrieve_many(
        jobs, store=store, on_log=lambda m: print("  ", m),
        max_wait_seconds=args.max_wait_minutes * 60,
        max_in_flight=args.max_in_flight,
    )
    elapsed = time.time() - started

    ok = [n for n, p in results.items() if p is not None]
    ko = [n for n, p in results.items() if p is None]
    print()
    print(f"{len(ok)}/{len(results)} files ready in {elapsed / 60:.1f} min.")
    print("That is the real CDS queue time for this account.")
    if ko:
        print(f"Failed: {', '.join(ko)}", file=sys.stderr)
        print("Run it again: whatever is downloaded is not requested again.", file=sys.stderr)

    print()
    print(f"Next step:  python backend/scripts/cds_build_baseline.py "
          f"--name {name} --glob '{name}_*.nc'")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
