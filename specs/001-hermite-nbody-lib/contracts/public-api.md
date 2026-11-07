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
| MPI | No change to the signatures of `Simulation`. Under `H4NB_MPI=ON` with more than one rank, each rank constructs one `Simulation` with the full particle set. The library selects the device by local rank. `devices` is ignored. Done (compiled; GPU path not run). | T030, T031 |
| `Config::device_offset` | New `int`, default 0, must be ≥ 0. Several ranks only. | T030 |
| `Config::mpi_host_staging` | New `bool`, default `false`. Several ranks only: stage the MPI buffers through pinned host memory. | T032 |
| `RankScope`, `rank()`, `ranks()`, `local_rank()`, `max_over_ranks()`, `rank_table()`, `abort_ranks()` | New. Plain C++ types only. See the section "Ranks". | T030, T034, T035 |

## Compatibility

- Code that does not set the new fields gets the current behaviour: `tile=128`, `blocks_per_sm=4`. These are the values of the constants `BI` and `4` in commit `339ce35`. So results stay bit-identical.
- The snapshot format stays version 1. Exact restart (version 2, plan O8) is not in this plan.

## Ranks (MPI)

Decision (task T030, 2026-11-07): the library uses MPI by itself when three conditions are true. The build has `H4NB_MPI=ON`. MPI is initialized. The world has more than one rank. There is no `Config` flag and no communicator handle. The header has no MPI type and no CUDA type (constitution III).

Reasons:

- `docs/multi-node-design.md` section 1.5 says that the library uses `MPI_COMM_WORLD` and that `Simulation` keeps its signature. An automatic rule meets both points.
- A communicator handle needs an opaque type. No user needs a sub-communicator now (constitution III, "not before a user needs it").
- The tools must not include `mpi.h`. Thus the tools stay the same source for both builds. The small rank functions below give them what they need.

Rules:

- The application initializes MPI. It can call `MPI_Init` itself, or it can create `h4nb::RankScope scope(argc, argv);` in `main`. `RankScope` calls `MPI_Init` only when MPI is not initialized, and then `MPI_Finalize` in its destructor. In a build without MPI it does nothing.
- The library copies `MPI_COMM_WORLD` (`MPI_Comm_dup`) at the first use. All its messages use this copy.
- With one rank (no MPI build, MPI not initialized, or one process), the one-process path runs. It is the same code as before, and it gives the same bits. `devices` applies.
- With more than one rank, each rank has one GPU (`docs/multi-node-design.md` section 3.3): device 0 when the process sees one device, otherwise `(local_rank + device_offset) % device count`. The constructor throws when `local_rank >= device count`.
- `Simulation` is collective. All ranks construct it with the same `Particles` and `Config`, and all ranks call each member function in the same order. `state()` and `levels()` give the full arrays on every rank (`MPI_Allgatherv`). `status()` (`MPI_BOR`), `stats()` (`MPI_MIN` for `min_r2`) and `diagnostics()` give the same values on every rank.
- Under MPI, `advance_to(t)` returns early when a rank has set `kNaN` (task T034). Then `time()` is less than `t`, and `status()` has `kNaN` on every rank.

Functions:

| Function | Meaning |
|---|---|
| `RankScope(int& argc, char**& argv)` | Initializes MPI when the build has MPI and MPI is not initialized. |
| `int rank()`, `int ranks()`, `int local_rank()` | This rank, the rank count, and the rank on the node. 0, 1 and 0 for one rank. |
| `int max_over_ranks(int)` | Collective. The largest value of all ranks, on every rank. The tools use it to agree on an error code. |
| `std::string rank_table(int device_offset)` | Collective. Rank 0 gets `mpi_library: ...` and one line `rank_<r>: host=... local_rank=... device=... name=... cc=...` for each rank. The other ranks get `""`. One rank: `""`. |
| `[[noreturn]] void abort_ranks(int code, const std::string&)` | Flushes all C output streams, prints the message with the rank, and calls `MPI_Abort`. Without MPI it calls `std::exit(code)`. |

Errors under MPI (task T034, "hybrid", Pavlo, 2026-11-07):

| Error | Behaviour |
|---|---|
| Bad `Config` field, bad input, no device, allocation failure in the constructor | The checks are local. An agreement (`MPI_MAX` of an error code) follows them. All ranks throw: the rank with the error throws its own exception, the other ranks throw the same type with the text "the setup failed on another rank". |
| NaN or Inf | Carried in the `MPI_MIN` reduce of `Tn` that runs at each block step. All ranks stop at the same block step. |
| Bad argument of `advance_to` | Each rank checks the same value. All ranks throw. |
| CUDA error or MPI error after the constructor checks | The library calls `MPI_Abort` (through `abort_ranks`). It prints the rank and the error first. The other ranks can wait in a collective, so a clean exit is not possible. |

