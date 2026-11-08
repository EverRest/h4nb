# Contract: frame and thin snapshot formats

All values are little-endian.

## 1. Frame (HTTP response of `/api/runs/{run}/frames/{index}`)

Content type `application/octet-stream`.

| Offset | Type | Field |
|---|---|---|
| 0 | `char[4]` | magic `"H4VF"` |
| 4 | `uint32` | version = 1 |
| 8 | `uint32` | count k (number of particles in the frame) |
| 12 | `uint32` | fields: bit 0 pos, bit 1 vel, bit 2 mass |
| 16 | `float64` | time |
| 24 | `float32[3]` | center: position of the central body (the page subtracts it, so the view follows the central body) |
| 36 | `float32` | scale: max \|x − center\| over the frame (for the camera) |
| 40 | `float32[3k]` | positions x, y, z interleaved (relative to `center`) |
| — | `float32[3k]` | velocities, if bit 1 |
| — | `float32[k]` | masses, if bit 2 |

The particle order is the order of `/ids`. The header is 40 bytes, so the arrays are 4-byte aligned for `Float32Array`.

Size for k = 200 000 with pos only: 40 + 2.4 MB.

float32 is enough for display: the relative error is about 6e-8 of the coordinate. The frame is never used for physics.

## 2. Thin snapshot (output of `h4nb-viz thin`, Phase 2)

File name: the same name as the source snapshot with the extension `.thin`, in `OUT_DIR`. `OUT_DIR` also gets copies of all `.dat` files, `config.used` and `run_info.txt`, so it is a complete run directory for the app.

| Offset | Type | Field |
|---|---|---|
| 0 | `char[8]` | magic `"H4NBTHIN"` |
| 8 | `uint32` | version = 1 |
| 12 | `uint32` | seed |
| 16 | `uint64` | k |
| 24 | `uint64` | n of the source snapshot |
| 32 | `float64` | time |
| 40 | `int64[k]` | id |
| — | `float64[k]` | m |
| — | `float32[3k]` | position x, y, z interleaved (absolute, not relative) |
| — | `float32[3k]` | velocity vx, vy, vz interleaved |

The subset follows plan.md DD3 with the seed in the header. The server reads a thin run with the seed and k of the file; `max_points` larger than k gives k.

For the orbital elements (spec P1–P5) of a thin run, the central body is in the subset, so `G` and the central body are available. The histograms then use only the k particles; the page says "thin run: statistics from k particles".
