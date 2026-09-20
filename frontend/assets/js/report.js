// The risk report: a sentence that sums the home up, the four risks, the plan to prepare
// and the basic emergency kit. Picking a risk shows its first steps and the products to
// buy for it, and turns the background to its colours. "Before" turns the page to what
// already happened near the home, and "2050" to how the climate behind each risk changes.
// A second page, "What this home needs", turns the plan's shopping steps into a kit of
// real products; a third, the basic emergency kit: what keeps working when the services stop.

import { api } from "./api.js";
import { media } from "./media.js";
import { $, $$, esc, setHtml, niceDate, PROFILES, store, homeLabel, addressKey, debounce } from "./util.js";

const ORDER = ["wildfire", "flood", "heat", "avalanche"];
const NAMES = { wildfire: "Fire", flood: "Flooding", heat: "Heat waves", avalanche: "Avalanches" };
const PLAN_STEPS = 6;    // the plan's steps in the card under the risks, as many as fit
const SHOP_ROWS = 4;     // the products beside them, as many as fit
const KIT_SIZE = 4;
const TAGS = { wildfire: "Fire", flood: "Flood", heat: "Heat", avalanche: "Avalanche", emergency: "Emergency" };
const COUNT = ["", "One thing", "Two things", "Three things", "Four things"];
const WORDS = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"];
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
const STAR_SVG = `<svg class="who-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#A6E22E"
  stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="8" r="3.6"></circle>
  <path d="M4.8 20c0-4 3.2-6.4 7.2-6.4s7.2 2.4 7.2 6.4"></path></svg>`;
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
let horizon = "today";   // "before", what already happened; the risks "today"; or around "2050"
let page = "risks";      // "risks"; "shop", what this home needs; or "kit", the basic emergency kit
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

// The steps of the summary: the emergency numbers, the first step against the worst risk,
// then the alerts; then the other risks' first steps and the rest of the emergency plan.
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
  return picks.slice(0, PLAN_STEPS);
}

// ------------------------------------------------------------------ who lives here
// The report answers with the household it used; before it comes back, what was picked.
// Naming them where the plan is means "Update plan" visibly changes something.
function householdWho() {
  const chosen = ((data && data.personalization) || {}).profile;
  if ((chosen || []).length) return chosen;
  return params.who.map((k) => (PROFILES.find(([key]) => key === k) || [k, k])[1]);
}

function householdLineHtml() {
  const who = householdWho();
  if (!who.length) return "";
  return `<p class="plan-who">${STAR_SVG}<span>Ranked for ${esc(who.join(" · ").toLowerCase())}
    <button type="button" class="plain-link" data-household-open>change</button></span></p>`;
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
  // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
  setHtml($("#addrLine2"), [esc(town), esc(home)].filter(Boolean).join(" · ")
    + (approx ? ` · <span class="approx" title="${esc(note)}">approximate location</span>` : ""));
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
  $("#heroGap").hidden = true;
  $("#heroTitle").textContent = "Checking flood, fire, avalanche and heat data for your area…";
  $("#heroText").textContent = PROGRESS[0];
  progressTimer = setInterval(() => {
    i = (i + 1) % PROGRESS.length;
    $("#heroText").textContent = PROGRESS[i];
  }, 3200);
}

// A source that did not answer leaves risks unmeasured. Saying so under the headline is
// the whole point: an empty tile the reader takes for a calm one is worse than no tile.
function gapLine(partial) {
  if (!partial) return "";
  const again = partial.retry ? ` We can analyse them again ${partial.retry}.` : "";
  return `${partial.note}${again}`;
}

function renderHero() {
  stopProgress();
  const head = horizon === "2050" && data.ahead ? data.ahead
    : horizon === "before" && data.past ? data.past : data.headline;
  $("#heroTitle").textContent = head.title;
  $("#heroText").textContent = head.text;
  const gap = gapLine(data.partial);
  $("#heroGap").textContent = gap;
  $("#heroGap").hidden = !gap;
}

