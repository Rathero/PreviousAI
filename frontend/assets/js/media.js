// The home's pictures: a thumbnail in the report's hero and a viewer that opens it large.
// The home at street level (Google Street View), or from the air when there is no
// panorama; the AI illustration of the risk picked on the page; and the narrated video
// briefing. Illustrations and narration come from fal.ai; the page labels them as AI,
// without naming the provider.

import { api } from "./api.js";
import { $, esc, setHtml, REDUCED_MOTION } from "./util.js";

const PIN_SVG = `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="rgba(247,245,239,0.55)"
  stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21z"></path><circle cx="12" cy="9.5" r="2.6"></circle></svg>`;

let place = null;          // {lat, lon, label, aerial, zoom}
let street = null;         // Street View metadata once known
let previews = [];         // the risks with an AI illustration, worst first
let selected = null;       // the risk picked on the page: the thumbnail shows its illustration
let mode = null;           // what the viewer shows: "street" | "risk:<key>" | "briefing"
let placeToken = 0;        // guards the Street View lookup against a newer place
let token = 0;             // guards the viewer's async work against a newer state
let map = null;            // the viewer's aerial map
let thumbMap = null;       // the thumbnail's aerial map
let lastFocus = null;
let failure = null;        // the thumbnail's message when the address was not found

const box = () => $("#media");
const viewer = () => $("#viewer");

function header(title, source) {
  $("#mediaTitle").textContent = title;
  $("#mediaSource").textContent = source || "";
  $("#mediaSource").hidden = !source;
}

function teardownMap() {
  if (map) { map.remove(); map = null; }
}

function teardownThumbMap() {
  if (thumbMap) { thumbMap.remove(); thumbMap = null; }
}

function statusHtml(text, { error = false, spinner = false } = {}) {
  return spinner
    ? `<div class="media-status"><div class="spinner" aria-hidden="true"></div><span>${text}</span></div>`
    : `<div class="media-placeholder${error ? " error" : ""}">${PIN_SVG}<span>${text}</span></div>`;
}

function monthYear(date) {
  const m = /^(\d{4})-(\d{2})/.exec(date || "");
  if (!m) return "";
  return new Date(+m[1], +m[2] - 1, 1).toLocaleDateString("en-GB", { month: "short", year: "numeric" });
}

function aerialMap(el, { interactive }) {
  const aerial = place.aerial;
  const zoom = Math.min(place.zoom || 17, aerial.max_zoom || 18);
  const m = L.map(el, {
    zoomControl: interactive, attributionControl: interactive, scrollWheelZoom: false,
    dragging: interactive, doubleClickZoom: interactive, boxZoom: interactive, keyboard: interactive,
    touchZoom: interactive, maxZoom: aerial.max_zoom || 19,
  }).setView([place.lat, place.lon], zoom);
  L.tileLayer(aerial.url, { maxZoom: aerial.max_zoom || 19, attribution: esc(aerial.attribution) }).addTo(m);
  L.marker([place.lat, place.lon], {
    icon: L.divIcon({ className: "", html: '<div class="home-pin"></div>', iconSize: [22, 22], iconAnchor: [11, 11] }),
    keyboard: false, interactive: false,
  }).addTo(m);
  setTimeout(() => m.invalidateSize(), 60);
  return m;
}

