# Contract: public API (`include/h4nb/h4nb.hpp`)

The header at commit `339ce35` is the base contract. This file lists the rules and the planned additions. The public API exposes no CUDA type (constitution III).

## Existing contract (unchanged)

- `Simulation(const Particles&, const Config&)` uploads the data, computes a and j, and selects the first steps. It throws `std::invalid_argument` for bad input and `std::runtime_error` for a CUDA error.
- `advance_to(double t)`: `t` is a multiple of `dt_max` and not less than `time()`. On return, all particles are synchronized at `t`.
- `diagnostics()` works only at sync points. It costs N²/2 pair evaluations.
- `state()`, `levels()`, `status()`, `stats()`, `time()`.
- `load_text`, `write_snapshot`, `read_snapshot`.

## Planned additions

| Item | Change | Task |
|---|---|---|
| `Config::tile` | New `int`, default 128. Allowed: 64, 128, 256. | T008 |
| `Config::blocks_per_sm` | New `int`, default 4. Allowed: 1 to 16. | T008 |
| `Simulation` constructor | Validates all `Config` fields. Throws `std::invalid_argument` with the field name. No silent clamp. | T009 |
| `load_text`, `read_snapshot` | Throw `std::runtime_error` for a repeated ID, m ≤ 0, a non-finite value or N < 2. The message names the file, the line (text) or the index (binary), and the field. | T010 |
| `build_info()` | New free function. Returns a `std::string` with the commit, the CUDA version and the compiled architectures. `h4nb_run` writes it to `run_info.txt`. | T027 |
| `Config::dissipation`, `drag_tau`, `drag_vbg` | New. Default `Off`. The constructor rejects `LinearDrag` with τ ≤ 0. | T041 |
| `Diagnostics::W_diss` | New `double`. Work of the dissipative forces since the start. | T042 |
| MPI | No change to the signatures. Under `H4NB_MPI=ON`, each rank constructs one `Simulation` with the full particle set. The library selects the device by local rank. `devices` is ignored. | T030, T031 |

## Compatibility

- Code that does not set the new fields gets the current behaviour: `tile=128`, `blocks_per_sm=4`. These are the values of the constants `BI` and `4` in commit `339ce35`. So results stay bit-identical.
- The snapshot format stays version 1. Exact restart (version 2, plan O8) is not in this plan.
