// Three.js view of h4nb-viz: particle points, colour modes, camera presets and the frame loader.
// Spec: specs/003-run-visualization (V1, V2, V3, FR-010). The module is served as it is, with no build step.
import * as THREE from "three";
import { OrbitControls } from "./vendor/OrbitControls.js";

// The inferno colormap, 256 entries of R, G, B bytes (matplotlib 3.11.2).
const INFERNO = new Uint8Array([
  0, 0, 4, 1, 0, 5, 1, 1, 6, 1, 1, 8, 2, 1, 10, 2, 2, 12, 2, 2, 14, 3, 2, 16,
  4, 3, 18, 4, 3, 20, 5, 4, 23, 6, 4, 25, 7, 5, 27, 8, 5, 29, 9, 6, 31, 10, 7, 34,
  11, 7, 36, 12, 8, 38, 13, 8, 41, 14, 9, 43, 16, 9, 45, 17, 10, 48, 18, 10, 50, 20, 11, 52,
  21, 11, 55, 22, 11, 57, 24, 12, 60, 25, 12, 62, 27, 12, 65, 28, 12, 67, 30, 12, 69, 31, 12, 72,
  33, 12, 74, 35, 12, 76, 36, 12, 79, 38, 12, 81, 40, 11, 83, 41, 11, 85, 43, 11, 87, 45, 11, 89,
  47, 10, 91, 49, 10, 92, 50, 10, 94, 52, 10, 95, 54, 9, 97, 56, 9, 98, 57, 9, 99, 59, 9, 100,
  61, 9, 101, 62, 9, 102, 64, 10, 103, 66, 10, 104, 68, 10, 104, 69, 10, 105, 71, 11, 106, 73, 11, 106,
  74, 12, 107, 76, 12, 107, 77, 13, 108, 79, 13, 108, 81, 14, 108, 82, 14, 109, 84, 15, 109, 85, 15, 109,
  87, 16, 110, 89, 16, 110, 90, 17, 110, 92, 18, 110, 93, 18, 110, 95, 19, 110, 97, 19, 110, 98, 20, 110,
  100, 21, 110, 101, 21, 110, 103, 22, 110, 105, 22, 110, 106, 23, 110, 108, 24, 110, 109, 24, 110, 111, 25, 110,
  113, 25, 110, 114, 26, 110, 116, 26, 110, 117, 27, 110, 119, 28, 109, 120, 28, 109, 122, 29, 109, 124, 29, 109,
  125, 30, 109, 127, 30, 108, 128, 31, 108, 130, 32, 108, 132, 32, 107, 133, 33, 107, 135, 33, 107, 136, 34, 106,
  138, 34, 106, 140, 35, 105, 141, 35, 105, 143, 36, 105, 144, 37, 104, 146, 37, 104, 147, 38, 103, 149, 38, 103,
  151, 39, 102, 152, 39, 102, 154, 40, 101, 155, 41, 100, 157, 41, 100, 159, 42, 99, 160, 42, 99, 162, 43, 98,
  163, 44, 97, 165, 44, 96, 166, 45, 96, 168, 46, 95, 169, 46, 94, 171, 47, 94, 173, 48, 93, 174, 48, 92,
  176, 49, 91, 177, 50, 90, 179, 50, 90, 180, 51, 89, 182, 52, 88, 183, 53, 87, 185, 53, 86, 186, 54, 85,
  188, 55, 84, 189, 56, 83, 191, 57, 82, 192, 58, 81, 193, 58, 80, 195, 59, 79, 196, 60, 78, 198, 61, 77,
  199, 62, 76, 200, 63, 75, 202, 64, 74, 203, 65, 73, 204, 66, 72, 206, 67, 71, 207, 68, 70, 208, 69, 69,
  210, 70, 68, 211, 71, 67, 212, 72, 66, 213, 74, 65, 215, 75, 63, 216, 76, 62, 217, 77, 61, 218, 78, 60,
  219, 80, 59, 221, 81, 58, 222, 82, 56, 223, 83, 55, 224, 85, 54, 225, 86, 53, 226, 87, 52, 227, 89, 51,
  228, 90, 49, 229, 92, 48, 230, 93, 47, 231, 94, 46, 232, 96, 45, 233, 97, 43, 234, 99, 42, 235, 100, 41,
  235, 102, 40, 236, 103, 38, 237, 105, 37, 238, 106, 36, 239, 108, 35, 239, 110, 33, 240, 111, 32, 241, 113, 31,
  241, 115, 29, 242, 116, 28, 243, 118, 27, 243, 120, 25, 244, 121, 24, 245, 123, 23, 245, 125, 21, 246, 126, 20,
  246, 128, 19, 247, 130, 18, 247, 132, 16, 248, 133, 15, 248, 135, 14, 248, 137, 12, 249, 139, 11, 249, 140, 10,
  249, 142, 9, 250, 144, 8, 250, 146, 7, 250, 148, 7, 251, 150, 6, 251, 151, 6, 251, 153, 6, 251, 155, 6,
  251, 157, 7, 252, 159, 7, 252, 161, 8, 252, 163, 9, 252, 165, 10, 252, 166, 12, 252, 168, 13, 252, 170, 15,
  252, 172, 17, 252, 174, 18, 252, 176, 20, 252, 178, 22, 252, 180, 24, 251, 182, 26, 251, 184, 29, 251, 186, 31,
  251, 188, 33, 251, 190, 35, 250, 192, 38, 250, 194, 40, 250, 196, 42, 250, 198, 45, 249, 199, 47, 249, 201, 50,
  249, 203, 53, 248, 205, 55, 248, 207, 58, 247, 209, 61, 247, 211, 64, 246, 213, 67, 246, 215, 70, 245, 217, 73,
  245, 219, 76, 244, 221, 79, 244, 223, 83, 244, 225, 86, 243, 227, 90, 243, 229, 93, 242, 230, 97, 242, 232, 101,
  242, 234, 105, 241, 236, 109, 241, 237, 113, 241, 239, 117, 241, 241, 121, 242, 242, 125, 242, 244, 130, 243, 245, 134,
  243, 246, 138, 244, 248, 142, 245, 249, 146, 246, 250, 150, 248, 251, 154, 249, 252, 157, 250, 253, 161, 252, 255, 164,
]);

