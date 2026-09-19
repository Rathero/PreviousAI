// Entry point: two views, one page. "/" asks for the home; "/report?address=..." shows it.

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
  if (url.pathname === "/report" && url.searchParams.get("address")) {
    home.hidden = true;
    report.hidden = false;
    document.title = `${url.searchParams.get("address")} · Previous AI`;
    showReport(url.searchParams);
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
