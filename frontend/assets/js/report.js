// The risk report: a sentence that sums the home up, the four risks, what already
// happened near it and the plan to prepare. Picking a risk shows its story and its
// first steps, and turns the background to its colours.

import { api } from "./api.js";
import { media } from "./media.js";
import { $, $$, esc, niceDate, PROFILES, store, homeLabel, addressKey } from "./util.js";

const ORDER = ["wildfire", "flood", "heat", "avalanche"];
const NAMES = { wildfire: "Fire", flood: "Flooding", heat: "Heat waves", avalanche: "Avalanches" };
const SEGMENTS = 10;
const FIRST_STEPS = 3;
const CHECKABLE = new Set(["before", "buy", "first"]);
const PROGRESS = [
  "Reading decades of daily climate records…",
  "Checking the official flood maps…",
  "Looking for wildfires and avalanches on record…",
  "Comparing the climate with its projection to 2050…",
  "Preparing your action plan…",
];
const ICONS = {
  wildfire: '<path d="M12 3c3.2 3.4 5 6 5 8.8a5 5 0 0 1-10 0C7 9 8.8 6.4 12 3z"></path>'
    + '<path d="M12 13c1 1.1 1.6 2.1 1.6 3a1.6 1.6 0 0 1-3.2 0c0-.9.6-1.9 1.6-3z"></path>',
  flood: '<path d="M12 3.4c3 3.7 5 6.3 5 8.8a5 5 0 0 1-10 0c0-2.5 2-5.1 5-8.8z"></path>'
    + '<path d="M9.6 13.3a2.7 2.7 0 0 0 2.2 2.8"></path>',
  heat: '<circle cx="12" cy="12" r="4"></circle><path d="M12 2.4v2.3M12 19.3v2.3M2.4 12h2.3M19.3 12h2.3'
    + 'M5.2 5.2l1.6 1.6M17.2 17.2l1.6 1.6M18.8 5.2l-1.6 1.6M6.8 17.2l-1.6 1.6"></path>',
  avalanche: '<path d="M4.2 18.4 8.4 7.3l4.5-2.1 6.2 5-.9 8.2z"></path><path d="m8.4 7.3 4.2 3 6.5-.1M12.6 10.3v8.1"></path>',
};
const CHECK_SVG = `<svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="rgba(166,226,46,0.9)"
  stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"></path></svg>`;

let app = null;
let params = null;       // {address, home, floor, who}
let data = null;         // the report view
let located = null;      // the point the address resolved to
let token = 0;
let abort = null;
let active = null;       // the risk picked on the page
let horizon = "today";   // the risks as they are today, or around 2050
let activePlan = "emergency";
let progressTimer = null;
let householdDraft = [];

// ------------------------------------------------------------------ plan helpers
function planStoreKey() { return `pai:plan:${addressKey(params.address)}`; }
function checkedItems() { return new Set(store.get(planStoreKey(), [])); }

function plans() { return ((data && data.action_plan) || {}).plans || []; }

function checkable(plan) {
  if (plan.key === "emergency") return plan.items;
  return plan.phases.filter((p) => CHECKABLE.has(p.key)).flatMap((p) => p.items);
}

function doneCount(items) {
  const done = checkedItems();
  return items.filter((i) => done.has(i.id)).length;
}

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

// A product proposed for a step: the store's photo, what it is, the price and a direct
// link to the store's page. Photos load from the stores without a referrer.
const EUROS = new Intl.NumberFormat("en-IE", { style: "currency", currency: "EUR" });

function productHtml(p) {
  return `<a class="product" href="${esc(p.url)}" target="_blank" rel="noopener${p.partner ? " sponsored" : ""}">
    <span class="product-img"><img src="${esc(p.image)}" alt="" loading="lazy" decoding="async"
      referrerpolicy="no-referrer"></span>
    <span class="product-body">
      <span class="product-name">${esc(p.name)}</span>
      <span class="product-what">${esc(p.what)}</span>
      <span class="product-buy"><b>${EUROS.format(p.price)}</b> · ${esc(p.store)}<span aria-hidden="true"> →</span></span>
    </span></a>`;
}

function productsHtml(item) {
  const list = item.products || [];
  return list.length ? `<div class="products">${list.map(productHtml).join("")}</div>` : "";
}

