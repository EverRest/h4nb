# Multi-node design for h4nb

Status: implemented on 2026-11-07 (tasks T029 to T036). The MPI build compiles. The error paths before the GPU ran under `mpirun -np 2` in a container without a GPU. The GPU path under MPI has not run yet (quickstart A9). Section 10 lists where the code differs from the first design text.
Audience: the developers who build the MPI path, and the reviewers of the constitution and spec changes.

Decisions made by the user (2026-11-07):

- Configuration format: `key=value` arguments. No INI file. FR-019 and plan D1 stay unchanged.
- Constitution version for MPI: 2.0.0 (MAJOR).
- Diagnostics under MPI: each rank computes `N²/G` pair work for its own targets. Rank 0 adds the rank partials in rank order.
- Library: CUDA-aware MPI. NCCL is not used.
- Error path (Q6), "hybrid" (user, 2026-11-07): errors at agreement points stop all ranks cleanly with the normal exit codes. Errors after which the ranks cannot agree stop all ranks with `MPI_Abort`. See section 5.2.

Open items that remain: section 9.2, question 5 (cluster size).

Sources read: `CLAUDE.md`, `docs/cuda-best-practices.md`, `specs/001-hermite-nbody-lib/spec.md` (FR-010, FR-019, FR-022), and `docs/superpowers/plans/2026-11-07-h4nb.md` (D2, D3, O7). Also read: `src/simulation.cu` (`step()`, `diagnostics()`), `tools/h4nb_run.cpp`, and TZ line 558.

---

## 1. Architecture

### 1.1 Layout

Keep the j-parallel layout of plan D2. Each GPU owns N/G particles. Each GPU is one MPI rank.

One block step has four collective phases:

1. **Minimum time.** Each rank reduces its own `next` values. All ranks reduce the minimum `Tn` (`MPI_Allreduce`, `MPI_MIN`).
2. **Gather of active targets.** Each rank predicts its own particles. It selects its active particles. All ranks gather these targets in rank order (`MPI_Allgatherv`). The counts come from a small `MPI_Allgather`.
3. **Partial forces.** Each rank computes the partial force of its own sources on all `NA` targets. It sends the slice of each owner in one exchange (`MPI_Alltoallv`).
4. **Owner sum and correct.** Each owner adds the `G` partials in rank order. It then runs `correct_kernel` and `update_particle`. This matches the current device-order sum in `simulation.cu`.

This maps one-to-one onto the current code. The peer copies in `step()` become the three collectives. The rank index replaces the device index.

### 1.2 Recommendation: CUDA-aware MPI

Use **CUDA-aware MPI** with `MPI_Allgatherv` and `MPI_Alltoallv`. Pass device pointers directly. Fall back to host staging only when the cluster MPI is not CUDA-aware.

Reasons:

- The traffic per step is `O(N_active)`. The collectives are small and latency-bound at high rank counts. MPI gives explicit control over the message order.
- The summation order must be fixed (constitution IV, FR-022). MPI gives a fixed order when we sum the received rows ourselves in rank order. The library does not depend on an internal reduction algorithm.
- TZ line 558 allows CUDA-aware MPI or NCCL. MPI is the default MPI stack on most supercomputers.

### 1.3 Why not NCCL for the reduce-scatter

`ncclReduceScatter` sums the values in an order set by its ring or tree. The order can change with the rank count and the topology. Each output element can use a different start rank. This breaks the fixed rank order of FR-022. A bitwise-identical result would then need an extra exact-sum step. NCCL also adds a new dependency.

NCCL remains a valid option for the all-gather only. Do not use it for the reduce-scatter. Revisit this only if MPI latency is measured as the bottleneck (see gated optimisation O4).

### 1.4 Dependencies

MPI is a new dependency. The constitution, principle V, allows only the CUDA toolkit and the C++ standard library. Section 7 gives the amendment text.

MPI must be optional. Build it with `-DH4NB_MPI=ON`. The default build stays MPI-free. This keeps the single-process path and the `cpu` tests free of MPI.

### 1.5 Public API

The public header must not expose MPI or CUDA types (constitution III). Use this rule:

