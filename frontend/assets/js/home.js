// The home address screen: address (typed, suggested or spoken), type of home and floor.

import { api } from "./api.js";
import { $, $$, esc, debounce, store, REDUCED_MOTION } from "./util.js";

let app = null;
let kind = "house";
let suggestAbort = null;
let suggestions = [];
let active = -1;

const MAX_RECORDING_MS = 15000;
let recorder = null;
let recTimer = null;

function setKind(next) {
  kind = next;
  $$(".pill[data-kind]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.kind === kind)));
  $("#floorField").hidden = kind !== "apartment";
}

function message(text, isError = false) {
  const el = $("#addressMsg");
  // Recommended by Norma — fixed with Claude Opus 5 via Claude Code
  // Plain text, never markup: callers pass their words unescaped.
  el.textContent = text || "";
  el.classList.toggle("error", !!isError);
}

// ------------------------------------------------------------------ suggestions
function closeSuggestions() {
  const list = $("#suggestions");
  list.hidden = true;
  list.innerHTML = "";
  suggestions = [];
  active = -1;
  $("#address").setAttribute("aria-expanded", "false");
  $("#address").removeAttribute("aria-activedescendant");
}

function renderSuggestions() {
  const list = $("#suggestions");
  if (!suggestions.length) return closeSuggestions();
  list.innerHTML = suggestions.map((s, i) => `
    <li role="option" id="sugg-${i}" data-i="${i}" aria-selected="${i === active}">
      <span class="s1">${esc(s.line1)}</span>${s.line2 ? `<span class="s2">${esc(s.line2)}</span>` : ""}
    </li>`).join("");
  list.hidden = false;
  $("#address").setAttribute("aria-expanded", "true");
  if (active >= 0) $("#address").setAttribute("aria-activedescendant", `sugg-${active}`);
}

function choose(i) {
  const s = suggestions[i];
  if (!s) return;
  $("#address").value = s.text;
  closeSuggestions();
  message("");
}

const fetchSuggestions = debounce(async (text) => {
  if (suggestAbort) suggestAbort.abort();
  if (text.trim().length < 3) return closeSuggestions();
  suggestAbort = new AbortController();
  try {
    const res = await api.suggest(text, suggestAbort.signal);
    if ($("#address").value !== text) return;
    suggestions = res.results || [];
    active = -1;
    if (document.activeElement === $("#address")) renderSuggestions();
  } catch (err) {
    if (err.name !== "AbortError") closeSuggestions();
  }
}, 220);

// ------------------------------------------------------------------ voice input
function voiceReady() {
  return !!(app.health && app.health.fal && app.health.fal.configured
    && navigator.mediaDevices && window.MediaRecorder);
}

function setMic(state) {
  const b = $("#mic");
  b.setAttribute("aria-pressed", String(state === "recording"));
  b.setAttribute("aria-busy", String(state === "busy"));
  b.setAttribute("aria-label", state === "recording" ? "Stop recording" : "Say your address instead of typing it");
}

async function sendRecording(blob) {
  setMic("busy");
  message("Transcribing…");
  try {
    const res = await api.transcribe(blob);
    if (!res.text) {
      message("No words were recognised. Try again, a little closer to the microphone.", true);
      return;
    }
    const text = res.text.replace(/[.。]+$/, "");
    $("#address").value = text;
    $("#address").focus();
    message(`Heard: “${text}”. Check it, then press See risks.`);
    fetchSuggestions(text);
  } catch (err) {
    message(`Voice input failed: ${err.message}`, true);
  } finally {
    setMic("idle");
  }
}

async function toggleRecording() {
  if (recorder && recorder.state === "recording") { recorder.stop(); return; }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    message("The microphone is not available. Type the address instead.", true);
    return;
  }
  const type = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"]
    .find((t) => MediaRecorder.isTypeSupported(t)) || "";
  const rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
  const chunks = [];
  rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
  rec.onstop = () => {
    clearTimeout(recTimer);
    stream.getTracks().forEach((t) => t.stop());
    recorder = null;
    setMic("idle");
    const blob = new Blob(chunks, { type: rec.mimeType || type || "audio/webm" });
    if (blob.size < 1500) { message("Nothing was heard. Try again, a little closer to the microphone.", true); return; }
    sendRecording(blob);
  };
  recorder = rec;
  rec.start();
  setMic("recording");
  message(`Listening… say the street, number and town, then press the microphone again.`);
  recTimer = setTimeout(() => { if (rec.state === "recording") rec.stop(); }, MAX_RECORDING_MS);
}

// ------------------------------------------------------------------ submit
function submit(e) {
  e.preventDefault();
  const input = $("#address");
  const address = input.value.trim();
  if (address.length < 3) {
    input.setAttribute("aria-invalid", "true");
    message("Tell us your home's address: street, number and town.", true);
    input.focus();
    return;
  }
  input.removeAttribute("aria-invalid");
  closeSuggestions();
  const params = new URLSearchParams({ address, home: kind });
  const floor = $("#floor").value.trim();
  if (kind === "apartment" && floor !== "") params.set("floor", String(Math.max(0, Math.round(+floor) || 0)));
  const who = store.get("pai:household", []);
  if (Array.isArray(who) && who.length) params.set("who", who.join(","));
  store.set("pai:lastHome", { address, home: kind, floor: kind === "apartment" ? floor : "" });
  app.navigate(`/report?${params}`);
}

export function initHome(appRef) {
  app = appRef;
  $$(".pill[data-kind]").forEach((b) => b.addEventListener("click", () => setKind(b.dataset.kind)));
  $("#homeForm").addEventListener("submit", submit);

  const input = $("#address");
  input.addEventListener("input", () => {
    input.removeAttribute("aria-invalid");
    if (!$("#addressMsg").classList.contains("error")) message("");
    fetchSuggestions(input.value);
  });
  input.addEventListener("keydown", (e) => {
    if ($("#suggestions").hidden) return;
    if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(active + 1, suggestions.length - 1); renderSuggestions(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(active - 1, 0); renderSuggestions(); }
    else if (e.key === "Enter" && active >= 0) { e.preventDefault(); choose(active); }
    else if (e.key === "Escape") { closeSuggestions(); }
  });
  input.addEventListener("blur", () => setTimeout(closeSuggestions, 160));
  $("#suggestions").addEventListener("mousedown", (e) => {
    const li = e.target.closest("li[data-i]");
    if (li) { e.preventDefault(); choose(+li.dataset.i); }
  });

  $("#mic").addEventListener("click", toggleRecording);
  document.addEventListener("health", () => { $("#mic").hidden = !voiceReady(); });
}

export function showHome(params) {
  const last = store.get("pai:lastHome", null) || {};
  const address = params.get("address") || last.address || "";
  const home = params.get("home") || last.home || "house";
  const floor = params.get("floor") ?? last.floor ?? "";
  $("#address").value = address;
  $("#floor").value = floor;
  setKind(home === "apartment" ? "apartment" : "house");
  message("");
  $("#mic").hidden = !voiceReady();
  const video = $("#homeVideo");
  if (REDUCED_MOTION) {
    video.removeAttribute("autoplay");
    video.pause();
  } else {
    video.play().catch(() => { /* autoplay can be refused: the poster stays */ });
  }
  if (!address) setTimeout(() => $("#address").focus(), 50);
}
