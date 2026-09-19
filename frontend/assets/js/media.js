// The large media card: the home at street level (Google Street View), or from the air
// when there is no panorama; the AI illustration of a risk; and the narrated video
// briefing. Illustrations and narration come from fal.ai; the page labels them as AI,
// without naming the provider.

import { api } from "./api.js";
import { $, esc, REDUCED_MOTION } from "./util.js";

const PIN_SVG = `<svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="rgba(247,245,239,0.55)"
  stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21z"></path><circle cx="12" cy="9.5" r="2.6"></circle></svg>`;

let place = null;          // {lat, lon, label, aerial, zoom}
let street = null;         // Street View metadata once known
let previews = [];         // the risks with an AI illustration, worst first
let mode = "street";
let token = 0;             // guards async work against a newer state
let map = null;
let listeners = [];

const box = () => $("#media");

function header(title, source, { closable = false } = {}) {
  $("#mediaTitle").textContent = title;
  $("#mediaSource").textContent = source || "";
  $("#mediaSource").hidden = !source;
  $("#mediaClose").hidden = !closable;
}

function notify() {
  const btn = $("#previewBtn");
  btn.hidden = !previews.length;
  btn.setAttribute("aria-pressed", String(mode.startsWith("risk:")));
  listeners.forEach((fn) => fn(mode));
}

function teardownMap() {
  if (map) { map.remove(); map = null; }
}

function placeholder(text, { error = false, spinner = false } = {}) {
  teardownMap();
  const el = box();
  el.classList.toggle("empty", !spinner && !error);
  el.innerHTML = spinner
    ? `<div class="media-status"><div class="spinner" aria-hidden="true"></div><span>${text}</span></div>`
    : `<div class="media-placeholder${error ? " error" : ""}">${PIN_SVG}<span>${text}</span></div>`;
}

// ------------------------------------------------------------------ street view
function monthYear(date) {
  const m = /^(\d{4})-(\d{2})/.exec(date || "");
  if (!m) return "";
  return new Date(+m[1], +m[2] - 1, 1).toLocaleDateString("en-GB", { month: "short", year: "numeric" });
}

function renderStreet() {
  const el = box();
  teardownMap();
  el.classList.remove("empty");
  const when = monthYear(street.date);
  header("Street view", when ? `Captured ${when}` : "");
  el.innerHTML = `<img class="media-fill" alt="Street-level view of ${esc(place.label || "the home")}"
    src="${esc(street.image)}"><span class="media-credit">${esc(street.copyright || "© Google")}</span>`;
  const img = el.querySelector("img");
  img.addEventListener("error", () => { if (mode === "street") renderAerial(); }, { once: true });
}

function renderAerial() {
  const el = box();
  el.classList.remove("empty");
  const aerial = place.aerial;
  if (typeof L === "undefined" || !aerial) {
    header("Street view", "");
    placeholder("There is no street-level picture of this address.");
    return;
  }
  header("Aerial view", "");
  teardownMap();
  el.innerHTML = `<div class="media-map" id="mediaMap" role="img" aria-label="Aerial view of the home"></div>`;
  const zoom = Math.min(place.zoom || 17, aerial.max_zoom || 18);
  map = L.map("mediaMap", {
    zoomControl: true, attributionControl: true, scrollWheelZoom: false, maxZoom: aerial.max_zoom || 19,
  }).setView([place.lat, place.lon], zoom);
  L.tileLayer(aerial.url, { maxZoom: aerial.max_zoom || 19, attribution: esc(aerial.attribution) }).addTo(map);
  L.marker([place.lat, place.lon], {
    icon: L.divIcon({ className: "", html: '<div class="home-pin"></div>', iconSize: [22, 22], iconAnchor: [11, 11] }),
    keyboard: false, interactive: false,
  }).addTo(map);
  setTimeout(() => map && map.invalidateSize(), 60);
}

function renderStreetOrAerial() {
  if (!place) return;
  if (street && street.available) renderStreet();
  else renderAerial();
}

