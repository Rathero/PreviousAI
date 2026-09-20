// Thin wrappers over the backend API. Every call rejects with a readable message.

async function request(url, options = {}) {
  let resp;
  try {
    resp = await fetch(url, options);
  } catch (err) {
    if (err && err.name === "AbortError") throw err;
    throw new Error("The server is not responding. Check your connection and try again.");
  }
  let body = null;
  try { body = await resp.json(); } catch (_) { body = null; }
  if (!resp.ok) {
    const detail = body && (typeof body.detail === "string" ? body.detail : null);
    const error = new Error(detail || `The server answered ${resp.status}.`);
    error.status = resp.status;
    throw error;
  }
  return body;
}

const qs = (params) => new URLSearchParams(
  Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")).toString();

export const api = {
  health: () => request("/api/health"),
  suggest: (q, signal) => request(`/api/suggest?${qs({ q })}`, { signal }),
  locate: (q, signal) => request(`/api/locate?${qs({ q })}`, { signal }),
  report: (params, signal) => request(`/api/report?${qs(params)}`, { signal }),
  streetview: (lat, lon, signal) => request(`/api/streetview?${qs({ lat, lon })}`, { signal }),
  transcribe: (blob) => request("/api/transcribe", {
    method: "POST", headers: { "Content-Type": blob.type || "audio/webm" }, body: blob,
  }),
  briefingStart: (body) => request("/api/briefing", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  }),
  briefingStatus: (id) => request(`/api/briefing/${encodeURIComponent(id)}`),
  // The national analysis: the ranking, one municipality, and its exposed buildings.
  analysisRanking: (params, signal) => request(`/api/analysis/ranking?${qs(params)}`, { signal }),
  analysisMunicipality: (code, signal) =>
    request(`/api/analysis/municipality/${encodeURIComponent(code)}`, { signal }),
  analysisBuildings: (code, params, signal) =>
    request(`/api/analysis/buildings/${encodeURIComponent(code)}?${qs(params)}`, { signal }),
  // The PDF comes back as a file, not JSON: the raw response, or a readable error.
  reportPdf: async (params) => {
    let resp;
    try {
      resp = await fetch(`/api/report/pdf?${qs(params)}`);
    } catch (_) {
      throw new Error("The server is not responding. Check your connection and try again.");
    }
    if (!resp.ok) {
      let detail = null;
      try { detail = (await resp.json()).detail; } catch (_) { detail = null; }
      const error = new Error(typeof detail === "string" ? detail : `The server answered ${resp.status}.`);
      error.status = resp.status;
      throw error;
    }
    return resp;
  },
};
