// Entry point: two views, one page. "/" asks for the home; "/report?address=..." shows its
// risks, "/shop?address=..." what it needs and "/kit?address=..." the basic emergency kit,
// all from the same report.

import { api } from "./api.js";
import { initHome, showHome } from "./home.js";
import { initReport, showReport } from "./report.js";

export const app = {
  health: null,
  navigate(url, { replace = false } = {}) {
    if (replace) history.replaceState({}, "", url);
    else history.pushState({}, "", url);
    route();
  },
};

function route() {
  const url = new URL(window.location.href);
  const home = document.getElementById("home");
  const report = document.getElementById("report");
  const page = { "/report": "risks", "/shop": "shop", "/kit": "kit" }[url.pathname];
  if (page && url.searchParams.get("address")) {
    home.hidden = true;
    report.hidden = false;
    const prefix = { shop: "What this home needs · ", kit: "Basic emergency kit · " }[page] || "";
    document.title = `${prefix}${url.searchParams.get("address")} · Previous AI`;
    showReport(url.searchParams, page);
  } else {
    report.hidden = true;
    home.hidden = false;
    document.title = "Previous AI · Natural risks at your home";
    showHome(url.searchParams);
  }
  window.scrollTo(0, 0);
}

document.addEventListener("click", (e) => {
  const a = e.target.closest("a[data-nav]");
  if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) return;
  e.preventDefault();
  app.navigate(a.getAttribute("href"));
});
window.addEventListener("popstate", route);

async function boot() {
  initHome(app);
  initReport(app);
  route();
  try {
    app.health = await api.health();
  } catch (_) {
    app.health = null;
  }
  document.dispatchEvent(new CustomEvent("health", { detail: app.health }));
}

boot();
