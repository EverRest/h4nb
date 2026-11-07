# Data Model: h4nb

**Date**: 2026-11-07. Source of truth for the code: `include/h4nb/h4nb.hpp` and `src/simulation.cu` at commit `339ce35`. This file describes the entities and marks the planned changes with **(new)**.

## 1. Particle (host)

`h4nb::Particles` is a structure of arrays. Index 0 is the central body.

| Field | Type | Rule |
|---|---|---|
| `id` | `int64_t` | Unique. Kept from the input. Not the array index. **(new)** checked for uniqueness. |
| `m` | `double` | m > 0, finite. **(new)** checked. |
| `x, y, z` | `double` | Finite. **(new)** checked. |
| `vx, vy, vz` | `double` | Finite. **(new)** checked. |

`N = size()` includes the central body. N ≥ 2.

## 2. Particle state (device, one GPU or one rank)

Each GPU owns the global particles `[base, base + n)` (j-parallel layout, plan D2). The state uses `d4` (four doubles; `w` holds the mass in `x` and `xp`).

| Buffer | Size | Bytes per particle | Meaning |
|---|---|---|---|
| `x, v` | n | 64 | Corrected position (+ mass) and velocity at the particle time `t`. |
| `a, j` | n | 64 | Acceleration and jerk at `t`. |
| `xp, vp` | n | 64 | Predicted position and velocity at the block time `T`. Separate from `x, v`, so the force pass never reads a half-updated state. |
| `t, next` | n | 16 | Particle time and next update time, in integer ticks. |
| `level` | n | 4 | Block level k. Step = `dt_max / 2^k`. |
| `dmin, minr2, status` | n / 1 | 8 | Close-pair and error tracking. |
| `tx, tv, tid` | N | 72 per global particle | Gathered active targets. Also all positions for the potential. |
| `fa, fj, ra, rj, ca, cj` | N or G·n | — | Partial and summed forces. |
| `pa, pj` | `pcap` | — | Partial sums of the source split. |
| `phi` | N | 8 per global particle | Potential sums. |

Owned state: about 220 bytes per particle. Work buffers sized by N: about 200 bytes per global particle on each GPU. For N = 1 024 000: about 0.4 GB per GPU. This is small for all listed cards (RTX 4070 Ti: 12 GB; GTX 1060: 3 or 6 GB; GH200: 96 or 144 GB).

## 3. Time

- `tick = dt_max / 2^max_level`. All times are `int64_t` tick counts (plan D4).
- Level k has a step of `2^(max_level - k)` ticks.
- A particle is active at block time T when `next == T`.
- A particle can go down to a finer level at any step. It can go up one level only when T is a multiple of the new step (plan D5).

## 4. Config (library)

`h4nb::Config`. Existing fields stay. Planned additions:

| Field | Type | Default | Range | Meaning |
|---|---|---|---|---|
| `tile` **(new)** | `int` | 128 | 64, 128, 256 | Targets per block and sources per shared-memory tile in the force and potential kernels. |
| `blocks_per_sm` **(new)** | `int` | 4 | 1 to 16 | Target occupancy for the source split in `split()`. |
| `dissipation` **(new)** | enum `Dissipation` | `Off` | `Off`, `LinearDrag` | Dissipation model (research R7). |
| `drag_tau` **(new)** | `double` | 0 | > 0 when `LinearDrag` | Drag time τ. |
| `drag_vbg[3]` **(new)** | `double` | 0, 0, 0 | finite | Background velocity v_bg. |

The constructor of `Simulation` rejects a value out of range with `std::invalid_argument`. It does not clamp the value.

## 5. Run settings (tools)

`Settings` in `tools/settings.hpp` **(new)**. It holds one entry for each key:

| Field | Meaning |
|---|---|
| `name` | Key name, lower case, for example `eta`. |
| `type` | `real`, `int`, `bool`, `string`, `int_list`, `real_list`, `enum`. |
| `default` | Text of the default value. |
| `range` | Minimum and maximum, or the allowed enum values. |
| `help` | One line of help text. |
| `value`, `source` | Final value and its source: `default`, `preset`, `file:<path>:<line>`, `env`, `cli`. |

The full key list is in [contracts/run-config.md](contracts/run-config.md).

## 6. Diagnostics record

`h4nb::Diagnostics`: time, K, U, E, P[3], L[3], **(new)** W_diss (0 when dissipation is off). Computed only at sync points (multiples of `dt_max`). U uses the same softening as the force. Sums use a fixed order and Neumaier summation (plan D6).

The tool derives: relative energy error, max and mean relative error over the reference period, dP_rel and dL_rel with scales from the initial state (FR-013).

## 7. Stats and status

- `h4nb::Stats`: `block_steps`, `active_total`, `min_r2`.
- `StatusBits`: `kNaN` (NaN or Inf), `kDtUnderflow`, `kClosePair`. A bit stays set.

## 8. Run record **(new)**

Each run writes two text files to the output directory:

- `config.used`: every key, its final value and its source. It is valid input for `config=`.
- `run_info.txt`: commit, build type, `CMAKE_CUDA_ARCHITECTURES`, CUDA runtime and driver versions, GPU names and compute capabilities, rank count, host name, start time. These are the items of `docs/cuda-best-practices.md` section 6.

## 9. Convergence study **(new)**

`h4nb_study` writes `study.dat`. One row for each grid point:

`eta dt_max t_end max_rel_err mean_rel_err final_rel_err dP_rel dL_rel block_steps pair_evals wall_s pass`

`pass` is 1 when `max_rel_err <= energy_tol`.
