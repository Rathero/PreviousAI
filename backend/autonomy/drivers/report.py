"""Driver: builds reports with the checkout's code and keeps what the gate compares.

argv: JSON args ({"queries": [...]}), output path.
"""

import asyncio
import json
import os
import sys
import traceback

sys.path.insert(0, os.environ["TARGET_BACKEND"])


def main() -> None:
    args, out_path = json.loads(sys.argv[1]), sys.argv[2]
    out = {"results": {}}
    try:
        from app.report import build_report
    except BaseException as exc:  # noqa: BLE001
        out["error"] = f"cannot import app.report: {type(exc).__name__}: {exc}"
        json.dump(out, open(out_path, "w", encoding="utf-8"))
        return
    for q in args["queries"]:
        try:
            r = asyncio.run(build_report(query=q))
            out["results"][q] = {
                "hazards": [[h["key"], h.get("score"), h.get("level")] for h in r.get("hazards", [])],
                "overall": r.get("overall"),
                "witness": r.get("witness"),
                "warnings": r.get("warnings"),
                "location": r.get("location"),
            }
        except BaseException as exc:  # noqa: BLE001
            tb = traceback.format_exc().strip().splitlines()[-3:]
            out["results"][q] = {"error": f"{type(exc).__name__}: {exc} | " + " | ".join(tb)}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, default=str)


main()
