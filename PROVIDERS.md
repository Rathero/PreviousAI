# Providers

Every external service Previous AI uses, what it provides, where it is used and how it is
called. Two rules apply to all of them:

- **Every number carries its source.** Each indicator in a report has a `provenance`
  block (source, dataset, period, resolution, method, confidence, scale).
- **Only data score.** AI models, generated media, forecasts, alerts and partners never
  produce or change a score.

## At a glance

| Provider | What it gives the product | Access | Key | Used in |
|---|---|---|---|---|
| [Open-Meteo](#open-meteo) | ERA5 climate record, CMIP6 projections, 15-day ensemble forecast, terrain, town geocoding | Live HTTP, disk cache | No | Heat, rain, wildfire weather, avalanche terrain and snow, history extremes |
| [Copernicus CDS / EWDS](#copernicus-climate-data-store-and-early-warning-data-store) | ERA5 daily statistics (cross-check), fire-danger projection to 2060 | Batch jobs | `CDS_API_KEY`, `EWDS_API_KEY` | Wildfire card, ERA5 verification, `/api/cds/*` |
| [MITECO · SNCZI](#miteco--snczi-flood-zones) | Official flood zones of Spain (T10–T500, preferential flow) | Live WFS | No | Floods |
| [IGN](#ign-instituto-geográfico-nacional) | Flood water depths, CartoCiudad geocoder, PNOA aerial imagery | Live WMS / API / WMTS | No | Floods, address search, aerial view |
| [Catastro · INSPIRE](#catastro--inspire-download-service) | Every municipality of Spain and every building footprint, with year, use and dwellings | Batch ATOM + GML | No | The national analysis (`/analisis`) |
| [TALAIA](#talaia) | Who and what stands inside a polygon: schools, care homes, farms and livestock, hazardous sites, census population, replacement value | Batch REST | `TALAIA_API_KEY` | The national analysis (`/analisis`), never a report |
| [ICGC](#icgc-institut-cartogràfic-i-geològic-de-catalunya) | Sea-level rise, avalanche map and avalanche database | Live WMS + batch WFS | No | Floods, avalanches, history |
| [AGORA · University of Barcelona](#agora--university-of-barcelona) | Flood episodes per Catalan municipality, 1902–2020 | Batch | No | Floods, history |
| [Government of Catalonia](#government-of-catalonia) | Wildfire perimeters, fires by municipality, INFOCAT class, Pla Alfa level | Batch + live | No | Wildfires, history |
| [ThinkHazard! (GFDRR)](#thinkhazard-gfdrr-world-bank) | Regional flood, heat and wildfire levels, worldwide | Live JSON | No | Floods (outside the official maps), heat and wildfire contrast |
| [GDACS](#gdacs) | Ongoing flood and wildfire alerts | Live feed | No | Report alerts (never scored) |
| [NASA FIRMS](#nasa-firms) | Active fire hotspots | Live CSV | `FIRMS_MAP_KEY` (not set) | Report alerts (never scored) |
| [Nominatim (OpenStreetMap)](#nominatim-openstreetmap) | Geocoding outside Spain, region of a point | Live API, 1 request/s | No | Address search, ThinkHazard! region |
| [FireScope (INSAIT)](#firescope-insait) | AI-estimated wildfire risk at 30 m | Live range reads on Hugging Face | No | Wildfire context (never scored), fire-spread ignition |
| [Deepfire](#deepfire) | Satellite-detected fires, ELMFIRE fire-spread simulations | Live OGC API | `DEEPFIRE_CLIENT_ID` / `_SECRET` | Wildfire context, history, what-if |
| [Nebius Token Factory](#nebius-token-factory) | Typed AI decisions (Qwen3-235B) | Live API | `NEBIUS_API_KEY` | Household advice ranking, free-text requests, claim checks |
| [TypeSafe Jev](#typesafe-jev) | Typed AI decisions (fallback) | Live API | `TYPESAFE_API_KEY` | Same as Nebius, when Nebius fails |
| [fal.ai](#falai) | Illustration clips, narration, speech to text | Batch + live queue | `FAL_KEY` | Risk illustrations, video briefing, voice address input |
| [Google Street View](#google-street-view) | Street-level picture of the home | Live Static API | `GOOGLE_MAPS_API_KEY` | Picture of the home |
| [EOX Sentinel-2 cloudless](#eox-sentinel-2-cloudless) | Aerial imagery outside Spain | Live WMTS | No | Aerial fallback of the picture of the home |
| [Devin (Cognition)](#devin-cognition) | Autonomous code changes, judged by the gate | API v3 | `DEVIN_API_KEY`, `DEVIN_ORG_ID` | `backend/autonomy/`, `scripts/devin_run.py` |
| [Meteocat (open-data portal)](#meteocat-catalonias-open-data-portal) | Official weather stations | Live SoQL | No | The gate's reference answers |
| [Action plan partners](#action-plan-partners) | Products, services and insurance | Links | — | Action plan, "Buy or arrange" |

---

## Climate and weather

### Open-Meteo

Free HTTP APIs over Copernicus and ECMWF data, called directly with `httpx`
(`backend/app/providers/open_meteo.py`, `forecast.py`, `terrain.py`, `geocoding.py`).

| API | Data | How it is used |
|---|---|---|
| Archive API | **ERA5 / ERA5-Land** daily series since 1979 (max/min temperature, precipitation, wind, gusts, minimum humidity; snowfall since 1991) | The climate engine (`hazards.py`): days above 32/35/40 °C, tropical nights, heat record and trend; RX1day (wettest day of a typical year), 50/100 mm days; fire-prone weather days (30 °C, 35 % humidity, 15 km/h wind, dry week) and the 30-30-30 rule; snowfall for the avalanche proxy; hottest and wettest days for the history |
| Climate API | **CMIP6 HighResMIP** (EC-Earth3P-HR, MRI-AGCM3-2-S, MPI-ESM1-2-XR), 10 km | Change between 1995–2014 and 2036–2050 of hot days and RX1day (the delta of each model against itself, multi-model mean) |
| Ensemble API | **ECMWF AIFS ENS** (51 members, default) or IFS ENS | The next 15 days: chance of 35 °C days, tropical nights and 20 mm days compared with the usual for those dates (`outlook.py`, never scored) |
| Elevation API | **Copernicus DEM GLO-90** | 81 elevations around the point (16 rays up to 1 km) to find avalanche slopes of 28–55° |
| Geocoding API | **GeoNames** towns | Town names ("El Masnou", "Vielha") when the text is not a street address |

Open-Meteo limits by volume (per minute, hour and day): a new point costs about 1,800 of
the 5,000 hourly calls. The code only requests variables it uses, keeps each point's
series for 30 days, reuses the series of a saved point within 1 km and 50 m of height
(same ~9 km cell, and the report says so), retries the per-minute limit and falls back to
the saved series when the hourly or daily limit is hit. Free for non-commercial use;
commercial use needs an Open-Meteo API subscription.

### Copernicus Climate Data Store and Early Warning Data Store

Batch queues, never on the path of a request (`providers/cds.py`, called over its REST
API with `httpx` so error bodies stay readable).

- **ERA5 daily statistics** (`derived-era5-single-levels-daily-statistics`), downloaded
  with `scripts/cds_download.py` and aggregated by `scripts/cds_build_baseline.py` into
  `data/baseline/*.json`. Reports compare their Open-Meteo ERA5-Land figures with the
  native ERA5 over the same years (`report.verification`).
- **Fire danger indicators for Europe** (`sis-tourism-fire-danger-indicators`, EURO-CORDEX
  FWI), downloaded and built by `scripts/cds_hazards.py` into
  `data/cds/fire_danger_projections.json.gz`: days with FWI > 30 in 1981–2005 against
  2041–2060 (RCP4.5 and RCP8.5), shown on the wildfire card without changing its score.
- **CEMS historical FWI** (EWDS, separate account): the request is built and exposed by
  `/api/cds/preview`; no report uses it.
- `/api/cds/jobs`, `/api/cds/queue`, `/api/cds/status` submit and watch jobs in the
  background. `scripts/cds_collect.py` collects finished jobs later.

Keys: `CDS_API_KEY` (set), `EWDS_API_KEY` (empty). Each dataset's licence must be accepted
on its web page.

---

## Official maps and records

### TALAIA

`talaia.up.railway.app` (`providers/talaia.py`), called in batch by
`analysis_build.py --only assets`. Give it a polygon and it returns everything of value
inside it, with capacity, a replacement valuation and the resident population of the
ground.

It exists here because the cadastre stops short. Catastro says a building is there, when
it was raised, what it is broadly used for and how many dwellings it holds. It does not
say that the building is a care home with forty beds, that a thousand people live on that
block, or that the fuel depot two streets away is inside the same flood zone. This does.

| What it adds | Where it shows |
|---|---|
| Resident population of the flooded area (INE 1 km census grid, area-weighted) | The `People in a flood zone` column of the ranking |
| Schools, hospitals, care homes, campsites, named, with beds/students/capacity | "Who and what is inside", per municipality |
| Hazardous sites, response assets, livestock units | The same section |
| Replacement valuation | The same section, marked as modelled |

**It answers about an AREA, which is why it is never in a report.** A resident does not
act differently because two schools stand down the road; a town hall planning an
evacuation acts on nothing else. That is the whole line between the two products, and it
is the reason this integration was declined once for the report and taken for
`/analisis`.

**It never scores.** Like the fire detections and the alerts, it is context. A
municipality's flood score comes from the official SNCZI zones and the cadastral
buildings standing in them; nothing here moves it.

Two things about how it is asked:

- **The area sent is the box around the exposed buildings**, not the municipality. The
  free tier allows 250 km² per call and Murcia's bounding box is over a thousand, nine
  tenths of it country nobody will evacuate. The box around the buildings that stand in
  a flood zone is inside the limit and is the only part anyone acts on. When even that
  is over the limit the municipality records the refusal and its area.
- **Each returned asset is placed in a flood zone by our own test**, the same
  `app/spatial.py` index the buildings went through, rebuilt from the cached SNCZI
  polygons. So "three schools in the preferential flow zone" is the same statement, made
  the same way, as "1,213 buildings in it".

Limits worth repeating wherever the numbers are shown, and which the page does show:
population is the census grid apportioned to an area, not a count of who is inside those
buildings; the valuation is modelled from class defaults, not surveyed; and capacity is
what a place holds when full, not who is in it tonight.

Key: `TALAIA_API_KEY`, self-service (`POST /v1/signup`, confirmed by an emailed link;
the key is shown on the confirmation page, not mailed). Free tier: 60 requests a minute,
1,000 a day, 250 km² and 2,000 assets per call. Without a key `--only assets` says so and
builds nothing, and every other block of the analysis is unaffected.

---

### Catastro · INSPIRE download service

The Directorate General for Cadastre's INSPIRE ATOM feeds, downloaded in batch by
`backend/scripts/analysis_build.py`. Nothing here is on the path of a request.

| Feed | Data | How it is used |
|---|---|---|
| `CadastralParcels/{PP}/ES.SDGC.CP.atom_{PP}.xml` | One entry per municipality with its name and bounding box | The universe of the ranking: **7,597** municipalities, and the centre each climate cell is read at |
| `buildings/{PP}/ES.SDGC.bu.atom_{PP}.xml` | The download link for each municipality's buildings | Finding the right zip |
| `Buildings/{PP}/{code}-{NAME}/A.ES.SDGC.BU.{code}.zip` | Every building footprint of one town (about 1.5 MB), with its cadastral reference, year of construction, use, number of dwellings, number of units, floor area and condition | The exposure: each footprint's centre tested against the SNCZI flood zones |

Two things to know about its codes and its coverage:

- **It is not the INE code.** The cadastre agrees with INE for most towns but gives the
  provincial capitals a 900: Barcelona is `08900`, not `08019`. Joining the Catalan
  layers on the code alone silently loses 120 municipalities, the four capitals among
  them, so they are matched on the ground instead - the pair of bounding boxes that
  overlap best is the pair - and both codes are kept on the row.
- **It is the cadastre of common regime.** Alava, Gipuzkoa, Bizkaia and Navarre keep
  their own and publish nothing here, so their municipalities are absent from the
  ranking, which says so rather than showing an empty province.

The feeds declare ISO-8859-1 and mean it; read as UTF-8 they turn "Almeria" into a
replacement character and every match made on a name fails.

Licence: free reuse of the cadastral cartography, with attribution. It publishes
buildings, not the people in them: no owner or occupant data is downloaded or stored.

---

### MITECO · SNCZI flood zones

Spain's National Flood Zone Mapping System, WFS at `gis.miteco.gob.es/geoserver/agua`
(`providers/miteco.py`). Five layers per point, queried in parallel with attributes only:
preferential flow zone and the 10, 50, 100 and 500-year flood zones. The worst zone
containing the point scores (92, 88, 78, 66, 42) on the **Floods** risk; the river and
study name go into the headline. Only complete answers are cached. Free use with
attribution to MITECO.

The national analysis calls the same WFS differently: one `BBOX` query per municipality
per layer, which returns each feature's **whole** geometry (a river that crosses half a
province is several megabytes). Those polygons are indexed once per municipality by
`app/spatial.py` and every cadastral footprint is tested against that index, so an answer
for thousands of buildings costs five requests instead of thousands. The result was
checked against this per-point endpoint on a sample of Paiporta buildings and agreed on
all of them.

### IGN (Instituto Geográfico Nacional)

- **SNCZI water depths**, INSPIRE WMS (`providers/ign_flood.py`): river depths for the
  10, 100 and 500-year floods and coastal flood zones. A positive depth confirms flooding
  and picks the flood illustration (six depth bands); the home's floor is compared with
  it ("the mapped water would stay below your 4th floor"). No value never means "safe".
- **CartoCiudad** geocoder (`providers/cartociudad.py`): Spanish addresses to the building
  entrance, with cadastral reference and postal code; its `candidates` endpoint feeds the
  address suggestions while typing (only those in the town typed after a comma). Street
  types come in Spanish; in Catalonia they are shown as on the street signs ("Carrer",
  "Passeig", "Avinguda").
- **PNOA orthophoto** and **IGN base map** WMTS (`mapping.py`; the PDF report stitches its
  aerial picture from the same tiles, credited): the aerial view of the
  home when Street View has no panorama, in Spain.

Licence: CC BY 4.0 (IGN).

### ICGC (Institut Cartogràfic i Geològic de Catalunya)

- **Permanent flooding from sea-level rise**, WMS (`providers/icgc.py`): the smallest of
  44 modelled rises (7.7 to 84.8 cm) that floods the point, found by bisection (~7
  requests). It scores on the Floods risk.
- **Avalanche map 1:25,000 and avalanche database (BDAC)**, GeoServer WFS, downloaded by
  `scripts/catalonia_build.py --only avalanches` into `data/catalonia/avalanches.json.gz`
  (17,811 zones, 6,468 observed avalanches 1971–2024, 739 recalled in surveys, the 7
  snow-climate zones of the daily bulletin) and queried locally
  (`catalonia_store.avalanches_near`, `hazards_avalanche.py`). Inside a mapped path scores
  90, avalanche slopes 75, distance and observed avalanches set floors. Observed
  avalanches appear in the history.

Licence: public access (ICGC).

### AGORA · University of Barcelona

228 flood episodes in Catalonia, 1902–2020, linked to 947 municipalities, with victims and
losses (ArcGIS FeatureServer, downloaded by `scripts/catalonia_build.py`). The number of
episodes that affected the municipality scores on the Floods risk (capped at 60: it is a
municipal figure), and the latest episodes appear in the history. The service states no
licence: non-academic use needs the University of Barcelona's permission.

### Government of Catalonia

| Dataset | Access | Use |
|---|---|---|
| Wildfire perimeters 1986–2024 (Department of Agriculture) | Yearly shapefiles, batch (`catalonia_build.py`, needs `pyshp`) | Fires within 5 km score the **Wildfires** risk; inside a perimeter sets a floor of 60; the nearest fires appear in the history |
| Wildfires by municipality 2011–today (Socrata) | Batch | Municipal context on the wildfire card |
| INFOCAT municipal danger and vulnerability (Civil Protection, Socrata) | Live, whole table cached 30 days (`providers/gencat_fire.py`) | Official contrast on the wildfire card, never scored |
| Pla Alfa daily fire-danger level (Agents Rurals, ArcGIS) | Live, 30-minute cache | Today's level, next to the alerts, never scored |

Catalan labels are translated to English at the edge. Licence: Llicència oberta d'ús
d'informació – Catalunya.

---

## Regional and global context

### ThinkHazard! (GFDRR, World Bank)

Hazard levels by province or region, worldwide (`providers/thinkhazard.py`). The region of
a point comes from Nominatim; the levels for river, urban and coastal flooding give a
regional flood card (never above 70, never at country level), and the heat and wildfire
levels sit next to the ERA5 cards as a contrast.

### GDACS

The United Nations and European Commission alert feed (`providers/gdacs.py`), cached 30
minutes. Current flood alerts within 300 km and wildfire alerts within 60 km go into the
report's `alerts`; they never score.

### NASA FIRMS

VIIRS active-fire hotspots within 50 km in the last two days (`providers/firms.py`). Only
queried with `FIRMS_MAP_KEY`, which is not set.

### Nominatim (OpenStreetMap)

Forward geocoding outside Spain and reverse geocoding for the ThinkHazard! region
(`providers/nominatim.py`), at most one request per second through a process-wide lock,
everything cached. Its usage policy forbids autocomplete, so suggestions while typing only
come from CartoCiudad.

---

## Wildfire intelligence

### FireScope (INSAIT)

The FireScope 2026 wildfire risk map (CVPR 2026, CC BY 4.0): a 12 GB GeoTIFF for Europe
on Hugging Face, read tile by tile with HTTP range requests and a pure-Python LZW decoder
(`providers/firescope.py`, pinned revision). It gives the AI-estimated risk at the point,
the highest risk within 1 km and the nearest risky land within 3 km: context on the
wildfire card that never scores, and the ignition point of the fire-spread what-if.

### Deepfire

Satellite fire detections (VIIRS, MODIS, MTG, Sentinel-3, Landsat) grouped into fires, and
the ELMFIRE fire-spread model (`providers/deepfire.py`, `fire_spread.py`):

- fires burning now within 50 km (report alerts, 10-minute cache);
- fires detected within 10 km since January 2025 (wildfire context and the history of the
  place, 6-hour cache);
- `POST /api/fire-spread`: a 6-hour simulation from the nearest risky land with today's
  weather, measured against the home. A what-if, never scored.

Credentials `DEEPFIRE_CLIENT_ID` / `DEEPFIRE_CLIENT_SECRET` (set) are exchanged for a
bearer token once per process.

---

## AI

The AI answers **typed questions** only: a choice among options written by code, or the
probability that a statement is true. It never writes the report and never produces a
scored number (`providers/ai.py`). Answers are cached per request, and every call reports
its tokens, cost and latency.

### Nebius Token Factory

The default service (`providers/nebius.py`), model `Qwen/Qwen3-235B-A22B-Instruct-2507`
pinned. All questions of a call go in one chat completion whose reply is forced by a JSON
schema to our options; probabilities are read from the token log-probabilities, not asked
of the model. Used for:

- **Household advice** (`advice.py`): when the person says who lives there (the icon at the
  top right of the report), the hand-written advice is ranked for those people and shown
  first in the emergency plan.
- **Free-text requests** (`interpret.py`, `/api/risk?ask=`, `/api/interpret`): place, dates
  and people read from a sentence; the calendar maths are done in code.
- **Claim checks** (`claims.py`, `/api/check`): each sentence of a listing, blog or chatbot
  answer judged against the report as supported, contradicted or not covered.

### TypeSafe Jev

`jev-1.13.0` (`providers/jev.py`) answers the same questions in the same shape and takes
over when Nebius fails; `AI_PROVIDER=typesafe` makes it the default.

---

## Generated media

### fal.ai

Used through the official `fal-client` package (`providers/fal.py`). It illustrates,
narrates and listens; it never touches a number.

| Model | Use |
|---|---|
| `fal-ai/nano-banana-2` | Stills of the illustration library (text to image) |
| `fal-ai/nano-banana-2/edit` | The six flood depths as edits of one street |
| `openai/gpt-image-2/edit` | The two deepest flood bands (2 m and 3 m of water) |
| `fal-ai/kling-video/v2.5-turbo/pro/image-to-video` | 5-second clips from the stills |
| `fal-ai/elevenlabs/tts/eleven-v3` (voice "Brian") | Narration of the video briefing |
| `fal-ai/elevenlabs/speech-to-text/scribe-v2` | The microphone in the address box |

- **Illustration library**: 19 clips generated once by `scripts/fal_media.py` and kept in
  `data/media/illustrations` with a manifest of models, prompts and seeds. In a report, the
  data pick the clip: the mapped water depth for floods, the level for the other risks. In
  the app, picking a risk turns the picture of the home into its clip, and "What it could
  look like" opens it large, labelled "AI illustration · not this place" with the value
  that chose it.
- **Video briefing**: the "Video briefing" button next to the picture. The script is written
  by code from the report, word for word (`briefing.py`); fal.ai only reads it aloud;
  ffmpeg (bundled by `imageio-ffmpeg`) assembles the scenes over the illustrations. Cached
  by content.
- **Voice input**: `/api/transcribe` uploads the recording to fal's CDN with a one-hour
  expiry and returns the text into the address box, where the person checks it.

---

## Imagery of the home

### Google Street View

Street View Static API (`providers/streetview.py`, `/api/streetview`). The free metadata
call finds the nearest outdoor panorama within 60 m and its date; the image is requested
from that panorama turned towards the address, proxied by the backend so the key never
reaches the browser, and never stored (only the panorama id, position and date are
cached). The PDF report embeds the same image, credited "© Google", drawn on request and
not kept on the server. Needs `GOOGLE_MAPS_API_KEY` with the Street View Static API
enabled. Without a key or a panorama, the app shows the aerial view.

### EOX Sentinel-2 cloudless

Sentinel-2 cloudless 2016 WMTS (CC BY 4.0): the aerial view outside Spain, where PNOA does
not reach. In Spain the aerial view is IGN's PNOA orthophoto.

---

## Engineering automation

### Devin (Cognition)

API v3 (`providers/devin.py`, `scripts/devin_run.py`). When a report finds a number that
rests on one source (`evidence.py`: every heat figure in Catalonia comes from ERA5), it
queues a task. `devin_run.py` gives Devin the task's specification
(`backend/autonomy/tasks/station_witness/SPEC.md`), Devin writes code on a branch of
`DEVIN_REPO`, and the gate (`backend/autonomy/gate.py`) judges each push in a separate
checkout with 16 checks against references Devin did not write. Failures go back to the
session; runs are recorded in `data/autonomy/runs/` and served at `/api/autonomy/runs`.
Budget per run: 20 ACUs by default.

### Meteocat (Catalonia's open-data portal)

Official automatic weather stations (XEMA) through the portal's SoQL API. The gate's
oracle (`backend/autonomy/tasks/station_witness/oracle.py`) asks the portal for its own
server-side aggregates to check Devin's station witness.

---

## Action plan partners

The Action plan (`backend/app/action_plan.py`) links products, services and insurance in
its "Buy or arrange" and "After" steps: **Leroy Merlin**, **Verisure**, **Catalana
Occidente**, **Mapfre**, **Xiaomi**, **Applus+**, **Bureau Veritas**, **Cortizo**,
**Ortovox**, **Mitsubishi Electric** and **ISOVER (Saint-Gobain)**, plus the **My112** app
of the Spanish emergency services. Partners never change a score or which plans appear:
the plans shown are those of the risks present at the address, worst first.

Each thing to buy also carries one or two real products (`backend/app/products.py`): the
direct link to the product page, the store's own photo (loaded from the store's image
server without a referrer) and the price that page showed on the day it was checked,
which the plan states. The stores are **Leroy Merlin**, **Xiaomi**, **Shelly**,
**Bauhaus**, **Decathlon** and **Midland**; no key is needed. Links and prices change:
check them again, and update `CHECKED`, before relying on them. Products never decide
which steps appear.

The wider measure catalogue with costs, standards and official programmes (MITECO grants,
Consorcio de Compensación de Seguros, ICGC and AEMET bulletins, climate shelters...) is
served by `/api/protection` and carried by every full report (`report.protection`).

---

## Environment variables

| Variable | Provider | State |
|---|---|---|
| `CDS_API_KEY` | Copernicus CDS | set |
| `EWDS_API_KEY` | Copernicus EWDS | empty |
| `NEBIUS_API_KEY`, `NEBIUS_MODEL` | Nebius Token Factory | set, default model |
| `TYPESAFE_API_KEY`, `JEV_MODEL` | TypeSafe Jev | set, `jev-1.13.0` |
| `AI_PROVIDER` | Nebius or TypeSafe first | empty (Nebius first) |
| `FAL_KEY` | fal.ai | set |
| `GOOGLE_MAPS_API_KEY` | Google Street View | set |
| `DEEPFIRE_CLIENT_ID`, `DEEPFIRE_CLIENT_SECRET` | Deepfire | set |
| `FIRMS_MAP_KEY` | NASA FIRMS | empty |
| `DEVIN_API_KEY`, `DEVIN_ORG_ID`, `DEVIN_REPO` | Devin | set |
| `FORECAST_PROVIDER` | ECMWF AIFS or IFS | `ecmwf-aifs` |
| `ERA5_ARCHIVE_START`, `OFFLINE_FALLBACK` | Open-Meteo archive | `1979-01-01`, `1` |
