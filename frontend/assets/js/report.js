// The risk report: the home, four risks, what already happened and the action plan.

import { api } from "./api.js";
import { media } from "./media.js";
import {
  $, $$, esc, niceDate, FAMILY_COLOR, FAMILY_FADED, PROFILES, store, homeLabel, addressKey,
} from "./util.js";

const ORDER = ["wildfire", "flood", "heat", "avalanche"];
const NAMES = { wildfire: "Wildfires", flood: "Floods", heat: "Heat waves", avalanche: "Avalanches" };
const BARS = 14;
const CHECKABLE = new Set(["before", "buy", "first"]);
const PROGRESS = [
  "Reading decades of daily climate records…",
  "Checking the official flood maps…",
  "Looking for wildfires and avalanches on record…",
  "Comparing the climate with its projection to 2050…",
  "Preparing your action plan…",
];

let app = null;
let params = null;       // {address, home, floor, who}
let data = null;         // the report view
let located = null;      // the point the address resolved to
let token = 0;
let abort = null;
let expanded = new Set();
let activePlan = "emergency";
let progressTimer = null;
let householdDraft = [];

// ------------------------------------------------------------------ helpers
const colour = (key) => FAMILY_COLOR[key] || "#F7F5EF";

function bars(key, score) {
  const lit = score == null ? 0 : Math.max(0, Math.min(BARS, Math.round((score / 100) * BARS)));
  return Array.from({ length: BARS }, (_, i) =>
    `<i style="background:${i < lit ? colour(key) : FAMILY_FADED[key]}"></i>`).join("");
}

const CHEVRON = `<svg class="chevron" width="14" height="14" viewBox="0 0 24 24" fill="none"
  stroke="rgba(247,245,239,0.6)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
  aria-hidden="true"><polyline points="6 9 12 15 18 9"></polyline></svg>`;

function planStoreKey() { return `pai:plan:${addressKey(params.address)}`; }
function checkedItems() { return new Set(store.get(planStoreKey(), [])); }

function linkify(text) {
  // Emergency numbers become phone links; everything else stays escaped text.
  return esc(text).replace(/\b(112|061)\b/g, '<a class="plain-link" href="tel:$1">$1</a>');
}

function segmentsHtml(segments) {
  return (segments || []).map((s) => {
    if (!s.url) return linkify(s.text);
    if (s.partner) {
      return `<a class="partner" href="${esc(s.url)}" target="_blank" rel="noopener sponsored"
        title="Partner">${esc(s.text)}</a>`;
    }
    return `<a class="plain-link" href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.text)}</a>`;
  }).join("");
}

function setStatus(text) { $("#risksStatus").textContent = text || ""; }

function stopProgress() {
  clearInterval(progressTimer);
  progressTimer = null;
  const p = $("#risksProgress");
  if (p) p.remove();
}

function startProgress() {
  stopProgress();
  let i = 0;
  const line = document.createElement("p");
  line.className = "risks-progress";
  line.id = "risksProgress";
  line.textContent = PROGRESS[0];
  $("#riskList").after(line);
  progressTimer = setInterval(() => {
    i = (i + 1) % PROGRESS.length;
    const el = $("#risksProgress");
    if (el) el.textContent = PROGRESS[i];
  }, 3200);
}

// ------------------------------------------------------------------ header
function renderHeader() {
  const typed = params.address;
  const [first, ...rest] = typed.split(",");
  const loc = located || (data && data.location);
  const line1 = (loc && loc.name && !/^-?\d/.test(loc.name) ? loc.name : first).trim();
  const town = (loc && loc.town) || rest.join(",").trim();
  const home = params.home ? homeLabel(params.home, params.floor) : "";
  const approx = loc && (loc.precision === "town" || loc.precision === "place" || loc.address_not_found);
  const note = ((data && data.notes) || []).find((n) => /^The (analysed point|address)/.test(n)) || "";
  $("#addrLine1").textContent = line1;
  $("#addrLine2").innerHTML = [esc(town), esc(home)].filter(Boolean).join(" · ")
    + (approx ? ` · <span class="approx" title="${esc(note)}">approximate location</span>` : "");
  const badge = $("#householdBadge");
  badge.hidden = !params.who.length;
  badge.textContent = String(params.who.length);
}

// ------------------------------------------------------------------ risks
function riskRowsLoading() {
  $("#riskList").innerHTML = ORDER.map((key) => `
    <div class="risk loading" data-family="${key}">
      <div class="risk-toggle" aria-hidden="true">
        <div class="risk-name"><span class="risk-dot" style="background:${colour(key)}"></span>
          <span class="risk-title">${NAMES[key]}</span></div>
        <div class="risk-right"><div class="bars">${bars(key, null)}</div>
          <span class="risk-value na">—</span>${CHEVRON}</div>
      </div>
    </div>`).join("");
}