function pricesNote(plan) {
  const items = plan.items || plan.phases.flatMap((ph) => ph.items);
  const seen = ((data && data.action_plan) || {}).prices_seen;
  if (!seen || !items.some((i) => (i.products || []).length)) return "";
  return `<p class="plan-fine">Products link to each store's own page. Prices as seen on
    ${niceDate(seen)}; they change.</p>`;
}

// The three steps of the summary: the emergency numbers, the first step against the
// worst risk, then the alerts; the other risks' first steps if there is room.
function summarySteps() {
  const all = plans();
  const emergency = all.find((p) => p.key === "emergency");
  const hazards = all.filter((p) => p.key !== "emergency");
  const picks = [];
  const add = (item) => { if (item && !picks.some((p) => p.id === item.id)) picks.push(item); };
  add(emergency && emergency.items[1]);
  if (hazards[0]) add(checkable(hazards[0])[0]);
  add(emergency && emergency.items[0]);
  hazards.slice(1).forEach((h) => add(checkable(h)[0]));
  ((emergency && emergency.items) || []).slice(2).forEach(add);
  return picks.slice(0, FIRST_STEPS);
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

// ------------------------------------------------------------------ hero
function stopProgress() {
  clearInterval(progressTimer);
  progressTimer = null;
}

function heroLoading() {
  stopProgress();
  let i = 0;
  $("#heroTitle").textContent = "Looking at this home…";
  $("#heroText").textContent = PROGRESS[0];
  progressTimer = setInterval(() => {
    i = (i + 1) % PROGRESS.length;
    $("#heroText").textContent = PROGRESS[i];
  }, 3200);
}

function renderHero() {
  stopProgress();
  const head = horizon === "2050" && data.ahead ? data.ahead : data.headline;
  $("#heroTitle").textContent = head.title;
  $("#heroText").textContent = head.text;
}

function heroError(message) {
  stopProgress();
  $("#heroTitle").textContent = "We could not analyse this address.";
  $("#heroText").innerHTML = `${esc(message)} <a class="text-link"
    href="/?address=${encodeURIComponent(params.address)}" data-nav>Edit the address</a>`;
}

// ------------------------------------------------------------------ tiles
function bars(score) {
  const lit = score == null || score <= 0 ? 0 : Math.max(1, Math.round(score / 10));
  return Array.from({ length: SEGMENTS }, (_, i) => `<i${i < lit ? ' class="on"' : ""}></i>`).join("");
}

function tileHtml(key, risk) {
  if (risk && horizon === "2050" && data && data.ahead) return futureTileHtml(key);
  const loading = !risk;
  const score = risk ? risk.score : null;
  const value = score == null ? "—" : `${score}%`;
  const dim = !loading && !risk.worth;
  return `
    <button type="button" class="tile${dim ? " dim" : ""}${loading ? " loading" : ""}" data-family="${key}"
      aria-pressed="${active === key}"${loading ? " disabled" : ""}>
      <span class="tile-main">
        <span class="tile-name"><span class="tile-dot" aria-hidden="true"></span>${NAMES[key]}</span>
        <span class="tile-value">${value}</span>
        <span class="tile-bars" aria-hidden="true">${bars(score)}</span>
        <span class="tile-fact">${loading ? '<span class="skeleton-line"></span>' : esc(risk.fact || "")}</span>
      </span>
      <svg class="tile-icon" width="58" height="58" viewBox="0 0 24 24" fill="none" stroke-width="1.1"
        stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[key]}</svg>
    </button>`;
}

function renderTiles() {
  const byKey = Object.fromEntries(((data && data.risks) || []).map((r) => [r.key, r]));
  $("#tiles").innerHTML = ORDER.map((k) => tileHtml(k, byKey[k])).join("");
}

// ------------------------------------------------------------------ detail card
function whenLabel(when) {
  return /^\d{4}-\d{2}-\d{2}/.test(when || "") ? niceDate(when) : when || "";
}

function stepHtml(item, done) {
  const id = `step-${item.id}`;
  return `<li class="step"><input type="checkbox" id="${esc(id)}" data-item="${esc(item.id)}"
    ${done.has(item.id) ? "checked" : ""}><label for="${esc(id)}">${segmentsHtml(item.segments)}</label></li>`;
}

function stepsColumn(title, items, all, link, planKey) {
  const done = checkedItems();
  return `
    <div class="col">
      <div class="col-head"><h2>${esc(title)}</h2>
        <span class="done-count">${doneCount(all)} of ${all.length} done</span></div>
      <ul class="steps">${items.map((i) => stepHtml(i, done)).join("")}</ul>
      <button type="button" class="more" data-plan-open="${esc(planKey)}">${esc(link)}</button>
    </div>`;
}

function summaryHtml() {
  const h = data.history || {};
  const facts = h.highlights || [];
  const left = `
    <div class="col">
      <h2>What has happened around this home</h2>
      ${facts.length ? `<ul class="facts">${facts.map((f) =>
        `<li><b>${esc(f.number)}</b><span>${esc(f.text)}</span></li>`).join("")}</ul>`
        : `<p class="muted">${esc(h.note || "No floods, wildfires or avalanches are on record near this address.")}</p>`}
    </div>`;
  const all = plans().flatMap(checkable);
  return left + stepsColumn("Your action plan", summarySteps(), all, "See the full plan →", "emergency");
}

function storyHtml(risk) {
  const rows = risk.story || [];
  return `
    <div class="col">
      <h2>${esc(risk.story_title)}</h2>
      ${rows.length ? `<ul class="story">${rows.map((r) =>
        `<li><span class="when">${esc(whenLabel(r.when))}</span><span class="what">${esc(r.text)}</span></li>`).join("")}</ul>`
        : `<p class="muted">Nothing on record near this address.</p>`}
      ${risk.illustration ? `<button type="button" class="more" data-illustration="${esc(risk.key)}">What it could look like →</button>` : ""}
    </div>`;
}

function riskStepsHtml(risk) {
  const plan = plans().find((p) => p.key === risk.key);
  if (!plan) return "";
  const all = checkable(plan);
  const first = all.slice(0, FIRST_STEPS);
  const rest = all.length - first.length;
  return stepsColumn("What to do first", first, all,
    rest > 0 ? `See the other ${rest} step${rest > 1 ? "s" : ""} →` : "See the full plan →", plan.key);
}

function calmHtml() {
  return `
    <div class="calm">
      ${CHECK_SVG}
      <h2>Nothing to prepare for here</h2>
      <p>This address scores at the bottom of the scale for this hazard, so your plan has no steps for it.</p>
    </div>`;
}

function renderDetail() {
  if (horizon === "2050" && data && data.ahead) { renderFutureDetail(); return; }
  const el = $("#detail");
  const risk = active && data && (data.risks || []).find((r) => r.key === active);
  el.dataset.view = !risk ? "summary" : risk.worth ? "risk" : "calm";
  if (!risk) el.innerHTML = summaryHtml();
  else if (!risk.worth) el.innerHTML = calmHtml();
  else el.innerHTML = storyHtml(risk) + riskStepsHtml(risk);
  addMoney(el, risk);
}

function detailLoading() {
  const col = [62, 88, 74, 80].map((w) => `<span class="skeleton-line" style="width:${w}%"></span>`).join("");
  $("#detail").dataset.view = "loading";
  $("#detail").innerHTML = `<div class="col">${col}</div><div class="col">${col}</div>`;
}

function select(key) {
  active = active === key ? null : key;
  $("#report").dataset.active = active || "";
  $$(".tile", $("#tiles")).forEach((t) => t.setAttribute("aria-pressed", String(t.dataset.family === active)));
  renderDetail();
  media.select(active && data ? data.risks.find((r) => r.key === active) : null);
}

// ------------------------------------------------------------------ 2050
// The same four risks around 2050: how the climate behind each one changes, from the
// report's projections. Scores, official maps and past events describe today, so the
// 2050 view shows the change and its numbers instead of a score.
function ahead(key) { return ((data && data.ahead && data.ahead.risks) || {})[key] || {}; }

const shiftNumber = (v) => String(Math.abs(v) >= 10 ? Math.round(v) : Math.round(v * 10) / 10);

function shiftHtml(bars) {
  const top = Math.max(bars.from.value, bars.to.value) || 1;
  const unit = bars.unit ? ` ${bars.unit}` : "";
  const row = (p, cls) => `
    <span class="shift-row${cls}"><span class="shift-label">${esc(p.label)}</span>
      <span class="shift-track"><i style="width:${Math.max(4, Math.round((p.value / top) * 100))}%"></i></span>
      <span class="shift-num">${esc(shiftNumber(p.value) + unit)}</span></span>`;
  return `<span class="tile-shift">${row(bars.from, "")}${row(bars.to, " to")}</span>`;
}

function futureTileHtml(key) {
  const f = ahead(key);
  const parts = /^([+−-]?\d+)\s*(.*)$/.exec(f.change || "");
  const value = !f.available ? "—"
    : parts ? `${esc(parts[1])}<small>${esc(parts[2])}</small>` : `<small class="word">${esc(f.change || "")}</small>`;
  const dim = !f.available || f.direction === "same";
  return `
    <button type="button" class="tile future${dim ? " dim" : ""}" data-family="${key}"
      aria-pressed="${active === key}">
      <span class="tile-main">
        <span class="tile-name"><span class="tile-dot" aria-hidden="true"></span>${NAMES[key]}</span>
        <span class="tile-value">${value}</span>
        ${f.bars ? shiftHtml(f.bars) : ""}
        <span class="tile-fact">${esc(f.fact || "")}</span>
      </span>
      <svg class="tile-icon" width="58" height="58" viewBox="0 0 24 24" fill="none" stroke-width="1.1"
        stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[key]}</svg>
    </button>`;
}

function futureSummaryHtml() {
  const items = data.ahead.highlights || [];
  const left = `
    <div class="col">
      <h2>What changes by 2050</h2>
      ${items.length ? `<ul class="facts ahead-facts">${items.map((f) =>
        `<li data-family="${esc(f.family)}"><b>${esc(f.number)}</b><span>${esc(f.text)}</span></li>`).join("")}</ul>`
        : `<p class="muted">The climate models project little change here by 2050.</p>`}
      <p class="ahead-fine">${esc(data.ahead.scenario)}</p>
    </div>`;
  const all = plans().flatMap(checkable);
  return left + stepsColumn("Your action plan", summarySteps(), all, "See the full plan →", "emergency");
}

function futureStoryHtml(key) {
  const f = ahead(key);
  const rows = f.rows || [];
  return `
    <div class="col">
      <h2>${esc(f.title)}</h2>
      ${rows.length ? `<ul class="ahead-rows" data-family="${esc(key)}">${rows.map((r) => `
        <li><span class="ahead-label">${esc(r.label)}</span>
          <span class="ahead-values"><b>${esc(r.from)}</b><span class="ahead-arrow" aria-hidden="true">→</span>
            <span class="visually-hidden">to</span><b>${esc(r.to)}</b>
            <span class="ahead-change">${esc(r.change)}</span></span></li>`).join("")}</ul>`
        : `<p class="muted">${esc(f.fact)}</p>`}
      ${(f.notes || []).map((n) => `<p class="ahead-fine">${esc(n)}</p>`).join("")}
      ${f.periods ? `<p class="ahead-fine">${esc(f.periods)} ${esc(data.ahead.scenario)}</p>` : ""}
    </div>`;
}

function renderFutureDetail() {
  const el = $("#detail");
  const risk = active && (data.risks || []).find((r) => r.key === active);
  if (!risk) {
    el.dataset.view = "summary";
    el.innerHTML = futureSummaryHtml();
    addMoney(el, null);
    return;
  }
  const f = ahead(risk.key);
  if (!f.available && !(f.notes || []).length && !risk.worth) {
    el.dataset.view = "calm";
    el.innerHTML = `<div class="calm"><h2>Nothing to prepare for here</h2><p>${esc(f.fact)}</p></div>`;
    return;
  }
  el.dataset.view = "risk";
  el.innerHTML = futureStoryHtml(risk.key) + (riskStepsHtml(risk) || `
    <div class="col">
      <h2>What to do first</h2>
      <p class="muted">Today this risk scores low here, so your plan has no steps for it yet.</p>
      <button type="button" class="more" data-plan-open="emergency">See the full plan →</button>
    </div>`);
  addMoney(el, risk);
}

// ------------------------------------------------------------------ public money
// Grants, tax deductions and public cover that can pay for part of the plan, from the
// report's checked catalogue: who can apply, how much, until when, and the official page.
let grantsFamily = "all";
let grantsFocus = null;

function grants() { return (data && data.grants) || { items: [], groups: [], families: {} }; }

function grantsFor(key) {
  const items = grants().items || [];
  if (!key || key === "all") return items;
  return items.filter((g) => (g.families || []).includes(key));
}

// The strip at the bottom of the card: how many programmes can pay for this.
function moneyHtml(key) {
  const g = grants();
  const text = key ? ((g.families || {})[key] || {}).text : g.summary;
  if (!text) return "";
  return `
    <button type="button" class="money" data-grants-open="${esc(key || "all")}">
      <span class="money-icon" aria-hidden="true">€</span>
      <span class="money-text">${esc(text)}</span>
      <span class="money-go">See which →</span>
    </button>`;
}

function addMoney(el, risk) {
  if (el.dataset.view === "calm") return;
  el.insertAdjacentHTML("beforeend", moneyHtml(risk ? risk.key : null));
}

function grantHtml(item) {
  const dots = (item.families || []).map((f) =>
    `<span class="dot" data-family="${esc(f)}" title="${esc(NAMES[f] || f)}"></span>`).join("");
  return `
    <article class="grant">
      <div class="grant-head">
        <h4>${esc(item.name)}</h4>
        <span class="grant-status" data-status="${esc(item.status)}">${esc(item.status_label)}</span>
      </div>
      <p class="grant-body">${esc(item.official_name ? `${item.official_name} · ${item.body}` : item.body)}</p>
      <p class="grant-amount">${esc(item.amount)}</p>
      <p class="grant-funds">${esc(item.funds)}</p>
      ${item.note ? `<p class="grant-note">${esc(item.note)}</p>` : ""}
      <div class="grant-foot">
        <span class="grant-dots">${dots}</span>
        <a class="plain-link" href="${esc(item.url)}" target="_blank" rel="noopener">Official page</a>
        ${item.ref ? `<span class="grant-ref">${esc(item.ref)}</span>` : ""}
      </div>
    </article>`;
}

function renderGrants() {
  const g = grants();
  const families = ORDER.filter((k) => grantsFor(k).length);
  if (grantsFamily !== "all" && !families.includes(grantsFamily)) grantsFamily = "all";
  const tabs = ["all", ...families].map((k) => `
    <button type="button" class="tab" role="tab" data-grants-family="${esc(k)}" aria-selected="${k === grantsFamily}">
      ${k !== "all" ? `<span class="dot" data-family="${esc(k)}"></span>` : ""}
      ${k === "all" ? "All" : NAMES[k]}<span class="count">${grantsFor(k).length}</span></button>`).join("");
  const list = grantsFor(grantsFamily);
  const groups = (g.groups || []).map((grp) => {
    const items = list.filter((i) => i.group === grp.key);
    if (!items.length) return "";
    return `
      <section class="grant-group">
        <h3>${esc(grp.label)}</h3>
        ${grp.note ? `<p class="grant-group-note">${esc(grp.note)}</p>` : ""}
        <div class="grant-list">${items.map(grantHtml).join("")}</div>
      </section>`;
  }).join("");
  $("#grants").innerHTML = `
    ${g.intro ? `<p class="plan-note">${esc(g.intro)}</p>` : ""}
    ${families.length > 1 ? `<div class="tabs" role="tablist" aria-label="Risks">${tabs}</div>` : ""}
    ${groups || `<p class="muted">No public programme for this risk here yet.</p>`}
    ${g.note ? `<p class="plan-fine">${esc(g.note)}</p>` : ""}`;
}

function openGrants(key) {
  if (!data) return;
  grantsFamily = key || "all";
  renderGrants();
  grantsFocus = document.activeElement;
  $("#grantsDialog").hidden = false;
  document.body.classList.add("modal-open");
  setTimeout(() => $("#grantsClose").focus(), 0);
}

function closeGrants() {
  if ($("#grantsDialog").hidden) return;
  $("#grantsDialog").hidden = true;
  if ($("#viewer").hidden && $("#planDialog").hidden) document.body.classList.remove("modal-open");
  if (grantsFocus && document.contains(grantsFocus)) grantsFocus.focus();
}

function setHorizon(next) {
  horizon = next === "2050" ? "2050" : "today";
  $("#report").dataset.horizon = horizon;
  $$(".horizon-btn").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.horizon === horizon)));
  if (!data) return;
  renderHero();
  renderTiles();
  renderDetail();
}

