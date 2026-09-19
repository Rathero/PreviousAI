// The risk report: a sentence that sums the home up, the four risks, what already
// happened near it and the plan to prepare. Picking a risk shows its story and its
// first steps, and turns the background to its colours. A second page, "What this home
// needs", turns the plan's shopping steps into a kit of real products.

import { api } from "./api.js";
import { media } from "./media.js";
import { $, $$, esc, niceDate, PROFILES, store, homeLabel, addressKey } from "./util.js";

const ORDER = ["wildfire", "flood", "heat", "avalanche"];
const NAMES = { wildfire: "Fire", flood: "Flooding", heat: "Heat waves", avalanche: "Avalanches" };
const FIRST_STEPS = 3;
const KIT_SIZE = 4;
const TAGS = { wildfire: "Fire", flood: "Flood", heat: "Heat", avalanche: "Avalanche", emergency: "Emergency" };
const COUNT = ["", "One thing", "Two things", "Three things", "Four things"];
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
// The small icons next to the numbers of what happened.
const FACT_ICONS = {
  waves: '<path d="M3 8.2c1.8 1.7 3.6 1.7 5.4 0s3.6-1.7 5.4 0 3.6 1.7 5.4 0"></path>'
    + '<path d="M3 12.8c1.8 1.7 3.6 1.7 5.4 0s3.6-1.7 5.4 0 3.6 1.7 5.4 0"></path>'
    + '<path d="M3 17.4c1.8 1.7 3.6 1.7 5.4 0s3.6-1.7 5.4 0 3.6 1.7 5.4 0"></path>',
  flame: ICONS.wildfire,
  satellite: '<circle cx="12" cy="12" r="1.6"></circle><path d="M8.6 15.4a4.8 4.8 0 0 1 0-6.8M15.4 8.6a4.8 4.8 0 0 1 0 6.8"></path>'
    + '<path d="M5.8 18.2a8.8 8.8 0 0 1 0-12.4M18.2 5.8a8.8 8.8 0 0 1 0 12.4"></path>',
  mountain: ICONS.avalanche,
  sun: ICONS.heat,
  rain: ICONS.flood,
};
const FAMILY_ICON = { flood: "waves", wildfire: "flame", heat: "sun", avalanche: "mountain" };
const SHIELD_SVG = `<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#A6E22E" stroke-width="1.3"
  stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3.5 5.5 6v5.5c0 4.2 2.8 7.3 6.5 9 3.7-1.7 6.5-4.8 6.5-9V6z"></path>
  <path d="m9.3 12.2 1.9 1.9 3.6-3.6"></path></svg>`;
const TICK_SVG = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#A6E22E" stroke-width="2"
  stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"></path></svg>`;
// The service a home worth preparing for can ask a partner for, by its worst risk.
const SERVICES = {
  wildfire: { partner: "verisure", title: "Monitored alarm with smoke detection",
    text: "A monitoring centre watches the detectors and calls the fire brigade, even when you are away." },
  flood: { partner: "verisure", title: "Monitored alarm with a flood detector",
    text: "You are told the moment water reaches the detector, even when you are away." },
  avalanche: { partner: "applus", title: "Roof and structure inspection",
    text: "A certified engineer checks how the roof and the walls facing the slope would take the snow." },
  heat: { partner: "mitsubishi_electric", title: "A heat pump, installed",
    text: "It cools the home on the hottest days and heats it in winter, fitted by an installer." },
};

let app = null;
let params = null;       // {address, home, floor, who}
let data = null;         // the report view
let located = null;      // the point the address resolved to
let token = 0;
let abort = null;
let active = null;       // the risk picked on the page
let horizon = "today";   // the risks as they are today, or around 2050
let page = "risks";      // "risks", or "shop": what this home needs
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
const EUROS = new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR" });
const EUROS_ROUND = new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });

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
// Each tile is as wide as its score: the worst risks take the room.
function grow(risk) { return risk && risk.score != null ? risk.score : 1; }

function tileIcon(key) {
  return `<svg class="tile-icon" width="34" height="34" viewBox="0 0 24 24" fill="none" stroke-width="1.2"
    stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[key]}</svg>`;
}