function riskRow(risk) {
  const key = risk.key;
  const open = expanded.has(key);
  const value = risk.score == null ? "—" : `${risk.score}%`;
  const level = risk.level ? `, ${risk.level}` : "";
  const cards = (risk.cards || []).length > 1
    ? `<ul class="risk-cards">${risk.cards.map((c) => `<li><span>${esc(c.label)}</span><b>${c.score}%</b></li>`).join("")}</ul>`
    : "";
  const pressed = media.mode() === `risk:${key}`;
  return `
    <div class="risk" data-family="${key}">
      <button type="button" class="risk-toggle" id="risk-${key}-btn" aria-expanded="${open}"
        aria-controls="risk-${key}-body" aria-label="${esc(NAMES[key])}: ${esc(value)}${esc(level)}">
        <div class="risk-name"><span class="risk-dot" style="background:${colour(key)}"></span>
          <span class="risk-title">${NAMES[key]}</span></div>
        <div class="risk-right"><div class="bars" aria-hidden="true">${bars(key, risk.score)}</div>
          <span class="risk-value${risk.score == null ? " na" : ""}">${value}</span>${CHEVRON}</div>
      </button>
      <div class="risk-body" id="risk-${key}-body" ${open ? "" : "hidden"}>
        <p class="risk-desc">${esc(risk.summary || "Not assessed at this address.")}</p>
        ${risk.home_note ? `<p class="risk-home">${esc(risk.home_note)}</p>` : ""}
        ${cards}
        ${risk.illustration ? `<button type="button" class="risk-media" data-risk="${key}" aria-pressed="${pressed}">
          <svg width="9" height="10" viewBox="0 0 9 10" aria-hidden="true"><path d="M1 1v8l7-4z" fill="currentColor"></path></svg>
          What it could look like</button>` : ""}
      </div>
    </div>`;
}

function renderRisks() {
  const byKey = Object.fromEntries((data.risks || []).map((r) => [r.key, r]));
  $("#riskList").innerHTML = ORDER.filter((k) => byKey[k]).map((k) => riskRow(byKey[k])).join("");
}

function renderRiskError(message) {
  $("#riskList").innerHTML = `<div class="risks-error"><b>We could not analyse this address.</b>
    <span>${esc(message)}</span>
    <span><a href="/?address=${encodeURIComponent(params.address)}" data-nav>&larr; Edit address</a></span></div>`;
}

// ------------------------------------------------------------------ history
function renderHistoryLoading() {
  $("#history").innerHTML = [80, 64, 72, 56].map((w) => `<div class="skeleton-line" style="width:${w}%"></div>`).join("");
}

function renderHistory() {
  const h = data.history || {};
  const items = h.items || [];
  const summary = (h.summary || []).length ? `<p class="history-summary">${h.summary.map(esc).join(" · ")}</p>` : "";
  const rows = items.map((it) => `
    <li>
      <span class="h-date">${niceDate(it.date)}</span>
      <span class="h-dot" style="background:${colour(it.family)}" aria-hidden="true"></span>
      <div class="h-body">
        <span class="h-title">${esc(it.title)}</span>
        ${it.detail ? `<span class="h-detail">${esc(it.detail)}</span>` : ""}
      </div>
    </li>`).join("");
  $("#history").innerHTML = summary + (rows ? `<ul class="history-list">${rows}</ul>` : "")
    + (h.note ? `<p class="muted-note">${esc(h.note)}</p>` : "")
    + (!rows && !h.note ? `<p class="muted-note">No incidents on record near this address.</p>` : "");
}

// ------------------------------------------------------------------ action plan
function checkableIds(plan) {
  if (plan.key === "emergency") return plan.items.map((i) => i.id);
  return plan.phases.filter((p) => CHECKABLE.has(p.key)).flatMap((p) => p.items.map((i) => i.id));
}

function renderPlanTabs() {
  const plans = (data.action_plan || {}).plans || [];
  if (!plans.some((p) => p.key === activePlan)) activePlan = plans.length > 1 ? plans[1].key : "emergency";
  const done = checkedItems();
  $("#planTabs").innerHTML = plans.map((p) => {
    const ids = checkableIds(p);
    const n = ids.filter((id) => done.has(id)).length;
    return `<button type="button" class="tab" role="tab" data-plan="${esc(p.key)}" aria-controls="plan"
        aria-selected="${p.key === activePlan}">
      ${p.key !== "emergency" ? `<span class="dot" style="background:${colour(p.key)}"></span>` : ""}
      ${esc(p.label)}<span class="count">${n}/${ids.length}</span></button>`;
  }).join("");
}

