// Page logic of h4nb-viz: run list, time slider, playback, keys, presentation mode, themes,
// movie recording and file export. Spec: specs/003-run-visualization (US1, US3, V6, FR-011).
// Drawing is in scene.js, plots in plots.js, export helpers in record.js and card.js.
import "./api.js"; // Adds the token to the API requests. Must load first.
import { FrameLoader, View, drawColorBar } from "./scene.js";
import { Plots } from "./plots.js";
import { Recorder, extensionFor, saveFile, stamp, uploadExport } from "./record.js";
import { drawCard } from "./card.js";

const PLAY_FPS = 6; // Frames per second while playing.
const RUN_POLL_MS = 5000; // The run list is read again this often.
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
};

function setStatus(text) {
  $("status").textContent = text;
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
    info.textContent = `${run.state} · ${run.snapshots} snapshots`;
    item.append(button, info);
    list.append(item);
  }
}

async function refreshRuns() {
  try {
    renderRuns(await fetchJson("/api/runs"));
  } catch (error) {
    setStatus(error.message);
  }
}

async function selectRun(name) {
  setStatus(`Loading ${name} ...`);
  const detail = await fetchJson(`/api/runs/${encodeURIComponent(name)}`);
  state.run = name;
  state.detail = detail;
  state.loader = new FrameLoader({ run: name });
  const frames = detail.frames;
  document.body.classList.toggle("single", frames.length <= 1); // A single frame has no time controls.
  $("slider").max = String(Math.max(0, frames.length - 1));
  $("pres-name").textContent = name;
  if (frames.length === 0) {
    setStatus(`${name} has no snapshot.`);
    return;
  }
  await showFrame(0, true);
  try {
    await state.plots.load(name, detail.config.G);
  } catch (error) {
    setStatus(`Plots: ${error.message}`);
  }
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

async function readServerStatus() {
  try {
    state.ffmpeg = Boolean((await fetchJson("/api/status")).ffmpeg);
  } catch (error) {
    state.ffmpeg = false;
  }
}

function main() {
  applyTheme(savedTheme());
  setPlotsShown(savedPlots());
  bindControls();
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
  setInterval(playTick, 1000 / PLAY_FPS);
  setStatus("Select a run.");
}

main();