// ------------------------------------------------------------------ full plan
function renderPlanTabs() {
  const all = plans();
  if (!all.some((p) => p.key === activePlan)) activePlan = "emergency";
  $("#planTabs").innerHTML = all.map((p) => {
    const items = checkable(p);
    const label = p.key === "emergency" ? p.label : NAMES[p.key] || p.label;
    return `<button type="button" class="tab" role="tab" data-plan="${esc(p.key)}" aria-controls="plan"
        aria-selected="${p.key === activePlan}">
      ${p.key !== "emergency" ? `<span class="dot" data-family="${esc(p.key)}"></span>` : ""}
      ${esc(label)}<span class="count">${doneCount(items)}/${items.length}</span></button>`;
  }).join("");
}

function planItemHtml(item, isCheckable, done) {
  if (!isCheckable) return `<li class="bullet"><span>${segmentsHtml(item.segments)}</span></li>`;
  return `<li><label class="check"><input type="checkbox" data-item="${esc(item.id)}"
    ${done.has(item.id) ? "checked" : ""}><span>${segmentsHtml(item.segments)}</span></label>${productsHtml(item)}</li>`;
}

function renderPlan() {
  const ap = (data && data.action_plan) || {};
  const plan = plans().find((p) => p.key === activePlan) || plans()[0];
  if (!plan) { $("#plan").innerHTML = `<p class="muted">No plan available.</p>`; return; }
  const done = checkedItems();
  if (plan.key === "emergency") {
    const household = (ap.household || []).length
      ? `<section class="household"><h3>For your household</h3><ul>${ap.household.map((a) =>
        `<li>${esc(a.text)}</li>`).join("")}</ul></section>`
      : "";
    $("#plan").innerHTML = `${household}<ul class="emergency">
      ${plan.items.map((i) => planItemHtml(i, true, done)).join("")}</ul>${pricesNote(plan)}`;
    return;
  }
  const note = plan.note ? `<p class="plan-note">${esc(plan.note)}</p>` : "";
  $("#plan").innerHTML = `${note}<div class="phases" data-family="${esc(plan.key)}">${plan.phases.map((ph) => `
    <section class="phase" data-phase="${esc(ph.key)}">
      <h3>${esc(ph.label)}</h3>
      <ul>${ph.items.map((i) => planItemHtml(i, CHECKABLE.has(ph.key), done)).join("")}</ul>
    </section>`).join("")}</div>${pricesNote(plan)}`;
}