- If the library runs under MPI (`H4NB_MPI` build), it uses `MPI_COMM_WORLD`.
- The application calls `MPI_Init` and `MPI_Finalize`. The library does not call them.
- `Simulation` keeps its signature. Each rank constructs it with the full `Particles`. Each rank keeps only its own slice on the device.

Add no new public field in the first step. The device of each rank comes from the local rank (section 3.3).

Implementation (T030): the rule above is used. Two plain fields were added to `Config`, because the keys of section 3.1 and T032 need them: `device_offset` and `mpi_host_staging`. Small rank functions were added (`RankScope`, `rank()`, `ranks()`, `local_rank()`, `max_over_ranks()`, `rank_table()`, `abort_ranks()`), so that the tools do not include `mpi.h`. The library uses a copy of `MPI_COMM_WORLD` (`MPI_Comm_dup`). With one rank, the one-process path runs unchanged. Details: `specs/001-hermite-nbody-lib/contracts/public-api.md`, section "Ranks".

---

## 2. Determinism across ranks

### 2.1 Rules

1. Every sum in the force path uses a fixed order: rank 0, then rank 1, and so on. The library sums the received rows itself. It never uses `MPI_Reduce` or `MPI_Allreduce` with `MPI_SUM` on floating-point data in the force path. MPI does not guarantee the order of those operations.
2. Order-independent operations are allowed. Use `MPI_MIN` for `Tn` and for the `minr2` bits. Use `MPI_BOR` for the status bits.
3. The diagnostics sums use the same rule. Each rank sends its row of per-particle values. Rank 0 adds the rows in rank order, then it makes the Neumaier sum over the particles (see section 10, note 2).
4. No floating-point atomics (constitution IV).

### 2.2 What is bit-identical

| Case | Bit-identical? | Condition |
|---|---|---|
| Same build, same rank count, same device model per rank, same input | **Yes** | Required. This is FR-022 for MPI runs. |
| One process, `devices = {0, 1}`, against `mpirun -n 2`, same device model | **Yes (verify on a GPU)** | Same partial sums in the same rank order. Same kernel launch geometry. The diagnostics use the same host function `diag_sum()`, and rank h has the role of device h (MPI-M1). |
| Different rank count (for example 2 against 4) | **No** | The partial sums are split at different points. The sum tree changes. |
| Different GPU model in one run (`sms` differs, so `split()` differs) | **No** | `split()` depends on the SM count. The chunks differ. |
| Different MPI library or different compiler flags | **No** | Not tested. Record them with the result. |

Say this in every result file. Do not claim bit-identical results across rank counts. This matches the note in `cuda-best-practices.md` section 2.

### 2.3 Tolerance for different rank counts

Compare runs with different rank counts with a written tolerance. Use the GPU test tolerances: 1e-10 for the force path and 1e-12 for diagnostics. The user approved them.

This tolerance is not for `mpirun -n P` against one process with P devices. These runs give the same bits, also in the diagnostics (section 2.2). Compare them with `cmp`.

---

## 3. Configuration and launch

### 3.1 Settings

Every parameter can be set in three places. The tools read them in this order. Later sources win.

1. **Defaults** in the `Config` struct.
2. **Config file**, option `config=<path>`. One key per line, written as `key=value`. There are no sections. Blank lines and lines that start with `#` are skipped. A file parser of about 30 lines lives in `tools/`. The library (`Config`) has no parser.
3. **Environment**, variable `H4NB_<KEY>` for each key, in upper case. Examples: `H4NB_ETA`, `H4NB_DEVICE_OFFSET`.
4. **CLI**, arguments `key=value` for each key.

An unknown key in the file, in the environment or on the CLI is an error. Each run writes `config.used` to the output directory. This file holds the final value of every key.

The MPI keys are these:

| Key | Environment variable | Default | Meaning |
|---|---|---|---|
| `device_offset` | `H4NB_DEVICE_OFFSET` | `0` | Added to the local rank to pick the GPU. Use only when the launcher cannot bind one GPU per task. |
| `devices` | `H4NB_DEVICES` | `0` | Single process only. Ignored under MPI. |

### 3.2 Launch

**OpenMPI on a node with 4 GPUs (2 nodes, 8 ranks):**

```
mpirun -np 8 --map-by ppr:4:node --bind-to core ./h4nb_run ic=disk.snap out=run1 t_end=10 eta=0.0005
```