function tileHtml(key, risk) {
  if (risk && horizon === "2050" && data && data.ahead) return futureTileHtml(key, risk);
  const loading = !risk;
  const score = risk ? risk.score : null;
  const value = score == null ? "—" : `${score}%`;
  const dim = !loading && !risk.worth;
  const fact = loading ? '<span class="skeleton-line"></span>' : !dim && risk.fact ? esc(risk.fact) : "";
  return `
    <button type="button" class="tile${dim ? " dim" : ""}${loading ? " loading" : ""}" data-family="${key}"
      style="--grow:${grow(risk)}" aria-pressed="${active === key}"${loading ? " disabled" : ""}>
      <span class="tile-name"><span class="tile-dot" aria-hidden="true"></span>${NAMES[key]}</span>
      ${fact ? `<span class="tile-fact">${fact}</span>` : ""}
      <span class="tile-foot"><span class="tile-value">${value}</span>${tileIcon(key)}</span>
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

function stepsColumn(title, items, all, link) {
  const done = checkedItems();
  return `
    <div class="col">
      <div class="col-head"><h2>${esc(title)}</h2>
        <span class="done-count">${doneCount(all)} of ${all.length} done</span></div>
      <ul class="steps">${items.map((i) => stepHtml(i, done)).join("")}</ul>
      <a class="more" href="${esc(pageHref("shop"))}" data-nav>${esc(link)}</a>
    </div>`;
}

function factHtml(f) {
  const icon = FACT_ICONS[f.icon || FAMILY_ICON[f.family]];
  return `<li data-family="${esc(f.family || "")}">${icon ? `<svg class="fact-icon" width="22" height="22"
    viewBox="0 0 24 24" fill="none" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"
    aria-hidden="true">${icon}</svg>` : ""}<b>${esc(f.number)}</b><span>${esc(f.text)}</span></li>`;
}

function summaryHtml() {
  const h = data.history || {};
  const facts = h.highlights || [];
  const left = `
    <div class="col">
      <h2>What has happened around this home</h2>
      ${facts.length ? `<ul class="facts">${facts.map(factHtml).join("")}</ul>`
        : `<p class="muted">${esc(h.note || "No floods, wildfires or avalanches are on record near this address.")}</p>`}
    </div>`;
  const all = plans().flatMap(checkable);
  return left + stepsColumn("Your action plan", summarySteps(), all, "See the full plan →");
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
    rest > 0 ? `See the other ${rest} step${rest > 1 ? "s" : ""} →` : "See the full plan →");
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

function futureTileHtml(key, risk) {
  const f = ahead(key);
  const parts = /^([+−-]?\d+)\s*(.*)$/.exec(f.change || "");
  const value = !f.available ? "—"
    : parts ? `${esc(parts[1])}<small>${esc(parts[2])}</small>` : `<small class="word">${esc(f.change || "")}</small>`;
  const dim = !f.available || f.direction === "same";
  return `
    <button type="button" class="tile future${dim ? " dim" : ""}" data-family="${key}"
      style="--grow:${grow(risk)}" aria-pressed="${active === key}">
      <span class="tile-name"><span class="tile-dot" aria-hidden="true"></span>${NAMES[key]}</span>
      ${f.fact ? `<span class="tile-fact">${esc(f.fact)}</span>` : ""}
      <span class="tile-foot"><span class="tile-value">${value}</span>${tileIcon(key)}</span>
    </button>`;
}

function futureSummaryHtml() {
  const items = data.ahead.highlights || [];
  const left = `
    <div class="col">
      <h2>What changes by 2050</h2>
      ${items.length ? `<ul class="facts ahead-facts">${items.map(factHtml).join("")}</ul>`
        : `<p class="muted">The climate models project little change here by 2050.</p>`}
      <p class="ahead-fine">${esc(data.ahead.scenario)}</p>
    </div>`;
  const all = plans().flatMap(checkable);
  return left + stepsColumn("Your action plan", summarySteps(), all, "See the full plan →");
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
      <a class="more" href="${esc(pageHref("shop"))}" data-nav>See the full plan →</a>
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

// ------------------------------------------------------------------ what this home needs
// The plan's shopping steps as a kit: one product for each thing to buy, taking turns
// between the risks worth preparing for (worst first), with the emergency kit filling any
// gap; the free steps that help most; and the service a partner offers for the worst risk.
function queryString() {
  return new URLSearchParams(Object.entries({
    address: params.address, home: params.home, floor: params.floor, who: params.who.join(","),
  }).filter(([, v]) => v !== "" && v != null)).toString();
}

function pageHref(target) { return `/${target === "shop" ? "shop" : "report"}?${queryString()}`; }

function haveKey() { return `pai:have:${addressKey(params.address)}`; }
function owned() { return new Set(store.get(haveKey(), [])); }

function buySteps(plan) {
  return plan.phases.filter((ph) => ph.key === "buy").flatMap((ph) => ph.items)
    .filter((i) => (i.products || []).length);
}

function kitProducts() {
  const all = plans();
  const lists = all.filter((p) => p.key !== "emergency").map((p) => ({ family: p.key, items: buySteps(p) }));
  const picks = [];
  const add = (item, family) => {
    const product = item.products[0];
    if (picks.length < KIT_SIZE && !picks.some((p) => p.id === product.id)) picks.push({ ...product, family });
  };
  for (let round = 0; picks.length < KIT_SIZE && lists.some((l) => l.items[round]); round++) {
    lists.forEach((l) => { if (l.items[round]) add(l.items[round], l.family); });
  }
  const emergency = all.find((p) => p.key === "emergency");
  ((emergency && emergency.items) || []).filter((i) => (i.products || []).length)
    .forEach((i) => add(i, "emergency"));
  return picks;
}

function freeSteps() {
  const all = plans();
  const picks = all.filter((p) => p.key !== "emergency").map((p) => {
    const before = p.phases.find((ph) => ph.key === "before");
    return before && before.items[0];
  }).filter(Boolean).slice(0, 2);
  const emergency = all.find((p) => p.key === "emergency");
  const spare = ((emergency && emergency.items) || []).filter((i) => !(i.products || []).length).reverse();
  spare.forEach((i) => { if (picks.length < 3) picks.push(i); });
  return picks.slice(0, 3);
}

function worthRisks() {
  return ((data && data.risks) || []).filter((r) => r.worth).sort((a, b) => b.score - a.score);
}

function shopCardHtml(p, have) {
  return `
    <article class="pv-card prod" data-family="${esc(p.family)}">
      <div class="prod-media">
        <img src="${esc(p.image)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer">
        <span class="prod-tag">${esc(TAGS[p.family] || "")}</span>
      </div>
      <div class="prod-body">
        <h3>${esc(p.name)}</h3>
        <p>${esc(p.what)}</p>
      </div>
      <div class="prod-price"><b>${EUROS.format(p.price)}</b><span>${esc(p.store)}</span></div>
      <a class="prod-buy" href="${esc(p.url)}" target="_blank" rel="noopener${p.partner ? " sponsored" : ""}">View at the store ↗</a>
      <button type="button" class="prod-have" data-have="${esc(p.id)}" aria-pressed="${have}">${have
        ? "✓ You have this one" : "I already have it"}</button>
    </article>`;
}

function serviceHtml() {
  const worst = worthRisks()[0];
  const service = worst && SERVICES[worst.key];
  const partner = service && (((data.action_plan || {}).partners) || {})[service.partner];
  if (!partner) return "";
  return `
    <div class="service-icon">${SHIELD_SVG}</div>
    <div class="service-body">
      <span class="service-title">${esc(service.title)}</span>
      <span class="service-text">${esc(service.text)}</span>
    </div>
    <div class="service-side">
      <div class="service-price"><b>Quote on request</b><span>${esc(partner.name)}</span></div>
      <a class="prod-buy service-cta" href="${esc(partner.url)}" target="_blank" rel="noopener sponsored">Request a quote ↗</a>
    </div>`;
}

function renderShop() {
  if (!data) {
    $("#shopTitle").textContent = "Looking at this home…";
    $("#shopText").textContent = "";
    $("#kitCount").textContent = "";
    $("#kitTotal").textContent = "";
    $("#freeList").innerHTML = "";
    $("#shopGrid").innerHTML = "";
    $("#shopService").hidden = true;
    $("#shopNote").textContent = "";
    return;
  }
  const have = owned();
  const kit = kitProducts();
  const missing = kit.filter((p) => !have.has(p.id));
  const total = missing.reduce((sum, p) => sum + p.price, 0);
  $("#shopTitle").textContent = missing.length
    ? `${COUNT[missing.length]} this home is missing.` : "This home has everything on the list.";
  const home = params.home === "apartment" ? "flat" : params.home === "house" ? "house" : "home";
  const risks = worthRisks().map((r) => `${NAMES[r.key].toLowerCase()} at ${r.score}%`);
  const chosen = risks.length
    ? `Chosen for a ${home} with ${risks.length > 1 ? `${risks.slice(0, -1).join(", ")} and ${risks[risks.length - 1]}` : risks[0]}.`
    : `Chosen for a ${home} where no risk stands out.`;
  $("#shopText").textContent = `${chosen} We earn a commission if you buy through these links — you pay the same price.`;
  $("#kitCount").textContent = `Your kit · ${missing.length} item${missing.length === 1 ? "" : "s"}`;
  $("#kitTotal").textContent = EUROS_ROUND.format(total);
  $("#freeList").innerHTML = freeSteps().map((i) =>
    `<li>${TICK_SVG}<span>${segmentsHtml(i.segments)}</span></li>`).join("");
  $("#shopGrid").innerHTML = kit.map((p) => shopCardHtml(p, have.has(p.id))).join("");
  const service = serviceHtml();
  $("#shopService").innerHTML = service;
  $("#shopService").hidden = !service;
  const seen = (data.action_plan || {}).prices_seen;
  $("#shopNote").textContent = `${seen ? `Prices as seen on each store's page on ${niceDate(seen)}; they change. ` : ""}`
    + "Store links are affiliate links: Previous AI earns a commission on purchases, and the price you pay is "
    + "the same. We choose what fits your risk report, not what pays most.";
}

function toggleHave(id) {
  const have = owned();
  if (have.has(id)) have.delete(id); else have.add(id);
  store.set(haveKey(), [...have]);
  renderShop();
  const again = $(`#shopGrid [data-have="${CSS.escape(id)}"]`);
  if (again) again.focus();
}