function heroError(message) {
  stopProgress();
  $("#heroGap").hidden = true;
  $("#heroTitle").textContent = "We could not analyse this address.";
  // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
  setHtml($("#heroText"), `${esc(message)} <a class="text-link"
    href="/?address=${encodeURIComponent(params.address)}" data-nav>Edit the address</a>`);
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
  if (risk && horizon === "before" && data && data.past) return pastTileHtml(key, risk);
  const loading = !risk;
  const score = risk ? risk.score : null;
  const value = score == null ? "—" : `${score}%`;
  const dim = !loading && !risk.worth;
  // An unmeasured risk keeps its line even while dimmed: "—" on its own reads as a zero.
  const gap = !loading && risk.unavailable;
  const fact = loading ? '<span class="skeleton-line"></span>'
    : gap ? "No data for this address today."
    : !dim && risk.fact ? esc(risk.fact) : "";
  return `
    <button type="button" class="tile${dim ? " dim" : ""}${gap ? " gap" : ""}${loading ? " loading" : ""}" data-family="${key}"
      style="--grow:${grow(risk)}" aria-pressed="${active === key}"${loading ? " disabled" : ""}>
      <span class="tile-name"><span class="tile-dot" aria-hidden="true"></span>${NAMES[key]}</span>
      ${fact ? `<span class="tile-fact">${fact}</span>` : ""}
      <span class="tile-foot"><span class="tile-value">${value}</span>${tileIcon(key)}</span>
    </button>`;
}

// Worst first: the tiles read in the same order as their width. Ties and the
// loading state keep ORDER, so nothing jumps before the scores arrive.
function tileOrder(byKey) {
  return ORDER.slice().sort((a, b) => grow(byKey[b]) - grow(byKey[a]));
}

function renderTiles() {
  const byKey = Object.fromEntries(((data && data.risks) || []).map((r) => [r.key, r]));
  // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
  setHtml($("#tiles"), tileOrder(byKey).map((k) => tileHtml(k, byKey[k])).join(""));
}

// ------------------------------------------------------------------ detail card
function whenLabel(when) {
  return /^\d{4}-\d{2}-\d{2}/.test(when || "") ? niceDate(when) : when || "";
}

function stepHtml(item, done) {
  const id = `step-${item.id}`;
  return `<li class="step" data-fit><input type="checkbox" id="${esc(id)}" data-item="${esc(item.id)}"
    ${done.has(item.id) ? "checked" : ""}><label for="${esc(id)}">${segmentsHtml(item.segments)}</label></li>`;
}

// The steps that fit, and the link that opens the whole plan: every step of every plan,
// in the dialog, never another page.
function stepsColumn(title, items, all, link, planKey) {
  const done = checkedItems();
  return `
    <div class="col">
      <div class="col-head"><h2>${esc(title)}</h2>
        <span class="done-count">${doneCount(all)} of ${all.length} done</span></div>
      ${householdLineHtml()}
      <ul class="steps">${items.map((i) => stepHtml(i, done)).join("")}</ul>
      <button type="button" class="more" data-plan-open="${esc(planKey)}">${esc(link)}</button>
    </div>`;
}

function factHtml(f) {
  const icon = FACT_ICONS[f.icon || FAMILY_ICON[f.family]];
  return `<li data-family="${esc(f.family || "")}">${icon ? `<svg class="fact-icon" width="22" height="22"
    viewBox="0 0 24 24" fill="none" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"
    aria-hidden="true">${icon}</svg>` : ""}<b>${esc(f.number)}</b><span>${esc(f.text)}</span></li>`;
}

// Today: the plan, and the basic emergency kit beside it. What already happened near the
// home is the "Before" view's.
function summaryHtml() {
  const all = plans().flatMap(checkable);
  return stepsColumn("Your action plan", summarySteps(), all, "See the full plan →", "emergency")
    + kitHtml();
}

// ------------------------------------------------------------------ what to buy
// Beside the plan: with no risk picked, the basic emergency kit, our own list for every
// home, with what it costs in all and the button that buys it store by store; with a risk
// picked, the products its plan proposes, each linked to its store's own page.
function shopRowHtml(p, sponsored) {
  return `
    <li data-fit><a class="kit-row" href="${esc(p.url)}" target="_blank" rel="noopener${sponsored ? " sponsored" : ""}">
      <span class="kit-shot"><img src="${esc(p.image)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer"></span>
      <span class="kit-item"><b>${esc(p.name)}</b><span>${esc(p.what)}</span></span>
      <span class="kit-price"><b>${EUROS.format(p.price)}</b><small>${esc(p.store)} ↗</small></span></a></li>`;
}

function kitHtml() {
  const kit = advancedKit();
  if (!kit || !(kit.items || []).length) return "";
  return `
    <div class="col kit-col">
      <div class="col-head"><h2>Basic emergency kit</h2>
        <a class="col-link" href="${esc(pageHref("kit"))}" data-nav>See all ${kit.items.length} →</a></div>
      <ul class="kit-preview">${kit.items.slice(0, SHOP_ROWS).map((i) => shopRowHtml(i, true)).join("")}</ul>
      <div class="kit-buy">
        <div class="adv-total"><b>${EUROS_ROUND.format(kit.total)}</b><span>the whole kit</span></div>
        <button type="button" class="adv-cta" data-adv-buy>Buy the kit</button>
      </div>
    </div>`;
}

