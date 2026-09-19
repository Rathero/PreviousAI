"""Previous AI HTTP API and web app.

No endpoint that serves a person calls the Climate Data Store synchronously: the
/api/cds/* endpoints submit and watch batch jobs, they never feed a report.
"""

from __future__ import annotations

import asyncio
import datetime as dt

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import (autonomy_store, briefing, cache, claims, config, dwelling as DW, interpret, mapping,
               media, pdf_report, protection, report as R, scoring, video, view)
from .providers import ai, cds, cds_baseline, fal, geocoding, miteco, open_meteo, streetview

FRONTEND_DIR = config.ROOT / "frontend"

app = FastAPI(
    title="Previous AI",
    version=config.VERSION,
    description=(
        "Flood, wildfire, avalanche and extreme heat reports for a home, with the source of "
        "every figure. Data from ERA5 (Copernicus), CMIP6 and official Spanish and Catalan "
        "sources."
    ),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _deepfire_available() -> bool:
    from .providers import deepfire
    return deepfire.available()


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "version": config.VERSION,
        "cache": cache.stats(),
        "cds": cds.credentials_status(),
        "deepfire": {"configured": _deepfire_available()},
        "streetview": {"configured": streetview.available()},
        "baselines": cds_baseline.available(),
        "archive_window": {"start": config.ARCHIVE_START, "end": open_meteo.archive_end_date()},
        "ai": ai.status(),
        "fal": {
            "configured": fal.available(),
            "models": {"image": config.FAL_IMAGE_MODEL, "edit": config.FAL_EDIT_MODEL,
                       "video": config.FAL_VIDEO_MODEL, "tts": config.FAL_TTS_MODEL,
                       "stt": config.FAL_STT_MODEL},
            "illustrations": media.status()["generated"],
            "ffmpeg": video.available(),
        },
    }


# --------------------------------------------------------------------------- #
# The address
# --------------------------------------------------------------------------- #
@app.get("/api/suggest")
async def suggest(q: str = Query(min_length=1, max_length=200)):
    """Address suggestions while typing (Spanish addresses)."""
    return {"query": q, "results": await geocoding.suggest(q)}


@app.get("/api/locate")
async def locate(q: str = Query(min_length=2, max_length=300)):
    """The point an address resolves to, before the report is built."""
    try:
        place = await geocoding.resolve(q)
    except geocoding.GeocodingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    lat, lon = float(place["latitude"]), float(place["longitude"])
    code = (place.get("country_code") or "").upper()
    spain = code == "ES" if code else miteco.in_spain(lat, lon)
    return {**{k: place.get(k) for k in ("latitude", "longitude", "precision", "geocoder",
                                         "ref_catastral", "country", "address_not_found")},
            **view.place_lines(place), "label": view.street_name(place.get("label")),
            "aerial": mapping.AERIAL_PNOA if spain else mapping.AERIAL_S2}


@app.get("/api/geocode")
async def geocode(q: str = Query(min_length=2), count: int = 5):
    try:
        return {"query": q, "results": await geocoding.search(q, count=count)}
    except geocoding.GeocodingError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _trip(start: str | None, end: str | None) -> tuple[dt.date, dt.date] | None:
    if not (start or end):
        return None
    try:
        trip = (dt.date.fromisoformat(start or end), dt.date.fromisoformat(end or start))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="dates must be YYYY-MM-DD") from exc
    if trip[1] < trip[0] or (trip[1] - trip[0]).days > 90:
        raise HTTPException(status_code=400,
                            detail="the stay must end after it starts and last at most 90 days")
    return trip


def _profile(profile: str | None) -> list[str]:
    return [p for p in (profile or "").split(",") if p in interpret.PROFILES]


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #
@app.get("/api/report")
async def home_report(
    address: str = Query(min_length=2, max_length=300, description="The home's address"),
    home: str | None = Query(None, description="house | apartment"),
    floor: str | None = Query(None, description="Floor of the flat (0 = ground floor)"),
    who: str | None = Query(None, description="Who lives there, comma-separated: "
                                              + ", ".join(interpret.PROFILES)),
):
    """The web app's report for a home: four risks, the history and the action plan."""
    return view.app_view(await _home_report(address, home, floor, who))


