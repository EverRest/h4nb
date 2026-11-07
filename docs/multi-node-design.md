# Multi-node design for h4nb

Status: design only. No source change is made by this document.
Audience: the developers who build the MPI path, and the reviewers of the constitution and spec changes.

Sources read: `CLAUDE.md`, `docs/cuda-best-practices.md`, `specs/001-hermite-nbody-lib/spec.md` (FR-010, FR-019, FR-022), `docs/superpowers/plans/2026-11-07-h4nb.md` (D2, D3, O7), `src/simulation.cu` (current `step()`, `diagnostics()`), `tools/h4nb_run.cpp`, and TZ line 558 (CUDA-aware MPI or NCCL).

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

---

## 2. Determinism across ranks

### 2.1 Rules

1. Every sum in the force path uses a fixed order: rank 0, then rank 1, and so on. The library sums the received rows itself. It never uses `MPI_Reduce` or `MPI_Allreduce` with `MPI_SUM` on floating-point data in the force path. MPI does not guarantee the order of those operations.
2. Operations that do not depend on the order are allowed: `MPI_MIN` on `Tn` and on the `minr2` bits, and `MPI_BOR` on the status bits.
3. The diagnostics sums use the same rule. Each rank sends its partial sum. Rank 0 adds the partials in rank order (Neumaier, see section 4).
4. No floating-point atomics (constitution IV).

### 2.2 What is bit-identical

| Case | Bit-identical? | Condition |
|---|---|---|
| Same build, same rank count, same device model per rank, same input | **Yes** | Required. This is FR-022 for MPI runs. |
| Single process with `devices = {0, 1}` against `mpirun -n 2` with the same device model | **Expected, to be verified** | The same partial sums are formed in the same rank order. The force kernel launch geometry is the same. |
| Different rank count (for example 2 against 4) | **No** | The partial sums are split at different points. The sum tree changes. |
| Different GPU model in one run (`sms` differs, so `split()` differs) | **No** | `split()` depends on the SM count. The chunks differ. |
| Different MPI library or different compiler flags | **No** | Not tested. Record them with the result. |

Say this in every result file. Do not claim bit-identical results across rank counts. This matches the note in `cuda-best-practices.md` section 2.

### 2.3 Tolerance for different rank counts

Compare runs with different rank counts with a written tolerance. Use the same tolerance as the GPU test (1e-10 for the force path, 1e-12 for diagnostics, as approved by the user).

---

## 3. Configuration and launch

### 3.1 Settings

The spec (FR-019) forbids INI files and requires `key=value` arguments. The plan (D1) says the library reads no configuration file. **This design does not add INI keys.** Section 8 lists the conflict. The user must decide.

The MPI settings are these:

| Setting | Where | Meaning |
|---|---|---|
| `devices=` | tool argument (`h4nb_run`) | Ignored under MPI. The local rank selects the device. |
| `ranks_per_node=` | not needed | Set by the launcher, not by the program. |
| `H4NB_DEVICE_OFFSET` | environment, optional | Adds an offset to the local rank. Use only when the launcher cannot bind GPUs. Otherwise omit. |

Do not add `H4NB_*` settings for numerics. Numerics come from the run arguments and are recorded with each result.

### 3.2 Launch

**OpenMPI on a node with 4 GPUs (2 nodes, 8 ranks):**

```
mpirun -np 8 --map-by ppr:4:node --bind-to core ./h4nb_run ic=disk.snap out=run1 t_end=10 eta=0.0005
```

**Slurm:**

```
srun --ntasks-per-node=4 --gpus-per-task=1 --gpu-bind=single:1 ./h4nb_run ic=disk.snap out=run1 t_end=10 eta=0.0005
```

Use `--gpu-bind=single:1` so that each task sees one GPU. Then the device index is 0 for each task.

### 3.3 Device mapping

Each rank finds its local rank with `MPI_Comm_split_type(MPI_COMM_WORLD, MPI_COMM_TYPE_SHARED, ...)`. Then:

- If the launcher exposes one GPU per task (`CUDA_VISIBLE_DEVICES` set per task, as with Slurm `--gpu-bind=single`), the rank uses device 0.
- Otherwise the rank uses device `local_rank % cudaGetDeviceCount()`.

The library checks that `local_rank < cudaGetDeviceCount()`. If not, it throws. It does not share a device silently.

Do not set `CUDA_VISIBLE_DEVICES` inside the program. The launcher owns this setting.

---

## 4. Diagnostics and snapshot I/O

### 4.1 Diagnostics (energy, momentum, angular momentum)

The current code downloads all positions, computes the potential over unique pairs `j > i` (plan D6), and sums on the host.

Under MPI, the cost of the current design is too high at large rank counts. Each rank would send `N` doubles to rank 0.

Use this design:

1. Each rank holds the positions of all particles. It already has them from the target gather of the last step. At a sync point the state is exact.
2. Each rank computes the potential for **its own targets**. It sums over **all** other particles, not only `j > i`. This doubles the pair work. The work is then equal on all ranks (`N²/G` pairs per rank). The unique-pair trick only halves the work of a single device. The diagnostics run rarely (FR-021), so the extra work is acceptable.
3. Each rank computes the Neumaier partial sums of K, U, P and L for its own particles.
4. Each rank sends 8 doubles to rank 0 (`MPI_Gather`). Rank 0 adds them in rank order with Neumaier summation.