**Slurm:**

```
srun --ntasks-per-node=4 --gpus-per-task=1 --gpu-bind=single:1 ./h4nb_run ic=disk.snap out=run1 t_end=10 eta=0.0005
```

Use `--gpu-bind=single:1`. Each task then sees one GPU, with device index 0.

### 3.3 Device mapping

Each rank finds its local rank with `MPI_Comm_split_type(MPI_COMM_WORLD, MPI_COMM_TYPE_SHARED, ...)`. The `device_offset` value comes from section 3.1. Then:

- If the launcher exposes one GPU per task (`CUDA_VISIBLE_DEVICES` set per task, as with Slurm `--gpu-bind=single`), the rank uses device 0.
- Otherwise the rank uses device `(local_rank + device_offset) % cudaGetDeviceCount()`. The default `device_offset` is 0.

The library checks that `local_rank < cudaGetDeviceCount()`. If not, it throws. It does not share a device silently.

Do not set `CUDA_VISIBLE_DEVICES` inside the program. The launcher owns this setting.

---

## 4. Diagnostics and snapshot I/O

### 4.1 Diagnostics (energy, momentum, angular momentum)

The current code downloads all positions. It computes the potential over unique pairs `j > i` (plan D6). It sums on the host.

Under MPI, the cost of the current design is too high at large rank counts. Each rank would send `N` doubles to rank 0.

Use this design:

1. Each rank holds the positions of all particles. It already has them from the target gather of the last step. At a sync point the state is exact.
2. Each rank computes the potential for **its own targets**. It sums over **all** other particles, not only `j > i`. This doubles the pair work. The work is then equal on all ranks (`N²/G` pairs per rank). The unique-pair trick only halves the work of a single device. The diagnostics run rarely (FR-021), so the extra work is acceptable.
3. Each rank computes the Neumaier partial sums of K, U, P and L for its own particles.
4. Each rank sends 8 doubles to rank 0 (`MPI_Gather`). Rank 0 adds them in rank order with Neumaier summation.

Result: the diagnostics cost is `O(N²/G)` per rank. The code sends `8·N·P` bytes to rank 0, not `O(G)` (section 10, note 2). The diagnostic values are bit-identical to one process with the same parts on P devices.

### 4.2 Snapshots and text output

- **Snapshot.** Rank 0 writes the file. The other ranks send their owned slices with `MPI_Gatherv`. The slices arrive in rank order. Rank order equals global index order, so the file layout is unchanged (`io.cpp`).
  - Cost: `N × 64 B` at rank 0 for each snapshot. At `N = 1 024 000` this is about 64 MB per snapshot. The gather time depends on the network, and it is measured on the cluster.
- **Energy and performance records.** Rank 0 writes them. Only rank 0 opens the files (FR-020).
- **Parallel write.** Not in v1. The single-file snapshot is written by rank 0. Use HDF5 or MPI-IO only after a measured need (gated optimisation O8).

### 4.3 Input

Every rank reads the full input file. For 1 M particles this is about 64 MB per rank. This is acceptable on the target systems. Measure it if the input is larger.

---

## 5. Error handling

### 5.1 Rule

**One rank fails. All ranks stop.** A rank that throws before a collective leaves the other ranks waiting. This is a deadlock.

### 5.2 Design

**Decision (Q6, user, 2026-11-07): hybrid.** This replaces items 1 to 5 below where they differ.

- **Errors at agreement points: a clean collective stop.** All ranks return the normal exit code of `h4nb_run` (1 runtime, 2 settings or input, 3 NaN). Rank 0 writes the files and the verdict.
  - NaN or Inf: the flag goes into the `MPI_Allreduce` (`MPI_MIN`) of `Tn` that runs at each block step. The message holds `{Tn, no-NaN flag}` as two `int64` values. All ranks see the flag after the same block step, and `advance_to()` returns early on all ranks. The tool then sees `kNaN` in `status()` (`MPI_BOR`) and returns 3.
  - Settings and input checks in the tool: each rank checks. Then all ranks agree on the largest error code (`MPI_MAX`, `h4nb::max_over_ranks`). A rank with an error calls the same agreement from its error handler. A settings error is printed one time.
  - `Simulation` constructor: the checks, the device selection and the allocations are local. An `MPI_MAX` agreement follows them, before the first collective. All ranks throw.
  - File writes (rank 0 only): rank 0 records the error. All ranks agree at the next diag time and at the end of the run. All ranks return 1.
