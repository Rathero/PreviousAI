"""From an address to a complete, traceable report.

Four hazards: flooding, wildfire, avalanches and extreme heat. The location is resolved,
every source is queried in parallel (live APIs with a disk cache, and the local batch
layers), the hazard cards are built and scored, and the report is completed with what the
home adds (who acts on each measure), the history of the place and the action plan.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import time

import httpx

from . import (action_plan, advice, cache, config, dwelling as DW, evidence, hazards as HZ,
               hazards_avalanche as HA, hazards_official as HO, hazards_regional as HG, history,
               interpret, mapping, media, narrative, outlook, protection, scoring, series as S)
from . import wildfire_context as WC
from .hazards import MONTHS_EN
from .providers import (ai, catalonia_store, cds_baseline, cds_layers, deepfire, fal, firescope,
                        firms, forecast, gdacs, gencat_fire, geocoding, icgc, ign_flood, miteco,
                        nominatim, open_meteo, terrain, thinkhazard)
from .providers.catalonia_store import parse_losses

SEASON_MONTHS = {
    "winter": {12, 1, 2},
    "spring": {3, 4, 5},
    "summer": {6, 7, 8},
    "autumn": {9, 10, 11},
    "fall": {9, 10, 11},
}


def parse_months(months: str | None, season: str | None) -> set[int] | None:
    if season:
        key = season.strip().lower()
        if key in SEASON_MONTHS:
            return set(SEASON_MONTHS[key])
    if months:
        out = {
            int(m) for m in str(months).replace(" ", "").split(",")
            if m.isdigit() and 1 <= int(m) <= 12
        }
        return out or None
    return None


trip_months = interpret.trip_months


def is_cached(query: str) -> bool:
    """Whether a place's climate record is already saved, without touching the network."""
    coords = geocoding.parse_coordinates(query)
    if coords:
        lat, lon = coords
    else:
        place = cache.get("geocode", f"{geocoding.RESOLVE_KEY}:{query}")
        if not place:
            return False
        lat, lon = place["latitude"], place["longitude"]
    params = {
        "latitude": round(float(lat), 4),
        "longitude": round(float(lon), 4),
        "start_date": config.ARCHIVE_START,
        "end_date": open_meteo.archive_end_date(),
        "daily": ",".join(open_meteo.ARCHIVE_DAILY),
        "timezone": "UTC",
    }
    key = f"{open_meteo.ARCHIVE_URL}?{sorted(params.items())}"
    return cache.get("archive", key, allow_stale=True) is not None


def _add_derived(s: S.DailySeries) -> S.DailySeries:
    """Derived variables computed on the UNFILTERED series: 7-day rain needs contiguous
    days, which a seasonal month filter would break."""
    s.vars["precip_7d"] = S.rolling_sum(s.get("precipitation_sum"), 7)
    return s


