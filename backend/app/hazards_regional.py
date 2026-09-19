"""Regional levels (ThinkHazard!) and the Copernicus fire-danger projection.

From ThinkHazard! only the levels inside the product's scope are used: river (FL),
urban (UF) and coastal (CF) flooding, extreme heat (EH) and wildfire (WF).

  - Flooding gets its own regional card (outside Spain it is the only flood
    information; in Spain the official SNCZI card takes precedence).
  - Heat and wildfire get the regional level as a contrast next to the ERA5 score,
    without changing it.

A card with a low or missing regional level is not shown: an explicit "does not
apply" is information, an empty card is not.
"""

from __future__ import annotations

from . import scoring
from .hazards import Hazard
from .indicators import CDS_FIRE_PROJ, THINKHAZARD, Indicator, Provenance
from .providers.thinkhazard import HAZARD_EN, LEVEL_EN, LEVEL_ORDER

SHOW_LEVELS = {"MED", "HIG"}
CODES = ("FL", "UF", "CF", "EH", "WF")


def _ind(key, label, value, unit, prov: dict, *, period, method, confidence="high",
         display=None, context=None) -> Indicator:
    extras = {"display": display} if display is not None else {}
    return Indicator(
        key=key, label=label,
        value=None if value is None else round(float(value), 3),
        unit=unit,
        provenance=Provenance(period=period, method=method, confidence=confidence, **prov),
        context=context, extras=extras,
    )


def th_indicator(th: dict, code: str, label: str) -> Indicator | None:
    """ThinkHazard's level for one hazard, as a traceable indicator."""
    if not th or not th.get("levels") or code not in th["levels"]:
        return None
    level = th["levels"][code]
    div = th["division"]
    scope = div["scope"]
    scale = {"admin2": ("province", "region"), "admin1": ("region", "region"),
             "country": ("country", "country")}.get(scope, ("region", "region"))
    return _ind(
        f"thinkhazard_{code.lower()}", label, scoring.score_thinkhazard(level, scope), "/100",
        {**THINKHAZARD, "scale": scale[0], "scale_kind": scale[1]},
        period="current ThinkHazard! release",
        method=f"level published for {div['label']}, translated to the product scale "
               f"(high 70, medium 45, low 22, very low 6)",
        display=f"{LEVEL_EN.get(level, level)} · {div['label']}",
        confidence="medium" if scope != "country" else "low",
        context="Level for the whole country: it does not describe this area and does not score"
                if scope == "country" else "Regional level, not the point's",
    )


def _th(th: dict | None, code: str) -> tuple[str | None, float | None]:
    if not th or not th.get("levels"):
        return None, None
    level = th["levels"].get(code)
    return level, scoring.score_thinkhazard(level, th["division"]["scope"])


def _level_text(level: str | None) -> str:
    return LEVEL_EN.get(level or "no-data", "no data")


def hazard_flood_regional(th: dict | None, spain: bool) -> Hazard | None:
    """River (outside Spain), surface-water and coastal flooding at regional level.

    In Spain river flooding is covered by the official SNCZI flood zone, which is
    street-scale; repeating it at provincial level would only contradict it.
    """
    codes = [("UF", "Urban flooding from rain"), ("CF", "Coastal flooding")]
    if not spain:
        codes.insert(0, ("FL", "River flooding"))
    levels = {c: _th(th, c) for c, _ in codes}
    shown = [c for c, (lvl, _) in levels.items() if lvl in SHOW_LEVELS]
    if not shown or th["division"]["scope"] == "country":
        return None
    score = max(levels[c][1] for c in shown)
    short = {"FL": "river", "UF": "urban (rain)", "CF": "coastal"}
    parts = [f"{_level_text(levels[c][0])} {short[c]}" for c in shown]
    joined = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    place = th["division"]["label"].split(" · ")[0]
    headline = f"In {place}: {joined} flooding"
    indicators = [i for c, label in codes if (i := th_indicator(th, c, label))]
    return Hazard(
        key="flood_regional", label="Flooding · regional level", score=score,
        level=scoring.level_for(score), headline=headline, primary_metric="thinkhazard_uf",
        indicators=indicators,
        limitation="Level for the whole province or region: it says there are areas with "
                   "that hazard in it, not that this address is in one. "
                   + ("In Spain, for river and coastal flooding, the official flood zone "
                      "card takes precedence." if spain else
                      "Outside Spain there is no street-scale official flood mapping in "
                      "this report."),
    )


def enrich_climate(hazards: list[Hazard], th: dict | None) -> None:
    """A regional second opinion on the climate cards: it does not change the score."""
    pairs = {"heat": ("EH", "Regional extreme heat level (ThinkHazard!)"),
             "wildfire": ("WF", "Regional wildfire level (ThinkHazard!)")}
    for h in hazards:
        if h.key in pairs:
            ind = th_indicator(th, *pairs[h.key])
            if ind:
                ind.value = None  # context only: ERA5 gives the score
                ind.extras["contrast"] = True
                ind.provenance.method += "; shown as a contrast and does not score"
                h.indicators.append(ind)


def regional_table(th: dict | None) -> dict | None:
    """ThinkHazard's levels for the product's hazards, as a summary table."""
    if not th or not th.get("levels"):
        return None
    rows = sorted(
        ({"code": c, "hazard": HAZARD_EN.get(c, c), "level": lvl, "level_text": _level_text(lvl)}
         for c, lvl in th["levels"].items() if c in CODES),
        key=lambda r: -LEVEL_ORDER.get(r["level"], -1))
    return {"division": th["division"]["label"], "scope": th["division"]["scope"],
            "rows": rows, "url": th["division"].get("url") or "https://thinkhazard.org/"}


def enrich_wildfire_projection(hazard: Hazard, proj: dict | None) -> None:
    """Official projection of high fire-danger days (EFFIS Fire Weather Index).

    It does not replace the ERA5 proxy's score: it is another source, other models and
    only the June-September season. It shows where things are heading, with an explicit
    scenario and period.
    """
    if not proj:
        return
    base = proj.get("historical_1981_2005", {})
    labels = {"historical_1981_2005": "1981-2005", "rcp4_5_2041_2060": "2041-2060 RCP4.5",
              "rcp8_5_2041_2060": "2041-2060 RCP8.5"}
    for run, label in labels.items():
        vals = proj.get(run)
        if not vals:
            continue
        high = vals.get("high")
        ctx = None
        if run != "historical_1981_2005" and base.get("high") is not None and high is not None:
            ctx = f"{high - base['high']:+.0f} days compared with 1981-2005"
        hazard.indicators.append(_ind(
            f"fwi_high_{run}", f"Days with FWI > 30, high danger or worse ({label})", high,
            "days/year", CDS_FIRE_PROJ, period=label.split(" ")[0],
            method="annual mean of days with a Fire Weather Index above 30 (variable "
                   "fwi-nods-gt-30); EURO-CORDEX multi-model mean, nearest cell",
            confidence="medium", context=ctx,
        ))
    fut = proj.get("rcp8_5_2041_2060", {}).get("high")
    if base.get("high") is not None and fut is not None and fut - base["high"] >= 3:
        hazard.headline += (f"; by 2041-2060 (RCP8.5) {fut - base['high']:.0f} more days a year "
                            f"of high danger (FWI > 30) are projected")