// The products a risk's plan proposes: the first for each thing to buy, then the others.
function riskProducts(plan) {
  const lists = buySteps(plan).map((i) => i.products);
  const out = [];
  for (let round = 0; lists.some((l) => l[round]); round++) {
    lists.forEach((l) => { if (l[round] && !out.some((p) => p.id === l[round].id)) out.push(l[round]); });
  }
  return out;
}

function riskShopHtml(risk) {
  const plan = plans().find((p) => p.key === risk.key);
  const list = plan ? riskProducts(plan) : [];
  if (!list.length) return kitHtml();
  const seen = ((data && data.action_plan) || {}).prices_seen;
  return `
    <div class="col kit-col">
      <div class="col-head"><h2>What to buy</h2>
        ${list.length > 1 ? `<button type="button" class="col-link" data-plan-open="${esc(risk.key)}">See all ${list.length} →</button>` : ""}</div>
      <ul class="kit-preview">${list.slice(0, SHOP_ROWS).map((p) => shopRowHtml(p, !!p.partner)).join("")}</ul>
      <p class="kit-note">Chosen for ${esc(NAMES[risk.key].toLowerCase())}. Each links to its store's own page${seen
        ? `; prices as seen on ${niceDate(seen)}, they change` : ""}.</p>
    </div>`;
}

// On a screen the report fills, the card never scrolls: the rows a column cannot hold go,
// from the last, so the plan shows as many steps as fit and the shop as many products.
function fitRows(el) {
  el.querySelectorAll(":scope > .col").forEach((col) => {
    const rows = [...col.querySelectorAll("[data-fit]")];
    for (let i = rows.length - 1; i > 0 && col.scrollHeight > col.clientHeight + 1; i--) rows[i].remove();
  });
}

function storyHtml(risk) {
  const rows = risk.story || [];
  return `
    <div class="col">
      <h2>${esc(risk.story_title)}</h2>
      ${rows.length ? `<ul class="story">${rows.map((r) =>
        `<li><span class="when">${esc(whenLabel(r.when))}</span><span class="what">${esc(r.text)}</span></li>`).join("")}</ul>`
        : `<p class="muted">Nothing on record near this address.</p>`}
    </div>`;
}

function riskStepsHtml(risk) {
  const plan = plans().find((p) => p.key === risk.key);
  if (!plan) return "";
  const all = checkable(plan);
  return stepsColumn("What to do first", all.slice(0, PLAN_STEPS), all,
    all.length > PLAN_STEPS ? `See all ${all.length} steps →` : "See the full plan →", risk.key);
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
  if (horizon === "2050" && data && data.ahead) renderFutureDetail();
  else if (horizon === "before" && data && data.past) renderPastDetail();
  else renderTodayDetail();
  fitRows($("#detail"));
}

function renderTodayDetail() {
  const el = $("#detail");
  const risk = active && data && (data.risks || []).find((r) => r.key === active);
  el.dataset.view = !risk ? "summary" : risk.worth ? "risk" : "calm";
  // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
  if (!risk) setHtml(el, summaryHtml());
  // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
  else if (!risk.worth) setHtml(el, calmHtml());
  // Today a risk shows its first steps and what to buy for it; its story is the "Before"
  // view's.
  // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
  else setHtml(el, riskStepsHtml(risk) + riskShopHtml(risk));
}

function detailLoading() {
  const col = [62, 88, 74, 80].map((w) => `<span class="skeleton-line" style="width:${w}%"></span>`).join("");
  $("#detail").dataset.view = "loading";
  // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
  setHtml($("#detail"), `<div class="col">${col}</div><div class="col">${col}</div>`);
}

function select(key) {
  active = active === key ? null : key;
  $("#report").dataset.active = active || "";
  $$(".tile", $("#tiles")).forEach((t) => t.setAttribute("aria-pressed", String(t.dataset.family === active)));
  renderDetail();
  media.select(active && data ? data.risks.find((r) => r.key === active) : null);
}