async def build_report(
    *,
    query: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    label: str | None = None,
    months: set[int] | None = None,
    include_projection: bool = True,
    trip: tuple[dt.date, dt.date] | None = None,
    ask: str | None = None,
    profile: list[str] | None = None,
    force_home: bool = False,
    dwelling: dict | None = None,
) -> dict:
    """`ask` is a free-text request ("Seville in August with my parents"): the AI reads it
    into place, dates and who is going. Explicit `months`, `trip`, `profile` and
    `force_home` always win over what it understood. `dwelling` (house or flat, floor)
    never changes a score."""
    started = time.perf_counter()
    warnings: list[str] = []
    profile = [p for p in (profile or []) if p in interpret.PROFILES]

    # 1. Location ------------------------------------------------------------------
    understood = None
    if ask:
        understood = await interpret.run(ask)
        place, used = await interpret.resolve_place(understood)
        understood["place"]["used"] = used
        if months is None and trip is None:
            if understood.get("trip"):
                trip = tuple(dt.date.fromisoformat(d) for d in understood["trip"])
            elif understood.get("months"):
                months = set(understood["months"])
        if not profile:
            profile = [p["key"] for p in understood.get("profile", [])]
    elif query:
        place = await geocoding.resolve(query)
    elif lat is not None and lon is not None:
        place = {
            "name": label or f"{lat:.3f}, {lon:.3f}",
            "label": label or f"{lat:.4f}, {lon:.4f}",
            "latitude": lat, "longitude": lon,
            "country": None, "admin1": None, "timezone": None, "elevation": None,
        }
    else:
        raise ValueError("'ask', 'query' or both 'lat' and 'lon' are required")

    lat_f, lon_f = float(place["latitude"]), float(place["longitude"])
    if force_home:
        months, trip = None, None
    if trip and not months:
        months = trip_months(*trip)
    mode = "travel" if months else "home"

    # Coverage: which official sources apply here. The Catalan municipality is resolved
    # locally (milliseconds) and switches on the Catalan sources; MITECO's flood zones
    # cover all of Spain.
    cat = catalonia_store.store()
    municipality = cat.municipality_at(lat_f, lon_f) if cat.available else None
    spain = await _in_spain(place, lat_f, lon_f, municipality)
    if place.get("from_coordinates") and municipality:
        place = {**place, "label": f"{municipality['name']} ({lat_f:.4f}, {lon_f:.4f})"}

    # 2. Sources in parallel -------------------------------------------------------------
    # The terrain goes first (one light request, cached): its height decides whether a
    # climate series saved for a point a few hundred metres away can be reused.
    try:
        relief_first = await terrain.profile(lat_f, lon_f)
    except Exception as exc:  # noqa: BLE001 - same treatment as the parallel tasks
        relief_first = exc
    height = relief_first.get("center_m") if isinstance(relief_first, dict) else None
    if height is None:
        height = place.get("elevation")
    tasks = {
        "archive": open_meteo.fetch_archive(lat_f, lon_f, height),
        "thinkhazard": thinkhazard.regional_levels(lat_f, lon_f),
        "alerts": gdacs.current_alerts(lat_f, lon_f),
        "forecast": forecast.ensemble(lat_f, lon_f),
    }
    if firms.api_key():
        tasks["firms"] = firms.hotspots_near(lat_f, lon_f)
    if include_projection:
        tasks["proj_base"] = open_meteo.fetch_climate(lat_f, lon_f, *config.PROJECTION_BASE, height)
        tasks["proj_future"] = open_meteo.fetch_climate(lat_f, lon_f, *config.PROJECTION_FUTURE, height)
    if spain:
        tasks["flood_zones"] = miteco.flood_zones(lat_f, lon_f)
        tasks["flood_depths"] = ign_flood.flood_depths(lat_f, lon_f)
    if municipality:
        tasks["sea_level"] = icgc.sea_level_threshold(lat_f, lon_f)
    # Wildfire context: fuel and terrain (FireScope), the official Catalan class and
    # today's level, and fires seen by satellite (Deepfire). None of it scores.
    if firescope.raster_for(lat_f, lon_f):
        tasks["firescope"] = asyncio.to_thread(firescope.around, lat_f, lon_f)
    if municipality:
        tasks["infocat"] = gencat_fire.infocat(municipality["code"])
        tasks["pla_alfa"] = gencat_fire.pla_alfa(lat_f, lon_f)
    if deepfire.available():
        tasks["fires_now"] = deepfire.active_near(lat_f, lon_f)
        tasks["fires_record"] = deepfire.record_near(lat_f, lon_f)

    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    data = dict(zip(tasks.keys(), results))
    data["terrain"] = relief_first
    # Inside a river flood zone but no depth at the point: the model leaves buildings out,
    # so the depth is read at the nearest flooded cell (the street at the door).
    if isinstance(data.get("flood_zones"), dict) and isinstance(data.get("flood_depths"), dict):
        data["flood_depths"] = await ign_flood.complete_at_door(
            lat_f, lon_f, data["flood_zones"], data["flood_depths"])
    # Avalanches: ICGC's local layer (Catalonia), then snowfall only where there is
    # avalanche terrain, so flat places never pay for that request.
    data["avalanche"] = cat.avalanches_near(lat_f, lon_f) if municipality else None
    relief = data["terrain"] if isinstance(data["terrain"], dict) else None
    if (relief and relief["max_slope_deg"] >= 25) or (data["avalanche"] or {}).get("nivo_zone"):
        try:
            data["snow"] = open_meteo.summarize_snowfall(
                await open_meteo.fetch_snowfall(lat_f, lon_f, height))
        except (httpx.HTTPError, open_meteo.UpstreamError) as exc:
            data["snow"] = exc

    archive = data["archive"]
    if isinstance(archive, Exception):
        raise RuntimeError(f"could not get the ERA5 climate record: {archive}")

    if archive.get("_stale"):
        last_day = (archive.get("daily", {}).get("time") or ["?"])[-1]
        near = archive.get("_nearby")
        where = (f"for a nearby point ({near['distance_km']} km away, same ~9 km grid)"
                 if near else "for this point")
        warnings.append(f"Open-Meteo did not respond (request limit or network): using the "
                        f"saved ERA5 record {where}, which runs until {last_day}.")

    # 3. Series ------------------------------------------------------------------------
    full_all = _add_derived(S.DailySeries.from_open_meteo(archive))
    full = full_all.subset(months=months)
    recent = full.subset(min_year=config.CLIMATOLOGY_START)
    if len(recent) < 365:
        recent = full
        warnings.append("Short climatological window; the whole available record is used.")

    # 4. Hazards -----------------------------------------------------------------------
    hazard_list = [
        HZ.hazard_heat(recent, full, months),
        HZ.hazard_rain(recent, full),
        HZ.hazard_wildfire(recent, full, months),
    ]
    th = _ok(data, "thinkhazard", "ThinkHazard! regional levels", warnings)
    if th and not th.get("division"):
        warnings.append(f"ThinkHazard!: {th.get('reason')}.")
        th = None
    HG.enrich_climate(hazard_list, th)
    for h in hazard_list:
        if h.key == "wildfire":
            HG.enrich_wildfire_projection(h, cds_layers.fire_projection(lat_f, lon_f))
            WC.enrich(h, firescope=_ok(data, "firescope", "FireScope wildfire risk map", warnings),
                      infocat=_ok(data, "infocat", "INFOCAT municipal wildfire class", warnings),
                      record=_ok(data, "fires_record", "Deepfire satellite fire record", warnings))

    # 5. Projections -------------------------------------------------------------------
    projection = None
    if include_projection:
        base, future = data.get("proj_base"), data.get("proj_future")
        if isinstance(base, Exception) or isinstance(future, Exception):
            warnings.append("CMIP6 projections unavailable for this query.")
        else:
            try:
                base_s = _climate_series(base, months)
                future_s = _climate_series(future, months)
                projection = HZ.build_projection(base_s, future_s)
                HZ.attach_projections(hazard_list, projection)
            except (KeyError, ValueError) as exc:
                warnings.append(f"Projections discarded: {exc}")

    if mode == "travel":
        _relabel_for_travel(hazard_list, months or set())
        warnings.append(
            "Seasonal window: the score measures the intensity of the chosen months, as if the "
            "whole year were like that, so a summer destination can score higher in August than "
            "a desert on its annual average."
        )

    # Official sources come AFTER the seasonal adjustment: they are maps and records, not
    # seasonal series, and they are not rescaled.
    official, coverage, official_events = _official_hazards(
        data, municipality, spain, lat_f, lon_f, cat, warnings)
    hazard_list.extend(official)
    world, world_notes, ruled_out = _regional_hazards(data, th, spain, warnings)
    hazard_list.extend(world)
    coverage["notes"].extend(world_notes)
    coverage["ruled_out"] = ruled_out
    shared = _shared_series_note(archive)
    coverage["notes"][:0] = _precision_notes(place, lat_f, lon_f) + shared
    if shared:
        coverage["shared_series"] = shared[0]
    coverage["not_covered"] = NOT_COVERED
    alerts = _ok(data, "alerts", "GDACS alerts", warnings)
    fc = data.get("forecast")
    if isinstance(fc, Exception):
        next_days = {"unavailable": str(fc)}
    else:
        next_days = outlook.build(fc, full_all, trip, months)
    hotspots = _ok(data, "firms", "NASA FIRMS active fires", warnings)
    if alerts is not None and hotspots:
        alerts["hotspots"] = hotspots
    # Today, never scored: the Catalan Pla Alfa level and the fires burning now.
    pla_alfa = _ok(data, "pla_alfa", "Pla Alfa fire danger level", warnings)
    fires_now = _ok(data, "fires_now", "Deepfire active fires", warnings)
    if pla_alfa or fires_now:
        alerts = alerts if alerts is not None else {"alerts": [], "checked": 0, "source": None}
        if pla_alfa:
            alerts["pla_alfa"] = pla_alfa
        if fires_now:
            alerts["active_fires"] = fires_now
    fires_record = data.get("fires_record") if isinstance(data.get("fires_record"), dict) else None
    if fires_record and fires_record.get("fires"):
        official_events["satellite_fires"] = [
            {k: f[k] for k in ("first", "last", "distance_km", "detections", "area_ha", "confidence")}
            for f in fires_record["fires"][:6]]

    hazard_list.sort(key=lambda h: -(h.score or 0))
    overall = scoring.aggregate([h.score for h in hazard_list])

    # 6. Cross-check against the Copernicus CDS baseline, over the SAME years in both
    # layers (a "verified" badge that compares different periods would lie).
    cell = cds_baseline.nearest_cell(lat_f, lon_f)
    verification = None
    if cell:
        matched = _matched_window(full_all, None, cell["baseline"].get("period"))
        verification = cds_baseline.cross_check(lat_f, lon_f, matched)

    report = {
        "location": {
            "label": place.get("label") or place.get("name"),
            "name": place.get("name"),
            "town": place.get("town") or (municipality or {}).get("name"),
            "latitude": lat_f,
            "longitude": lon_f,
            "country": place.get("country"),
            "admin1": place.get("admin1"),
            "admin2": place.get("admin2"),
            "elevation_m": archive.get("elevation", place.get("elevation")),
            "timezone": place.get("timezone"),
            "precision": place.get("precision"),
            "geocoder": place.get("geocoder"),
            "ref_catastral": place.get("ref_catastral"),
            "postal_code": place.get("postal_code"),
            "address_not_found": place.get("address_not_found"),
        },
        "mode": mode,
        "window": {
            "months": sorted(months) if months else list(range(1, 13)),
            "climatology": f"{recent.year_range[0]}-{recent.year_range[1]}",
            "full_record": f"{full.year_range[0]}-{full.year_range[1]}",
            "days_analysed": len(full),
        },
        "overall": {
            "score": overall,
            "level": scoring.level_for(overall),
            "method": "the worst hazard dominates; the next ones add at most 15/7/4 % of the "
                      "remaining headroom (backend/app/scoring.py)",
        },
        "hazards": [h.to_dict() for h in hazard_list],
        "projection": projection,
        "events": {**_events(full_all, months), **official_events},
        "coverage": coverage,
        "regional": HG.regional_table(th),
        "alerts": alerts,
        "outlook": next_days,
        "map": mapping.build(lat=lat_f, lon=lon_f, place=place, archive=archive, data=data,
                             spain=spain, municipality=municipality),
        "verification": verification,
        "warnings": warnings,
        "meta": {
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "from_cache": bool(archive.get("_cached")),
            "stale_cache": bool(archive.get("_stale")),
            "version": config.VERSION,
            "ai": {"configured": ai.available(), "provider": ai.name(), "model": ai.model(),
                   "fal_configured": fal.available()},
        },
    }
    # Numbers resting on one source: said in the report and queued for the autonomous
    # engineering layer. Never changes a number.
    report["evidence_gaps"] = evidence.gaps(report)
    # Illustrations: the card's own value picks a clip from the pregenerated library.
    media.attach(report)
    # Today's fire-spread what-if, only if it has already been run: a report never waits
    # for a simulation.
    if deepfire.available():
        from . import fire_spread
        fs = data.get("firescope") if isinstance(data.get("firescope"), dict) else None
        report["fire_spread"] = fire_spread.cached_view(lat_f, lon_f, fs)
    report["narrative"] = narrative.summarize(report)
    if understood is not None:
        report["interpretation"] = understood

    # Advice for the household: only when something is known about them.
    person_text = ask if understood and understood.get("by") else None
    personal = await advice.personalize(report, person_text, profile)
    if personal:
        report["narrative"]["advice"] = personal["items"]
        report["narrative"]["advice_by"] = personal["by"]
        report["personalization"] = {k: v for k, v in personal.items() if k != "items"}
    # The home (never a score), the measures, the history and the action plan.
    report["dwelling"] = DW.describe(report, dwelling)
    report["protection"] = protection.build(report, profile, dwelling)
    report["history"] = history.build(report)
    report["action_plan"] = action_plan.build(report)
    report["meta"]["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
    # The AI service listed is the one that answered (or none without a key).
    report["sources"] = [{k: v for k, v in s.items() if k != "ai_provider"} for s in SOURCES
                         if s.get("ai_provider") in (None, ai.provider())]
    return report


def _matched_window(
    full: S.DailySeries, months: set[int] | None, period: str | None
) -> dict[str, float | None]:
    """Fast-layer indicators recomputed over another source's period (the CDS baseline,
    or a weather station's years), so the comparison is like for like."""
    scoped = full.subset(months=months)
    if period and "-" in period:
        try:
            y0, y1 = (int(p) for p in period.split("-", 1))
            scoped = S.DailySeries(
                dates=[d for d in scoped.dates if y0 <= d.year <= y1],
                vars={
                    k: [v for d, v in zip(scoped.dates, vals) if y0 <= d.year <= y1]
                    for k, vals in scoped.vars.items()
                },
            )
        except ValueError:
            pass
    if not scoped.dates:
        return {}

    tmax = scoped.get("temperature_2m_max")
    return {
        "hot_days_35": S.per_year(S.frequency(scoped, "temperature_2m_max", lambda v: v >= 35)),
        "hot_days_32": S.per_year(S.frequency(scoped, "temperature_2m_max", lambda v: v >= 32)),
        "hot_days_40": S.per_year(S.frequency(scoped, "temperature_2m_max", lambda v: v >= 40)),
        "tropical_nights": S.per_year(S.frequency(scoped, "temperature_2m_min", lambda v: v >= 20)),
        "heat_record": max(S.clean(tmax), default=None),
        "precip_p99": S.percentile(scoped.get("precipitation_sum"), 99),
        "annual_precip": (
            None if S.mean(scoped.get("precipitation_sum")) is None
            else S.mean(scoped.get("precipitation_sum")) * 365.25
        ),
    }


def _relabel_for_travel(hazard_list: list, months: set[int]) -> None:
    """Over a seasonal window "12 days/year" means "if the whole year were like August";
    the unit says so, and the context translates it into days out of ten."""
    window = " and ".join(MONTHS_EN[m] for m in sorted(months)) or "the chosen period"
    for hazard in hazard_list:
        for ind in hazard.indicators:
            if ind.value is None or not ind.unit.endswith("/year"):
                continue
            if not ind.provenance.dataset.startswith("era5"):
                continue  # only the climate series are filtered by months
            share = ind.value / 365.25
            ind.unit = ind.unit.replace("/year", "/year equiv.")
            note = (
                f"Calculated only over {window}: {share * 100:.0f} % of those days, "
                f"or {share * 10:.1f} out of 10. Expressed as equivalent days a year so the "
                f"score is comparable with the whole year."
            )
            ind.context = f"{ind.context} {note}" if ind.context else note


FIRE_RADIUS_M = 5000

# What the product does NOT cover, stated in the response itself.
NOT_COVERED = [
    {"hazard": "Flooding from sewers and intense local rain",
     "reason": "Official flood maps cover rivers and the coast; street-level surface-water "
               "flooding needs a drainage model. Extreme rain (ERA5) is shown as its driver."},
    {"hazard": "Avalanche paths outside the Catalan Pyrenees",
     "reason": "No open per-point avalanche map elsewhere; outside Catalonia there is only a "
               "terrain (slopes) and snowfall proxy."},
    {"hazard": "Today's avalanche danger",
     "reason": "It is a daily bulletin (danger 1-5 per zone, in winter): the avalanche card "
               "names the bulletin zone but never scores it."},
    {"hazard": "Official fire danger index (FWI) history",
     "reason": "A fire-weather proxy computed on ERA5 is used instead, plus the official FWI "
               "projection in Spain."},
    {"hazard": "Urban heat island",
     "reason": "ERA5's ~9 km cell averages city and countryside: a dense centre can be 2-5 °C "
               "hotter than the heat card says."},
]


def _ok(data: dict, key: str, label: str, warnings: list[str]):
    """Result of a parallel task, or None with a warning if it failed."""
    value = data.get(key)
    if isinstance(value, Exception):
        warnings.append(f"{label} unavailable ({type(value).__name__}); omitted.")
        return None
    return value


def _regional_hazards(data: dict, th: dict | None, spain: bool,
                      warnings: list[str]) -> tuple[list, list[str], dict[str, str]]:
    """Regional flooding (ThinkHazard!) and avalanches. What does not apply leaves a note,
    and a hazard ruled out by the data (flat or snowless terrain) says so."""
    hazards, notes, ruled_out = [], [], {}
    flood = HG.hazard_flood_regional(th, spain)
    if flood:
        hazards.append(flood)
    relief = _ok(data, "terrain", "Copernicus DEM terrain", warnings)
    snow = _ok(data, "snow", "ERA5-Land snowfall", warnings)
    card, note, excluded = HA.hazard_avalanche(data.get("avalanche"), relief, snow)
    if card:
        hazards.append(card)
    if note:
        notes.append(note)
        if excluded:
            ruled_out["avalanche"] = note.split(": ", 1)[-1][:1].upper() + note.split(": ", 1)[-1][1:]
    return hazards, notes, ruled_out


async def _in_spain(place: dict, lat: float, lon: float, municipality: dict | None) -> bool:
    """Does Spanish official mapping apply to this point?

    Spain's bounding box includes Portugal: the geocoder's country decides, and for bare
    coordinates Nominatim's (the same query ThinkHazard! then uses, so it is cached).
    """
    if municipality:
        return True
    if not miteco.in_spain(lat, lon):
        return False
    code = (place.get("country_code") or "").upper()
    if not code:
        try:
            address = await asyncio.wait_for(nominatim.reverse(lat, lon), timeout=8)
            code = (address.get("country_code") or "").upper()
        except (httpx.HTTPError, asyncio.TimeoutError, ValueError):
            return True  # no answer: the bounding box stands
    return code == "ES" if code else True


def _precision_notes(place: dict, lat: float, lon: float) -> list[str]:
    """What the analysed point means when it is not an exact address."""
    notes = []
    if place.get("address_not_found"):
        notes.append(f"The address \"{place['address_not_found']}\" was not found: the "
                     f"centre of {place.get('name')} is analysed instead.")
    if place.get("precision") in ("town", "place"):
        notes.append(f"The analysed point is the centre of {place.get('name')} "
                     f"({lat:.4f}, {lon:.4f}). Point cards (flood zone, sea, avalanche zones) apply "
                     f"to that point, not to the whole town: give a street and number for "
                     f"your home.")
    return notes


def _shared_series_note(archive: dict) -> list[str]:
    """Says so when the climate record is the one saved for a point next door."""
    near = archive.get("reused_from")
    if not near:
        return []
    return [f"The ERA5 record is the one already fetched for a point {near['distance_km'] * 1000:,.0f} m "
            f"away at the same height ({near['latitude']:.4f}, {near['longitude']:.4f}): ERA5-Land "
            f"cells are ~9 km, so it is the same climate. Only the point cards (flood zone, sea, "
            f"avalanche zones) are specific to this address."]


def _official_hazards(data: dict, municipality: dict | None, spain: bool, lat: float, lon: float,
                      cat, warnings: list[str]) -> tuple[list, dict, dict]:
    """Cards built from official maps and records.

    Everything is best effort: if an official service is down, a warning is given and the
    report comes out anyway with the rest.
    """
    hazards, events, notes, sources = [], {}, [], []

    if spain:
        result = data.get("flood_zones")
        depths = data.get("flood_depths")
        if isinstance(result, Exception):
            warnings.append(f"MITECO flood zones unavailable: {type(result).__name__}.")
            result = None
        if isinstance(depths, Exception):
            warnings.append(f"IGN water depths unavailable: {type(depths).__name__}.")
            depths = None
        if result or depths:
            hazards.append(HO.hazard_flood_zones(result, depths))
            if result:
                sources.append("SNCZI · MITECO")
            if depths:
                sources.append("SNCZI water depths · IGN")
            for r in (result, depths):
                if r and r.get("errors"):
                    warnings.append("Some flood zone layers did not respond: "
                                    + ", ".join(r["errors"]))

    if municipality:
        manifest = cat.manifest

        agora = manifest.get("agora", {})
        episodes = cat.flood_episodes(municipality["code"])
        hazards.append(HO.hazard_flood_history(
            municipality, episodes, agora.get("episodes_period", "1902-2020")))
        sources.append("AGORA · UB")
        events["flood_episodes"] = [
            {"date": e.get("start"), "category": e.get("category"),
             "victims": e.get("victims"), "losses_eur": parse_losses(e.get("losses_raw")),
             "losses_raw": e.get("losses_raw"), "phenomena": e.get("phenomena"),
             "report_url": e.get("report_url")}
            for e in episodes[:6]
        ]

        fires = cat.fires_near(lat, lon, FIRE_RADIUS_M)
        hazards.append(HO.hazard_fire_history(
            fires, municipality, cat.municipal_fire_stats(municipality["code"]),
            manifest.get("fires", {}).get("period", "1986-2024"),
            manifest.get("stats", {}).get("period", "2011-2026")))
        sources.append("Wildfires · Government of Catalonia")
        events["nearby_fires"] = [
            {k: f[k] for k in ("year", "date", "distance_m", "area_ha", "municipality", "inside")}
            for f in fires[:6]
        ]

        slr = data.get("sea_level")
        if isinstance(slr, Exception):
            warnings.append(f"ICGC sea-level rise service unavailable: {type(slr).__name__}.")
        elif slr:
            sources.append("Permanent flooding · ICGC")
            relief = data.get("terrain") if isinstance(data.get("terrain"), dict) else {}
            if slr.get("threshold_m") is not None:
                hazards.append(HO.hazard_sea_level(slr))
            elif relief.get("center_m", 0) <= 30:  # "stays above water" means nothing up a mountain
                notes.append(f"Sea-level rise checked: the point stays above water even with "
                             f"the largest rise modelled by ICGC "
                             f"({slr['max_modelled_m'] * 100:.0f} cm).")

        aval = data.get("avalanche")
        if aval and (aval["zones"] or aval["observations"] or aval["nivo_zone"]):
            sources.append("Avalanches · ICGC")
            events["avalanches"] = [{k: o[k] for k in ("code", "year", "distance_m", "inside")}
                                    for o in aval["observations"][:6]]

        if municipality.get("match") == "nearest":
            notes.append(f"The point falls outside the municipal polygons (right on the "
                         f"coastline); {municipality['name']} is assigned, "
                         f"{municipality['distance_m']} m away.")
    elif not cat.available and spain:
        warnings.append("The Catalan data layers are not installed "
                        "(backend/scripts/catalonia_build.py).")

    coverage = {
        "region": "Catalonia" if municipality else ("Spain" if spain else "global"),
        "extended": bool(municipality),
        "municipality": municipality,
        "official_sources": sources,
        "notes": notes,
        "summary": (
            "Extended coverage in Catalonia: official flood zones, flood history, wildfires "
            "with a perimeter, the official wildfire danger class and today's Pla Alfa level, "
            "sea-level rise and, in the Pyrenees, ICGC's avalanche map."
            if municipality else
            "Official SNCZI flood zones. Additional regional detail is available for Catalonia."
            if spain else
            "Worldwide coverage: heat, extreme rain and fire weather (ERA5), regional flood "
            "levels (ThinkHazard!) and an avalanche terrain and snow proxy. Outside Spain there "
            "is no street-scale official mapping."
        ),
    }
    return hazards, coverage, events


def _climate_series(payload: dict, months: set[int] | None) -> S.DailySeries:
    """The Climate API returns one column per model; they are averaged before use."""
    daily = payload["daily"]
    dates = [dt.date.fromisoformat(d) for d in daily["time"]]
    merged = {v: open_meteo.merge_models(payload, v) for v in open_meteo.CLIMATE_DAILY}
    s = S.DailySeries(dates=dates, vars=merged)
    return s.subset(months=months)


def _events(full: S.DailySeries, months: set[int] | None) -> dict:
    """Notable days of the climate record (filtered by the months of a seasonal window)."""
    scoped = full.subset(months=months)
    return {
        "wettest_days": S.extreme_days(scoped, "precipitation_sum", top=5),
        "hottest_days": S.extreme_days(scoped, "temperature_2m_max", top=5),
        "note": "The extreme days come from the full ERA5 record.",
    }


SOURCES = [
    {
        "name": "ERA5 / ERA5-Land (Copernicus Climate Change Service)",
        "role": "Daily record since 1979: temperature, precipitation, wind, humidity, snowfall",
        "access": "Open-Meteo Archive API (fast layer) and Climate Data Store (batch layer)",
        "licence": "Copernicus / CC BY 4.0",
        "url": "https://cds.climate.copernicus.eu/datasets/derived-era5-single-levels-daily-statistics",
    },
    {
        "name": "CMIP6 HighResMIP",
        "role": "Daily projections to 2050, downscaled to 10 km and bias-corrected against ERA5",
        "access": "Open-Meteo Climate API",
        "licence": "CC BY 4.0",
        "url": "https://open-meteo.com/en/docs/climate-api",
    },
    {
        "name": "ThinkHazard! (GFDRR, World Bank)",
        "role": "Hazard level by region for river, urban and coastal flooding, extreme heat "
                "and wildfire",
        "access": "Live JSON per region; the region comes from Nominatim (OpenStreetMap)",
        "licence": "Open use with attribution; each hazard's data belong to third parties",
        "url": "https://thinkhazard.org/",
    },
    {
        "name": "GDACS (United Nations and European Commission)",
        "role": "Ongoing flood and wildfire alerts near the point (not scored)",
        "access": "Live JSON feed, 30-minute cache",
        "licence": "Free use with attribution to GDACS",
        "url": "https://www.gdacs.org/",
    },
    {
        "name": "ECMWF AIFS ENS (European Centre for Medium-Range Weather Forecasts)",
        "role": "15-day ensemble forecast, compared with the usual for those dates (not scored)",
        "access": "Open-Meteo Ensemble API, 3-hour cache",
        "licence": "ECMWF open data (CC BY 4.0)",
        "url": "https://open-meteo.com/en/docs/ensemble-api",
    },
    {
        "name": "Nebius Token Factory",
        "ai_provider": "nebius",
        "role": "Typed AI decisions with probabilities (an open-weights LLM forced to choose "
                "among our options, probabilities from its token log-probabilities): reads "
                "free-text requests, checks claims against the report and ranks advice. Never "
                "produces a scored number",
        "access": "Nebius Token Factory API (NEBIUS_API_KEY), cached per request",
        "licence": "Commercial API; each model under its own open-weights licence",
        "url": "https://docs.tokenfactory.nebius.com/",
    },
    {
        "name": "TypeSafe Jev",
        "ai_provider": "typesafe",
        "role": "Typed AI decisions with confidence: reads free-text requests, checks claims "
                "against the report and ranks advice. Never produces a scored number",
        "access": "TypeSafe API (TYPESAFE_API_KEY), cached per request",
        "licence": "Commercial API; TypeSafe does not train on customer requests",
        "url": "https://docs.typesafe.ai/",
    },
    {
        "name": "fal.ai (generated media)",
        "role": "Illustration clips chosen by each hazard's value, the briefing's voice and "
                "speech to text for the address box. Never produces or changes a number",
        "access": "fal.ai API (FAL_KEY); illustrations generated once in batch and kept in "
                  "data/media",
        "licence": "Commercial API; generated media usable commercially per fal.ai's and each "
                   "model's terms",
        "url": "https://fal.ai/",
    },
    {
        "name": "SNCZI · flood water depths (IGN)",
        "role": "River water depth T10/T100/T500 and coastal flood zone T100/T500 at the point",
        "access": "Live INSPIRE WMS, cached",
        "licence": "CC BY 4.0 (IGN)",
        "url": "https://servicios.idee.es/wms-inspire/riesgos-naturales/inundaciones",
    },
    {
        "name": "SNCZI · Flood zones (MITECO)",
        "role": "Official T10/T50/T100/T500 and preferential flow flood zones, all of Spain",
        "access": "Live WFS, cached",
        "licence": "Free use with attribution to Spain's Ministry for the Ecological Transition",
        "url": "https://gis.miteco.gob.es/geoserver/agua/ows",
    },
    {
        "name": "AGORA (University of Barcelona)",
        "role": "228 flood episodes in Catalonia, 1902-2020, with victims and losses",
        "access": "ArcGIS FeatureServer, downloaded in batch",
        "licence": "Not stated: permission from the University of Barcelona is needed for "
                   "non-academic use",
        "url": "https://agora.ub.edu/",
    },
    {
        "name": "Wildfire perimeters (Government of Catalonia)",
        "role": "1,011 fires with a perimeter in Catalonia, 1986-2024",
        "access": "Yearly SHP files, downloaded in batch",
        "licence": "Llicència oberta d'ús d'informació – Catalunya (open licence)",
        "url": "https://agricultura.gencat.cat/ca/serveis/cartografia-sig/bases-cartografiques/boscos/incendis-forestals/",
    },
    {
        "name": "Wildfires by municipality (Government of Catalonia, open data)",
        "role": "Municipal fire record 2011-today, including outbreaks without a perimeter",
        "access": "Socrata API, downloaded in batch",
        "licence": "Llicència oberta d'ús d'informació – Catalunya (open licence)",
        "url": "https://analisi.transparenciacatalunya.cat/Medi-Rural-Pesca/Incendis-forestals-a-Catalunya-Anys-2011-2024/bks7-dkfd",
    },
    {
        "name": "ICGC · Permanent flooding from sea-level rise",
        "role": "Smallest sea-level rise that floods the point, Catalan coast",
        "access": "Live WMS, cached",
        "licence": "Public access (ICGC)",
        "url": "https://www.icgc.cat/ca/Ambits-tematics/Ambit-litoral/Aplicacions-i-visors/Inundacio-permanent-la-pujada-del-nivell-del-mar",
    },
    {
        "name": "ICGC · Avalanche zones map 1:25,000 and avalanche database (BDAC)",
        "role": "17,811 mapped avalanche zones, 6,468 observed avalanches (1971-2024) and 739 "
                "recalled in local surveys, Catalan Pyrenees",
        "access": "ICGC GeoServer WFS, downloaded in batch (catalonia_build.py)",
        "licence": "Public access (ICGC)",
        "url": "https://www.icgc.cat/en/Geoinformation-and-Maps/Data-and-products/Databases-and-catalogues/Database-avalanches-Catalonia-BDAC",
    },
    {
        "name": "Copernicus DEM GLO-90",
        "role": "Slopes around the point, for avalanche terrain",
        "access": "Open-Meteo Elevation API (81 points per report)",
        "licence": "Copernicus DEM licence (free use with attribution)",
        "url": "https://open-meteo.com/en/docs/elevation-api",
    },
    {
        "name": "Fire danger indicators for Europe (Copernicus CDS)",
        "role": "Official projection of high fire-danger days (FWI > 30), 1981-2005 vs "
                "2041-2060 (RCP4.5 and RCP8.5)",
        "access": "Climate Data Store, downloaded in batch (cds_hazards.py)",
        "licence": "Copernicus product licence",
        "url": "https://cds.climate.copernicus.eu/datasets/sis-tourism-fire-danger-indicators",
    },
    {
        "name": "FireScope 2026 wildfire risk map (INSAIT)",
        "role": "AI-estimated 2026 wildfire risk at 30 m around the point, Europe and Asia: "
                "fuel and terrain next to the fire-weather score (context, not scored)",
        "access": "GeoTIFF on Hugging Face, read tile by tile with HTTP range requests, "
                  "cached per point; pinned revision",
        "licence": "CC BY 4.0 · Markov et al., FireScope, CVPR 2026",
        "url": "https://firescope.ai/",
    },
    {
        "name": "Municipal wildfire danger and vulnerability · INFOCAT (Catalan Civil Protection)",
        "role": "Official static wildfire danger (relative to the Catalan average) and "
                "vulnerability of the municipality, and whether it must have a wildfire plan "
                "(contrast, not scored)",
        "access": "Socrata API, whole table cached for 30 days",
        "licence": "Llicència oberta d'ús d'informació – Catalunya (open licence)",
        "url": "https://analisi.transparenciacatalunya.cat/Seguretat/Obligacions-i-vig-ncies-dels-plans-de-protecci-civil-m/eqag-gzjs",
    },
    {
        "name": "Pla Alfa (Agents Rurals, Government of Catalonia)",
        "role": "Today's operational wildfire danger level per municipality, 0-4 (not scored)",
        "access": "ArcGIS FeatureServer behind the official viewer, 30-minute cache",
        "licence": "Public information of the Government of Catalonia",
        "url": "https://interior.gencat.cat/ca/arees_dactuacio/agents-rurals/pla-alfa/",
    },
    {
        "name": "Deepfire",
        "role": "Fires detected by satellite (VIIRS, MODIS, MTG, Sentinel-3, Landsat) burning now "
                "within 50 km and since January 2025 within 10 km; fire-spread simulations "
                "(ELMFIRE) on request. None of it is scored",
        "access": "Deepfire OGC API and fire-spread API (DEEPFIRE_CLIENT_ID and "
                  "DEEPFIRE_CLIENT_SECRET), cached",
        "licence": "Commercial API",
        "url": "https://docs.deepfire.co/",
    },
]
