"""Collects from the CDS the jobs that are already done: submit today, collect tomorrow.

The same CDS request can take minutes in the morning and more than an hour without even
starting later on, so "submit and wait" is not a viable pattern:

    1. `cds_download.py` queues and waits a reasonable while.
    2. If time runs out, the jobs are NOT lost: they stay alive in the CDS.
    3. This script collects them when they are ready, even the next day.

    python backend/scripts/cds_collect.py            # collects whatever is ready
    python backend/scripts/cds_collect.py --watch    # waits until they are
    python backend/scripts/cds_collect.py --all      # includes jobs submitted elsewhere
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Explicit UTF-8: the Windows console uses cp1252 and chokes on "→" or "·".
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from app import config  # noqa: E402
from app.providers import cds  # noqa: E402


def collect_once(include_unknown: bool = False) -> tuple[int, int]:
    """Returns (downloaded, still waiting)."""
    pending = cds.pending_jobs()
    try:
        account = cds.account_jobs()
    except cds.CdsError as exc:
        print(f"Could not query the CDS: {exc}", file=sys.stderr)
        return 0, len(pending)

    by_id = {j["job_id"]: j for j in account["jobs"]}
    downloaded = waiting = 0

    for job_id, info in pending.items():
        short = job_id[:8]
        row = by_id.get(short)
        status = row["status"] if row else "unknown"
        target = Path(info["target"])

        if status == "successful":
            try:
                href, _size = cds.job_result_href(job_id, store=info.get("store", "cds"))
                cds.download_href(href, target)
                cds.forget_pending(job_id)
                print(f"  [done] {target.name}  ({target.stat().st_size / 1e6:.2f} MB)")
                downloaded += 1
            except Exception as exc:  # noqa: BLE001
                print(f"  [failed] {target.name}: {exc}", file=sys.stderr)
        elif status in ("failed", "dismissed", "rejected"):
            print(f"  [dropped] {target.name}: the CDS left it as '{status}'")
            cds.forget_pending(job_id)
        else:
            wait = row.get("waiting_minutes") if row else None
            extra = f", waiting {wait:.0f} min" if wait else ""
            print(f"  [waiting] {target.name}: {status}{extra}")
            waiting += 1

    if include_unknown:
        # Finished jobs this project did not submit (loose tests, another
        # machine). They are saved with the jobID as the name, so they are not lost.
        for row in account["jobs"]:
            if row["status"] != "successful":
                continue
            if any(k.startswith(row["job_id"]) for k in pending):
                continue
            target = config.CDS_DIR / f"rescued_{row['job_id']}.nc"
            if target.exists():
                continue
            try:
                href, _ = cds.job_result_href(row["job_id"])
            except cds.CdsError:
                continue  # the short jobID is not enough to request the result
            cds.download_href(href, target)
            print(f"  [rescued] {target.name}")
            downloaded += 1

    return downloaded, waiting


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--watch", action="store_true",
                   help="keep polling until none is left waiting")
    p.add_argument("--every", type=float, default=120.0, help="seconds between polls")
    p.add_argument("--max-minutes", type=float, default=240.0)
    p.add_argument("--all", action="store_true", dest="include_unknown",
                   help="also collect finished jobs this project did not submit")
    args = p.parse_args()

    if not cds.credentials("cds")[1]:
        print("The CDS token is missing (CDS_API_KEY in .env, or ~/.cdsapirc).", file=sys.stderr)
        return 1

    started = time.time()
    while True:
        pending = cds.pending_jobs()
        print(f"{len(pending)} job(s) recorded as pending")
        downloaded, waiting = collect_once(args.include_unknown)
        print(f"-> {downloaded} downloaded, {waiting} waiting")

        if not args.watch or waiting == 0:
            break
        if (time.time() - started) / 60 > args.max_minutes:
            print(f"Time is up ({args.max_minutes:.0f} min). The jobs are still "
                  f"alive: run this script again whenever you like.")
            break
        print(f"   (next poll in {args.every:.0f}s)\n")
        time.sleep(args.every)

    if any(config.CDS_DIR.glob("*.nc")):
        print()
        print("Next step:  python backend/scripts/cds_build_baseline.py "
              "--name valencia --glob 'valencia_*.nc'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
