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
- **Four risks**, each with its level (0–100) and one fact. Picking one turns the page to
  its colours, shows what already happened near the home (flood episodes, wildfires, fires
  seen by satellite, avalanches, the wettest and hottest days on record), what it means for
  this home (a 4th-floor flat is not a ground floor) and its first steps; the picture
  becomes an AI illustration of what that risk could look like.
- **Action plan**: a basic emergency plan and, for each risk worth preparing for, what to
  do before, what to buy or arrange (with partners), what to do during and after. What to
  buy comes with real products: the store's photo, the price and a direct link to buy it.
  Tick items off as you go; tell us who lives there and the plan puts first what matters
  for them.
- **PDF report** to keep and share: the pictures of the home, every value behind each
  score with its period and source, what already happened, the climate to 2050, the full
  action plan with its partners and the sources. On a phone it opens the share sheet.

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
frontend/            The web app: two views, no build step (ES modules, Leaflet)
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
  media.py           The fal.ai illustration library, picked by each card's value
  briefing.py        The narrated video briefing (script written by code)
  pdf_report.py      The report as a PDF (ReportLab), with the pictures of the home
  view.py            The report as the web app shows it (headline, facts, stories)
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
