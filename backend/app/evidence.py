"""Evidence gaps: numbers in a report that rest on a single source.

Every number says where it comes from. A stricter rule follows: a number that can be
checked against an independent source should be. When a report finds one that cannot
yet (every heat figure comes from ERA5, and the only cross-check compares ERA5 with
ERA5), the report says so and queues a task for the autonomous engineering layer
(`backend/autonomy/`), which hands it to Devin.

This never changes a number, a score or a card.
"""

from __future__ import annotations

from . import autonomy_store

STATION_WITNESS = "station-witness"


def gaps(report: dict) -> list[dict]:
    out = []
    in_catalonia = (report.get("coverage") or {}).get("region") == "Catalonia"
    heat = any(h.get("key") == "heat" for h in report.get("hazards") or [])
    witness = report.get("witness")
    if in_catalonia and heat and not (isinstance(witness, dict) and witness.get("available")):
        place = (report.get("location") or {}).get("name")
        try:
            item = autonomy_store.request(
                STATION_WITNESS,
                "Every heat number (hot days, tropical nights, the record) comes from one model, "
                "ERA5, and the only cross-check compares ERA5 with ERA5. Catalonia's official "
                "weather stations (Meteocat) could be an independent witness.",
                place)
        except OSError:  # a read-only disk must not break a report
            item = {"status": "requested", "run_id": None}
        out.append({
            "hazard": "heat",
            "what": "Extreme heat",
            "why": "Every heat number comes from one model (ERA5); the only cross-check "
                   "compares ERA5 with ERA5.",
            "wanted": "An independent witness: Meteocat's official weather stations.",
            "task": STATION_WITNESS,
            "status": item.get("status"),
            "run_id": item.get("run_id"),
        })
    return out