// Drops the risk picked without touching the card: the caller renders it again. The
// background and the pictures go back to the whole home.
function clearActive() {
  if (!active) return;
  active = null;
  $("#report").dataset.active = "";
  $$(".tile", $("#tiles")).forEach((t) => t.setAttribute("aria-pressed", "false"));
  media.select(null);
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

// The 2050 view only shows what changes: the plan is today's.
function futureSummaryHtml() {
  const items = data.ahead.highlights || [];
  return `
    <div class="col wide">
      <h2>What changes by 2050</h2>
      ${items.length ? `<ul class="facts ahead-facts">${items.map(factHtml).join("")}</ul>`
        : `<p class="muted">The climate models project little change here by 2050.</p>`}
      <p class="ahead-fine">${esc(data.ahead.scenario)}</p>
    </div>`;
}

function futureStoryHtml(key) {
  const f = ahead(key);
  const rows = f.rows || [];
  return `
    <div class="col wide">
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
    // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
    setHtml(el, futureSummaryHtml());
    return;
  }
  const f = ahead(risk.key);
  if (!f.available && !(f.notes || []).length && !risk.worth) {
    el.dataset.view = "calm";
    // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
    setHtml(el, `<div class="calm"><h2>Nothing to prepare for here</h2><p>${esc(f.fact)}</p></div>`);
    return;
  }
  el.dataset.view = "risk";
  // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
  setHtml(el, futureStoryHtml(risk.key));
}

// ------------------------------------------------------------------ before
// What already happened near the home, from the report's history: each risk's number on
// its tile; in the card, what stands out and the record, newest first, or a risk's story
// beside its own record.
function past(key) { return ((data && data.past && data.past.risks) || {})[key] || {}; }

function pastTileHtml(key, risk) {
  const p = past(key);
  const value = p.value == null ? "—" : `${esc(p.value)}${p.unit ? `<small>${esc(p.unit)}</small>` : ""}`;
  return `
    <button type="button" class="tile past${p.available ? "" : " dim"}" data-family="${key}"
      style="--grow:${grow(risk)}" aria-pressed="${active === key}">
      <span class="tile-name"><span class="tile-dot" aria-hidden="true"></span>${NAMES[key]}</span>
      ${p.fact ? `<span class="tile-fact">${esc(p.fact)}</span>` : ""}
      <span class="tile-foot"><span class="tile-value">${value}</span>${tileIcon(key)}</span>
    </button>`;
}

function recordHtml(rows, notes = [], empty = "Nothing on record near this address.") {
  const sources = [...new Set(rows.map((r) => r.source).filter(Boolean))];
  const title = (r) => (r.url
    ? `<a class="plain-link" href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title)}</a>` : esc(r.title));
  return `
    <div class="col">
      <div class="col-head"><h2>On record</h2><span class="done-count">Newest first</span></div>
      ${rows.length ? `<ul class="story record">${rows.map((r) => `
        <li><span class="when">${esc(whenLabel(r.date))}</span>
          <span class="what"><span class="dot" data-family="${esc(r.family)}" aria-hidden="true"></span>
            <span>${title(r)}${r.detail ? `<small>${esc(r.detail)}</small>` : ""}</span></span></li>`).join("")}</ul>`
        : `<p class="muted">${esc(empty)}</p>`}
      ${notes.map((n) => `<p class="ahead-fine">${esc(n)}</p>`).join("")}
      ${sources.length ? `<p class="ahead-fine">Sources: ${sources.map(esc).join(" · ")}.</p>` : ""}
    </div>`;
}

function pastSummaryHtml() {
  const h = data.history || {};
  const facts = h.highlights || [];
  return `
    <div class="col">
      <h2>What has happened around this home</h2>
      ${facts.length ? `<ul class="facts">${facts.map(factHtml).join("")}</ul>`
        : `<p class="muted">${esc(h.note || "No floods, wildfires or avalanches are on record near this address.")}</p>`}
      ${facts.length && h.note ? `<p class="ahead-fine">${esc(h.note)}</p>` : ""}
    </div>${recordHtml(h.items || [])}`;
}

function renderPastDetail() {
  const el = $("#detail");
  const risk = active && (data.risks || []).find((r) => r.key === active);
  if (!risk) {
    el.dataset.view = "summary";
    setHtml(el, pastSummaryHtml());
    return;
  }
  const p = past(risk.key);
  if (!(risk.story || []).length && !(p.record || []).length) {
    el.dataset.view = "calm";
    setHtml(el, `<div class="calm"><h2>Nothing on record here</h2><p>${esc(p.fact || "")}</p></div>`);
    return;
  }
  el.dataset.view = "risk";
  setHtml(el, storyHtml(risk) + recordHtml(p.record || [], p.notes || [], p.empty
    || "Nothing on record near this address."));
}

// ------------------------------------------------------------------ public money
// Grants, tax deductions and public cover that can pay for part of the plan, from the
// report's checked catalogue: who can apply, how much, until when, and the official page.
// The "Public programmes" button beside the horizons opens them, on the risk picked if any.
let grantsFamily = "all";
let grantsFocus = null;

function grants() { return (data && data.grants) || { items: [], groups: [], families: {} }; }

function grantsFor(key) {
  const items = grants().items || [];
  if (!key || key === "all") return items;
  return items.filter((g) => (g.families || []).includes(key));
}

function grantHtml(item) {
  const relevant = grants().families || {};
  const dots = (item.families || []).filter((f) => relevant[f]).map((f) =>
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
  // Only the risks that matter at this home get a tab.
  const families = ORDER.filter((k) => (g.families || {})[k] && grantsFor(k).length);
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
  // What does not exist here, said as plainly as what does.
  const gaps = (grantsFamily === "all" ? ORDER : [grantsFamily]).flatMap((k) =>
    (((g.families || {})[k] || {}).gaps || []).map((text) =>
      `<li><span class="dot" data-family="${esc(k)}" aria-hidden="true"></span><span>${esc(text)}</span></li>`));
  // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
  setHtml($("#grants"), `
    ${g.intro ? `<p class="plan-note">${esc(g.intro)}</p>` : ""}
    ${families.length > 1 ? `<div class="tabs" role="tablist" aria-label="Risks">${tabs}</div>` : ""}
    ${groups || `<p class="muted">No public programme for this risk here yet.</p>`}
    ${gaps.length ? `<section class="grant-group"><h3>Not available here</h3>
      <ul class="grant-gaps">${gaps.join("")}</ul></section>` : ""}
    ${g.note ? `<p class="plan-fine">${esc(g.note)}</p>` : ""}`);
}

function openGrants(key) {
  if (!data) return;
  grantsFamily = key || "all";
  const n = (grants().items || []).length;
  $("#grantsSub").textContent = grants().summary
    || `${n} programme${n === 1 ? "" : "s"} that can pay for part of the plan`;
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

// Before, Today and 2050 when the report has them, and the public money when a programme
// applies here.
function renderControls() {
  $("#heroControls").hidden = !data;
  if (!data) return;
  $('.horizon-btn[data-horizon="before"]').hidden = !data.past;
  $('.horizon-btn[data-horizon="2050"]').hidden = !data.ahead;
  $("#grantsBtn").hidden = !(grants().items || []).length;
  $("#grantsBtn").title = grants().summary || "";
}

function setHorizon(next) {
  const wanted = ["before", "2050"].includes(next) ? next : "today";
  // Before, today and 2050 answer different questions, so moving between them starts
  // from the whole home again rather than keeping the risk picked in the one before.
  if (wanted !== horizon) clearActive();
  horizon = wanted;
  $("#report").dataset.horizon = horizon;
  $$(".horizon-btn").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.horizon === horizon)));
  if (!data) return;
  renderHero();
  renderTiles();
  renderDetail();
}

// ------------------------------------------------------------------ full plan
// Every step of every plan, and nothing to buy: the products live outside the dialog,
// beside the risks ("What to buy") and on the pages that sell them.
function renderPlanTabs() {
  const all = plans();
  if (!all.some((p) => p.key === activePlan)) activePlan = "emergency";
  // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
  setHtml($("#planTabs"), all.map((p) => {
    const items = checkable(p);
    const label = p.key === "emergency" ? p.label : NAMES[p.key] || p.label;
    return `<button type="button" class="tab" role="tab" data-plan="${esc(p.key)}" aria-controls="plan"
        aria-selected="${p.key === activePlan}">
      ${p.key !== "emergency" ? `<span class="dot" data-family="${esc(p.key)}"></span>` : ""}
      ${esc(label)}<span class="count">${doneCount(items)}/${items.length}</span></button>`;
  }).join(""));
}

function planItemHtml(item, isCheckable, done) {
  if (!isCheckable) return `<li class="bullet"><span>${segmentsHtml(item.segments)}</span></li>`;
  return `<li><label class="check"><input type="checkbox" data-item="${esc(item.id)}"
    ${done.has(item.id) ? "checked" : ""}><span>${segmentsHtml(item.segments)}</span></label></li>`;
}

// The head of the dialog: what this plan is, how much of it is done, and who it was
// ranked for. The bar is the whole plan's, not the tab's, so closing a tab never looks
// like progress lost.
function renderPlanHead() {
  const all = plans().flatMap(checkable);
  const done = doneCount(all);
  const who = householdWho();
  const parts = [`${done} of ${all.length} steps done`];
  if (who.length) parts.push(`ranked for ${who.join(" · ").toLowerCase()}`);
  $("#planSub").textContent = parts.join(" · ");
  const bar = $("#planBar");
  bar.style.setProperty("--done", all.length ? `${Math.round((done / all.length) * 100)}%` : "0%");
  bar.setAttribute("aria-valuenow", String(all.length ? Math.round((done / all.length) * 100) : 0));
}

// What the household changes in the plan: the advice the report ranked for these people,
// with the ones written for them marked.
function householdBlockHtml(items) {
  if (!items.length) return "";
  const who = householdWho();
  return `
    <section class="household">
      <div class="household-head">
        ${STAR_SVG}<h3>For your household</h3>
        ${who.length ? `<span class="household-who">${esc(who.join(" · "))}</span>` : ""}
      </div>
      <ul>${items.map((a) => `<li${(a.profiles || []).length ? ' class="for-them"' : ""}>
        <span>${esc(a.text)}</span>
        ${a.hazard_label ? `<small>${esc(a.hazard_label)}</small>` : ""}</li>`).join("")}</ul>
    </section>`;
}

function renderPlan() {
  const ap = (data && data.action_plan) || {};
  const plan = plans().find((p) => p.key === activePlan) || plans()[0];
  if (!plan) { $("#plan").innerHTML = `<p class="muted">No plan available.</p>`; return; }
  renderPlanHead();
  const done = checkedItems();
  if (plan.key === "emergency") {
    const household = householdBlockHtml(ap.household || []);
    // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
    setHtml($("#plan"), `${household}<ul class="emergency">
      ${plan.items.map((i) => planItemHtml(i, true, done)).join("")}</ul>`);
    return;
  }
  const note = plan.note ? `<p class="plan-note">${esc(plan.note)}</p>` : "";
  // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
  setHtml($("#plan"), `${note}<div class="phases" data-family="${esc(plan.key)}">${plan.phases.map((ph) => `
    <section class="phase" data-phase="${esc(ph.key)}">
      <h3>${esc(ph.label)}</h3>
      <ul>${ph.items.map((i) => planItemHtml(i, CHECKABLE.has(ph.key), done)).join("")}</ul>
    </section>`).join("")}</div>`);
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

function pageHref(target) { return `/${{ shop: "shop", kit: "kit" }[target] || "report"}?${queryString()}`; }

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
  // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
  setHtml($("#freeList"), freeSteps().map((i) =>
    `<li>${TICK_SVG}<span>${segmentsHtml(i.segments)}</span></li>`).join(""));
  // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
  setHtml($("#shopGrid"), kit.map((p) => shopCardHtml(p, have.has(p.id))).join(""));
  const service = serviceHtml();
  // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
  setHtml($("#shopService"), service);
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

// ------------------------------------------------------------------ the basic emergency kit
// The same for every home: what keeps working with no power, no network and no shop open.
// Its items come from the report's catalogue; buying it opens them store by store.
let advFocus = null;

function advancedKit() { return (data && data.advanced_kit) || null; }

function advItemHtml(item) {
  return `
    <article class="pv-card adv-item">
      <div class="adv-shot"><img src="${esc(item.image)}" alt="${esc(item.alt)}" loading="lazy" decoding="async"></div>
      <div class="adv-body"><h3>${esc(item.name)}</h3><p>${esc(item.what)}</p></div>
      <div class="prod-price"><b>${EUROS.format(item.price)}</b><span>${esc(item.store)}</span></div>
      <a class="prod-buy adv-buy" href="${esc(item.url)}" target="_blank" rel="noopener sponsored">View at the store ↗</a>
    </article>`;
}

function renderKit() {
  const kit = advancedKit();
  if (!kit) {
    $("#advLead").textContent = "";
    setHtml($("#advGrid"), "");
    $("#advNote").textContent = "";
    return;
  }
  const n = kit.items.length;
  const many = WORDS[n] || String(n);
  $("#advLead").textContent = `${many} things that keep working with no electricity, no phone network and no `
    + "shop open. After a big fire or flood, that is the first 72 hours.";
  setHtml($("#advGrid"), kit.items.map(advItemHtml).join("") + `
    <div class="adv-summary">
      <div class="adv-summary-head">
        <span class="adv-summary-title">The whole kit</span>
        <span class="adv-summary-text">${esc(many)} items across ${esc((WORDS[kit.stores] || String(kit.stores)).toLowerCase())}
          stores, in one list you can shop at your own pace.</span>
      </div>
      <div class="adv-summary-foot">
        <div class="adv-total"><b>${EUROS_ROUND.format(kit.total)}</b><span>in total</span></div>
        <button type="button" class="adv-cta" data-adv-buy>Buy the kit</button>
      </div>
    </div>`);
  $("#advNote").textContent = `Indicative prices (${kit.priced}); the store's own price is the one that counts. `
    + `Store links are affiliate links: Previous AI earns a commission and you pay the same price. ${kit.note}`;
}