const FRAME_MAGIC = "H4VF";
const FRAME_FIELDS = "pos,vel";
const FIELD_VEL = 2;
const FLY_ELEVATION = 0.5; // Radians above the disk plane for the fly-around view.
const FLY_RATE = 0.05; // Radians per second.

// Read one binary frame (contracts/frame-format.md section 1).
export function parseFrame(buffer) {
  const dv = new DataView(buffer);
  const magic = String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3));
  if (magic !== FRAME_MAGIC) throw new Error("the response is not a frame");
  const count = dv.getUint32(8, true);
  const fields = dv.getUint32(12, true);
  const time = dv.getFloat64(16, true);
  const scale = dv.getFloat32(36, true);
  // The arrays start at byte 40 and at 40 + 12 * count. Both offsets are multiples of 4.
  const pos = new Float32Array(buffer, 40, 3 * count);
  const vel = fields & FIELD_VEL ? new Float32Array(buffer, 40 + 12 * count, 3 * count) : null;
  return { count, time, scale, pos, vel };
}

// Keeps the last `cacheFrames` frames in memory and loads frames ahead of time (FR-010).
export class FrameLoader {
  constructor({ run, maxPoints = 200000, seed = 1, cacheFrames = 64 }) {
    this.base = `/api/runs/${encodeURIComponent(run)}/frames/`;
    this.query = `?max_points=${maxPoints}&seed=${seed}&fields=${FRAME_FIELDS}`;
    this.cacheFrames = cacheFrames;
    this.cache = new Map(); // Insertion order is the use order: the oldest entry comes first.
    this.pending = new Map();
  }

  get(index) {
    if (this.cache.has(index)) {
      const frame = this.cache.get(index);
      this.cache.delete(index);
      this.cache.set(index, frame);
      return Promise.resolve(frame);
    }
    if (this.pending.has(index)) return this.pending.get(index);
    const request = fetch(this.base + index + this.query)
      .then(async (response) => {
        if (!response.ok) throw new Error(`frame ${index}: HTTP ${response.status}`);
        return parseFrame(await response.arrayBuffer());
      })
      .then(
        (frame) => {
          this.pending.delete(index);
          this.cache.set(index, frame);
          while (this.cache.size > this.cacheFrames) this.cache.delete(this.cache.keys().next().value);
          return frame;
        },
        (error) => {
          this.pending.delete(index);
          throw error;
        },
      );
    this.pending.set(index, request);
    return request;
  }

  prefetch(indices) {
    for (const index of indices) this.get(index).catch(() => {});
  }
}

// A round white sprite. Additive blending turns many of them into a glow (research R2).
function softSprite() {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 64;
  const ctx = canvas.getContext("2d");
  const grad = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
  grad.addColorStop(0, "rgba(255,255,255,1)");
  grad.addColorStop(0.35, "rgba(255,255,255,0.6)");
  grad.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, 64, 64);
  return new THREE.CanvasTexture(canvas);
}

// Draw the inferno colour bar on a canvas.
export function drawColorBar(canvas) {
  const ctx = canvas.getContext("2d");
  for (let x = 0; x < canvas.width; x++) {
    const i = Math.floor((x / (canvas.width - 1)) * 255) * 3;
    ctx.fillStyle = `rgb(${INFERNO[i]},${INFERNO[i + 1]},${INFERNO[i + 2]})`;
    ctx.fillRect(x, 0, 1, canvas.height);
  }
}