function showPage(next) {
  page = next === "shop" ? "shop" : "risks";
  $("#report").dataset.page = page;
  $("#risksPage").hidden = page !== "risks";
  $("#shopPage").hidden = page !== "shop";
  const back = $("#editLink");
  if (page === "shop") {
    back.textContent = "← Back to your risks";
    back.setAttribute("href", pageHref("risks"));
    renderShop();
  } else {
    back.textContent = "← Edit address";
    back.setAttribute("href",
      `/?${new URLSearchParams({ address: params.address, home: params.home || "house", floor: params.floor || "" })}`);
  }
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
    renderShop();
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
    $("#shopTitle").textContent = "We could not analyse this address.";
    $("#shopText").textContent = err.status === 404 ? err.message : "";
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

  $("#shopPage").addEventListener("click", (e) => {
    const have = e.target.closest("[data-have]");
    if (have) { toggleHave(have.dataset.have); return; }
    const full = e.target.closest("[data-plan-open]");
    if (full) openPlan(full.dataset.planOpen);
  });
  // A store photo that does not load leaves the tinted frame, not a broken image.
  $("#shopGrid").addEventListener("error", (e) => {
    const frame = e.target.closest && e.target.closest(".prod-media");
    if (frame) frame.classList.add("broken");
  }, true);

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

export function showReport(search, target = "risks") {
  const next = {
    address: (search.get("address") || "").trim(),
    home: search.get("home") === "apartment" ? "apartment" : (search.get("home") === "house" ? "house" : ""),
    floor: search.get("floor") ?? "",
    who: (search.get("who") || "").split(",").filter((k) => PROFILES.some(([p]) => p === k)),
  };
  // Moving between the two pages of the same report keeps what is loaded.
  if (params && JSON.stringify(params) === JSON.stringify(next) && (data || token)) {
    closePlan();
    showPage(target);
    return;
  }
  params = next;
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
  showPage(target);
  token++;
  loadReport();
  locate();
}