let planFocus = null;

function openPlan(key) {
  if (!data) return;
  activePlan = key || "emergency";
  renderPlanTabs();
  renderPlan();
  planFocus = document.activeElement;
  $("#planDialog").hidden = false;
  document.body.classList.add("modal-open");
  setTimeout(() => $("#planClose").focus(), 0);
}

function closePlan() {
  if ($("#planDialog").hidden) return;
  $("#planDialog").hidden = true;
  if ($("#viewer").hidden) document.body.classList.remove("modal-open");
  if (planFocus && document.contains(planFocus)) planFocus.focus();
}

function onChecked(e) {
  const box = e.target.closest("input[data-item]");
  if (!box) return;
  const done = checkedItems();
  if (box.checked) done.add(box.dataset.item); else done.delete(box.dataset.item);
  store.set(planStoreKey(), [...done]);
  // Both places show the same ticks and counts.
  const id = box.dataset.item;
  const inDetail = !!box.closest("#detail");
  renderDetail();
  if (!$("#planDialog").hidden) { renderPlanTabs(); renderPlan(); }
  const again = $(`${inDetail ? "#detail" : "#plan"} input[data-item="${CSS.escape(id)}"]`);
  if (again) again.focus();
}

// ------------------------------------------------------------------ PDF
let pdfBusy = false;