- **Errors after which the ranks cannot agree: `MPI_Abort`.** A CUDA error, an MPI error or an exception on one rank only. The other ranks can wait in a collective. The library (or the tool) flushes all C output streams, prints the message with the rank, and calls `MPI_Abort`. The library communicator uses `MPI_ERRORS_RETURN`, so an MPI error becomes an exception with the call name and the rank.

First design text (kept for reference):

1. **CUDA error or allocation failure on one rank.** The rank calls `MPI_Abort(MPI_COMM_WORLD, code)`. This stops all ranks. The library prints the rank, the CUDA error and the call. Use this as the first version. It is simple and it cannot deadlock. Upgrade path: an error-flag `MPI_Allreduce` once per step. Use it only if clean exits are needed.
2. **Invalid numerical value (NaN or Inf).** The status word is OR-reduced across ranks at each sync point (`MPI_Allreduce`, `MPI_BOR`). The owner of the bad target sets the bit. After the reduce, every rank sees the bit. Every rank then throws the same error at the same step. No rank is left in a collective.
3. **Too small time step (`kDtUnderflow`) and close pair (`kClosePair`).** Same as the NaN case. They are status bits.
4. **Invalid input** (size mismatch, `N < G`, bad `max_level`). Each rank checks the same input. Each rank throws the same error. No collective has run yet, so this is safe.
5. **Output error** (cannot write a snapshot). Rank 0 checks the write. Rank 0 calls `MPI_Abort` if the write fails. The other ranks then stop.

### 5.3 NaN and Inf across ranks

- The NaN check `x != x` (or `!(x - x == 0)`) works on each rank. It needs no change.
- The status word of each rank has bits for its own targets. The OR-reduce makes the word global.
- The run stops at the first sync point after the bad value. The sync point is the end of the block step. It is one step later than the bad value. Document this delay in the run log.
- Implementation: the check is at the start of each block step (phase 1). The time in the message of `h4nb_run` is the time of the last finished block step.

---

## 6. Test strategy

### 6.1 In the CPU-only container (no GPU)

What the container can check:

1. **Build with MPI.** Install `openmpi-bin` and `libopenmpi-dev` in the container (Ubuntu 24.04). Configure with `-DH4NB_MPI=ON`. Build all targets.
2. **MPI-free build is unchanged.** Build without `H4NB_MPI`. Run `ctest -L cpu`. The result must match the current result.
3. **A new CPU test under MPI, label `cpu-mpi`.** Run it with `mpirun -n 2 --allow-run-as-root --oversubscribe ctest`. The test checks the logic that needs no GPU:
   - the fixed-order sum helper gives the same bits as a serial sum in rank order;
   - the split of `N` into rank slices (`base` and `n`) covers `[0, N)` exactly once;
   - `MPI_Allgatherv` gives the slices in rank order;
   - the OR-reduce of status bits and the min-reduce of `Tn` give the expected values on every rank.
4. **`mpirun -n 2` smoke test.** Run `h4nb_mkdisk` on one rank and `h4nb_run` on two ranks. The GPU path is not reached. The run must exit with a clear message ("no CUDA device"), and it must exit on both ranks. This checks the error path of section 5.2 item 1.

### 6.2 On a cluster (GPU needed)

1. **Single node, 2 GPUs.** Compare `mpirun -np 2` with `devices={0,1}` in one process. Expect the bit-identical result in section 2.2. Record the result or the first difference.
2. **Rank count change.** Run the same input with 2, 4 and 8 ranks. Check the tolerance of section 2.3.
3. **Repeatability.** Run the same configuration twice with the same rank count. The output must be identical.
4. **Scaling.** Measure strong scaling (fixed N, more ranks) and weak scaling (N grows with the rank count). Report the speed-up against one GPU (cuda-best-practices section 6).
5. **Error path.** Insert a NaN in one particle. All ranks must exit with a non-zero code in the same step.
6. **Acceptance.** Repeat the 128k and 1M acceptance runs of the plan (Task 7) on the cluster. Record the hardware and the MPI stack with the result.

