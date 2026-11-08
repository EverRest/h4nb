// Page logic of h4nb-viz: run list, time slider, playback, keys, presentation mode, themes,
// movie recording and file export. Spec: specs/003-run-visualization (US1, US3, V6, FR-011).
// Drawing is in scene.js, plots in plots.js, export helpers in record.js and card.js.
import "./api.js"; // Reads the token from the fragment and adds it to the API requests. Load first.
import { FrameLoader, View, drawColorBar } from "./scene.js";
import { Plots } from "./plots.js";
import { Recorder, extensionFor, saveFile, stamp, uploadExport } from "./record.js";
import { drawCard } from "./card.js";
import { hasToken } from "./api.js";

const PLAY_FPS = 6; // Frames per second while playing.
const RUN_POLL_MS = 5000; // The run list is read again this often. A running run gets a new frame list at this rate.
const SERIES_MS = 15000; // A running run gets new curves this often.
const STATUS_MS = 5000; // The server status is read this often. Stop shows within about 20 s (ready check of 15 s).
const THEME_KEY = "h4nb-viz.theme";
const PLOTS_KEY = "h4nb-viz.plots";

const $ = (id) => document.getElementById(id);
const state = {
  view: null,
  plots: null,
  run: null,
  detail: null,
  loader: null,
  frame: null,
  index: 0,
  playing: false,
  presentation: false,
  recorder: null,
  ffmpeg: false,
  runState: null, // state of the selected run in /api/runs
  seriesSource: null, // "prometheus" or "files": the source of the last curves
  promStatus: undefined, // /api/status: { prometheus, prometheus_ok, grafana_url }. undefined: not read. null: failed.
};

function setStatus(text) {
  $("status").textContent = text;
}

