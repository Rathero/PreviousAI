# Previous AI

**Today's awareness. Protect what matters.**

Give Previous AI the address of a home and it shows the natural risks around it —
**fire, flooding, heat waves and avalanches** — what has already happened nearby, and
an action plan to prepare. Every figure comes from public scientific or official data and
carries its source; AI and generated media help read the report but never produce a
score.

- **One sentence** that sums the home up ("Two things are worth preparing for at this
  home"), next to a picture of it (Google Street View; aerial imagery when there is no
  panorama) and a narrated **video briefing** of the report.
- **Four risks**, each as wide as its level (0–100), with one fact. Picking one turns the page to
  its colours, shows what already happened near the home (flood episodes, wildfires, fires
  seen by satellite, avalanches, the wettest and hottest days on record), what it means for
  this home (a 4th-floor flat is not a ground floor) and its first steps; the picture
  becomes an AI illustration of what that risk could look like.
- **Action plan**: a basic emergency plan and, for each risk worth preparing for, what to
  do before, what to buy or arrange (with partners), what to do during and after. What to
  buy comes with real products: the store's photo, the price and a direct link to buy it.
  Tick items off as you go; tell us who lives there and the plan puts first what matters
  for them.
- **What this home needs** (`/shop`): the plan's shopping steps as a kit of four real
  products (taking turns between the risks worth preparing for), its total, the free steps
  that help most and the service a partner offers for the worst risk; mark what you
  already have and the kit shrinks.
- **PDF report** to keep and share: the pictures of the home, every value behind each
  score with its period and source, what already happened, the climate to 2050, the full
  action plan with its partners and the sources. On a phone it opens the share sheet.
- **Today / 2050**: the same four risks around 2050, as the change in what drives each one
  (days of high fire danger, rain on the wettest day, hot days and tropical nights) from
  the climate projections, carried onto today's record. Scores, official maps and past
  events describe today and are not projected; the 2050 view says so instead of inventing
  a score.