// One row per item, the same as everywhere else in the app: the store's photo, what it
// is, the price and the link that opens its page.
function advStoreRowHtml(item) {
  return `
    <li><a class="kit-row" href="${esc(item.url)}" target="_blank" rel="noopener sponsored">
      <span class="kit-shot"><img src="${esc(item.image)}" alt="" loading="lazy" decoding="async"
        referrerpolicy="no-referrer"></span>
      <span class="kit-item"><b>${esc(item.name)}</b><span>${esc(item.what)}</span></span>
      <span class="kit-price"><b>${EUROS.format(item.price)}</b><small>View ↗</small></span></a></li>`;
}

function openAdv() {
  const kit = advancedKit();
  if (!kit) return;
  const stores = [];
  kit.items.forEach((item) => {
    let s = stores.find((x) => x.name === item.store);
    if (!s) { s = { name: item.store, items: [] }; stores.push(s); }
    s.items.push(item);
  });
  $("#advSub").textContent = `${kit.items.length} items across ${stores.length} `
    + `store${stores.length === 1 ? "" : "s"} · each one opens at its own shop`;
  setHtml($("#advStores"), stores.map((s) => `
    <section class="adv-store">
      <div class="adv-store-head">
        <h3>${esc(s.name)}</h3>
        <span>${s.items.length} item${s.items.length > 1 ? "s" : ""} ·
          ${EUROS.format(s.items.reduce((t, i) => t + i.price, 0))}</span>
      </div>
      <ul class="kit-preview">${s.items.map(advStoreRowHtml).join("")}</ul>
    </section>`).join(""));
  // Buying the whole kit in one go. The checkout is not built yet, so the button does
  // nothing; when it is, this is where the purchase starts.
  setHtml($("#advFoot"), `
    <div class="adv-total"><b>${EUROS_ROUND.format(kit.total)}</b><span>the whole kit</span></div>
    <button type="button" class="adv-cta" data-buy-kit>Buy this kit</button>`);
  advFocus = document.activeElement;
  $("#advDialog").hidden = false;
  document.body.classList.add("modal-open");
  setTimeout(() => $("#advClose").focus(), 0);
}