function itemHtml(item, checkable, done) {
  if (!checkable) return `<li class="bullet"><span>${segmentsHtml(item.segments)}</span></li>`;
  return `<li><label class="check"><input type="checkbox" data-item="${esc(item.id)}"
    ${done.has(item.id) ? "checked" : ""}><span>${segmentsHtml(item.segments)}</span></label></li>`;
}

function renderPlan() {
  const ap = data.action_plan || {};
  const plans = ap.plans || [];
  const plan = plans.find((p) => p.key === activePlan) || plans[0];
  if (!plan) { $("#plan").innerHTML = `<p class="muted-note">No plan available.</p>`; return; }
  const done = checkedItems();
  if (plan.key === "emergency") {
    const household = (ap.household || []).length
      ? `<ul class="household-list">${ap.household.map((a) => `<li>${esc(a.text)}
          <span class="who">${a.profiles && a.profiles.length ? "· for your household" : ""}</span></li>`).join("")}</ul>`
      : "";
    $("#plan").innerHTML = `${household}<div class="emergency scroll"><ul>
      ${plan.items.map((i) => itemHtml(i, true, done)).join("")}</ul></div>`;
    return;
  }
  const note = plan.note ? `<p class="plan-note">${esc(plan.note)}</p>` : "";
  $("#plan").innerHTML = `${note}<div class="phases">${plan.phases.map((ph) => `
    <section class="phase" style="--phase-color:${colour(plan.key)}">
      <h3>${esc(ph.label)}</h3>
      <div class="scroll"><ul>${ph.items.map((i) => itemHtml(i, CHECKABLE.has(ph.key), done)).join("")}</ul></div>
    </section>`).join("")}</div>`;
}

function renderPlanLoading() {
  $("#planTabs").innerHTML = "";
  $("#plan").innerHTML = [70, 86, 60].map((w) => `<div class="skeleton-line" style="width:${w}%"></div>`).join("");
}

// ------------------------------------------------------------------ footer
function renderFooter() {
  $("#repFoot").textContent = "Risk levels are 0-100 hazard scores built from public scientific and official "
    + "data. They are not probabilities, valuations or insurance advice.";
}

// ------------------------------------------------------------------ household
function renderHouseholdChips() {
  $("#householdChips").innerHTML = PROFILES.map(([key, label]) =>
    `<button type="button" class="chip-toggle" data-profile="${key}" aria-pressed="${householdDraft.includes(key)}">${esc(label)}</button>`).join("");
}

function openHousehold(open) {
  const pop = $("#householdPop");
  pop.hidden = !open;
  $("#householdBtn").setAttribute("aria-expanded", String(open));
  if (open) {
    householdDraft = [...params.who];
    renderHouseholdChips();
    const first = pop.querySelector("button");
    if (first) first.focus();
  }
}

function applyHousehold() {
  params.who = [...householdDraft];
  store.set("pai:household", params.who);
  openHousehold(false);
  const url = new URL(window.location.href);
  if (params.who.length) url.searchParams.set("who", params.who.join(","));
  else url.searchParams.delete("who");
  history.replaceState({}, "", url);
  renderHeader();
  loadReport({ keepMedia: true });
}

// ------------------------------------------------------------------ loading
async function loadReport({ keepMedia = false } = {}) {
  const mine = ++token;
  if (abort) abort.abort();
  abort = new AbortController();
  if (!keepMedia) {
    riskRowsLoading();
    renderHistoryLoading();
  }
  renderPlanLoading();
  setStatus("");
  startProgress();
  try {
    data = await api.report({
      address: params.address, home: params.home, floor: params.floor,
      who: params.who.join(",") || undefined,
    }, abort.signal);
    if (mine !== token) return;
    stopProgress();
    renderHeader();
    renderRisks();
    media.setPreviews((data.risks || []).filter((r) => r.illustration).sort((a, b) => b.score - a.score));
    renderHistory();
    renderPlanTabs();
    renderPlan();
    renderFooter();
    if (!located) {
      located = data.location;
      media.setPlace({ lat: data.location.latitude, lon: data.location.longitude,
                       label: data.location.label, aerial: data.aerial, zoom: data.zoom });
    }
  } catch (err) {
    if (err.name === "AbortError" || mine !== token) return;
    stopProgress();
    renderRiskError(err.status === 404 ? err.message
      : "Our data sources are busy right now. Please try again in a few minutes.");
    $("#history").innerHTML = "";
    $("#plan").innerHTML = "";
    $("#planTabs").innerHTML = "";
    if (!located) media.error("We could not find this address.");
  }
}

async function locate() {
  const mine = token;
  try {
    const loc = await api.locate(params.address);
    if (mine !== token || located) return;
    located = loc;
    renderHeader();
    media.setPlace({ lat: loc.latitude, lon: loc.longitude, label: loc.label, aerial: loc.aerial,
                     zoom: loc.precision === "address" ? 18 : loc.precision === "street" ? 17 : 15 });
  } catch (_) {
    // The report call reports the problem.
  }
}