- **Public money**: grants, tax deductions and public cover that can pay for part of the
  plan (checked against the official pages, with amounts, deadlines and who applies: the
  household, the owners' association, the town hall, or anyone after damage), and what
  does not exist here, said as plainly.

- **The same thing backwards** (`/analisis`): every municipality of Spain ranked against
  the same data, and inside the ones already crossed with the official flood maps, the
  buildings that stand in them — how many dwellings, how old — each one a link to its own
  report. For whoever has to reach the homes rather than live in one.

The app is public: no sign-up and no login.

## Run it

Requirements: Python 3.11 or newer.

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --port 8000
```

Open http://localhost:8000. Keys go in `.env` (see `.env.example` and
[PROVIDERS.md](PROVIDERS.md)); without them the app still works with the open data
sources, and each optional feature switches itself off.

On macOS or Linux use `.venv/bin/python` instead of `.venv/Scripts/python.exe`.

## How it works

```
frontend/            The web app: three views, no build step (ES modules, Leaflet)
backend/app/         FastAPI API and the report engine
  report.py          Orchestrates a report: location, sources in parallel, cards, extras
  hazards*.py        Climate cards (ERA5), official cards (MITECO, IGN, ICGC, AGORA,
                     Government of Catalonia), avalanches, regional levels
  scoring.py         Every breakpoint from a physical value to a 0-100 score
  indicators.py      The provenance contract
  history.py         What already happened near the home
  action_plan.py     The action plan and its partners
  products.py        The real products the plan proposes: store, link, photo, price
  dwelling.py        House or flat, and the floor: who acts, what the water means
  protection.py      The measure catalogue (costs, standards, official programmes)
  grants.py          Public money for the home: the checked catalogue and who applies
  ahead.py           The 2050 view: each risk's drivers from the climate projections
  media.py           The fal.ai illustration library, picked by each card's value
  briefing.py        The narrated video briefing (script written by code)
  pdf_report.py      The report as a PDF (ReportLab), with the pictures of the home
  view.py            The report as the web app shows it (headline, facts, stories)
  simulations.py     The four hazards drawn by AI on a photo of a demo home's street
  demo.py            The demo homes, answered from packs built ahead of time
  analysis.py        The report backwards: every municipality ranked, then its buildings
  spatial.py         Point-in-polygon for thousands of points against one big polygon set
  providers/         One module per external service
backend/scripts/     Batch pipelines: cache warm-up, Catalan layers, Copernicus CDS,
                     fal.ai library, Devin runs
backend/autonomy/    The gate that judges Devin's code
data/                Batch layers, illustration library and the runtime cache
```

Two speeds keep the app fast: live APIs with a disk cache for everything a request needs
(Open-Meteo, official WMS/WFS, AI, Street View), and batch layers built offline for what
changes little (Catalan wildfire perimeters and avalanche map, flood episodes, Copernicus
projections). The Climate Data Store is a job queue that can take hours, so it is never
on the path of a request.

### The demo home

A demonstration has a third speed: nothing at all. Most of a report is cached for a
month, but alerts expire in half an hour and the forecast in three, and when one of them
moves the report moves with it — a different briefing to encode, a street simulation
drawn for a level the card no longer shows. So `backend/scripts/demo_build.py` builds
the whole thing once for the addresses pinned in `demo.py` (today, **Avinguda Garona 10,
Vielha**) and files it in `data/demo`: the report, the PDF, the narrated briefing, the
point the address resolves to, and the address itself as the first suggestion while it
is typed. `/api/report`, `/api/report/pdf`, `/api/locate` and `/api/briefing` then answer
from those files in milliseconds, and the page fetches the briefing before anyone presses
the button.

A pack is an ordinary report, built by the same code from the same sources, and it
carries the moment it was built — so build it the morning of the demonstration: a pack
from last week describes last week's alerts. `--whole` covers the detours too (the same
home as a flat on the fourth floor, the plan re-ranked for children), `--check` says what
is ready and how old it is, and `PREVIOUS_DEMO=0` puts every pinned address back on the
live path.

Google's terms do not allow the street-level picture of the home to be stored, so that
one picture, and the map tiles, are still fetched while the page opens.

### Which homes this threatens (`/analisis`)

The report asks one address what threatens it. `/analisis` asks the country the opposite
question — which homes are threatened — because a town hall, a comarca or an emergency
service cannot type eight thousand addresses, and the households who most need a report
are the ones who will never go looking for one. It is the same engine and the same
scales at two other units:

- **Municipality.** All **7,597** of the cadastre of common regime, ranked. What can be
  known for every town at once: the official EURO-CORDEX fire-danger grid at its centre,
  and in Catalonia the flood episodes, burnt area and avalanche zones already on disk for
  the reports.
- **Building.** For the municipalities the batch has been pointed at, every cadastral
  footprint crossed with the five official SNCZI flood zones — the same question
  `providers/miteco.py` asks for one point, asked once per building. It answers with the
  count of exposed buildings, the dwellings inside them and how many were raised before
  1980, and every row links to that building's own report.
- **Who is inside.** The cadastre says a building is there and how many dwellings it
  holds; it does not say it is a care home with forty beds, or that a thousand people
  live on that block. [TALAIA](PROVIDERS.md#talaia) does, for the area around the
  exposed buildings: resident population, named schools and care homes with their
  capacity, hazardous sites, livestock and a modelled replacement value — each one put
  in a flood zone by the same test the buildings went through. It needs
  `TALAIA_API_KEY`; without it the analysis is built exactly as before and says the
  inventory was not asked for.

```bash
python backend/scripts/analysis_build.py --only universe    # who exists, from the cadastre
python backend/scripts/analysis_build.py --only climate     # the fire-danger grid, offline
python backend/scripts/analysis_build.py --only catalonia   # the Catalan layers
python backend/scripts/analysis_build.py --only exposure --municipality 46188
python backend/scripts/analysis_build.py --only assets      # who is inside (TALAIA)
python backend/scripts/analysis_build.py --only ranking     # assemble
```

Nothing is computed on the request path: the build writes `data/analysis/` and the API
only reads it, so two people opening the same ranking see the same list. What cannot be
known for every town says so instead of scoring low — heat is filled in only where the
rate-limited climate record allowed it, the flood column exists only where the buildings
have been counted, and the Basque provinces and Navarre are absent because they keep
their own cadastre.

Two scales are its own, and they are in `scoring.py` with the rest: `fire_weather_fwi`
(days a year with FWI > 30, a laxer threshold than the report's 30-30-30 rule, so a
separate scale) and the municipal flood reading, where the worst zone sets a ceiling and
the share of the town standing in it decides how much of that ceiling the town gets.

It ranks buildings and places, never people. The unit is a cadastral footprint and what
the cadastre publishes about it — year, use, dwellings, floor area — plus, where the
inventory has been asked for, the institutions on that ground and the census population
of it. Census population is a figure for an area, not for a household; no resident,
owner or occupant data is downloaded, stored or shown.

### Scores

Each risk is the worst of its cards, 0–100: very low < 20 ≤ low < 40 ≤ moderate < 60 ≤
high < 80 ≤ very high. The breakpoints are published in `backend/app/scoring.py` and at
`/api/sources`. The home (type and floor) and the household never change a score: the
hazard belongs to the place.

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/report?address=&home=house\|apartment&floor=&who=` | The web app's report |
| `GET /api/report/pdf?address=&home=&floor=&who=` | The same report as a PDF, drawn on request |
| `GET /api/analysis/ranking?hazard=&province=&q=&exposed=&limit=&offset=` | Every municipality, ranked |
| `GET /api/analysis/municipality/{code}` | One municipality: its scores, their sources, its exposure |
| `GET /api/analysis/buildings/{code}?zone=` | Its buildings inside an official flood zone |
| `GET /api/risk?q=` (or `ask=`, or `lat=&lon=`) | The full report, every indicator and its provenance, map layers, forecast |
| `GET /api/suggest?q=` | Address suggestions while typing (Spain) |
| `GET /api/locate?q=` | The point an address resolves to |
| `GET /api/streetview?lat=&lon=` | Street View availability and image |
| `POST /api/briefing`, `GET /api/briefing/{id}` | Narrated video briefing |
| `POST /api/transcribe` | Voice to text for the address box |
| `POST /api/check` | Fact-check a text about the place against its report |
| `GET /api/interpret?text=` | What the AI reads from a free-text request |
| `GET /api/compare?q=A;B;C` | Compare up to four places |
| `POST /api/fire-spread` | Fire-spread what-if from the nearest risky land (Deepfire) |
| `GET /api/protection` | The measure catalogue |
| `GET /api/sources` | Sources, scoring scales and disclaimer |
| `GET /api/illustrations` | The illustration library and how it was made |
| `GET /api/autonomy/runs` | Devin runs and the gate's verdicts |
| `GET /api/cds/*` | Copernicus CDS jobs (batch) |
| `GET /api/health` | Status of every provider |

Interactive documentation: http://localhost:8000/docs.

## Batch jobs

```bash
# Warm the cache for a list of homes (mind Open-Meteo's hourly limit)
.venv/Scripts/python.exe backend/scripts/prewarm.py --places "Carrer Sarriulera 10, Vielha"

# The demo homes: report, PDF and narrated briefing built ahead of the demonstration
.venv/Scripts/python.exe backend/scripts/demo_build.py --whole
.venv/Scripts/python.exe backend/scripts/demo_build.py --check

# Rebuild the Catalan layers (needs backend/requirements-batch.txt)
.venv/Scripts/python.exe backend/scripts/catalonia_build.py

# Copernicus: ERA5 cross-check baseline and the fire-danger projection
.venv/Scripts/python.exe backend/scripts/cds_download.py --preset valencia
.venv/Scripts/python.exe backend/scripts/cds_build_baseline.py --name valencia --glob "valencia_*.nc"
.venv/Scripts/python.exe backend/scripts/cds_hazards.py download
.venv/Scripts/python.exe backend/scripts/cds_hazards.py build

# fal.ai illustration library (prices and prompts first)
.venv/Scripts/python.exe backend/scripts/fal_media.py --dry-run

# Devin: take the task the reports queued, or print its prompt
.venv/Scripts/python.exe backend/scripts/devin_run.py --from-queue
.venv/Scripts/python.exe backend/scripts/devin_run.py --task station-witness --dry-run
```

## What the report does not say

- It describes the natural **hazard** of a place from public data. It is not a
  valuation, insurance advice or a flood study.
- Outside the official maps (Spain's SNCZI flood zones, Catalonia's records and avalanche
  map), sources describe a grid cell (~9 km) or a region, not the plot, and the report
  says so on each value.
- Being outside a mapped flood zone does not mean being safe: only the studied stretches
  are mapped.
- Forecasts, alerts, satellite fires, AI estimates and simulations are shown as context
  and never change a score.