// ------------------------------------------------------------------ thumbnail
function renderThumb() {
  const el = $("#thumbMedia");
  const label = $("#thumbLabel");
  const btn = $("#thumb");
  teardownThumbMap();
  const ill = selected && selected.illustration;
  if (ill) {
    // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
    setHtml(el, `<video ${REDUCED_MOTION ? "" : "autoplay loop"} muted playsinline preload="auto"
      poster="${esc(ill.poster || "")}" src="${esc(ill.video)}"></video>`);
    label.textContent = "AI illustration";
    btn.disabled = false;
    btn.setAttribute("aria-label",
      `See what ${selected.label.toLowerCase()} could look like: an AI illustration of a generic place`);
    return;
  }
  if (failure) {
    // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
    setHtml(el, statusHtml(esc(failure), { error: true }));
    label.textContent = "";
    btn.disabled = true;
    return;
  }
  if (!place || !street) {
    // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
    setHtml(el, statusHtml("", { spinner: true }));
    label.textContent = "";
    btn.disabled = true;
    return;
  }
  btn.disabled = false;
  if (street.available) {
    // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
    setHtml(el, `<img alt="" src="${esc(street.image)}">`);
    const when = monthYear(street.date);
    label.textContent = when ? `Street View · ${when}` : "Street View";
    btn.setAttribute("aria-label", "Open the street view of the home");
    el.querySelector("img").addEventListener("error", () => {
      street = { available: false };
      renderThumb();
    }, { once: true });
  } else if (place.aerial && typeof L !== "undefined") {
    el.innerHTML = `<span class="thumb-map" id="thumbMap"></span>`;
    thumbMap = aerialMap($("#thumbMap"), { interactive: false });
    label.textContent = "Aerial view";
    btn.setAttribute("aria-label", "Open the aerial view of the home");
  } else {
    // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
    setHtml(el, statusHtml("No picture of this address"));
    label.textContent = "";
    btn.disabled = true;
  }
}

// ------------------------------------------------------------------ viewer
function openViewer() {
  const v = viewer();
  if (!v.hidden) return;
  lastFocus = document.activeElement;
  v.hidden = false;
  document.body.classList.add("modal-open");
  setTimeout(() => $("#mediaClose").focus(), 0);
}

function closeViewer() {
  token++;
  teardownMap();
  box().innerHTML = "";
  mode = null;
  $("#briefingBtn").disabled = false;
  if (viewer().hidden) return;
  viewer().hidden = true;
  if ($("#planDialog").hidden) document.body.classList.remove("modal-open");
  if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
}

function renderStreet() {
  const el = box();
  teardownMap();
  const when = monthYear(street.date);
  header("Street view", when ? `Captured ${when}` : "");
  // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
  setHtml(el, `<img class="media-fill" alt="Street-level view of ${esc(place.label || "the home")}"
    src="${esc(street.image)}"><span class="media-credit">${esc(street.copyright || "© Google")}</span>`);
  el.querySelector("img").addEventListener("error", () => {
    if (mode !== "street") return;
    street = { available: false };
    renderAerial();
    renderThumb();
  }, { once: true });
}

function renderAerial() {
  const el = box();
  teardownMap();
  if (typeof L === "undefined" || !place.aerial) {
    header("Street view", "");
    // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
    setHtml(el, statusHtml("There is no street-level picture of this address."));
    return;
  }
  header("Aerial view", "");
  el.innerHTML = `<div class="media-map" id="mediaMap" role="img" aria-label="Aerial view of the home"></div>`;
  map = aerialMap($("#mediaMap"), { interactive: true });
}

function renderIllustration(risk) {
  const ill = risk.illustration;
  const el = box();
  teardownMap();
  header(`${risk.label} · what it could look like`, "");
  const c = ill.chosen_by || {};
  const chosen = c.shown ? `Chosen by ${esc(c.label.toLowerCase())}: ${esc(c.shown)}.` : "";
  const others = previews.length > 1
    ? `<div class="media-switch" role="group" aria-label="Risks with an AI illustration">${previews.map((r) =>
      `<button type="button" data-switch="${esc(r.key)}" aria-pressed="${r.key === risk.key}">${esc(r.label)}</button>`).join("")}</div>`
    : "";
  // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
  setHtml(el, `
    <video class="media-fill" ${REDUCED_MOTION ? "controls" : "autoplay loop"} muted playsinline preload="auto"
      poster="${esc(ill.poster || "")}" src="${esc(ill.video)}"
      aria-label="${esc(ill.title)}. AI illustration of a generic place"></video>
    <span class="media-badge">AI illustration · not this place</span>${others}
    <div class="media-caption"><b>${esc(ill.title)}.</b> ${esc(ill.caption)}
      ${risk.home_note ? `<span class="home-note">${esc(risk.home_note)}</span>` : ""}
      <span class="fine">${chosen} ${esc(ill.limitation || "")}</span></div>`);
}

