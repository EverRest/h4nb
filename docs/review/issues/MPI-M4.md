# MPI-M4. Run record: no run_id, hashes, schema, end status, or MPI environment

- Severity: MEDIUM
- Location: `tools/run_info.hpp`, `tools/h4nb_run.cpp:300-303` (.dat headers), `src/mpi_comm.cpp:150-185` (`rank_table`), `tools/h4nb_pack.sh:64-74`, `src/build_info.cu`.
- Problems:
  1. No run_id, no config or input hash, no schema version or units in the .dat headers. Runs of 1/2/4/8 ranks differ only by folder name.
  2. No end record: run_info.txt has `start_utc` only (no `end_utc`, `exit_code`, `total_wall_s`). A failed run (ran: no GPU, exit 1) leaves header-only .dat files and an empty `energy_periods.dat` that look like a valid empty run.
  3. ~~At `-np 1` in an MPI build, the 1-rank point runs the one-process path, not `step_mpi()`.~~ **Partly closed 2026-11-08:** `step_mpi()` is gone; one `step()` holds both exchange paths. At `-np 1`, `mpi` is still false, so the peer-copy branch runs (same as a non-MPI build). `rank_table` empty / no `mpi_library` at `-np 1` is still open.
  4. Rank lines have no GPU `uuid`/`pci`, no `CUDA_VISIBLE_DEVICES`, no CPU affinity or NUMA. Silent GPU sharing (MPI-M5) cannot be seen.
  5. No MPI environment: `OMPI_MCA_*`, `UCX_*`, `MPICH_*`, `FI_*`, `SLURM_*`. No `mpi_cuda_aware`, `mpi_host_staging`, `device_offset` in run_info (only in config.used).
  6. `build_info()` says only `mpi: on`, not the MPI header version used at compile time. A runtime libmpi from another module cannot be detected.
  7. `h4nb_pack.sh` collects `nvidia-smi` of the packing host only. Not collected: `nvidia-smi topo -m`, `ompi_info --parsable` (`mpi_built_with_cuda_support`), `ucx_info -v`, `module list`, `lscpu`/`numactl -H`, per-node GPU lists, the mpirun stdout.
- Fix:
  - Header of each .dat file: `# h4nb <file> schema=2 run_id=<utc-host-pid> config_sha=<16 hex> ic_sha=<16 hex> units: time[code] wall_s[s] bytes[B]` (FNV-1a 64 in code, no new dependency).
  - `summary.json` on rank 0 at the end and on the error paths that reach it: run_id, commit, exit_code, verdict, end_utc, total_wall_s, t_setup, t_init_force, ranks, nodes, exec_path, mpi_library, mpi_header, cuda_aware, host_staging, phase min/mean/max, max_rel_err, steps, mean and median NA.
  - run_info.txt: `exec_path: single|mpi`, `mpi_header` (`comm::header_version()` in mpi_comm.cpp from `MPI_VERSION`, `OMPI_*_VERSION` or `MPICH_VERSION`), `mpi_cuda_aware`, `mpi_host_staging`, `device_offset`, `system_processor`, `end_utc`, `exit_code`; per rank: `uuid= pci= cvd= cpus= numa=`; one filtered `env_rank0:` block. Write the MPI lines for every rank count.
  - `h4nb_pack.sh --mpi`: run the commands above.


Source: docs/review/mpi-review.md (main @ 1e26eaa). Line numbers refer to 1e26eaa. Run `git pull` first.
