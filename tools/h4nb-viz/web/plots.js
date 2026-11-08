// Accuracy and speed plots of h4nb-viz (D1 to D5). The curves come from /api/runs/{run}/series.
// Spec: specs/003-run-visualization, "Accuracy and performance", FR-014.
import uPlot from "./vendor/uPlot.esm.js";
import { saveFile } from "./record.js";

const PANEL_HEIGHT = 170;
const COLORS = ["#f0a030", "#5fb3ff", "#e0e0e0", "#7fd17f"];
const INCOMPLETE_COLOR = "#ff6b6b";

// Each panel names its series. `log` puts the y axis on a log scale. `right` is a second y axis
// (`range` is optional, the default is automatic). `bars` lists the series drawn as bars.
const PANELS = [
  {
    id: "D1",
    title: "Relative energy error",
    names: ["energy_rel_err", "dissipated_work"],
    yLabel: "relative error, dimensionless",
    log: true,
    dashed: ["dissipated_work"],
  },
  {
    id: "D2",
    title: "Error per reference period",
    names: ["period_max_rel_err", "period_incomplete"],
    yLabel: "max relative error per period",
    log: true,
    bars: ["period_max_rel_err", "period_incomplete"],
    colors: { period_incomplete: INCOMPLETE_COLOR },
    xName: "period",
  },
  {
    id: "D3",
    title: "Momentum and angular momentum drift",
    names: ["momentum_rel_change", "angular_momentum_rel_change"],
    yLabel: "relative change, dimensionless",
    log: true,
  },
  {
    id: "D4",
    title: "Time steps and closest approach",
    names: ["dt_min", "dt_mean", "dt_max", "r_min"],
    yLabel: "time step",
    log: true,
    right: { name: "r_min", label: "r_min" },
  },
  {
    id: "D5",
    title: "Speed and progress",
    names: ["pairs_per_second", "progress_ratio"],
    yLabel: "pairs per second",
    right: { name: "progress_ratio", label: "progress, dimensionless", range: [0, 1] },
  },
];

// Series that are fetched but not drawn on their own.
const HELPER_SERIES = ["period_complete"];

const LABELS = {
  energy_rel_err: "relative error",
  dissipated_work: "W_diss",
  period_max_rel_err: "max error per period",
  period_incomplete: "incomplete period",
  momentum_rel_change: "dP / P",
  angular_momentum_rel_change: "dL / L",
  dt_min: "dt_min",
  dt_mean: "dt_mean",
  dt_max: "dt_max",
  r_min: "r_min",
  pairs_per_second: "pairs/s",
  progress_ratio: "progress",
};

function tooltipText(u, panel, metrics) {
  const idx = u.cursor.idx;
  if (idx === null || idx === undefined) return "";
  const xName = panel.xName === "period" ? "period" : "t";
  const lines = [`${xName} = ${u.data[0][idx].toPrecision(5)}`];
  panel.names.forEach((name, i) => {
    const value = u.data[i + 1][idx];
    if (value === null || value === undefined) return;
    lines.push(`${LABELS[name]}: ${value.toPrecision(4)}  [${metrics[name]}]`);
  });
  return lines.join("\n");
}

// Join the series of a panel on one x axis. A missing point is null, so a gap stays a gap.
function joinSeries(panel, series) {
  const present = panel.names.filter((name) => series[name]);
  const tables = present.map((name) => [
    series[name].x,
    series[name].y.map((v) => (panel.log && !(v > 0) ? null : v)),
  ]);
  return { present, data: tables.length === 1 ? tables[0] : uPlot.join(tables) };
}

// Range of a log axis: whole decades around the data. The automatic range can fail for very small values.
function logRange(u, lo, hi) {
  if (!(lo > 0) || !(hi > 0)) return [1e-16, 1];
  const a = Math.pow(10, Math.floor(Math.log10(lo)));
  const b = Math.pow(10, Math.ceil(Math.log10(hi)));
  return a === b ? [a / 10, b * 10] : [a, b];
}

// One tick per decade. uPlot's own log ticks loop forever for values below about 1e-15 (rounding),
// so the ticks are set here.
function logSplits(u, axisIdx, min, max) {
  const splits = [];
  for (let e = Math.ceil(Math.log10(min)); e <= Math.floor(Math.log10(max)); e++) splits.push(Math.pow(10, e));
  return splits.length ? splits : [min, max];
}

// Add the series that a panel needs but the server does not send. Incomplete periods are a copy of
// the period errors where energy_periods.dat says complete = 0.
function derive(series) {
  const max = series.period_max_rel_err;
  const complete = series.period_complete;
  if (max && complete) {
    series.period_incomplete = {
      x: max.x,
      y: max.y.map((v, i) => (complete.y[i] === 0 ? v : null)),
      metric: "energy_periods.dat:complete",
    };
  }
  return series;
}

const SERIES_TIMEOUT_MS = 20000; // The curves of one run must arrive within this time.

export class Plots {
  constructor(container, { onSeek }) {
    this.container = container;
    this.onSeek = onSeek;
    this.charts = [];
    this.time = null;
    this.generation = 0; // Counts the loads. An older load that ends late is dropped.
  }

  clear() {
    for (const chart of this.charts) chart.u.destroy();
    this.charts = [];
    this.container.replaceChildren();
  }

