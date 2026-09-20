// The report read backwards: every municipality ranked, then the buildings inside the
// official flood zones, each one a link to its own report.
//
// Everything shown here was computed in batch by backend/scripts/analysis_build.py. The
// page sorts and filters what the API hands it and never calculates a score of its own:
// two people opening the same ranking have to see the same list.

import { api } from "./api.js";
import { $, esc, setHtml } from "./util.js";

const PAGE = 50;

const state = {
  hazard: "overall",
  province: "",
  query: "",
  exposed: false,
  offset: 0,
  rows: [],
  total: 0,
  meta: {},
  hazards: [],
  provinces: [],
  isCount: false,
};

let app = null;
let searchTimer = null;
let inflight = null;

// The zones, worst first, as the official mapping names them.
const ZONE_LABEL = {
  zfp: "Preferential flow zone",
  t10: "Flood zone T=10 years",
  t50: "Flood zone T=50 years",
  t100: "Flood zone T=100 years",
  t500: "Flood zone T=500 years",
};

const USE_LABEL = {
  "1_residential": "Home",
  "2_agriculture": "Farm",
  "3_industrial": "Industrial",
  "4_1_office": "Office",
  "4_2_retail": "Retail",
  "4_3_publicServices": "Public service",
};

const levelClass = (level) => `lvl-${String(level || "no data").replace(/\s+/g, "-")}`;

const fmt = (n, digits = 0) =>
  n === null || n === undefined ? "—" : Number(n).toLocaleString("en", {
    minimumFractionDigits: digits, maximumFractionDigits: digits });

export function initAnalysis(application) {
  app = application;

  $("#anHazards").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-hazard]");
    if (!btn) return;
    setState({ hazard: btn.dataset.hazard, offset: 0 });
  });

  $("#anProvince").addEventListener("change", (e) =>
    setState({ province: e.target.value, offset: 0 }));

  $("#anQuery").addEventListener("input", (e) => {
    const value = e.target.value;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => setState({ query: value, offset: 0 }), 250);
  });

  $("#anExposed").addEventListener("change", (e) =>
    setState({ exposed: e.target.checked, offset: 0 }));

  $("#anMore").addEventListener("click", () => load({ append: true }));

  $("#anTable").addEventListener("click", (e) => {
    const row = e.target.closest("[data-code]");
    if (row) openMunicipality(row.dataset.code);
  });

  const dialog = $("#anDialog");
  dialog.addEventListener("click", (e) => {
    if (e.target.closest("[data-close]")) closeDialog();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !dialog.hidden) closeDialog();
  });
}

export function showAnalysis(params) {
  state.hazard = params.get("hazard") || "overall";
  state.province = params.get("province") || "";
  state.query = params.get("q") || "";
  state.exposed = params.get("exposed") === "1";
  state.offset = 0;
  $("#anQuery").value = state.query;
  $("#anExposed").checked = state.exposed;
  load({ append: false });
  const code = params.get("municipality");
  if (code) openMunicipality(code);
  else closeDialog({ silent: true });
}

function setState(patch) {
  Object.assign(state, patch);
  const qs = new URLSearchParams();
  if (state.hazard !== "overall") qs.set("hazard", state.hazard);
  if (state.province) qs.set("province", state.province);
  if (state.query) qs.set("q", state.query);
  if (state.exposed) qs.set("exposed", "1");
  const url = `/analisis${qs.toString() ? `?${qs}` : ""}`;
  history.replaceState({}, "", url);
  load({ append: false });
}

async function load({ append }) {
  if (inflight) inflight.abort();
  inflight = new AbortController();
  const offset = append ? state.offset + PAGE : 0;
  if (!append) setHtml($("#anTable"), `<p class="an-loading">Reading the ranking…</p>`);
  try {
    const data = await api.analysisRanking({
      hazard: state.hazard, province: state.province, q: state.query,
      exposed: state.exposed ? "true" : "", limit: PAGE, offset,
    }, inflight.signal);
    state.offset = offset;
    state.rows = append ? state.rows.concat(data.rows) : data.rows;
    state.total = data.total;
    state.meta = data.meta || {};
    state.hazards = data.hazards || [];
    state.provinces = data.provinces || [];
    state.isCount = !!data.is_count;
    render();
  } catch (err) {
    if (err && err.name === "AbortError") return;
    setHtml($("#anTable"), `<p class="an-empty">${esc(err.message)}</p>`);
    $("#anMore").hidden = true;
  } finally {
    inflight = null;
  }
}