export class View {
  constructor(container) {
    this.container = container;
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    if (!this.renderer.capabilities.isWebGL2) throw new Error("WebGL 2 is required");
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(this.renderer.domElement);
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(40, 1, 1e-3, 1e6);
    this.camera.up.set(0, 1, 0);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.addEventListener("start", () => {
      this.flying = false; // A drag stops the fly-around.
    });
    this.geometry = new THREE.BufferGeometry();
    this.material = new THREE.PointsMaterial({
      map: softSprite(),
      vertexColors: true,
      transparent: true,
      depthWrite: false,
      sizeAttenuation: false,
    });
    this.scene.add(new THREE.Points(this.geometry, this.material));
    this.mode = "speed";
    this.range = [0, 0];
    this.flying = false;
    this.angle = 0;
    this.scale = 1;
    this.frame = null;
    this.setTheme("dark");
    new ResizeObserver(() => this.resize()).observe(this.container); // Follows the window and the plots.
    this.resize();
  }

  setTheme(theme) {
    const light = theme === "light";
    this.scene.background = new THREE.Color(light ? 0xf4f5f8 : 0x05060a);
    this.material.blending = light ? THREE.NormalBlending : THREE.AdditiveBlending;
    this.material.needsUpdate = true;
  }

  resize() {
    const w = this.container.clientWidth;
    const h = Math.max(this.container.clientHeight, 1);
    this.renderer.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.material.size = Math.min(4, Math.max(1.5, h / 250)); // Point size grows with the screen height.
  }

  // A fixed drawing size for a recording or an export. The CSS size does not change. Call restoreSize() after.
  setBufferSize(width, height, ratio) {
    this.renderer.setPixelRatio(ratio);
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
  }

  restoreSize() {
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.resize();
  }

  // Return the view as a PNG data URL at 2x scale. The image is read in the same task as the render,
  // so the drawing buffer still holds it. preserveDrawingBuffer is not needed.
  exportPng() {
    const w = this.container.clientWidth;
    const h = Math.max(this.container.clientHeight, 1);
    this.setBufferSize(w, h, 2);
    this.renderer.render(this.scene, this.camera);
    const url = this.renderer.domElement.toDataURL("image/png");
    this.restoreSize();
    return url;
  }

  setMode(mode) {
    this.mode = mode;
    if (this.frame) this.setFrame(this.frame);
  }

  // Set the frame to show. The positions are relative to the central body.
  setFrame(frame) {
    this.frame = frame;
    this.scale = frame.scale || this.scale;
    this.geometry.setAttribute("position", new THREE.BufferAttribute(frame.pos, 3));
    this.geometry.setAttribute("color", new THREE.BufferAttribute(this.colors(frame), 3));
    this.geometry.computeBoundingSphere();
  }

  // Colour each particle by the value of the mode, scaled to the range of this frame.
  colors(frame) {
    const n = frame.count;
    const value = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      if (this.mode === "radius") {
        const x = frame.pos[3 * i], y = frame.pos[3 * i + 1], z = frame.pos[3 * i + 2];
        value[i] = Math.hypot(x, y, z);
      } else if (frame.vel) {
        value[i] = Math.hypot(frame.vel[3 * i], frame.vel[3 * i + 1], frame.vel[3 * i + 2]);
      }
    }
    let lo = Infinity, hi = -Infinity;
    for (let i = 0; i < n; i++) {
      if (value[i] < lo) lo = value[i];
      if (value[i] > hi) hi = value[i];
    }
    this.range = [n ? lo : 0, n ? hi : 0];
    const span = hi > lo ? hi - lo : 1;
    const out = new Float32Array(3 * n);
    for (let i = 0; i < n; i++) {
      const k = Math.round(((value[i] - lo) / span) * 255) * 3;
      out[3 * i] = INFERNO[k] / 255;
      out[3 * i + 1] = INFERNO[k + 1] / 255;
      out[3 * i + 2] = INFERNO[k + 2] / 255;
    }
    return out;
  }

  // Put the camera at a distance that shows the whole frame.
  fit(scale) {
    this.scale = scale || 1;
    this.setPreset("fly");
  }

  setPreset(name) {
    this.flying = name === "fly";
    const d = 2.6 * this.scale;
    this.controls.target.set(0, 0, 0);
    if (name === "top") this.camera.position.set(0, 0, d);
    if (name === "edge") this.camera.position.set(d, 0, 0); // The disk plane is seen edge-on.
    if (name === "fly") this.placeFly(d);
    this.camera.lookAt(0, 0, 0);
  }

  placeFly(d) {
    const cosE = Math.cos(FLY_ELEVATION);
    this.camera.position.set(d * cosE * Math.cos(this.angle), d * cosE * Math.sin(this.angle), d * Math.sin(FLY_ELEVATION));
  }

  animate(dt) {
    if (this.flying) {
      this.angle += dt * FLY_RATE;
      this.placeFly(2.6 * this.scale);
      this.camera.lookAt(0, 0, 0);
    }
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }
}
