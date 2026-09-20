# Norma (Quality Clouds) — remediation defence

**Project:** Previous AI
**Static analysis:** Norma by Quality Clouds
**Remediation:** Claude Opus 5 via Claude Code
**Batches:** 19 September 2026 (commits `282b05b`, `ce6ca59`) and 20 September 2026 (working tree)

---

## How to verify this document

Every change made in response to a Norma finding carries the same marker on the line
next to it:

```bash
grep -rn "Recommended by Norma" backend/ frontend/assets
```

That returns **51 marked changes**, which reconcile to the themes below. Nothing in
this document is claimed without a marker behind it, and the two sections that are
*not* backed by a marker (§2 and §4) say so explicitly.

| # | Theme | Severity | Markers | Status |
|---|---|---|---|---|
| A | Unsanitised `innerHTML` (XSS) | High | 34 | Fixed |
| B | Errors swallowed with no trace | Low | 2 | Fixed |
| C | `subprocess` calls with no timeout | Medium | 5 | Fixed |
| D | PIL image handles never closed | Medium | 2 | Fixed |
| E | `else` after `raise` | Low | 1 | Fixed |
| F | Sensitive data leaving in an API response | High | 3 | Fixed |
| G | Prompt quality (5 findings) | Medium/Low | 2 | Fixed, 1 of 5 adapted — see §3 |
| H | No database behind application state | High | 2 | **Not fixed** — documented, see §2 |
| | **Total** | | **51** | |

---

## 1. What we fixed

### A — Unsanitised `innerHTML` (34 markers)

**Finding:** report data was interpolated into `innerHTML` across the front end, so any
string that reached a template could carry markup.

**Fix:** vendored DOMPurify (`frontend/vendor/dompurify/`, Apache-2.0, licence
included) and added one choke point in `frontend/assets/js/util.js`:

```js
const PURIFY = { ADD_ATTR: ["target", "referrerpolicy"] };
export function setHtml(el, html) { el.innerHTML = DOMPurify.sanitize(html, PURIFY); }
```

Every `innerHTML =` that builds markup from data was converted to `setHtml()`:
`report.js` (18), `media.js` (13), `home.js` (1), plus the helper itself. The templates
keep escaping their values with `esc()`, so this is defence in depth: `esc()` handles the
values, DOMPurify drops anything that could still execute (event handlers, `javascript:`
URLs). `ADD_ATTR` is narrow and deliberate — it re-allows only `target` on links and
`referrerpolicy` on store images, which DOMPurify strips by default.

One case was fixed the other way round: `home.js#message()` took no markup at all, so it
became `textContent`, and its two callers dropped the now-pointless `esc()`.

### B — Errors swallowed with no trace (2 markers)

`catch (_) { }` in `report.js` (geolocation) and `util.js` (`localStorage.setItem`)
became `catch (err) { console.warn(...) }`. Both still never break the page — a failed
save or a denied location is not fatal — but they are no longer invisible in the console.

### C — `subprocess` calls with no timeout (5 markers)

**Finding:** `subprocess.run` without `timeout=` blocks forever if the child stalls.
These are the autonomy runner's git calls, so a stalled `git fetch` hangs the whole run.

**Fix:** `backend/scripts/devin_run.py` gained `GIT_TIMEOUT_S = 300` and passes it to
`git()`; `backend/autonomy/gate.py` uses `timeout=60`;
`backend/autonomy/tasks/station_witness/checks.py` uses `timeout=120`.

Two follow-on changes were needed so the new failure mode does not make things worse:
the worktree cleanup in `devin_run.py` now catches `subprocess.SubprocessError` (the
parent of both `CalledProcessError` and `TimeoutExpired`) so a timing-out git cannot skip
the `shutil.rmtree` after it, and the second cleanup path wraps its `subprocess.run` in
`try/except TimeoutExpired` for the same reason.

### D — PIL image handles never closed (2 markers)

`Image.open(...)` used as a temporary in `providers/ign_flood.py` and `pdf_report.py`
left the file object to the garbage collector. Both are now `with Image.open(...) as img:`.
These run per request (flood depth at the door, aerial tiles for the PDF), so the leak
was proportional to traffic.

