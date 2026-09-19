# Task `station-witness`: bring the thermometer

## Why

The extreme-heat numbers of a report in Catalonia (days above 32/35/40 °C, tropical
nights, the heat record) all come from one model, ERA5, and the only cross-check the
report shows compares ERA5 with ERA5 (the Climate Data Store copy). Add an independent
witness: **Meteocat's official automatic weather stations (XEMA)**.

The witness never changes a score, a level, a card or their order. It sits beside the
model so people can see where the two agree and where they do not (a valley
thermometer and a 9 km model cell often disagree, and the report must say so).

## What to build

1. `backend/app/providers/meteocat.py` exposing

   ```python
   async def station_witness(lat: float, lon: float, elevation_m: float | None) -> dict | None
   ```

2. The wiring in `backend/app/report.py` described under "Report wiring".

## Source

Catalonia's open-data portal (Socrata). Base URL: `config.METEOCAT_URL`.

- Station metadata: dataset `yqwd-vj5e` (`codi_estacio`, `nom_estacio`, `latitud`,
  `longitud`, `altitud`, `codi_estat_ema`: `"2"` means operational).
- Daily data: dataset `7bvh-jvq2` (`codi_estacio`, `data_lectura`, `codi_variable`,
  `valor`, `estat`). Variable `1001` is the daily maximum temperature (Tx) and `1002`
  the daily minimum (Tn), in °C.
- SoQL reference: https://dev.socrata.com/docs/queries/ . The portal returns **1,000
  rows** unless you pass `$limit`. `valor` is text.

## Rules (the gate enforces exactly these, nothing else)

- **R1 · Valid readings.** Only Tx (`1001`) and Tn (`1002`) readings whose `estat` is
  exactly `"Representatiu"` count. `data_lectura` is the local calendar day.
- **R2 · Candidates.** Stations within 15 km of the point (great-circle distance, Earth
  radius 6,371 km) whose `altitud` is within ±150 m of `elevation_m`. With
  `elevation_m` None, skip the height condition.
- **R3 · Complete year.** A calendar year with ≥ 330 valid Tx readings **and** ≥ 330
  valid Tn readings.
- **R4 · Period.** The longest run of consecutive complete years that ends at the last
  complete calendar year (`today.year - 1`), capped at 30 years. A candidate with
  fewer than 10 such years does not qualify.
- **R5 · Successor splice.** A station that is not operational (`codi_estat_ema` is
  not `"2"`) may be continued by an operational station that is ≤ 1 km from it, has
  an `altitud` within ±60 m of it and itself satisfies R2. Let S be the successor's
  first day with a valid Tx or Tn reading. The spliced series takes every day ≥ S from
  the successor and every day < S from the predecessor. The splice qualifies only if,
  over the overlap (days on which **both** stations have a valid Tx **and** a valid
  Tn), there are ≥ 180 days and the mean differences (successor − predecessor) of Tx
  and of Tn are both within ±1.0 °C. A splice is judged on its combined series with
  R3 and R4.
- **R6 · Choice.** Among the qualifying candidates (single stations and splices),
  take the one whose most recent station (the station itself, or the successor) is
  nearest to the point; on a tie, the longer period. None qualifies → return `None`.
- **R7 · Metrics.** For each year of the period: `valid_tx_days`, `valid_tn_days`,
  `hot_days_32` / `hot_days_35` / `hot_days_40` = valid Tx ≥ 32 / 35 / 40,
  `tropical_nights` = valid Tn ≥ 20, `tmax_max` = the highest valid Tx. Observed rates
  over the whole period: Tx metrics = Σcount / Σvalid_tx_days × 365.25, tropical nights
  = Σcount / Σvalid_tn_days × 365.25, rounded to 2 decimals; `heat_record` = the
  highest `tmax_max`.
- **R8 · Daily series.** `daily` lists every date of the period that has a valid Tx or
  Tn in the (spliced) series, ascending, as ISO dates, with `null` where that
  variable has no valid reading.

## Return value

Illustrative values only (a made-up station), not the answer for any real town:

```jsonc
{
  "available": true,
  "stations": [            // one station, or predecessor then successor for a splice
    {"code": "AB", "name": "Example station", "latitude": 41.0, "longitude": 1.0,
     "elevation_m": 120.0, "distance_km": 3.21, "operational": true,
     "used_from": "2001-01-01", "used_to": "2025-12-31"}
  ],
  "splice": null,          // or {"from": "AA", "to": "AB", "overlap_days": 250,
                           //     "tmax_mean_diff": 0.12, "tmin_mean_diff": -0.3}
  "period": "2001-2025",
  "years": [{"year": 2001, "valid_tx_days": 365, "valid_tn_days": 364,
             "hot_days_32": 4, "hot_days_35": 1, "hot_days_40": 0,
             "tropical_nights": 12, "tmax_max": 35.2}],
  "observed": {"hot_days_32": 3.1, "hot_days_35": 0.52, "hot_days_40": 0.0,
               "tropical_nights": 14.27, "heat_record": 39.0},
  "daily": {"dates": ["2001-01-01"], "tmax": [12.5], "tmin": [4.0]},
  "provenance": {"source": "...", "dataset": "...", "period": "2001-2025",
                 "resolution": "...", "method": "...", "confidence": "high",
                 "url": "https://...", "scale": "...", "scale_kind": "point"},
  "limitation": "What this does NOT say ..."
}
```

`used_from` / `used_to` are the first and last dates of `daily` that come from each
station. Distances in km, rounded to 2 decimals.

## Report wiring

- Call the witness for points inside Catalonia (the report has a Catalan
  `municipality`), with the elevation the report shows in `location.elevation_m`.
- Put the result in `report["witness"]`: the witness **without** `daily`, plus
  - `"model_period"`: equal to `period`;
  - `"comparisons"`: one entry for each of `hot_days_35`, `hot_days_32`, `hot_days_40`,
    `tropical_nights`, `heat_record`:
    `{"key", "model", "observed", "difference", "agreement"}`. `model` is the fast
    layer's ERA5 value recomputed over the **same years** (use
    `_matched_window(full_all, None, witness["period"])`), `difference` = model −
    observed (2 decimals). `agreement`: both equal → `"high"`; observed 0 and model
    not → `"low"`; otherwise rel = |difference| / |observed|: ≤ 15 % `"high"`,
    ≤ 35 % `"medium"`, else `"low"`.
- `report["witness"]` is `None` outside Catalonia or when no station qualifies. When
  the portal fails: `{"available": false, "note": "<why, in English>"}` plus a line in
  `report["warnings"]`. The report must always build.
- Nothing else in the report changes: no score, level, card or order.

## Engineering rules

- Async `httpx`, like the other providers. Read `config.METEOCAT_URL` **at call time**
  (not at import), so it can be redirected.
- Cache with `app.cache` (namespace `"meteocat"`) for at least 7 days, so a repeated
  call works while the portal is down.
- English in every string a person reads. Catalan labels are translated at the edge;
  station names stay as Meteocat writes them.
- `provenance` has every field filled; `scale_kind` is `"point"`; `period` equals the
  witness period. `limitation` says what this does NOT say (at least 80 characters).
- Touch only: `backend/app/providers/meteocat.py` (new), `backend/app/report.py`,
  `backend/app/indicators.py` (additions only), `backend/app/config.py` (additions
  only), `docs/station-witness.md` (new). Nothing else: not `scoring.py`, not the hazards
  modules, not the frontend, not `backend/autonomy/`, not `data/`.
- No new dependencies: the gate runs your code with `backend/requirements.txt`.
- No unit tests: the gate below is the acceptance standard.

## How your work is judged

`python backend/autonomy/gate.py --task station-witness --self-check` runs the gate on
your machine. Checks that need the local data cache (building the El Masnou and Vielha
reports) show as skipped there. The authoritative run happens on the product's side after
you push, with spot-check dates drawn at random that you cannot see in advance. The
checks: `scope`, `contract`, `station_choice`, `period`, `completeness`, `counts`,
`observed`, `splice`, `spot_checks`, `physics`, `provenance`, `english`, `cache`,
`degradation`, `report`, `invariance`.