async def _home_report(address: str, home: str | None, floor: str | None, who: str | None) -> dict:
    try:
        return await R.build_report(query=address, profile=_profile(who), force_home=True,
                                    dwelling=DW.parse(home, floor))
    except geocoding.GeocodingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/report/pdf")
async def home_report_pdf(
    address: str = Query(min_length=2, max_length=300, description="The home's address"),
    home: str | None = Query(None, description="house | apartment"),
    floor: str | None = Query(None, description="Floor of the flat (0 = ground floor)"),
    who: str | None = Query(None, description="Who lives there, comma-separated"),
):
    """The same report as a PDF to keep and share: every value behind each score, what
    already happened, the climate to 2050, the full action plan and the sources, with the
    pictures of the home. Drawn on request, never stored."""
    rep = await _home_report(address, home, floor, who)
    app_view = view.app_view(rep)
    pictures = await pdf_report.pictures(rep)
    pdf = await asyncio.to_thread(pdf_report.render, rep, app_view, pictures)
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{pdf_report.filename(app_view)}"',
        "Cache-Control": "no-store",
    })


@app.get("/api/interpret")
async def interpret_request(text: str = Query(min_length=2, max_length=300)):
    """What the AI understands from a free-text request, without building the report."""
    return await interpret.run(text)


@app.get("/api/risk")
async def risk(
    q: str | None = Query(None, description="Address or town"),
    ask: str | None = Query(None, max_length=300,
                            description="Free-text request, read by the AI: 'Seville in August "
                                        "with my parents'"),
    lat: float | None = None,
    lon: float | None = None,
    months: str | None = Query(None, description="Months of a stay, comma-separated, e.g. 7,8"),
    season: str | None = Query(None, description="winter | spring | summer | autumn"),
    projection: bool = Query(True, description="Include the CMIP6 projection to 2050"),
    start: str | None = Query(None, description="First day of a stay, YYYY-MM-DD"),
    end: str | None = Query(None, description="Last day of a stay, YYYY-MM-DD"),
    profile: str | None = Query(None, description="Who lives there or is going, comma-separated: "
                                                  + ", ".join(interpret.PROFILES)),
    mode: str | None = Query(None, description="'home' forces the whole year even if the request "
                                               "names dates"),
    home: str | None = Query(None, description="house | apartment"),
    floor: str | None = Query(None, description="Floor of the flat (0 = ground floor)"),
):
    """The full report, with every indicator, its provenance and the map layers."""
    if not q and not ask and (lat is None or lon is None):
        raise HTTPException(status_code=400, detail="give 'ask', 'q' or both 'lat' and 'lon'")
    try:
        return await R.build_report(
            query=q, ask=ask, lat=lat, lon=lon,
            months=R.parse_months(months, season),
            include_projection=projection,
            trip=_trip(start, end),
            profile=_profile(profile),
            force_home=mode == "home",
            dwelling=DW.parse(home, floor),
        )
    except geocoding.GeocodingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


class CheckRequest(BaseModel):
    text: str = Field(min_length=12, max_length=claims.MAX_TEXT)
    lat: float
    lon: float
    label: str | None = None
    months: str | None = None
    start: str | None = None
    end: str | None = None


@app.post("/api/check")
async def check_claims(body: CheckRequest):
    """Fact-checks a text about the place (a listing, a blog, an AI chatbot's answer)
    sentence by sentence against the report for that point."""
    try:
        rep = await R.build_report(lat=body.lat, lon=body.lon, label=body.label,
                                   months=R.parse_months(body.months, None),
                                   trip=_trip(body.start, body.end), include_projection=False)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return await claims.check(rep, body.text)


@app.get("/api/compare")
async def compare(
    q: str = Query(description="Places separated by semicolons"),
    months: str | None = None,
    season: str | None = None,
):
    """Compares up to four places."""
    places = [p.strip() for p in q.split(";") if p.strip()][:4]
    if not places:
        raise HTTPException(status_code=400, detail="no valid place")
    parsed = R.parse_months(months, season)
    out = []
    for index, place in enumerate(places):
        try:
            # Open-Meteo limits by volume: new places are spaced out.
            if index and not R.is_cached(place):
                await asyncio.sleep(2.0)
            rep = await R.build_report(query=place, months=parsed, include_projection=False)
            out.append({
                "location": rep["location"],
                "overall": rep["overall"],
                "hazards": [
                    {"key": h["key"], "label": h["label"], "score": h["score"],
                     "level": h["level"], "headline": h["headline"]}
                    for h in rep["hazards"]
                ],
            })
        except Exception as exc:  # noqa: BLE001 - one bad place does not bring the comparison down
            out.append({"location": {"label": place}, "error": str(exc)})
    return {"mode": "travel" if parsed else "home", "results": out}


