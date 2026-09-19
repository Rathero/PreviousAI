"""Driver: calls the checkout's `meteocat.station_witness` and writes what came back.

argv: JSON args, output path. Modes:
  live   one call per point (the portal URL comes from the environment)
  cache  a live call, then the same call with config.METEOCAT_URL redirected to a
         dead address at call time: a cached answer must come back unchanged
"""

import asyncio
import inspect
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.environ["TARGET_BACKEND"])


def short(exc: BaseException) -> str:
    frames = traceback.extract_tb(exc.__traceback__)
    where = next((f"{os.path.basename(f.filename)}:{f.lineno}" for f in reversed(frames)
                  if "meteocat" in f.filename or "report" in f.filename), "")
    return f"{type(exc).__name__}: {exc}" + (f" (at {where})" if where else "")


def main() -> None:
    args, out_path = json.loads(sys.argv[1]), sys.argv[2]
    out = {"results": {}}
    try:
        from app import config
        from app.providers import meteocat
        fn = meteocat.station_witness
        out["is_coroutine"] = inspect.iscoroutinefunction(fn)
    except BaseException as exc:  # noqa: BLE001 - it is evidence, not our failure
        out["error"] = f"cannot import app.providers.meteocat.station_witness: {short(exc)}"
        json.dump(out, open(out_path, "w", encoding="utf-8"))
        return

    async def call(p):
        res = fn(p["lat"], p["lon"], p["elevation_m"])
        if inspect.isawaitable(res):
            res = await asyncio.wait_for(res, timeout=600)
        return res

    for p in args["points"]:
        started = time.perf_counter()
        try:
            if args.get("mode") == "cache":
                first = asyncio.run(call(p))
                config.METEOCAT_URL = args["dead_url"]
                try:
                    second = asyncio.run(call(p))
                except BaseException as exc:  # noqa: BLE001
                    second = f"raised {short(exc)}"
                out["results"][p["name"]] = {"first": first, "second": second}
            else:
                out["results"][p["name"]] = {"value": asyncio.run(call(p))}
        except BaseException as exc:  # noqa: BLE001
            out["results"][p["name"]] = {"error": short(exc)}
        out["results"][p["name"]]["seconds"] = round(time.perf_counter() - started, 2)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, default=str)


main()