// ------------------------------------------------------------------ illustrations
function renderIllustration(risk) {
  const ill = risk.illustration;
  const el = box();
  teardownMap();
  el.classList.remove("empty");
  header(`${risk.label} · what it could look like`, "", { closable: true });
  const c = ill.chosen_by || {};
  const chosen = c.shown ? `Chosen by ${esc(c.label.toLowerCase())}: ${esc(c.shown)}.` : "";
  const others = previews.length > 1
    ? `<div class="media-switch" role="group" aria-label="Risks with an AI illustration">${previews.map((r) =>
      `<button type="button" data-switch="${esc(r.key)}" aria-pressed="${r.key === risk.key}">${esc(r.label)}</button>`).join("")}</div>`
    : "";
  el.innerHTML = `
    <video class="media-fill" ${REDUCED_MOTION ? "controls" : "autoplay loop"} muted playsinline preload="auto"
      poster="${esc(ill.poster || "")}" src="${esc(ill.video)}"
      aria-label="${esc(ill.title)}. AI illustration of a generic place"></video>
    <span class="media-badge">AI illustration · not this place</span>${others}
    <div class="media-caption"><b>${esc(ill.title)}.</b> ${esc(ill.caption)}
      ${risk.home_note ? `<span class="home-note">${esc(risk.home_note)}</span>` : ""}
      <span class="fine">${chosen} ${esc(ill.limitation || "")}</span></div>`;
}

// ------------------------------------------------------------------ briefing
async function runBriefing(ctx) {
  const mine = ++token;
  mode = "briefing";
  notify();
  teardownMap();
  const el = box();
  el.classList.remove("empty");
  header("Video briefing", "", { closable: true });
  const status = (text) => {
    if (mine !== token) return;
    el.innerHTML = `<div class="media-status"><div class="spinner" aria-hidden="true"></div>
      <span>${esc(text)}</span><small>The script is written from your report, word for word, and
      read aloud by an AI voice. The pictures are AI illustrations of generic places.</small></div>`;
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
    header("Video briefing", res.narrated ? "" : "Silent version", { closable: true });
    const name = `previous-ai-briefing-${String(res.place || "home").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")}.mp4`;
    el.innerHTML = `
      <video class="media-fill contain" controls autoplay playsinline preload="auto" src="${esc(res.video)}"
        aria-label="Video briefing of this report"></video>
      <a class="media-badge" style="left:auto;right:12px;pointer-events:auto;text-decoration:none"
        href="${esc(res.video)}" download="${esc(name)}">Download · ${Math.round(res.duration_s)} s</a>`;
  } catch (err) {
    if (mine !== token) return;
    el.innerHTML = `<div class="media-status error"><span>${esc(err.message)}</span></div>`;
  } finally {
    if (mine === token) $("#briefingBtn").disabled = false;
  }
}

// ------------------------------------------------------------------ public API
export const media = {
  init() {
    $("#mediaClose").addEventListener("click", () => media.showStreet());
    $("#previewBtn").addEventListener("click", () => {
      if (mode.startsWith("risk:")) media.showStreet();
      else media.showIllustration(previews[0]);
    });
    box().addEventListener("click", (e) => {
      const pick = e.target.closest("[data-switch]");
      if (pick) media.showIllustration(previews.find((r) => r.key === pick.dataset.switch));
    });
  },
  onChange(fn) { listeners.push(fn); },
  mode() { return mode; },

  // The risks whose data picked an illustration, worst first: the header's
  // "AI preview" opens the first, and the picture offers the others.
  setPreviews(risks) {
    previews = risks || [];
    notify();
  },

  reset() {
    token++;
    place = null;
    street = null;
    previews = [];
    mode = "street";
    header("Street view", "");
    placeholder("Finding your home…", { spinner: true });
    notify();
  },

  async setPlace(p) {
    const mine = ++token;
    place = p;
    street = null;
    mode = "street";
    notify();
    try {
      street = await api.streetview(p.lat, p.lon);
    } catch (_) {
      street = { available: false };
    }
    if (mine !== token || mode !== "street") return;
    renderStreetOrAerial();
  },

  showStreet() {
    token++;
    mode = "street";
    notify();
    if (!place) return;
    renderStreetOrAerial();
    $("#briefingBtn").disabled = false;
  },

  showIllustration(risk) {
    if (!risk || !risk.illustration) return;
    token++;
    mode = `risk:${risk.key}`;
    notify();
    renderIllustration(risk);
    $("#briefingBtn").disabled = false;
  },

  startBriefing(ctx) { runBriefing(ctx); },

  error(text) {
    token++;
    header("Street view", "");
    placeholder(esc(text), { error: true });
  },
};