# --------------------------------------------------------------------------- #
# Street View (Google) for the home
# --------------------------------------------------------------------------- #
@app.get("/api/streetview")
async def streetview_meta(lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180)):
    """Whether there is a street-level picture of the home, and where to get it."""
    try:
        meta = await streetview.metadata(lat, lon)
    except streetview.StreetViewUnavailable as exc:
        return {"available": False, "reason": str(exc)}
    if not meta.get("available"):
        return {"available": False, "reason": meta.get("reason")}
    return {"available": True, "date": meta.get("date"), "copyright": meta.get("copyright"),
            "distance_m": meta.get("distance_m"), "heading": meta.get("heading"),
            "image": f"/api/streetview/image?lat={lat:.6f}&lon={lon:.6f}"}


@app.get("/api/streetview/image")
async def streetview_image(lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180)):
    try:
        data = await streetview.image(lat, lon)
    except streetview.StreetViewUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(content=data, media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=3600"})


# --------------------------------------------------------------------------- #
# Generated media (fal.ai): it illustrates, narrates and listens; it never scores
# --------------------------------------------------------------------------- #
MAX_AUDIO_BYTES = 4_000_000  # ~4 minutes of Opus; the button stops at 15 seconds


@app.post("/api/transcribe")
async def transcribe(request: Request,
                     task: str = Query("transcribe", pattern="^(transcribe|translate)$",
                                       description="'translate' returns English")):
    """Voice input for the address box: the recording, as the request body, to text.

    The text goes back into the box, where the person sees it before anything is
    analysed. Neither the recording nor the transcript is kept.
    """
    if not fal.available():
        raise HTTPException(status_code=503, detail="voice input needs FAL_KEY on the server")
    ctype = request.headers.get("content-type", "")
    if not ctype.startswith(("audio/", "video/webm", "video/mp4")):
        raise HTTPException(status_code=415, detail="send the recording as audio/* in the body")
    audio = await request.body()
    if not audio:
        raise HTTPException(status_code=400, detail="empty recording")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="recording too long")
    try:
        return await fal.transcribe(audio, ctype, task=task)
    except fal.FalUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


class BriefingRequest(BaseModel):
    lat: float
    lon: float
    label: str | None = None
    months: str | None = None
    start: str | None = None
    end: str | None = None
    profile: str | None = None
    home: str | None = None
    floor: str | None = None
    narrate: bool = True


@app.post("/api/briefing")
async def briefing_start(body: BriefingRequest):
    """Starts the narrated video briefing for a point and returns its job at once.

    The script is written by code from the report; fal.ai only reads it aloud. Poll
    GET /api/briefing/{id} until `status` is "done".
    """
    if not video.available():
        raise HTTPException(status_code=503, detail="ffmpeg not found: pip install imageio-ffmpeg")
    try:
        rep = await R.build_report(lat=body.lat, lon=body.lon, label=body.label,
                                   months=R.parse_months(body.months, None),
                                   trip=_trip(body.start, body.end), include_projection=False,
                                   profile=_profile(body.profile),
                                   dwelling=DW.parse(body.home, body.floor))
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return briefing.start(rep, narrate=body.narrate)


@app.get("/api/briefing/{job_id}")
async def briefing_status(job_id: str):
    job = briefing.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="briefing not found")
    return job


@app.get("/api/illustrations")
async def illustrations():
    """The illustration library: every scene, the value that picks it, and, once
    generated, the models and prompts that drew it."""
    generated = media.manifest()["scenes"]
    return {
        "library": media.status(),
        "scenes": [{**s, "generated": {k: generated[s["id"]].get(k) for k in
                                       ("image_model", "video_model", "generated_at", "seed")}
                    if media.generated(s["id"]) else None}
                   for s in media.catalogue()],
        "limitation": media.ILLUSTRATION_LIMITATION,
    }