---

## 7. Constitution amendment (text for review)

The changes below touch principle V and the Hardware and Toolchain section. They need the user's approval.

**Principle V (Simplicity).** Replace the dependency sentence with this text:

> - The dependencies are the CUDA toolkit (CUB and Thrust included) and the C++ standard library. The MPI library is an optional dependency. It is used only when the build sets `H4NB_MPI=ON`. No other dependency is allowed.

**Hardware and Toolchain Constraints.** Replace the single-node sentence with this text:

> - v1 runs as one process per GPU. The processes may run on one node or on several nodes. Multi-node runs use MPI, with CUDA-aware MPI where the system provides it. The number of ranks is set by the launcher.

**Principle IV (Deterministic Results).** Add this sentence:

> - Bit-identical results are guaranteed only for the same build, rank count and device list. Compare results for different rank counts with a written tolerance.

**Version.** Removing a constraint and adding a dependency changes the meaning of principle V. Under the governance rules, a change of meaning in a principle is a **MAJOR** change. The proposed version is **2.0.0**. The user chose 2.0.0 on 2026-11-07.

**Sync Impact Report.** List principle V, principle IV and the Hardware section as modified. Set the last amended date to the day of approval.

---

## 8. Spec and plan changes

### 8.1 spec.md (for h4nb-3a; do not edit before agreement)

1. **New user story (P2), "Run on several nodes".** A researcher runs one system on GPUs across several nodes. The results agree with one node. The run time per step decreases with more nodes. Independent test: run the same input on 2 GPUs of one node and on 2 nodes. Compare the results with section 2.3.
2. **FR-010, extend.** Add: "The GPUs may be on one or several nodes. Each GPU is one MPI rank. The exchange of the active targets and of the partial forces uses MPI. The owner adds the partial forces in rank order."
3. **FR-022, qualify.** Add: "Bit-identical results are required for the same build, rank count and device list. Runs with different rank counts are compared with the tolerance in the test plan."
4. **FR-019, no change.** Keep `key=value` arguments. The user decided this on 2026-11-07. Do not add an INI file.
5. **New SC (for example SC-010).** "A two-node run agrees with a one-node run of the same rank count within the stated tolerance. The cluster run records the MPI stack."
6. **Assumptions.** Replace "Multi-node work is out of scope" (if present) with the new scope.

### 8.2 plan (for h4nb-3a)

1. **D3 (line 35).** Replace "It does not use MPI or NCCL" with: "It uses MPI for more than one node. NCCL is not used for the reduce-scatter (design: docs/multi-node-design.md)."
2. **O7 (line 2071).** Move O7 into v1. Change the row to "Multi-node: MPI, CUDA-aware where available, with an ordered sum of the partial forces." Remove the gate. The user approved multi-node for v1.
3. **New task (after Task 5): "Task 5b: MPI path".** Steps:
   - (a) Add the `H4NB_MPI` CMake option and an optional `find_package(MPI)`.
   - (b) Select the device by local rank.
   - (c) Add the collectives to `step()` and `diagnostics()`, with rank-order sums.
   - (d) Add the `MPI_Abort` error path.
   - (e) Write the `cpu-mpi` tests of section 6.1.
   - (f) Register them with CTest.
   - (g) Run the cluster tests of section 6.2.
4. **Task 6 (tools).** `h4nb_run` runs under `mpirun` with no change to its arguments.
5. **Task 7 (acceptance).** Add one 2-node run and one 4-node run to the acceptance list.
6. **File structure.** Add `tests/test_mpi_logic.cpp` (label `cpu-mpi`).

---

## 9. Risks and open questions

### 9.1 Risks