// Downloads the report as a PDF; on a phone, where people share rather than save, it
// opens the share sheet when the browser can share files.
async function sharePdf() {
  if (pdfBusy) return;
  pdfBusy = true;
  const label = $("#pdfLabel");
  $("#pdfBtn").disabled = true;
  label.textContent = "Preparing PDF…";
  try {
    const resp = await api.reportPdf({
      address: params.address, home: params.home, floor: params.floor,
      who: params.who.join(",") || undefined,
    });
    const blob = await resp.blob();
    const match = /filename="([^"]+)"/.exec(resp.headers.get("Content-Disposition") || "");
    const name = match ? match[1] : "previous-ai-report.pdf";
    const file = new File([blob], name, { type: "application/pdf" });
    const phone = window.matchMedia && window.matchMedia("(pointer: coarse)").matches;
    if (phone && navigator.canShare && navigator.canShare({ files: [file] })) {
      await navigator.share({ files: [file], title: document.title });
    } else {
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    }
    label.textContent = "PDF report";
  } catch (err) {
    // Closing the share sheet is not an error.
    label.textContent = err.name === "AbortError" ? "PDF report" : "PDF failed · try again";
  } finally {
    pdfBusy = false;
    $("#pdfBtn").disabled = !data;
  }
}

// ------------------------------------------------------------------ footer
function renderFooter() {
  $("#repFoot").textContent = "Risk levels are 0–100 hazard scores built from public scientific and official "
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
  loadReport({ keep: true });
}