# --------------------------------------------------------------------------- #
# Method, sources and the measure catalogue
# --------------------------------------------------------------------------- #
@app.get("/api/sources")
async def sources():
    return {
        "sources": R.SOURCES,
        "scoring": {
            "levels": [{"from": lo, "to": hi, "label": name} for lo, hi, name in scoring.LEVELS],
            "breakpoints": {k: scoring.explain_breakpoints(k) for k in scoring.BREAKPOINTS},
            "categorical": {
                "flood_zone": scoring.FLOOD_ZONE_SCORES,
                "fire_history_inside_floor": scoring.FIRE_INSIDE_FLOOR,
                "thinkhazard_regional": scoring.THINKHAZARD_SCORES,
                "avalanche_zone": {"defined path (type 1)": scoring.AVALANCHE_ZONE_SCORES[1],
                                   "avalanche slopes (type 2)": scoring.AVALANCHE_ZONE_SCORES[2]},
                "avalanche_distance_m": [{"within_m": d, "score": s}
                                         for d, s in scoring.AVALANCHE_DISTANCE],
                "avalanche_reached_floor": {"within_m": scoring.AVALANCHE_REACHED_M,
                                            "floor": scoring.AVALANCHE_REACHED_FLOOR},
                "avalanche_proxy_max": scoring.AVALANCHE_PROXY_MAX,
            },
            "aggregation": "the worst hazard dominates; see backend/app/scoring.py",
        },
        "ai": ("The AI layer (Nebius Token Factory, or TypeSafe Jev) reads free-text requests, "
               "checks claims and ranks advice, always choosing among options written by code. "
               "fal.ai draws illustrations chosen by a hazard's value, reads the briefing's "
               "script and transcribes voice. Neither produces a scored number."),
        "disclaimer": (
            "This report describes the natural HAZARD of an area from public data. It is not a "
            "valuation, insurance advice or a flood study. Except for Spain's official mapping, "
            "the sources' resolution (from ~9 km to a whole province) does not resolve the "
            "scale of a plot."
        ),
    }


@app.get("/api/protection")
async def protection_catalogue(family: str | None = None):
    """The measures, partners and sources behind each hazard family."""
    cat = protection.catalogue()
    if family is None:
        return cat
    if family not in protection.FAMILIES:
        raise HTTPException(status_code=400,
                            detail=f"family must be one of {', '.join(protection.FAMILIES)}")
    measures = [m for m in cat["measures"] if m["family"] == family]
    used = {pid for m in measures for pid in m["partners"]}
    return {**cat, "families": {family: cat["families"][family]}, "measures": measures,
            "partners": {k: v for k, v in cat["partners"].items() if k in used}}


# --------------------------------------------------------------------------- #
# Autonomous engineering layer (Devin + the gate)
# --------------------------------------------------------------------------- #
@app.get("/api/autonomy/runs")
async def autonomy_runs():
    """What the reports queued and every Devin run with its gate's verdicts."""
    return {"runs": autonomy_store.runs(), "queue": autonomy_store.queue()}


@app.get("/api/autonomy/runs/{run_id}")
async def autonomy_run(run_id: str):
    run = autonomy_store.load_run(run_id)
    if run is None:
        raise HTTPException(404, "no such run")
    return run


# --------------------------------------------------------------------------- #
# Climate Data Store: always asynchronous, never on the user's path
# --------------------------------------------------------------------------- #
@app.get("/api/cds/queue")
async def cds_queue():
    """The account's CDS queue right now."""
    if not cds.credentials("cds")[1]:
        raise HTTPException(status_code=503, detail="the CDS token is missing")
    try:
        return await asyncio.to_thread(cds.account_jobs)
    except cds.CdsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/cds/status")
async def cds_status():
    return {
        "credentials": cds.credentials_status(),
        "baselines": cds_baseline.available(),
        "jobs": cds.all_jobs()[:20],
        "why_async": (
            "The CDS is a batch queue shared by the whole scientific community: a small "
            "request can take from minutes to hours. That is why it is submitted in the "
            "background and no report waits for it."
        ),
    }


