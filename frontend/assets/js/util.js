// Small helpers shared by the views.

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export const REDUCED_MOTION = !!(window.matchMedia &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches);

export const FAMILY_COLOR = {
  wildfire: "#E58A63", flood: "#7FB4DC", avalanche: "#C7CBD6", heat: "#E7C077",
  emergency: "#F7F5EF",
};
export const FAMILY_FADED = {
  wildfire: "rgba(229,138,99,0.22)", flood: "rgba(127,180,220,0.22)",
  avalanche: "rgba(199,203,214,0.22)", heat: "rgba(231,192,119,0.22)",
};

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
    try { window.localStorage.setItem(key, JSON.stringify(value)); } catch (_) { /* ignore */ }
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
