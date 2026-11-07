# MPI-H2. A constructor error on a non-root rank is not printed

- Severity: HIGH
- Location: `tools/h4nb_run.cpp:323-327`, with `src/simulation.cu:213-218`.
- Problem: when `Simulation` fails on rank k > 0 only (for example "local rank 4 >= device count 4", or `cudaMalloc` fails), all ranks agree on the code. Rank 0 prints only "the setup failed on another rank. See the message of that rank". Rank k returns its code at line 326 and prints nothing. The real cause is lost.
- Evidence (ran, code-review skill): MPMD `mpirun -n 1 h4nb_run ... : -n 1 h4nb_run ... devices=`. The message "devices must not be empty" of rank 1 is not printed.
- Fix: print the exception on a non-root rank when the error is local. For example, `construct_mpi` throws a type (or sets a flag) that tells "local" from "another rank", and the tool prints `e.what()` with the rank for a local error. Better: gather the error texts to rank 0 (`MPI_Gatherv`, as `rank_table` does) and print one line for each failed rank.


Source: docs/review/mpi-review.md (main @ 1e26eaa). Line numbers refer to 1e26eaa. Run `git pull` first.
