"""Context on the wildfire card: fuel and terrain, the official class, fires seen from space.

The wildfire card scores fire WEATHER from ERA5. Real risk also depends on fuel,
terrain and ignition, and three sources speak to that. None of them changes the score:

  - FireScope (INSAIT): an AI model's 30 m estimate of 2026 wildfire risk from
    satellite imagery and climate. AI never produces a scored number here, and its
    authors say it should not be the sole basis for safety decisions: context, low
    confidence.
  - INFOCAT (Catalan Civil Protection): the official static danger and vulnerability
    class of the municipality. Official, but municipal and relative to the Catalan
    average: a contrast, like the regional levels.
  - Deepfire: fires detected by satellite within 10 km since January 2025. Observed,
    but it includes agricultural and prescribed burns and misses small fires.
"""

from __future__ import annotations

import datetime as dt

from .hazards import Hazard
from .indicators import DEEPFIRE_FIRES, FIRESCOPE, GENCAT_INFOCAT, Indicator, Provenance

MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _ind(key, label, value, unit, prov: dict, *, period, method, confidence, display=None,
         context=None, scale=None, scale_kind=None, **extras) -> Indicator:
    """`beside=True` marks the indicators worth seeing without opening the card."""
    p = dict(prov)
    if scale:
        p["scale"], p["scale_kind"] = scale, scale_kind or p.get("scale_kind")
    ex = {"contrast": True, **extras}
    if display is not None:
        ex["display"] = display
    return Indicator(key=key, label=label,
                     value=None if value is None else round(float(value), 3), unit=unit,
                     provenance=Provenance(period=period, method=method, confidence=confidence, **p),
                     context=context, extras=ex)


def _cap(text: str) -> str:
    """First letter up, the rest as written ("Catalan" stays capitalised)."""
    return text[:1].upper() + text[1:]


def distance_text(metres: float | None) -> str:
    if metres is None:
        return "none"
    if metres < 1000:
        return f"{round(metres / 10) * 10:.0f} m" if metres >= 10 else "at the point"
    return f"{metres / 1000:.1f} km"


def day_text(iso: str | None) -> str:
    if not iso:
        return "?"
    d = dt.date.fromisoformat(iso[:10])
    return f"{d.day} {MONTH_ABBR[d.month - 1]} {d.year}"


def firescope_indicators(fs: dict | None) -> list[Indicator]:
    if not fs or not fs.get("covered"):
        return []
    method = ("FireScope's 2026 risk map (a vision-language model reading Sentinel-2 imagery and "
              "NASA POWER climate, trained on the US 'risk to potential structures' layer), "
              "read at 30 m; its classes: Safe < 25 ≤ Low < 50 ≤ Moderate < 75 ≤ High. "
              "AI output: shown as context and does not score")
    common = dict(period="2026 (annual likelihood and intensity)", confidence="low",
                  method=method)
    out = [_ind("firescope_point", "AI-estimated wildfire risk at the point (FireScope)",
                fs["value"], "/100", FIRESCOPE,
                display=f"{fs['value']:.0f}/100 · {fs['class']}" if fs["value"] is not None else None,
                context="Built-up land and water read 0: the risk is in the vegetation around.",
                scale="point (30 m)", **common)]
    if fs.get("max") is not None:
        share = fs.get("share_moderate") or 0
        out.append(_ind(
            "firescope_1km", "Highest AI-estimated risk within 1 km (FireScope)", fs["max"], "/100",
            FIRESCOPE, display=f"{fs['max']:.0f}/100 · {fs['max_class']}",
            context=(f"{share * 100:.0f} % of the land within 1 km is at moderate risk or higher "
                     f"(median {fs['median']:.0f}/100)."),
            scale="1 km radius", scale_kind="radius", beside=True, **common))
    near = fs.get("nearest_m") or {}
    moderate, high = near.get("moderate"), near.get("high")
    search = fs.get("search_m", 3000) / 1000
    out.append(_ind(
        "firescope_nearest", "Nearest land at moderate AI-estimated risk or higher",
        None if moderate is None else moderate / 1000, "km", FIRESCOPE,
        display=distance_text(moderate) if moderate is not None else f"none within {search:.0f} km",
        context=(f"High risk (75 or more): {distance_text(high)} away." if high is not None
                 else f"No land at high risk (75 or more) within {search:.0f} km."),
        scale=f"{search:.0f} km radius", scale_kind="radius", beside=True, **common))
    return out