function closeAdv() {
  if ($("#advDialog").hidden) return;
  $("#advDialog").hidden = true;
  if ($("#viewer").hidden && $("#planDialog").hidden && $("#grantsDialog").hidden) {
    document.body.classList.remove("modal-open");
  }
  if (advFocus && document.contains(advFocus)) advFocus.focus();
}

function showPage(next) {
  page = ["shop", "kit"].includes(next) ? next : "risks";
  $("#report").dataset.page = page;
  $("#risksPage").hidden = page !== "risks";
  $("#shopPage").hidden = page !== "shop";
  $("#kitPage").hidden = page !== "kit";
  $("#advancedLink").setAttribute("href", pageHref("kit"));
  const back = $("#editLink");
  if (page === "shop") {
    back.textContent = "← Back to your risks";
    back.setAttribute("href", pageHref("risks"));
    renderShop();
  } else if (page === "kit") {
    back.textContent = "← Back to your risks";
    back.setAttribute("href", pageHref("risks"));
    renderKit();
  } else {
    back.textContent = "← Edit address";
    back.setAttribute("href",
      `/?${new URLSearchParams({ address: params.address, home: params.home || "house", floor: params.floor || "" })}`);
    // The card fits its rows only while it shows.
    if (data) renderDetail();
  }
}

