# MPI-M5. select_device lets ranks share one GPU without an error

- Severity: MEDIUM
- Location: `src/mpi_comm.cpp:76-87` (line 83: `if (count == 1) return 0;`).
- Problem: when a rank sees one device, it returns 0 and skips the check `local_rank >= count`. On a 1-GPU node with `mpirun -np 2`, or with a wrong launcher binding (the same `CUDA_VISIBLE_DEVICES` for all ranks), several ranks use one GPU at a fraction of the speed. No error. Against design section 3.3 and the comment at line 88.
- Note: this path is also useful to test `mpirun -np 2` against `devices={0,0}` on one card.
- Fix: in the constructor, gather the GPU UUIDs (`cudaDeviceProp::uuid`) on the node communicator and throw on a duplicate. Allow sharing only with a new key, for example `mpi_share_device=1` (tests only). Write the UUID in each rank line (MPI-M4).


Source: docs/review/mpi-review.md (main @ 1e26eaa). Line numbers refer to 1e26eaa. Run `git pull` first.