async function runBriefing(ctx) {
  const mine = ++token;
  mode = "briefing";
  teardownMap();
  const el = box();
  header("Video briefing", "");
  const status = (text) => {
    if (mine !== token) return;
    // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
    setHtml(el, `<div class="media-status"><div class="spinner" aria-hidden="true"></div>
      <span>${esc(text)}</span><small>The script is written from your report, word for word, and
      read aloud by an AI voice. The pictures are AI illustrations of generic places.</small></div>`);
  };
  status("Writing the script from your report…");
  $("#briefingBtn").disabled = true;
  try {
    let job = await api.briefingStart(ctx);
    const started = Date.now();
    let retries = 0;
    while (job.status === "queued" || job.status === "running") {
      if (mine !== token) return;
      status(`${job.progress || "Working"}… (${Math.round((Date.now() - started) / 1000)} s)`);
      await new Promise((r) => setTimeout(r, 1200));
      try {
        job = await api.briefingStatus(job.id);
      } catch (err) {
        // Jobs live in the server's memory: after a restart the same request restarts it.
        if (err.status === 404 && retries++ < 2) { job = await api.briefingStart(ctx); continue; }
        throw err;
      }
    }
    if (mine !== token) return;
    if (job.status !== "done") throw new Error(job.error || "The briefing could not be made.");
    const res = job.result;
    const name = `previous-ai-briefing-${String(res.place || "home").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")}.mp4`;
    header("Video briefing", "");
    // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
    setHtml($("#mediaSource"), `${res.narrated ? "" : "Silent version · "}<a class="text-link"
      href="${esc(res.video)}" download="${esc(name)}">Download · ${Math.round(res.duration_s)} s</a>`);
    $("#mediaSource").hidden = false;
    // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
    setHtml(el, `
      <video class="media-fill contain" controls autoplay playsinline preload="auto" src="${esc(res.video)}"
        aria-label="Video briefing of this report"></video>`);
  } catch (err) {
    if (mine !== token) return;
    // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
    setHtml(el, `<div class="media-status error"><span>${esc(err.message)}</span></div>`);
  } finally {
    if (mine === token) $("#briefingBtn").disabled = false;
  }
}

// ------------------------------------------------------------------ public API
export const media = {
  init() {
    viewer().addEventListener("click", (e) => {
      if (e.target.closest("[data-close]")) { closeViewer(); return; }
      const pick = e.target.closest("[data-switch]");
      if (pick) media.showIllustration(previews.find((r) => r.key === pick.dataset.switch));
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !viewer().hidden) closeViewer();
    });
    $("#thumb").addEventListener("click", () => {
      if (selected && selected.illustration) media.showIllustration(selected);
      else media.showStreet();
    });
  },

  reset() {
    placeToken++;
    closeViewer();
    place = null;
    street = null;
    previews = [];
    selected = null;
    failure = null;
    renderThumb();
  },

  async setPlace(p) {
    const mine = ++placeToken;
    place = p;
    street = null;
    failure = null;
    renderThumb();
    let found;
    try {
      found = await api.streetview(p.lat, p.lon);
    } catch (_) {
      found = { available: false };
    }
    if (mine !== placeToken) return;
    street = found;
    renderThumb();
    if (mode === "street") media.showStreet();
  },

  // The risks whose data picked an illustration, worst first: the viewer offers them all.
  setPreviews(risks) { previews = risks || []; },

  // The risk picked on the page (or null): the thumbnail shows its illustration, if any.
  select(risk) {
    selected = risk || null;
    renderThumb();
  },

  showStreet() {
    token++;
    mode = "street";
    openViewer();
    if (!place || !street) {
      header("Street view", "");
      // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
      setHtml(box(), statusHtml("Finding your home…", { spinner: true }));
      return;
    }
    if (street.available) renderStreet();
    else renderAerial();
  },

  showIllustration(risk) {
    if (!risk || !risk.illustration) return;
    token++;
    mode = `risk:${risk.key}`;
    openViewer();
    renderIllustration(risk);
  },

  startBriefing(ctx) {
    openViewer();
    runBriefing(ctx);
  },

  close() { closeViewer(); },

  error(text) {
    placeToken++;
    failure = text;
    renderThumb();
  },
};