| Risk | Effect | Mitigation |
|---|---|---|
| Cluster MPI is not CUDA-aware | Traffic goes through host memory. Slower steps. | Host staging path. Measure the difference. |
| Latency per step at many ranks (3 collectives and 2 host syncs per block step) | Scaling stops when `N_active` is small. | Measure first (Nsight Systems). Gated O4 (CUDA graphs) and a batch of short steps. |
| `MPI_Abort` loses the last output | The run log has gaps. | Write the energy record each interval with flush. Accept the loss at abort. |
| Diagnostics do `N²/G` work per rank | Diagnostics cost more than one device. | Keep the interval large (FR-021). Measure the cost. |
| Diag point sends `8·N·P` bytes to rank 0 | Slow diag points at large N and P. | Keep the interval large (FR-021). Measure the cost (MPI-M8). |
| Snapshot gather at 1M particles (64 MB) | Slow snapshots on a slow network. | Snapshot interval set by the user. Parallel I/O only after measurement. |
| Input read by every rank (64 MB each at 1M) | Slow start on a shared file system. | Read on rank 0 and broadcast only if the start time is measured as a problem. |
| MPI and CUDA versions differ on the cluster | Build or run failure. | Record the MPI, CUDA and driver versions with each result. |

### 9.2 Open questions for the user

1. **Cluster MPI stack.** Decided: CUDA-aware MPI (user, 2026-11-07). Open: which MPI stack and which cluster do you use?
2. **Configuration format.** Decided: `key=value` arguments (user, 2026-11-07). Open: a peer session reported an INI decision. Confirm which one applies.
3. **Constitution version.** Decided: 2.0.0 (user, 2026-11-07).
4. **Diagnostics method.** Decided: `N²/G` per rank (user, 2026-11-07).
5. **Cluster size.** How many nodes and GPUs per node are the targets? This sets the scaling tests and the 1M-particle plan.
6. **Abort or clean stop.** Decided: hybrid (user, 2026-11-07). See section 5.2.

---

## 10. Implementation notes (2026-11-07)

Where the code differs from the text above, and why:

1. **Diagnostics (section 4.1).** Each rank runs the potential kernel of the one-process path for its **own sources**, with pairs `j > i` only. It does not sum over all pairs of its own targets. The work of rank r is about `N·n_r − n_r²/2` pairs. This is at most `N²/G` for each rank, so the cost bound of the decision holds. The total work is `N²/2`, not `N²`. The code uses the existing kernel. No new kernel needs a GPU check.
2. **Diagnostics sums (MPI-M1).** The MPI result is bit-identical to one process with the same parts on P devices. Rank h has the role of device h. Both paths call one host function, `diag_sum()` in `src/diag_sum.cpp`:
   - K, P and L: every rank has the full state from `state()`. Rank 0 computes them over all particles in index order.
   - U: `MPI_Gather` sends the `phi` row of each rank (N doubles) to rank 0 in rank order. For each particle, rank 0 adds the rows in rank order, as one process adds the device rows. Then it makes one Neumaier sum over the particles.
   - W_diss: `MPI_Gatherv` sends `wd` to rank 0 in global order. Rank 0 makes the Neumaier sum over the particles.
   - `MPI_Bcast` copies the 10 result values to all ranks. So every rank has the same `Diagnostics` bits. MPI adds no floating-point value.
   - Cost: `8·N·P` bytes to rank 0 at each diag point (64 MB at N = 1M and P = 8), plus `8·N` bytes for `wd` when dissipation is on. The test `tests/test_diag_order.cpp` checks the gather layout on the CPU.
   - MPI-M8 proposes to gather only the positions. For K, P and L this is now superseded: bit-identity needs the velocities of all particles on rank 0, and `state()` gives them.
3. **Snapshots and `state()` (section 4.2).** `state()` uses `MPI_Allgatherv`, not `MPI_Gatherv` to rank 0. Every rank gets the full set. The diagnostics need all positions on every rank anyway. Cost: `N × 64 B` on every rank for each call. Upgrade path: `MPI_Gatherv` to rank 0, after a measurement.
4. **Device selection (section 3.3).** One visible device: device 0. Otherwise `(local_rank + device_offset) % count`. The constructor throws when `local_rank >= count`.
5. **Tests (section 6.1).** No `cpu-mpi` test is in the repository (the task list has no test tasks). A check program outside the repository ran under `mpirun -np 1` to `-np 4`. It checked the rank order of `MPI_Allgatherv`, the row layout of `MPI_Alltoallv`, the bitwise rank-order sum, the `MPI_MIN` flag, `MPI_BOR`, `MPI_MAX`, and `abort_ranks` (all ranks stop, the file is flushed).