def infocat_indicators(info: dict | None) -> list[Indicator]:
    if not info or not (info.get("danger") or info.get("vulnerability") or info.get("plan")):
        return []
    period = f"current release (updated {info['updated']})" if info.get("updated") else "current release"
    method = ("municipal classes Catalan Civil Protection uses to decide which municipalities "
              "must have a wildfire action plan under INFOCAT; static danger relative to the "
              "Catalan average, not today's danger; official contrast, does not score")
    common = dict(period=period, confidence="high", method=method)
    out = []
    if info.get("danger"):
        out.append(_ind("infocat_danger", "Official wildfire danger of the municipality (INFOCAT)",
                        None, "", GENCAT_INFOCAT, display=_cap(info["danger"]),
                        context=f"Source wording: “Perill: {info.get('danger_ca')}”. "
                                "Today's operational level is the Pla Alfa.",
                        rank=info.get("danger_rank"), beside=True, **common))
    if info.get("vulnerability"):
        out.append(_ind("infocat_vulnerability", "Official vulnerability to wildfire (INFOCAT)",
                        None, "", GENCAT_INFOCAT, display=_cap(info["vulnerability"]),
                        context="How much is exposed where the forest meets homes, urbanisations "
                                "and infrastructure. Source wording: "
                                f"“Vulnerabilitat: {info.get('vulnerability_ca')}”.",
                        rank=info.get("vulnerability_rank"), beside=True, **common))
    if info.get("plan"):
        status = info.get("plan_status")
        when = f" on {day_text(info['plan_approved'])}" if info.get("plan_approved") else ""
        out.append(_ind("infocat_plan", "Municipal wildfire action plan (PAM)", None, "",
                        GENCAT_INFOCAT, display=_cap(info["plan"]),
                        context=(f"Plan status: {status}{when}." if status else None), **common))
    return out


def satellite_indicators(record: dict | None) -> list[Indicator]:
    if not record:
        return []
    fires = record.get("fires") or []
    since = day_text(record.get("since"))
    method = ("Deepfire's clusters of satellite hotspots; clusters of the same fire seen by "
              "different satellites merged (detections within 2 km, overlapping times); isolated "
              "single detections without high confidence left out; distance to the nearest "
              "detection. Includes agricultural and prescribed burns; small fires can be missed. "
              "Observed context, does not score")
    notes = []
    if fires:
        last = fires[0]
        size = f", perimeter ~{last['area_ha']:.0f} ha" if last.get("area_ha") else ""
        notes.append(f"Most recent: {day_text(last['first'])}, {last['distance_km']:.1f} km away, "
                     f"{last['detections']} detections{size}.")
        closest = min(fires, key=lambda f: f["distance_km"])
        if closest is not last:
            notes.append(f"Closest: {day_text(closest['first'])}, {closest['distance_km']:.1f} km away.")
    if record.get("singles_left_out"):
        notes.append(f"{record['singles_left_out']} isolated single detection(s) left out.")
    return [_ind("satellite_fires_10km",
                 f"Fires detected by satellite within {record.get('radius_km', 10)} km since {since}",
                 len(fires), "fires", DEEPFIRE_FIRES,
                 period=f"{record.get('since')} to {record.get('until')}",
                 method=method, confidence="medium", context=" ".join(notes) or None,
                 scale=f"{record.get('radius_km', 10)} km radius", beside=True)]


def enrich(hazard: Hazard, *, firescope: dict | None = None, infocat: dict | None = None,
           record: dict | None = None) -> None:
    """Adds the context indicators to the wildfire card. The score is untouched."""
    added = (firescope_indicators(firescope) + infocat_indicators(infocat)
             + satellite_indicators(record))
    if not added:
        return
    hazard.indicators.extend(added)
    notes = []
    if any(i.key.startswith("firescope") for i in added):
        notes.append("FireScope adds fuel and terrain, but it is an AI research model trained in "
                     "the United States, and its ~10 km patches can show seams: it is context, "
                     "not score.")
    if any(i.key.startswith("infocat") for i in added):
        notes.append("The official INFOCAT class describes the whole municipality relative to "
                     "Catalonia, not this address.")
    if any(i.key == "satellite_fires_10km" for i in added):
        notes.append("Satellites miss small fires and also see agricultural burns.")
    hazard.limitation = f"{hazard.limitation} {' '.join(notes)}".strip()