### E — `else` after `raise` (1 marker)

`providers/devin.py#_request` had an `if/elif/else` where one branch raised. It was
**reordered rather than flattened**, on purpose: the early-return case moved to the top
and the raise became a guard, so a `429` or `5xx` still falls through to the retry loop
below. A naive de-nesting would have turned every retryable status into an immediate
failure.

### F — Sensitive data leaving in an API response (3 markers) — *20 Sep, HIGH*

**Finding:** `fire_spread_start` and `fire_spread_status` in `backend/app/main.py`
caught every `Exception` and returned
`HTTPException(502, detail=f"Deepfire: {type(exc).__name__}: {exc}")`, putting the
provider's exception class and message — which can carry upstream URLs, ids and runtime
detail — into a public API response.

**Fix:** one fixed public message, full detail to the server log only.

```python
SPREAD_UNAVAILABLE = "The fire-spread simulation is unavailable right now."
...
except Exception as exc:
    log.exception("Deepfire fire-spread start failed")
    raise HTTPException(status_code=502, detail=SPREAD_UNAVAILABLE) from exc
```

`main.py` had no logger before this; `logging.getLogger(__name__)` was added and left at
the default configuration, so the traceback goes wherever uvicorn is already sending its
own logs. The coordinates were deliberately **not** logged: the whole scope of a report is
one dwelling, so a home's latitude and longitude are the sensitive part of the request and
had no business being written to a log file as part of a fix for a data-exposure finding.
The traceback carries the diagnostic value; `sim_id` is logged in the status handler
because it identifies a simulation, not a person.

### G — Prompt quality, 5 findings (2 markers) — *20 Sep*

All five were applied to `SYSTEM` in `backend/app/providers/nebius.py`. One of the five
was implemented in substance but not as literally written — see §3.

| Finding | What changed |
|---|---|
| Provide examples | A worked example was added, written in the exact shape `_prompt()` emits at runtime (`[id] choice:` / `  Options:` / `  - "opt"` / `[id] yes/no:`), so it demonstrates the real format rather than a paraphrase of it. Its content (a room, windows, lamps) is deliberately unrelated to floods, fire, heat and avalanches so it cannot bias a real answer. |
| Explicit error handling | The prompt now says what to do when the STATE leaves a question open or a field is missing. **Adapted — see §3.** |
| Specify length/detail | "Every value is one short string, an option or `yes`/`no`: no explanation, no units, no other text." |
| Prompt target and tone | "Keep a flat, machine-readable register." |
| Positive framing | "Use only the STATE… never invent facts" became "Answer strictly from what the STATE says plus ordinary common sense"; "Nothing else" became "Reply with exactly one JSON object…". |

`PROMPT_VERSION` was bumped `1 → 2` in the same change. It is part of the cache key, and
without the bump every answer cached against the old prompt would have been served as if
it had been given to the new one.

The answer and probability path was re-run after the change and still produces the same
shape (`_body`, `_prompt`, `_answers`, `_distribution` exercised on a synthetic reply).

---

## 2. What we did not fix

### H — "Application state has no database behind it" (HIGH, filed on `.claude/launch.json`)

**What Norma asked for:** move autonomy runs, briefing jobs, demo records and CDS jobs
into a shared database service, and replace the `Path.write_text()` calls in
`backend/app/autonomy_store.py`, `backend/app/demo.py` and `backend/app/providers/cds.py`
with database writes.

**Status:** not implemented. The constraint was recorded in code instead, at
`backend/app/main.py` (above `FRONTEND_DIR`) and `backend/app/briefing.py` (above `JOBS`),
both carrying the Norma marker.

**Why.** Five reasons, in order of weight:

1. **Three of the four modules named already persist to disk.** `autonomy_store.py`
   writes its queue and run records as JSON, `demo.py` writes its index and reports, and
   `providers/cds.py` snapshots job state to `jobs.json` and reloads it on start
   (`cds.py:556` writes, `cds.py:568-570` reads back). A restart does not erase them, so
   the premise holds for one module, not four.