function render() {
  renderHazards();
  renderProvinces();

  const meta = state.meta;
  $("#anMeta").textContent = state.total
    ? `${fmt(state.total)} municipalities · ${fmt(meta.with_exposure)} with their buildings `
      + `counted against the official flood maps · built ${meta.built || ""}`
    : "Nothing matches these filters.";

  const showsFlood = state.hazard === "flood" || state.isCount
    || state.rows.some((r) => r.exposure);
  const head = `
    <div class="an-row an-head">
      <span class="an-rank">#</span>
      <span class="an-name">Municipality</span>
      <span class="an-score">${esc(labelFor(state.hazard))}</span>
      <span class="an-fact">${showsFlood ? "Homes in a flood zone" : "What drives it"}</span>
    </div>`;

  // A count column is drawn against the biggest value on the page, not against 100:
  // the bar says "compared with the worst town here", which is what it is.
  const peak = state.isCount
    ? Math.max(1, ...state.rows.map((r) => r.homes_at_risk || 0)) : 100;

  const rows = state.rows.map((r) => {
    const value = state.isCount ? r.homes_at_risk : r.scores[state.hazard];
    const width = Math.max(2, Math.round(((value ?? 0) / peak) * 100));
    const shade = state.isCount ? scoreLevel(r.scores.flood) : scoreLevel(value);
    return `
      <button type="button" class="an-row" data-code="${esc(r.code)}">
        <span class="an-rank">${r.rank}</span>
        <span class="an-name">
          <strong>${esc(r.name)}</strong>
          <small>${esc(r.province)}${r.comarca ? ` · ${esc(r.comarca)}` : ""}</small>
        </span>
        <span class="an-score">
          <span class="an-bar ${levelClass(shade)}" style="width:${width}%"></span>
          <span class="an-num">${value === null || value === undefined ? "no data" : fmt(value, 0)}</span>
        </span>
        <span class="an-fact">${fact(r, showsFlood)}</span>
      </button>`;
  }).join("");

  setHtml($("#anTable"), head + (rows || `<p class="an-empty">Nothing matches these filters.</p>`));
  $("#anMore").hidden = state.rows.length >= state.total;

  setHtml($("#anNote"), note(meta));
}

function scoreLevel(score) {
  if (score === null || score === undefined) return "no data";
  if (score < 20) return "very low";
  if (score < 40) return "low";
  if (score < 60) return "moderate";
  if (score < 80) return "high";
  return "very high";
}

function labelFor(key) {
  const found = state.hazards.find((h) => h.key === key);
  return found ? found.label : key;
}

function fact(row, showsFlood) {
  if (showsFlood && row.exposure) {
    const e = row.exposure;
    return `<strong>${fmt(e.flooded_dwellings)}</strong> in ${fmt(e.flooded_buildings)} buildings`
      + `<small>${esc(ZONE_LABEL[e.worst_zone] || "")}</small>`;
  }
  const m = row.metrics || {};
  if (state.hazard === "fire_weather" && m.fire_weather_days !== undefined) {
    return `<strong>${fmt(m.fire_weather_days)}</strong> days a year of high fire danger`;
  }
  if (state.hazard === "flood_history" && m.flood_episodes !== undefined) {
    return `<strong>${fmt(m.flood_episodes)}</strong> flood episodes on record`;
  }
  if (state.hazard === "fire_history" && m.burnt_ha !== undefined) {
    return `<strong>${fmt(m.burnt_ha)}</strong> hectares burnt since 2011`;
  }
  if (state.hazard === "avalanche" && m.avalanche_zones !== undefined) {
    return `<strong>${fmt(m.avalanche_zones)}</strong> mapped avalanche zones`;
  }
  if (state.hazard === "heat" && m.heat_days_35 !== undefined) {
    return `<strong>${fmt(m.heat_days_35)}</strong> days a year above 35 °C`;
  }
  if (m.fire_weather_days !== undefined) {
    return `<strong>${fmt(m.fire_weather_days)}</strong> days a year of high fire danger`;
  }
  return "—";
}