Result: the diagnostics cost is `O(N²/G)` per rank and `O(G)` data at rank 0. The diagnostic values differ from the single-process values in the last bits, because the sum order differs. Compare them with the tolerance of section 2.3.

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

1. **CUDA error or allocation failure on one rank.** The rank calls `MPI_Abort(MPI_COMM_WORLD, code)`. This stops all ranks. The library prints the rank, the CUDA error and the call. Use this as the first version. It is simple and it cannot deadlock. Upgrade path: an error-flag `MPI_Allreduce` once per step. Use it only if clean exits are needed.
2. **Invalid numerical value (NaN or Inf).** The status word is OR-reduced across ranks at each sync point (`MPI_Allreduce`, `MPI_BOR`). The owner of the bad target sets the bit. After the reduce, every rank sees the bit. Every rank then throws the same error at the same step. No rank is left in a collective.
3. **Too small time step (`kDtUnderflow`) and close pair (`kClosePair`).** Same as the NaN case. They are status bits.
4. **Invalid input** (size mismatch, `N < G`, bad `max_level`). Each rank checks the same input. Each rank throws the same error. No collective has run yet, so this is safe.
5. **Output error** (cannot write a snapshot). Rank 0 checks the write. Rank 0 calls `MPI_Abort` if the write fails, so that the other ranks do not wait.

### 5.3 NaN and Inf across ranks

- The NaN check `x != x` (or `!(x - x == 0)`) works on each rank. It needs no change.
- The status word of each rank has bits for its own targets. The OR-reduce makes the word global.
- The run stops at the first sync point after the bad value. The sync point is the end of the block step. It is one step later than the bad value. Document this delay in the run log.

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

> - Bit-identical results are guaranteed only for the same build, the same number of ranks and the same device list. Results for different rank counts are compared with a written tolerance.

**Version.** Removing a constraint and adding a dependency changes the meaning of principle V. Under the governance rules, a change of meaning in a principle is a **MAJOR** change. The proposed version is **2.0.0**. The user decides between 2.0.0 (recommended) and 1.2.0 (if the user rules that the change is an addition only).

**Sync Impact Report.** List principle V, principle IV and the Hardware section as modified. Set the last amended date to the day of approval.

---

## 8. Spec and plan changes

### 8.1 spec.md (for h4nb-3a; do not edit before agreement)

1. **New user story (P2), "Run on several nodes".** A researcher runs one system on GPUs across several nodes. The results agree with one node. The run time per step decreases with more nodes. Independent test: the same input on 2 GPUs of one node and on 2 nodes, with the comparison of section 2.3.
2. **FR-010, extend.** Add: "The GPUs may be on one or several nodes. Each GPU is one MPI rank. The exchange of the active targets and of the partial forces uses MPI. The owner adds the partial forces in rank order."
3. **FR-022, qualify.** Add: "Bit-identical results are required for the same build, rank count and device list. Runs with different rank counts are compared with the tolerance in the test plan."
4. **FR-019, conflict.** This design adds no INI file. Do not change FR-019 without the user's decision (see section 9, question 2).
5. **New SC (for example SC-010).** "A two-node run agrees with a one-node run of the same rank count within the stated tolerance, and the runs are measured on a cluster with the MPI stack recorded."
6. **Assumptions.** Replace "Multi-node work is out of scope" (if present) with the new scope.

### 8.2 plan (for h4nb-3a)

1. **D3 (line 35).** Replace "It does not use MPI or NCCL" with: "It uses MPI for more than one node. NCCL is not used for the reduce-scatter (design: docs/multi-node-design.md)."
2. **O7 (line 2071).** Move O7 into v1. Change the row to "Multi-node: MPI, CUDA-aware where available, with an ordered sum of the partial forces." Remove the gate, because the user approved multi-node for v1.
3. **New task (after Task 5): "Task 5b: MPI path".** Steps: (a) `H4NB_MPI` CMake option and optional `find_package(MPI)`; (b) local-rank device selection; (c) collectives in `step()` and `diagnostics()`, with the rank-order sums; (d) `MPI_Abort` error path; (e) `cpu-mpi` tests of section 6.1; (f) CTest registration; (g) the cluster runs of section 6.2.
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
| Rank-order sum differs from the single-process sum in the last bits | Tests that compare the two need the tolerance. | Section 2.3. |
| Snapshot gather at 1M particles (64 MB) | Slow snapshots on a slow network. | Snapshot interval set by the user. Parallel I/O only after measurement. |
| Input read by every rank (64 MB each at 1M) | Slow start on a shared file system. | Read on rank 0 and broadcast only if the start time is measured as a problem. |
| MPI and CUDA versions differ on the cluster | Build or run failure. | Record the MPI, CUDA and driver versions with each result. |

### 9.2 Open questions for the user

1. **MPI or NCCL?** This design recommends CUDA-aware MPI with explicit ordered sums. Which MPI stack and which cluster do you use?
2. **Configuration format.** The spec (FR-019) and the plan (D1) forbid INI files. The request asked for INI keys. Keep `key=value` arguments only (recommended), or change FR-019 and D1?
3. **Constitution version.** Is the change 2.0.0 (MAJOR, recommended) or 1.2.0?
4. **Diagnostics method.** Accept the `N²/G` diagnostic work per rank (section 4.1), or keep the single-device unique-pair method with a gather of `N` doubles per rank?
5. **Cluster size.** How many nodes and GPUs per node are the targets? This sets the scaling tests and the 1M-particle plan.
6. **Abort or clean stop.** Is `MPI_Abort` on error acceptable (section 5.2 item 1)?