// ------------------------------------------------------------------ briefing
// A pinned home (backend/app/demo.py) already has its briefing rendered, and says so.
// Fetching it now, quietly, means pressing the button plays it instead of downloading
// it. It is the browser's own cache: a failure here costs nothing.
let preloaded = null;

function preloadBriefing() {
  const video = ((data && data.pinned) || {}).briefing_video;
  if (!video || preloaded === video) return;
  preloaded = video;
  fetch(video, { cache: "force-cache" }).catch(() => { /* it will be fetched when played */ });
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
  // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
  setHtml($("#householdChips"), PROFILES.map(([key, label]) =>
    `<button type="button" class="chip-toggle" data-profile="${key}" aria-pressed="${householdDraft.includes(key)}">${esc(label)}</button>`).join(""));
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
  const apply = $("#householdApply");
  apply.disabled = true;
  apply.textContent = "Updating…";
  openHousehold(false);
  const url = new URL(window.location.href);
  if (params.who.length) url.searchParams.set("who", params.who.join(","));
  else url.searchParams.delete("who");
  history.replaceState({}, "", url);
  renderHeader();
  loadReport({ keep: true }).finally(() => {
    apply.disabled = false;
    apply.textContent = "Update plan";
  });
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
    renderKit();
    renderControls();
    $("#pdfBtn").disabled = pdfBusy;
    const illustrated = (data.risks || []).filter((r) => r.illustration).sort((a, b) => b.score - a.score);
    media.setPreviews(illustrated);
    media.select(active ? data.risks.find((r) => r.key === active) : null);
    if (!located) {
      located = data.location;
      media.setPlace({ lat: data.location.latitude, lon: data.location.longitude,
                       label: data.location.label, aerial: data.aerial, zoom: data.zoom });
    }
    preloadBriefing();
  } catch (err) {
    if (err.name === "AbortError" || mine !== token) return;
    // The backend's own sentence when it wrote one: it knows whether the wait is minutes
    // or until tomorrow, and sending someone back too early is the same failure twice.
    heroError(err.detail || "Our data sources are busy right now. Please try again in a few minutes.");
    $("#tiles").innerHTML = "";
    $("#heroControls").hidden = true;
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
  } catch (err) {
    // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
    // The report call shows the problem to the user; this leaves a trace for developers.
    console.warn("Locating the address failed:", err);
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
  $("#grantsBtn").addEventListener("click", () => openGrants(active || "all"));
  $("#grantsDialog").addEventListener("click", (e) => {
    if (e.target.closest("[data-close]")) { closeGrants(); return; }
    const tab = e.target.closest("[data-grants-family]");
    if (tab) { grantsFamily = tab.dataset.grantsFamily; renderGrants(); }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("#grantsDialog").hidden) closeGrants();
  });

  $("#detail").addEventListener("click", (e) => {
    // The click must not reach the document listener that closes the popover again.
    if (e.target.closest("[data-household-open]")) { e.stopPropagation(); openHousehold(true); return; }
    if (e.target.closest("[data-adv-buy]")) { openAdv(); return; }
    const more = e.target.closest("[data-plan-open]");
    if (more) openPlan(more.dataset.planOpen);
  });
  $("#detail").addEventListener("change", onChecked);
  // A store photo that does not load leaves an empty frame, not a broken image.
  $("#detail").addEventListener("error", (e) => {
    const frame = e.target.closest && e.target.closest(".kit-shot");
    if (frame) frame.classList.add("broken");
  }, true);
  // On a desktop the card holds as many rows as the window allows, so it fits them again
  // when the window changes (a phone only changes height, as its address bar comes and goes).
  const desktop = window.matchMedia("(pointer: fine)");
  window.addEventListener("resize", debounce(() => {
    if (data && page === "risks" && desktop.matches) renderDetail();
  }, 150));
  $("#plan").addEventListener("change", onChecked);

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

  $("#kitPage").addEventListener("click", (e) => {
    if (e.target.closest("[data-adv-buy]")) openAdv();
  });
  $("#advDialog").addEventListener("click", (e) => {
    if (e.target.closest("[data-close]")) closeAdv();
  });
  // A store photo that does not load leaves an empty frame, not a broken image.
  $("#advStores").addEventListener("error", (e) => {
    const frame = e.target.closest && e.target.closest(".kit-shot");
    if (frame) frame.classList.add("broken");
  }, true);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("#advDialog").hidden) closeAdv();
  });

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
  // Moving between the pages of the same report keeps what is loaded.
  if (params && JSON.stringify(params) === JSON.stringify(next) && (data || token)) {
    closePlan();
    closeAdv();
    showPage(target);
    return;
  }
  params = next;
  data = null;
  located = null;
  active = null;
  activePlan = "emergency";
  setHorizon("today");
  $("#heroControls").hidden = true;
  closeGrants();
  $("#report").dataset.active = "";
  $("#editLink").setAttribute("href",
    `/?${new URLSearchParams({ address: params.address, home: params.home || "house", floor: params.floor || "" })}`);
  $("#repFoot").textContent = "";
  openHousehold(false);
  closePlan();
  closeAdv();
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