@app.post("/api/cds/jobs")
async def cds_submit(
    lat: float,
    lon: float,
    year_from: int = Query(2015, ge=1940),
    year_to: int = Query(2024, ge=1940),
    variable: str = "2m_temperature",
    daily_statistic: str = "daily_maximum",
):
    """Submits a request to the CDS and returns its record straight away."""
    if not cds.credentials("cds")[1]:
        raise HTTPException(status_code=503,
                            detail="the CDS token is missing: set CDS_API_KEY or ~/.cdsapirc")
    years = list(range(year_from, min(year_to, 2024) + 1))
    request = cds.build_daily_stats_request(
        variable=variable, years=years, daily_statistic=daily_statistic,
        area=cds.bbox_around(lat, lon),
    )
    return cds.submit(cds.DATASET_DAILY_STATS, request,
                      label=f"{variable}/{daily_statistic} {year_from}-{year_to} at {lat:.2f},{lon:.2f}")


@app.get("/api/cds/jobs")
async def cds_jobs():
    return {"jobs": cds.all_jobs()}


@app.get("/api/cds/jobs/{job_id}")
async def cds_job(job_id: str):
    record = cds.job(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="job not found")
    return record


@app.get("/api/cds/preview")
async def cds_preview(lat: float, lon: float, year_from: int = 2015, year_to: int = 2024):
    """The EXACT request that would be sent, without sending it."""
    years = list(range(year_from, min(year_to, 2024) + 1))
    return {
        "cds": {
            "url": cds.credentials("cds")[0],
            "dataset": cds.DATASET_DAILY_STATS,
            "request": cds.build_daily_stats_request(
                variable="2m_temperature", years=years,
                daily_statistic="daily_maximum", area=cds.bbox_around(lat, lon),
            ),
        },
        "ewds": {
            "url": cds.credentials("ewds")[0],
            "dataset": cds.DATASET_FIRE_HISTORICAL,
            "request": cds.build_fire_request(years=years, area=cds.bbox_around(lat, lon)),
        },
    }


# --------------------------------------------------------------------------- #
# Fire-spread what-if (Deepfire ELMFIRE), on request
# --------------------------------------------------------------------------- #
class SpreadRequest(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


@app.post("/api/fire-spread")
async def fire_spread_start(body: SpreadRequest):
    """Starts (or returns) today's simulation from the nearest risky land. Poll the
    returned id with GET /api/fire-spread/{id} until the status is not QUEUED."""
    from . import fire_spread
    from .providers import deepfire

    if not deepfire.available():
        raise HTTPException(status_code=503, detail="Deepfire is not configured on the server "
                                                    "(DEEPFIRE_CLIENT_ID / DEEPFIRE_CLIENT_SECRET)")
    try:
        return await fire_spread.start(body.lat, body.lon)
    except Exception as exc:  # noqa: BLE001 - the report is fine without the what-if
        raise HTTPException(status_code=502, detail=f"Deepfire: {type(exc).__name__}: {exc}") from exc


@app.get("/api/fire-spread/{sim_id}")
async def fire_spread_status(sim_id: str, lat: float, lon: float):
    from . import fire_spread
    from .providers import deepfire

    if not deepfire.available():
        raise HTTPException(status_code=503, detail="Deepfire is not configured on the server")
    try:
        return await fire_spread.status(sim_id, lat, lon)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Deepfire: {type(exc).__name__}: {exc}") from exc


# --------------------------------------------------------------------------- #
# The web app and generated media
# --------------------------------------------------------------------------- #
class RevalidatedFiles(StaticFiles):
    """Static files the browser always revalidates (ETag), so a new version is picked up."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers.setdefault("Cache-Control", "no-cache")
        return response


# Illustration clips and briefings. Range requests are served, so a video can be
# scrubbed before it has fully downloaded.
app.mount("/media", StaticFiles(directory=config.MEDIA_DIR), name="media")

if FRONTEND_DIR.exists():
    app.mount("/assets", RevalidatedFiles(directory=FRONTEND_DIR / "assets"), name="assets")
    app.mount("/vendor", RevalidatedFiles(directory=FRONTEND_DIR / "vendor"), name="vendor")

    def _page() -> Response:
        page = FRONTEND_DIR / "index.html"
        if page.exists():
            return FileResponse(page, headers={"Cache-Control": "no-store, max-age=0"})
        return JSONResponse({"message": "Previous AI API: the web app is missing"})

    @app.get("/", include_in_schema=False)
    async def index():
        return _page()

    @app.get("/report", include_in_schema=False)
    async def report_page():
        return _page()

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return FileResponse(FRONTEND_DIR / "assets" / "img" / "favicon.svg", media_type="image/svg+xml")