// The second status line: the sources of the data.
function renderSources() {
  const prom = state.promStatus;
  let promText = null;
  if (prom === null) promText = "Prometheus: unknown";
  else if (prom) promText = prom.prometheus === null ? "Prometheus: not set" : `Prometheus: ${prom.prometheus_ok ? "on" : "off"}`;
  const series = state.seriesSource ? `Curves: ${state.seriesSource}` : "";
  $("sources").textContent = [promText, series].filter(Boolean).join(" · ");
  const link = $("grafana");
  const url = prom && prom.grafana_url;
  link.hidden = !(url && /^https?:\/\//.test(url)); // Only web links. A javascript: URL is not shown.
  if (!link.hidden) link.href = url;
}

async function fetchJson(url) {
  const response = await fetch(url);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
  return body;
}

// The run list. Names come from the server and are set with textContent, never as HTML.
function renderRuns(runs) {
  const list = $("run-list");
  list.replaceChildren();
  for (const run of runs) {
    const item = document.createElement("li");
    if (run.run === state.run) item.classList.add("selected");
    const button = document.createElement("button");
    button.textContent = run.run;
    button.addEventListener("click", () => selectRun(run.run).catch((e) => setStatus(e.message)));
    const info = document.createElement("small");
    const tags = [run.state, `${run.snapshots} snapshots`];
    if (run.thin) tags.push("thin");
    if (run.archive) tags.push("archive");
    info.textContent = tags.join(" · ");
    item.append(button, info);
    list.append(item);
  }
}

// A link with #run=<label> opens the run whose Prometheus label is the value (contracts/http-api.md).
function applyHash(runs) {
  const hash = window.location.hash;
  if (!hash.startsWith("#run=")) return;
  let value;
  try {
    value = decodeURIComponent(hash.slice("#run=".length));
  } catch (error) {
    setStatus("The run label in the link is not valid.");
    return;
  }
  const matches = runs.filter((r) => r.prom_label === value);
  if (matches.length === 1) {
    if (!state.view) {
      setStatus("The 3D view is not available in this browser, so the run cannot be shown.");
      return;
    }
    selectRun(matches[0].run).catch((e) => setStatus(e.message));
  } else if (matches.length === 0) {
    setStatus(`No run with label ${value} in this root directory. Check the root directory of h4nb-viz.`);
  } else {
    setStatus(`Several runs match ${value}.`);
  }
}

let hashChecked = false;

async function refreshRuns() {
  try {
    const runs = await fetchJson("/api/runs");
    renderRuns(runs);
    if (!hashChecked) {
      hashChecked = true;
      applyHash(runs);
    }
    const entry = runs.find((r) => r.run === state.run);
    state.runState = entry ? entry.state : null;
    if (state.runState === "running") await refreshFrames();
  } catch (error) {
    setStatus(error.message);
  }
}

// The frame list of the selected run. A running run gets new snapshots, so the slider follows them.
async function refreshFrames() {
  const run = state.run;
  const detail = await fetchJson(`/api/runs/${encodeURIComponent(run)}`);
  if (state.run !== run) return; // The user selected another run while this request was in flight.
  if (detail.frames.length === state.detail.frames.length) return;
  state.detail = detail;
  $("slider").max = String(Math.max(0, detail.frames.length - 1));
  document.body.classList.toggle("single", detail.frames.length <= 1);
  if (!state.frame && state.view && detail.frames.length > 0) await showFrame(0, true); // The first frame arrived.
}

// The curves of a running run. The plots are drawn again with the new samples.
let seriesBusy = false;

async function refreshSeries() {
  if (seriesBusy || !state.run || state.runState !== "running" || !state.detail) return;
  const run = state.run;
  seriesBusy = true;
  try {
    const source = await state.plots.load(run, state.detail.config.G);
    if (state.run === run && source !== null) {
      state.seriesSource = source;
      state.plots.setTime(state.detail.frames[state.index].time);
    }
  } catch (error) {
    // The server did not answer. The old curves stay on the page.
  } finally {
    seriesBusy = false;
  }
  renderSources();
}

// Read the server status: whether Prometheus answers, and the Grafana link.
async function readServerStatus() {
  try {
    state.promStatus = await fetchJson("/api/status");
    state.ffmpeg = Boolean(state.promStatus.ffmpeg);
  } catch (error) {
    state.promStatus = null;
    state.ffmpeg = false;
  }
  renderSources();
}

async function selectRun(name) {
  setStatus(`Loading ${name} ...`);
  const detail = await fetchJson(`/api/runs/${encodeURIComponent(name)}`);
  state.run = name;
  state.detail = detail;
  state.frame = null;
  state.loader = new FrameLoader({ run: name });
  const frames = detail.frames;
  document.body.classList.toggle("single", frames.length <= 1); // A single frame has no time controls.
  $("slider").max = String(Math.max(0, frames.length - 1));
  $("pres-name").textContent = name;
  if (frames.length === 0) {
    state.plots.clear(); // The curves of the previous run must not stay under this name.
    state.seriesSource = null;
    setStatus(`${name} has no snapshot.`);
    return;
  }
  await showFrame(0, true);
  try {
    const source = await state.plots.load(name, detail.config.G);
    if (source !== null && state.run === name) state.seriesSource = source;
  } catch (error) {
    state.plots.clear();
    state.seriesSource = null;
    setStatus(`Plots: ${error.message}`);
  }
  renderSources();
  setStatus(`${name} · ${frames.length} frames · N = ${detail.config.n || "?"}`);
  refreshRuns();
}

// Show one frame. The newest request wins, so a slow frame never replaces a newer one.
async function showFrame(index, fit = false) {
  const frames = state.detail.frames;
  state.index = index;
  $("slider").value = String(index);
  const time = frames[index].time;
  $("time").textContent = `t = ${time.toPrecision(5)}`;
  $("pres-time").textContent = `t = ${time.toPrecision(5)}`;
  state.plots.setTime(time);
  const frame = await state.loader.get(index);
  if (state.index !== index) return;
  state.frame = frame;
  state.view.setFrame(frame);
  if (fit) state.view.fit(frame.scale);
  updateColorBar();
  state.loader.prefetch([index + 1, index + 2].filter((i) => i < frames.length));
}

// Move to the frame nearest to a simulation time (a click on a plot).
function seekTime(time) {
  if (!state.detail || state.detail.frames.length === 0) return;
  let best = 0;
  state.detail.frames.forEach((frame, i) => {
    if (Math.abs(frame.time - time) < Math.abs(state.detail.frames[best].time - time)) best = i;
  });
  showFrame(best).catch((e) => setStatus(e.message));
}

function updateColorBar() {
  drawColorBar($("colorbar"));
  const [lo, hi] = state.view.range;
  $("range").textContent = `${lo.toPrecision(3)} … ${hi.toPrecision(3)}`;
}

function step(delta) {
  if (!state.detail || state.detail.frames.length === 0) return;
  const last = state.detail.frames.length - 1;
  let next = state.index + delta;
  if (next > last) next = state.presentation ? 0 : last;
  if (next < 0) next = 0;
  showFrame(next).catch((e) => setStatus(e.message));
}

function playTick() {
  if (!state.playing || !state.detail || state.detail.frames.length < 2) return;
  const last = state.detail.frames.length - 1;
  if (state.index >= last && !state.presentation) {
    state.playing = false;
    updatePlayButton();
    if (state.recorder) stopRecording();
    return;
  }
  step(1);
}

function togglePlay() {
  state.playing = !state.playing;
  updatePlayButton();
}

function updatePlayButton() {
  $("play").textContent = state.playing ? "Pause" : "Play";
}

async function togglePresentation(force) {
  const on = force === undefined ? !state.presentation : force;
  state.presentation = on;
  document.body.classList.toggle("presentation", on);
  if (on) {
    state.view.setPreset("fly");
    state.playing = true;
    updatePlayButton();
    if (document.documentElement.requestFullscreen) {
      document.documentElement.requestFullscreen().catch(() => {});
    }
  } else if (document.fullscreenElement) {
    document.exitFullscreen().catch(() => {});
  }
}

// Record one playback from the first frame to the last. The buffer is 1920 x 1080 during the recording.
function toggleRecording() {
  if (state.recorder) {
    stopRecording();
    return;
  }
  if (!state.detail || state.detail.frames.length < 2) {
    setStatus("Select a run with more than one frame to record.");
    return;
  }
  try {
    state.recorder = new Recorder($("view").querySelector("canvas"));
    state.view.setBufferSize(1920, 1080, 1);
    state.recorder.start();
  } catch (error) {
    state.recorder = null;
    state.view.restoreSize();
    setStatus(error.message);
    return;
  }
  $("record").textContent = "Stop recording";
  setStatus("Recording ...");
  showFrame(0).catch((e) => setStatus(e.message));
  state.playing = true;
  updatePlayButton();
}

async function stopRecording() {
  const recorder = state.recorder;
  state.recorder = null;
  state.playing = false;
  updatePlayButton();
  $("record").textContent = "Record";
  const { blob, mime } = await recorder.stop();
  state.view.restoreSize();
  const name = `${state.run}-${stamp()}.${extensionFor(mime)}`;
  try {
    const saved = await uploadExport(name, blob);
    const hint = !saved.mp4 && extensionFor(mime) === "webm" && !state.ffmpeg
      ? " MP4 needs ffmpeg on the PATH of the server."
      : "";
    setStatus(`Saved ${saved.path}.${hint}`);
  } catch (error) {
    saveFile(name, blob); // The server did not take it. Download it in the browser.
    setStatus(`Server did not save the movie (${error.message}). It was downloaded instead.`);
  }
}

function exportView() {
  const url = state.view.exportPng();
  saveFile(`${state.run || "view"}-${stamp()}.png`, url);
}

function exportCard() {
  if (!state.detail) return;
  const canvas = drawCard(state.detail, state.run);
  saveFile(`${state.run}-card.png`, canvas.toDataURL("image/png"));
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  if (state.view) state.view.setTheme(theme);
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch (error) {
    // Storage can be blocked. The theme then resets on reload, which is acceptable.
  }
}

// The plots can be hidden to give the 3D view more room. The choice is kept in the browser.
function plotsShown() {
  return !document.body.classList.contains("no-plots");
}

function setPlotsShown(shown) {
  document.body.classList.toggle("no-plots", !shown);
  $("plots-toggle").setAttribute("aria-pressed", String(shown));
  try {
    localStorage.setItem(PLOTS_KEY, shown ? "shown" : "hidden");
  } catch (error) {
    // Storage can be blocked. The choice then resets on reload.
  }
}

function savedPlots() {
  try {
    return localStorage.getItem(PLOTS_KEY) !== "hidden";
  } catch (error) {
    return true;
  }
}

function savedTheme() {
  try {
    return localStorage.getItem(THEME_KEY) === "light" ? "light" : "dark";
  } catch (error) {
    return "dark";
  }
}

function bindControls() {
  document.addEventListener("keydown", (event) => {
    const tag = event.target.tagName;
    if (tag === "SELECT" || (tag === "INPUT" && event.target.type !== "range")) return;
    switch (event.key) {
      case " ":
        event.preventDefault();
        togglePlay();
        break;
      case "ArrowLeft":
        step(-1);
        break;
      case "ArrowRight":
        step(1);
        break;
      case "p":
      case "P":
        togglePresentation();
        break;
      case "t":
      case "T":
        applyTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light");
        break;
      default:
        break;
    }
  });
  document.addEventListener("fullscreenchange", () => {
    if (!document.fullscreenElement && state.presentation) togglePresentation(false);
  });
  $("play").addEventListener("click", togglePlay);
  $("slider").addEventListener("input", (event) => {
    showFrame(Number(event.target.value)).catch((e) => setStatus(e.message));
  });
  $("present").addEventListener("click", () => togglePresentation());
  $("theme").addEventListener("click", () => applyTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light"));
  $("plots-toggle").addEventListener("click", () => setPlotsShown(!plotsShown()));
  $("record").addEventListener("click", toggleRecording);
  $("png-view").addEventListener("click", exportView);
  $("png-card").addEventListener("click", exportCard);
  for (const button of document.querySelectorAll("[data-preset]")) {
    button.addEventListener("click", () => state.view && state.view.setPreset(button.dataset.preset));
  }
  $("color").addEventListener("change", (event) => {
    if (!state.view) return;
    state.view.setMode(event.target.value);
    updateColorBar();
  });
}

function startLoop() {
  let last = performance.now();
  const frame = (now) => {
    state.view.animate((now - last) / 1000);
    last = now;
    requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}

function isArchiveName(name) {
  const lower = name.toLowerCase();
  return lower.endsWith(".tar.gz") || lower.endsWith(".tgz") || lower.endsWith(".tar");
}

async function uploadArchive(file) {
  if (!isArchiveName(file.name)) {
    setStatus("Drop a .tar.gz, .tgz or .tar archive from h4nb_pack.sh.");
    return;
  }
  setStatus(`Uploading ${file.name}…`);
  const response = await fetch(`/api/archive?name=${encodeURIComponent(file.name)}`, {
    method: "POST",
    headers: { "Content-Type": "application/octet-stream" },
    body: file,
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
  const names = (body.runs || []).join(", ") || "(no runs with config.used)";
  setStatus(`Archive loaded: ${names}`);
  await refreshRuns();
}

function bindArchiveDrop() {
  // Drag and drop of a pack archive (FR-015 / T032). The file goes to the cache, not into a run directory.
  document.addEventListener("dragover", (event) => {
    if (![...event.dataTransfer.types].includes("Files")) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  });
  document.addEventListener("drop", (event) => {
    const file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
    if (!file) return;
    event.preventDefault();
    uploadArchive(file).catch((e) => setStatus(e.message));
  });
}

function main() {
  applyTheme(savedTheme());
  setPlotsShown(savedPlots());
  bindControls();
  bindArchiveDrop();
  if (!hasToken()) {
    setStatus("No access token in this tab. Open the link that the server printed.");
    return;
  }
  state.plots = new Plots($("plots"), { onSeek: seekTime });
  readServerStatus();
  try {
    state.view = new View($("view"));
  } catch (error) {
    setStatus(`${error.message}. The 3D view is not available in this browser.`);
    refreshRuns();
    return;
  }
  applyTheme(document.documentElement.dataset.theme);
  startLoop();
  refreshRuns();
  setInterval(refreshRuns, RUN_POLL_MS);
  setInterval(refreshSeries, SERIES_MS);
  setInterval(readServerStatus, STATUS_MS);
  setInterval(playTick, 1000 / PLAY_FPS);
  setStatus("Select a run. Drop a pack archive to open it.");
}

main();