  // Load the curves of one run and draw the panels. G is shown in the axis label (FR-014).
  // Returns the source of the curves, or null when a newer load took over.
  async load(run, G) {
    const generation = ++this.generation;
    const names = [...new Set([...PANELS.flatMap((p) => p.names), ...HELPER_SERIES])];
    const selected = names.filter((n) => n !== "period_incomplete").join(",");
    // A stalled server must not stop the refresh for good: the request is cut after SERIES_TIMEOUT_MS.
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), SERIES_TIMEOUT_MS);
    let body;
    try {
      const response = await fetch(`/api/runs/${encodeURIComponent(run)}/series?names=${selected}`, { signal: controller.signal });
      body = await response.json();
      if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
    } finally {
      clearTimeout(timer);
    }
    if (generation !== this.generation) return null;
    this.clear(); // Clear only after a good answer, so a failed refresh keeps the old curves.
    const series = derive(body.series);
    for (const panel of PANELS) this.build(panel, series, run, G);
    // All panels are in the page now, so each one can take its final width.
    for (const chart of this.charts) this.fit(chart);
    return body.source; // "prometheus" or "files".
  }

  build(panel, series, run, G) {
    const { present, data } = joinSeries(panel, series);
    if (present.length === 0) return;
    const metrics = Object.fromEntries(present.map((name) => [name, series[name].metric]));
    const box = document.createElement("div");
    box.className = "plot";
    const button = document.createElement("button");
    button.textContent = `${panel.id} PNG`;
    button.dataset.panel = panel.id;
    const host = document.createElement("div");
    box.append(button, host);
    this.container.append(box);

    const scales = { x: { time: false }, y: panel.log ? { distr: 3, range: logRange } : { distr: 1 } };
    const xLabel = panel.xName === "period" ? "reference period" : `time, G = ${G || "unknown"}`;
    const axes = [
      { label: xLabel },
      { label: panel.yLabel, splits: panel.log ? logSplits : undefined, values: panel.log ? (u, ticks) => ticks.map((v) => (v == null ? "" : v.toExponential(0))) : undefined },
    ];
    const seriesOpts = [{}];
    for (const [i, name] of present.entries()) {
      const isRight = panel.right && name === panel.right.name;
      if (isRight) {
        scales.p = panel.right.range ? { range: panel.right.range } : {};
        axes.push({ scale: "p", side: 1, label: panel.right.label });
      }
      const color = (panel.colors && panel.colors[name]) || COLORS[i % COLORS.length];
      const isBar = panel.bars && panel.bars.includes(name);
      seriesOpts.push({
        label: LABELS[name],
        stroke: color,
        fill: isBar ? `${color}99` : undefined,
        paths: isBar ? uPlot.paths.bars({ size: [0.6, 100] }) : undefined,
        width: 1.5,
        dash: panel.dashed && panel.dashed.includes(name) ? [4, 3] : undefined,
        scale: isRight ? "p" : "y",
      });
    }
    const chart = { panel, present, metrics, box, host, run, u: null };
    const opts = {
      width: Math.max(box.clientWidth, 300),
      height: PANEL_HEIGHT,
      title: `${panel.id} ${panel.title} · ${run}`,
      scales,
      axes,
      series: seriesOpts,
      cursor: { drag: { x: false, y: false } },
      hooks: {
        setCursor: [(u) => this.showTip(chart, u)],
        draw: [(u) => this.drawTimeLine(u)],
      },
    };
    chart.u = new uPlot(opts, data, host);
    // Each panel follows its own box. The box changes width when a panel is added or the page changes.
    new ResizeObserver(() => this.fit(chart)).observe(box);
    chart.u.over.addEventListener("click", (event) => {
      this.onSeek(chart.u.posToVal(event.offsetX, "x"));
    });
    button.addEventListener("click", () => {
      const url = this.exportPng(chart);
      if (url) saveFile(`${run}-${panel.id}.png`, url);
    });
    this.charts.push(chart);
    this.showTip(chart, chart.u);
  }

  showTip(chart, u) {
    if (!chart.tip) {
      chart.tip = document.createElement("pre");
      chart.tip.className = "tip";
      chart.box.append(chart.tip);
    }
    chart.tip.textContent = tooltipText(u, chart.panel, chart.metrics);
    chart.tip.style.display = chart.tip.textContent ? "block" : "none";
  }

  // The time cursor of the 3D view: a vertical line at the current time.
  drawTimeLine(u) {
    if (this.time === null || this.time === undefined) return;
    const x = u.valToPos(this.time, "x", true);
    const ctx = u.ctx;
    ctx.save();
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, u.bbox.top);
    ctx.lineTo(x, u.bbox.top + u.bbox.height);
    ctx.stroke();
    ctx.restore();
  }

  setTime(time) {
    this.time = time;
    for (const chart of this.charts) chart.u.redraw(false, false);
  }

  fit(chart) {
    chart.u.setSize({ width: Math.max(chart.host.clientWidth, 300), height: PANEL_HEIGHT });
  }

  exportPng(chart) {
    // The drawing canvas of uPlot. It holds the curves, the axes and the title.
    return chart.u.ctx.canvas.toDataURL("image/png");
  }
}
