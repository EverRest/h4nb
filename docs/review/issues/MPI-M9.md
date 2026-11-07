# MPI-M9. CI does not run MPI; no cpu-mpi tests; the GPU acceptance test is not written down

- Severity: MEDIUM (verification gap; tasks.md has no test tasks by Pavlo's decision, so these are recommendations)
- Location: `.github/workflows/ci.yml:17-30`, `CMakeLists.txt:39-43`.
- Problems:
  1. The build-mpi job compiles for sm_80 on x86_64 only. `ctest -L cpu` never initializes MPI, so no line of `mpi_comm.cpp` runs. mpirun is never called.
  2. The commit stamp says `-dirty` for most builds: `git status --porcelain` counts untracked files, and `.gitignore` has only `build/`. Evidence (ran): `h4nb_commit: 1e26eaa-dirty` with only `?? build-mpi/`. On the cluster every scaling run looks like modified code.
- Fix:
  - Stamp: `git status --porcelain --untracked-files=no`; add `build*/` to `.gitignore`.
  - CI: `-DCMAKE_CUDA_ARCHITECTURES="80;90"` in build-mpi; optional `ubuntu-24.04-arm` job (GH200 host is aarch64).
  - ctest label `cpu-mpi` (`MPIEXEC_EXECUTABLE`, `--oversubscribe`, `OMPI_ALLOW_RUN_AS_ROOT(_CONFIRM)=1`, TIMEOUT 60 so that a hang fails):
    1. No-GPU smoke: `mpirun -np 2 h4nb_run`: exit 1, "no CUDA device for rank", rank_0 and rank_1 lines (passes today).
    2. Settings agreement: `tile=7`, `device_offset=-1` at np 2/3: exit 2, one message.
    3. `h4nb_study`/`h4nb_bench` at np 2: exit 2.
    4. MPMD mismatch of settings and of input (MPI-H1): exit 2, no hang.
    5. `test_mpi_comm` (np 1..4): min_i64, bor, max_int, rank order of allgatherv, alltoallv row layout, bitwise rank-order Neumaier sum, rank_table format, RankScope, abort_ranks (WILL_FAIL, checks a flushed file). Extract `part_base(N,P,k)` (inline at `simulation.cu:244-246` and `:263-264`) and test that the parts cover [0, N) once.
  - GPU acceptance test (one node, 2 GPUs of one model): input `h4nb_mkdisk n=2047`, also 2049 and 127999 (uneven parts). A: `devices=0,1`; B: `mpirun -np 2`; C: B with `mpi_host_staging=1`; all with `diag=snap=T/16 perf=0`. Pass: `cmp` of all snapshots and `timesteps.dat` A=B=C; energy/momentum within 1e-12 (MPI-M1); B twice byte-identical (FR-022); 2 nodes against 1 node identical snapshots. Check that the run_info UUIDs differ. On a mismatch record the first snapshot and particle.


Source: docs/review/mpi-review.md (main @ 1e26eaa). Line numbers refer to 1e26eaa. Run `git pull` first.