function note(meta) {
  const missing = meta.not_covered;
  return `The ranking is built from what can be known for every town at once. `
    + `${fmt(meta.with_climate)} of ${fmt(meta.municipalities)} have the official `
    + `fire-danger grid; the flood column exists only for the ${fmt(meta.with_exposure)} `
    + `towns whose buildings have been crossed with the official maps, and heat only for `
    + `${fmt(meta.with_heat)}, because the climate record is rate-limited. Everything `
    + `else says "no data" instead of a low score.`
    + (missing ? ` The Basque provinces and Navarre are not here: ${esc(missing.reason)}.` : "")
    // The column is only as good as the mapping under it, and saying so is the
    // difference between a tool and a false reassurance.
    + ` And a low flood column is not a safe town: the official zones are studies of `
    + `mapped watercourses. Paiporta's urban area is classed T500 and Picanya has two `
    + `buildings mapped at all — both were flooded in October 2024.`;
}

function renderHazards() {
  const el = $("#anHazards");
  if (el.dataset.built === "1") {
    el.querySelectorAll("button").forEach((b) =>
      b.setAttribute("aria-selected", String(b.dataset.hazard === state.hazard)));
    return;
  }
  if (!state.hazards.length) return;
  setHtml(el, state.hazards.map((h) => `
    <button type="button" class="chip-btn" role="tab" data-hazard="${esc(h.key)}"
            aria-selected="${h.key === state.hazard}">${esc(h.label)}</button>`).join(""));
  el.dataset.built = "1";
}

function renderProvinces() {
  const el = $("#anProvince");
  if (el.dataset.built === "1" || !state.provinces.length) return;
  setHtml(el, `<option value="">All provinces</option>` + state.provinces.map((p) =>
    `<option value="${esc(p.code)}">${esc(p.name)}</option>`).join(""));
  el.value = state.province;
  el.dataset.built = "1";
}

// ------------------------------------------------------------------ one town

async function openMunicipality(code) {
  const dialog = $("#anDialog");
  dialog.hidden = false;
  document.body.classList.add("modal-open");
  $("#anTitle").textContent = "…";
  $("#anSub").textContent = "";
  setHtml($("#anDetail"), `<p class="an-loading">Reading the municipality…</p>`);
  try {
    const m = await api.analysisMunicipality(code);
    $("#anTitle").textContent = m.name;
    $("#anSub").textContent = [m.province, m.comarca].filter(Boolean).join(" · ");
    setHtml($("#anDetail"), detailHtml(m));
  } catch (err) {
    setHtml($("#anDetail"), `<p class="an-empty">${esc(err.message)}</p>`);
  }
}

function closeDialog({ silent = false } = {}) {
  const dialog = $("#anDialog");
  if (dialog.hidden) return;
  dialog.hidden = true;
  document.body.classList.remove("modal-open");
  if (!silent) $("#anQuery").blur();
}