2. **The one in-memory store degrades gracefully.** `briefing.JOBS` is a plain dict, but
   `briefing.get()` falls back to the finished `.json` and `.mp4` on disk. A completed
   briefing therefore survives a restart; an unfinished one is simply rendered again. The
   worst case a restart can cost is one re-render.

3. **The multi-replica risk is real but hypothetical here.** The service runs as a single
   uvicorn process against a local data directory — that is what `.claude/launch.json`,
   the file the finding was filed against, actually configures. There is no second replica
   to split state with, and no deployment that would create one.

4. **A database would not close the gap on its own.** Briefings produce mp4 and audio,
   reports produce PDFs, and the demo index points at both. Moving the *rows* to Postgres
   while the *bytes* stay on a local disk leaves exactly the same split-state problem the
   finding describes. Doing this properly means a database **and** object storage.

5. **It is a migration, not a remediation.** `backend/requirements.txt` contains no
   driver, ORM or migration tool. Delivering this means choosing a database, adding a
   service to the deployment, writing a schema and migrations, and rewriting the
   persistence layer of four modules — with no test suite in the repo to catch a
   regression.

**When to revisit:** the moment more than one replica is wanted. That trigger is written
into the code note, together with the object-storage caveat, so the next person to read
`main.py` finds the decision and its expiry condition rather than an unexplained absence.

---

## 3. Fixed, but not literally as recommended

### G — "Explicit error handling" in the Nebius prompt

**What Norma asked for:** *"If a question cannot be answered from the STATE, return the
value `unknown`. If the input JSON is invalid, return an error object with a defined
schema."*

**Why that specific wording was not used:** neither value could ever reach a caller.

- The reply is pinned by a strict JSON Schema built in `_prompt()`, with a per-question
  `enum` of exactly the options that question offers, sent as
  `response_format: {type: json_schema, strict: true}`. `"unknown"` is not a member of any
  enum, and an error object is not the schema being requested.
- `_answers()` raises `NebiusUnavailable` on any value outside a question's options. An
  `"unknown"` would therefore not degrade the answer — it would abort the whole call and
  push every question in it to the fallback backend.
- Uncertainty already has a dedicated and better channel in this module.
  `_distribution()` reads P(option) from the log-probabilities of the tokens the model
  chose *and* the ones it did not, at every token of each answer. A question the STATE
  leaves open shows up as a spread distribution and a low `confidence` — which is strictly
  more information than a sentinel string.

**What was done instead:** the prompt tells the model how to behave when the STATE is
thin, without offering a way out of the schema:

> Answer every question, including the ones the STATE leaves open: pick the listed option
> its evidence best supports. How sure you are is read from your own token probabilities,
> so a close call needs no hedging. When a field is missing or unreadable, treat it as
> absent and answer from what remains.

The reasoning is recorded in a comment directly above `SYSTEM` in `nebius.py`, so the
deviation is visible to the next reader and to the next scan.

---

## 4. Known gap in this document

This document reconstructs the 19 September batches from the markers left in the code,
which record what **was** fixed. If any finding from those batches was reviewed and
deliberately declined, that decision is not recorded anywhere in the repository and is
therefore missing from §2. The Norma reports for 19 September are the only source for it.

One change shipped in `ce6ca59` is **not** covered by a marker and is listed here for
completeness rather than claimed as a remediation: `backend/app/grants.py` was given a
second verification pass in that commit, re-reading every grant claim against its primary
source (BOE texts, the Consorcio's and Protección Civil's rules, the DOGC/CIDO entry, El
Masnou's fiscal ordinance, the Council of Ministers' declarations) and dropping the claims
that could not be found in one.

---

## 5. Spotted during remediation, not yet reported by Norma

`backend/app/briefing.py:792` writes `f"{type(exc).__name__}: {exc}"` into `job["error"]`,
which the page polls and displays. This is the same class of issue as finding F, in a
different file, and was left alone because it falls outside the batches Norma reported.
It is recorded here so it is clear it was seen rather than missed.
