# Research: Visualization of run results (h4nb-viz)

## R1 Where to render

- **Decision**: in the browser with WebGL. The server only reads and slices arrays.
- **Reason**: a laptop GPU draws 200 000 point sprites at 60 fps. Rendering on the server (matplotlib, VTK offscreen) needs much more CPU and gives no interaction.
- **Alternatives**: matplotlib movies (slow for 1M points, no interaction); ParaView (strong, but a large program for end users; kept as an export, Phase 3); Blender (best images, a lot of work); Grafana panel plugin (no good 3D, large project).

## R2 Glow effect

- **Decision**: `THREE.Points` with a soft round sprite texture made in code, `AdditiveBlending`, `depthWrite=false`, color from a colormap texture. The point size depends on the screen height.
- **Reason**: dense regions become bright without a bloom pass. No extra library.
- **Alternatives**: `UnrealBloomPass` (more GPU work, more code); density texture (only 2D).

## R3 Decimation subset

- **Decision**: keep particle `i` when `splitmix64(id_i ^ seed) < 2^64 · k / N`, plus the central body. With `numpy` this is one vector pass over the `id` array per run; the index list is cached.
- **Reason**: deterministic, the same set in each frame, needs no state on disk.
- **Alternatives**: `random.sample` with seed (needs a stored list); every k-th index (visible patterns if the IC generator orders particles by radius).

## R4 Curves library

- **Decision**: `uPlot` 1.6.30.
- **Reason**: about 50 KB, draws 10^5 points fast, ES module, MIT.
- **Alternatives**: Plotly (about 3.5 MB); Chart.js (slower for large series); D3 (much more code).

## R5 Movie export

- **Decision**: `canvas.captureStream(30)` + `MediaRecorder` (VP9 WebM; Safari gives MP4). With `ffmpeg`: `ffmpeg -i in.webm -c:v libx264 -pix_fmt yuv420p -crf 18 out.mp4`.
- **Reason**: no extra program for a first movie; MP4 for PowerPoint and Keynote.
- **Alternative**: frame-by-frame PNG to the server and `ffmpeg` (exact frame rate, more traffic). Kept as option `--exact` in Phase 2 if the real-time recording drops frames.

## R6 Prometheus queries

- **Decision**: `GET /api/v1/query_range?query=<metric>{run="<run>"}&start&end&step`, `step` = max(15 s, range/2000). `urllib` from the stdlib.
- **Reason**: no client library. 2000 points per curve is enough for a plot.
- **Note**: Prometheus stores wall time. The page plots against simulation time, so the server also queries `h4nb_sim_time` and joins the two series on the timestamp.

## R7 Orbital elements

- **Decision**: two-body elements relative to the central body with μ = G (m_c + m_i): a from the vis-viva equation, e from the eccentricity vector, inc from the angular momentum vector and the z axis.
- **Reason**: standard, vectorised in `numpy`, about 50 ms for 10^6 particles.
- **Note**: these are osculating elements for display. They are not used for any accuracy result.

## R8 Desktop wrapper

- **Decision**: Tauri 2 in Phase 3. It starts `h4nb-viz serve` as a sidecar and opens the page in the system web view.
- **Reason**: about 10 MB. Electron is about 150 MB.
- **Alternative**: `pywebview` (simpler, Python only; check in Phase 3 if a Rust toolchain is a problem).