function detailHtml(m) {
  const scores = Object.entries(m.scores)
    .filter(([, v]) => v !== null && v !== undefined)
    .sort((a, b) => b[1] - a[1]);

  const scoreList = `
    <div class="an-scores">
      ${scores.map(([k, v]) => `
        <div class="an-scorecell">
          <span class="an-scorekey">${esc(labelFor(k))}</span>
          <span class="an-bar ${levelClass(scoreLevel(v))}" style="width:${Math.max(2, v)}%"></span>
          <span class="an-num">${fmt(v)}</span>
        </div>`).join("")}
    </div>`;

  const exp = m.exposure && m.exposure.flood ? m.exposure : null;
  const exposure = exp ? `
    <section class="an-sec">
      <h3>The buildings that stand in an official flood zone</h3>
      <p class="an-secsub">
        ${fmt(exp.flood.buildings)} of ${fmt(exp.buildings.total)} buildings,
        ${fmt(exp.flood.dwellings)} dwellings, ${fmt(exp.flood.pre_1980)} of them in
        buildings raised before 1980. The cadastre's footprints crossed with the SNCZI
        flood zones the day this was built.
      </p>
      <div class="an-zones">
        ${exp.flood.by_zone.map((z) => `
          <div class="an-zone">
            <span class="an-zonename">${esc(z.label || ZONE_LABEL[z.zone] || z.zone)}</span>
            <span class="an-zonecount"><strong>${fmt(z.buildings)}</strong> buildings ·
              ${fmt(z.dwellings)} dwellings</span>
          </div>`).join("")}
      </div>
      <button type="button" class="chip-btn solid" id="anBuildings"
              data-code="${esc(m.code)}">See the buildings →</button>
      <div class="an-buildings" id="anBuildingList"></div>
    </section>` : `
    <section class="an-sec">
      <h3>The buildings have not been counted here yet</h3>
      <p class="an-secsub">
        Crossing this town's cadastral footprints with the official flood maps is a
        batch job: <code>analysis_build.py --only exposure --municipality ${esc(m.code)}</code>.
        Until it runs, this municipality has no flood column, and the ranking says so
        rather than assuming it is dry.
      </p>
    </section>`;

  const sources = `
    <section class="an-sec">
      <h3>Where every number comes from</h3>
      <ul class="an-sources">
        ${(m.indicators || []).map((i) => `
          <li>
            <span class="an-indname">${esc(i.label)}</span>
            <span class="an-indval">${fmt(i.value, i.unit === "ha" ? 1 : 0)} ${esc(i.unit)}</span>
            <small>${esc(i.provenance.source)} · ${esc(i.provenance.period)} ·
              ${esc(i.provenance.scale || "")}</small>
            <small class="an-method">${esc(i.provenance.method)}</small>
            ${i.context ? `<small class="an-ctx">${esc(i.context)}</small>` : ""}
          </li>`).join("")}
      </ul>
    </section>`;

  const own = m.centroid ? `
    <a class="chip-btn ghost" href="/report?address=${encodeURIComponent(m.centroid.join(", "))}"
       data-nav>Report for the centre of the town →</a>` : "";

  return scoreList + exposure + sources + `<div class="an-actions">${own}</div>`;
}

// The building list is loaded on demand: a town can have thousands of them.
document.addEventListener("click", async (e) => {
  const btn = e.target.closest("#anBuildings");
  if (!btn) return;
  const list = $("#anBuildingList");
  setHtml(list, `<p class="an-loading">Reading the buildings…</p>`);
  try {
    const data = await api.analysisBuildings(btn.dataset.code, { limit: 200 });
    setHtml(list, buildingsHtml(data));
    btn.hidden = true;
  } catch (err) {
    setHtml(list, `<p class="an-empty">${esc(err.message)}</p>`);
  }
});

function buildingsHtml(data) {
  if (!data.rows.length) return `<p class="an-empty">No exposed buildings.</p>`;
  return `
    <p class="an-secsub">The ${fmt(Math.min(data.rows.length, data.total))} worst of
      ${fmt(data.total)}. Each one opens its own report.</p>
    <div class="an-blist">
      ${data.rows.map((b) => `
        <a class="an-b" href="/report?address=${encodeURIComponent(`${b.lat}, ${b.lon}`)}" data-nav>
          <span class="an-bzone ${levelClass(scoreLevel(b.score))}">${esc(ZONE_LABEL[b.zone] || b.zone)}</span>
          <span class="an-bmain">
            <strong>${esc(USE_LABEL[b.use] || "Building")}${b.dwellings ? ` · ${fmt(b.dwellings)} dwellings` : ""}</strong>
            <small>${b.year ? `built ${b.year}` : "year unknown"}${b.area_m2 ? ` · ${fmt(b.area_m2)} m²` : ""}
              · ${esc(b.ref || "")}</small>
          </span>
          <span class="an-bgo">→</span>
        </a>`).join("")}
    </div>`;
}
