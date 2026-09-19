// Small helpers shared by the views.

import DOMPurify from "/vendor/dompurify/purify.es.js";

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Recommended by Norma — fixed with Claude Opus 5 via Claude Code
// Puts a template's markup into an element. The template escapes its values with esc();
// DOMPurify then drops whatever could still run (event handlers, javascript: links). It
// keeps target on links and referrerpolicy on store photos, which it drops by default.
const PURIFY = { ADD_ATTR: ["target", "referrerpolicy"] };

export function setHtml(el, html) {
  el.innerHTML = DOMPurify.sanitize(html, PURIFY);
}

export const REDUCED_MOTION = !!(window.matchMedia &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches);

export const PROFILES = [
  ["children", "Children"],
  ["older_adults", "Over-65s"],
  ["respiratory", "Asthma, lung or heart condition"],
  ["pregnancy", "Pregnancy"],
  ["reduced_mobility", "Reduced mobility"],
  ["outdoor", "Outdoor activities"],
];

// Storage can be unavailable (private windows, blocked site data): never let it break the page.
export const store = {
  get(key, fallback = null) {
    try {
      const v = window.localStorage.getItem(key);
      return v == null ? fallback : JSON.parse(v);
    } catch (_) { return fallback; }
  },
  set(key, value) {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch (err) {
      // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
      // Still never breaks the page, but a save that fails is no longer silent.
      console.warn("Could not save to this browser's storage:", err);
    }
  },
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// "2020-01-21" -> "21 Jan 2020"; "2012" -> "2012".
export function niceDate(iso) {
  if (!iso) return "";
  const m = /^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?/.exec(iso);
  if (!m) return esc(iso);
  if (!m[2]) return m[1];
  if (!m[3]) return `${MONTHS[+m[2] - 1]} ${m[1]}`;
  return `${+m[3]} ${MONTHS[+m[2] - 1]} ${m[1]}`;
}

export function ordinal(n) {
  const s = ["th", "st", "nd", "rd"], v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

export function homeLabel(kind, floor) {
  if (kind === "house") return "House";
  if (floor == null || floor === "") return "Apartment";
  const f = +floor;
  if (f < 0) return "Basement flat";
  if (f === 0) return "Ground-floor flat";
  return `${ordinal(f)}-floor flat`;
}

export function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

// A stable key for per-address conveniences (ticked plan items).
export function addressKey(text) {
  return String(text || "").toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, " ").trim();
}