// ------------------------------------------------------------------ loading
async function loadReport({ keep = false } = {}) {
  const mine = ++token;
  if (abort) abort.abort();
  abort = new AbortController();
  if (!keep) {
    renderTiles();
    detailLoading();
  }
  heroLoading();
  try {
    data = await api.report({
      address: params.address, home: params.home, floor: params.floor,
      who: params.who.join(",") || undefined,
    }, abort.signal);
    if (mine !== token) return;
    renderHeader();
    renderHero();
    renderTiles();
    renderDetail();
    renderFooter();
    $("#horizon").hidden = !data.ahead;
    $("#pdfBtn").disabled = pdfBusy;
    const illustrated = (data.risks || []).filter((r) => r.illustration).sort((a, b) => b.score - a.score);
    media.setPreviews(illustrated);
    media.select(active ? data.risks.find((r) => r.key === active) : null);
    if (!located) {
      located = data.location;
      media.setPlace({ lat: data.location.latitude, lon: data.location.longitude,
                       label: data.location.label, aerial: data.aerial, zoom: data.zoom });
    }
  } catch (err) {
    if (err.name === "AbortError" || mine !== token) return;
    heroError(err.status === 404 ? err.message
      : "Our data sources are busy right now. Please try again in a few minutes.");
    $("#tiles").innerHTML = "";
    $("#horizon").hidden = true;
    $("#detail").dataset.view = "empty";
    $("#detail").innerHTML = "";
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

  $("#tiles").addEventListener("click", (e) => {
    const tile = e.target.closest(".tile");
    if (tile && !tile.disabled && data) select(tile.dataset.family);
  });
  $("#horizon").addEventListener("click", (e) => {
    const btn = e.target.closest(".horizon-btn");
    if (btn) setHorizon(btn.dataset.horizon);
  });
  $("#detail").addEventListener("click", (e) => {
    const money = e.target.closest("[data-grants-open]");
    if (money) openGrants(money.dataset.grantsOpen);
  });
  $("#grantsDialog").addEventListener("click", (e) => {
    if (e.target.closest("[data-close]")) { closeGrants(); return; }
    const tab = e.target.closest("[data-grants-family]");
    if (tab) { grantsFamily = tab.dataset.grantsFamily; renderGrants(); }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("#grantsDialog").hidden) closeGrants();
  });

  $("#detail").addEventListener("click", (e) => {
    const more = e.target.closest("[data-plan-open]");
    if (more) { openPlan(more.dataset.planOpen); return; }
    const ill = e.target.closest("[data-illustration]");
    if (ill && data) media.showIllustration(data.risks.find((r) => r.key === ill.dataset.illustration));
  });
  $("#detail").addEventListener("change", onChecked);
  $("#plan").addEventListener("change", onChecked);
  // A store photo that does not load leaves an empty frame, not a broken image.
  $("#plan").addEventListener("error", (e) => {
    const frame = e.target.closest && e.target.closest(".product-img");
    if (frame) frame.classList.add("broken");
  }, true);

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
  $("#planDialog").addEventListener("click", (e) => {
    if (e.target.closest("[data-close]")) closePlan();
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
    if (e.key !== "Escape") return;
    if (!$("#householdPop").hidden) { openHousehold(false); $("#householdBtn").focus(); }
    else if (!$("#planDialog").hidden) closePlan();
  });

  $("#pdfBtn").addEventListener("click", sharePdf);

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
  active = null;
  activePlan = "emergency";
  setHorizon("today");
  $("#horizon").hidden = true;
  closeGrants();
  $("#report").dataset.active = "";
  $("#editLink").setAttribute("href",
    `/?${new URLSearchParams({ address: params.address, home: params.home || "house", floor: params.floor || "" })}`);
  $("#repFoot").textContent = "";
  openHousehold(false);
  closePlan();
  $("#pdfBtn").disabled = true;
  $("#pdfLabel").textContent = "PDF report";
  const h = app && app.health;
  $("#briefingBtn").hidden = !(h && h.fal && h.fal.ffmpeg);
  renderHeader();
  media.reset();
  token++;
  loadReport();
  locate();
}