// ------------------------------------------------------------------ public
export function initReport(appRef) {
  app = appRef;
  media.init();
  media.onChange((mode) => {
    $$(".risk-media").forEach((b) => b.setAttribute("aria-pressed", String(mode === `risk:${b.dataset.risk}`)));
    // The risk being illustrated opens in the list, so the picture keeps its context.
    const shown = mode.startsWith("risk:") ? mode.slice(5) : null;
    if (shown && !expanded.has(shown) && $(`#risk-${shown}-body`)) {
      expanded.add(shown);
      $(`#risk-${shown}-btn`).setAttribute("aria-expanded", "true");
      $(`#risk-${shown}-body`).hidden = false;
    }
  });

  $("#riskList").addEventListener("click", (e) => {
    const toggle = e.target.closest(".risk-toggle");
    if (toggle && toggle.tagName === "BUTTON") {
      const key = toggle.closest(".risk").dataset.family;
      if (expanded.has(key)) expanded.delete(key); else expanded.add(key);
      const open = expanded.has(key);
      toggle.setAttribute("aria-expanded", String(open));
      $(`#risk-${key}-body`).hidden = !open;
      return;
    }
    const mediaBtn = e.target.closest(".risk-media");
    if (mediaBtn && data) {
      const risk = (data.risks || []).find((r) => r.key === mediaBtn.dataset.risk);
      if (media.mode() === `risk:${risk.key}`) media.showStreet();
      else media.showIllustration(risk);
    }
  });

  $("#planTabs").addEventListener("click", (e) => {
    const tab = e.target.closest(".tab");
    if (!tab || !data) return;
    activePlan = tab.dataset.plan;
    renderPlanTabs();
    renderPlan();
  });
  $("#planTabs").addEventListener("keydown", (e) => {
    if (!["ArrowRight", "ArrowLeft"].includes(e.key)) return;
    const tabs = $$(".tab", $("#planTabs"));
    const i = tabs.findIndex((t) => t.getAttribute("aria-selected") === "true");
    const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
    if (next) { next.click(); $(`.tab[data-plan="${next.dataset.plan}"]`).focus(); }
  });
  $("#plan").addEventListener("change", (e) => {
    const box = e.target.closest("input[data-item]");
    if (!box) return;
    const done = checkedItems();
    if (box.checked) done.add(box.dataset.item); else done.delete(box.dataset.item);
    store.set(planStoreKey(), [...done]);
    renderPlanTabs();
  });

  $("#householdBtn").addEventListener("click", (e) => {
    e.stopPropagation();
    openHousehold($("#householdPop").hidden);
  });
  $("#householdChips").addEventListener("click", (e) => {
    const chip = e.target.closest(".chip-toggle");
    if (!chip) return;
    const key = chip.dataset.profile;
    householdDraft = householdDraft.includes(key) ? householdDraft.filter((k) => k !== key) : [...householdDraft, key];
    chip.setAttribute("aria-pressed", String(householdDraft.includes(key)));
  });
  $("#householdClear").addEventListener("click", () => { householdDraft = []; renderHouseholdChips(); });
  $("#householdApply").addEventListener("click", applyHousehold);
  document.addEventListener("click", (e) => {
    if (!$("#householdPop").hidden && !e.target.closest("#householdPop") && !e.target.closest("#householdBtn")) {
      openHousehold(false);
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("#householdPop").hidden) { openHousehold(false); $("#householdBtn").focus(); }
  });

  $("#briefingBtn").addEventListener("click", () => {
    const loc = located || (data && data.location);
    if (!loc) return;
    media.startBriefing({
      lat: loc.latitude, lon: loc.longitude, label: loc.label, home: params.home,
      floor: params.floor || null, profile: params.who.join(",") || null,
    });
  });
  document.addEventListener("health", () => {
    const h = app.health;
    $("#briefingBtn").hidden = !(h && h.fal && h.fal.ffmpeg);
  });
}

export function showReport(search) {
  params = {
    address: (search.get("address") || "").trim(),
    home: search.get("home") === "apartment" ? "apartment" : (search.get("home") === "house" ? "house" : ""),
    floor: search.get("floor") ?? "",
    who: (search.get("who") || "").split(",").filter((k) => PROFILES.some(([p]) => p === k)),
  };
  data = null;
  located = null;
  expanded = new Set();
  activePlan = "emergency";
  $("#editLink").setAttribute("href",
    `/?${new URLSearchParams({ address: params.address, home: params.home || "house", floor: params.floor || "" })}`);
  $("#repFoot").innerHTML = "";
  openHousehold(false);
  const h = app && app.health;
  $("#briefingBtn").hidden = !(h && h.fal && h.fal.ffmpeg);
  renderHeader();
  media.reset();
  token++;
  loadReport();
  locate();
}
