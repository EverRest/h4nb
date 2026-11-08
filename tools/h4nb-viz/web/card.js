// Run card S1 (spec Summary and export). The facts come from /api/runs/{run}.
// Missing values show "unknown" (FR-013).

const UNKNOWN = "unknown";

export function formatWall(seconds) {
  if (seconds === null || seconds === undefined) return UNKNOWN;
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

// Device lines look like `id=0 name=NVIDIA GeForce RTX 4070 Ti cc=8.9 sm_count=60`.
function deviceNames(info) {
  const names = Object.keys(info)
    .filter((key) => /^device_\d+$/.test(key))
    .sort()
    .map((key) => {
      const match = /name=(.*?)(?= cc=| sm_count=| error=|$)/.exec(info[key]);
      return match ? match[1].trim() : UNKNOWN;
    });
  return names.length ? names.join(", ") : UNKNOWN;
}

// The rows of the card: label and value.
export function cardRows(detail) {
  const info = detail.info || {};
  const config = detail.config || {};
  const energy = detail.final_energy_rel_err;
  return [
    ["Particles N", config.n || UNKNOWN],
    ["End time t_end", config.t_end || UNKNOWN],
    ["G", config.G || UNKNOWN],
    ["Central body id", config.central_id || "0"],
    ["GPU", deviceNames(info)],
    ["Ranks", info.ranks || UNKNOWN],
    ["Wall time", formatWall(detail.wall_s)],
    ["Final energy error", energy === null || energy === undefined ? UNKNOWN : energy.toExponential(2)],
    ["Build", info.build_type ? `${info.build_type}, commit ${info.h4nb_commit || UNKNOWN}` : UNKNOWN],
  ];
}

// Draw the card on a canvas at 2x scale. The layout is fixed, so the PNG looks the same on every machine.
export function drawCard(detail, name) {
  const scale = 2;
  const width = 800, height = 460;
  const canvas = document.createElement("canvas");
  canvas.width = width * scale;
  canvas.height = height * scale;
  const ctx = canvas.getContext("2d");
  ctx.scale(scale, scale);
  ctx.fillStyle = "#0c0f17";
  ctx.fillRect(0, 0, width, height);
  ctx.fillStyle = "#f0a030";
  ctx.font = "600 28px system-ui, sans-serif";
  ctx.fillText(name, 32, 56);
  ctx.fillStyle = "#7a8193";
  ctx.font = "14px system-ui, sans-serif";
  ctx.fillText("h4nb-viz run card", 32, 80);
  let y = 124;
  for (const [label, value] of cardRows(detail)) {
    ctx.fillStyle = "#7a8193";
    ctx.font = "15px system-ui, sans-serif";
    ctx.fillText(label, 32, y);
    ctx.fillStyle = "#d8dce6";
    ctx.font = "600 15px system-ui, sans-serif";
    ctx.fillText(String(value), 280, y);
    y += 34;
  }
  return canvas;
}
