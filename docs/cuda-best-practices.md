# CUDA and large-scale computing: best practices for h4nb

Read this file before you write or change code in `src/`, `tools/` or `tests/`.
The constitution (`.specify/memory/constitution.md`) has priority over this file.
Rules marked **[project]** come from mistakes in this repository.
The other rules come from the sources in section 7.

## 1. Kernels

- **Divergence.** A warp has 32 threads. If threads of one warp take different branches, the warp runs the branches one after the other. Avoid divergent branches inside a warp.
- A plain `if` is allowed. The cost is small if only one thread in 32 takes the other path (example: `j != i`). The cost is zero if the condition aligns with the warp boundary (`threadIdx.x / warpSize`).
- Keep short conditional blocks small. The compiler can then use predicated instructions. If two paths are expensive, group the elements by path or use two kernels. Read the SASS if you do not know what the compiler did.
- **Loops.** Give every loop a known upper limit. To process `n` elements, use a grid-stride loop: `for (i = blockIdx.x*blockDim.x + threadIdx.x; i < n; i += blockDim.x*gridDim.x)`. This loop works for any `n` and keeps memory access coalesced. Launch `<<<1,1>>>` for a serial debug run.
- Use signed `int` for loop counters. Use `#pragma unroll` to control unrolling. Use `__syncwarp()` after a divergent block if later code needs the warp together.
- **Synchronization.** Never put `__syncthreads()` in a branch that not all threads of the block take. Remove each synchronization point that you do not need.
- **Memory.** Make global memory access coalesced: thread k reads word k. Stride 2 gives only 50 % efficiency. Use SoA (structure of arrays) when threads read one field. Put data in shared memory when many threads of a block reuse it. Avoid bank conflicts. There are 32 banks. If many threads read one address, this is a broadcast and not a conflict. Use `__restrict__` on pointers that do not overlap.
- **Launch configuration.** Use a block size that is a multiple of 32. Start with 128 to 256 threads. Use more blocks than SMs (thousands for large problems). Add `__launch_bounds__`. Higher occupancy is not always faster. Launch kernels that must overlap in non-default streams. The default stream waits for all other streams.
- **Transfers.** Keep intermediate data on the device. Combine small copies into one copy. Use pinned memory with `cudaMemcpyAsync`. Do not use too much pinned memory.
- **No guessing.** Do not make the code more complex for speed without a measured reason. Measure with a profiler or benchmark before and after the change (constitution, principle II).

## 2. Numerics and determinism

- Use FP64 for all physical values. Do not use fast-math, mixed precision or Tensor Cores in v1 (constitution, principles I and II).
- The flag `-use_fast_math` changes single precision. A host flag such as `-ffast-math` breaks the NaN check `x != x`. Do not use it.
- Floating-point addition is not associative. The order of the sum changes the result. Fix the order of each sum. Use a fixed reduction tree or a sum over rows in index order.
- **Do not use floating-point atomics.** Integer atomics are allowed (`atomicOr` for status bits, `atomicMin` on non-negative bit patterns).
- A different number of threads or GPUs changes the reduction tree. Do not claim bit-identical results for different device lists.
- FMA rounds one time. A separate multiply and add rounds two times. CPU and GPU results can differ a little. This is not always a bug.
- Compare floating-point results with a tolerance. Write the tolerance down. Use exact comparison only for determinism checks (same input, same build, same device list) and for NaN checks.
- Use compensated summation (Neumaier) for diagnostic sums. Store time as integer ticks.
- **Never loosen a test threshold to make a test pass.** Find the cause. Record the measured value. Tell the user.

## 3. Errors and correctness

- Check the return code of each CUDA API call. Check each kernel launch with `cudaGetLastError()`.
- Call `cudaDeviceSynchronize()` before a CPU timer reads the time. You can also use CUDA events.
- Validate input at the boundary: array sizes, finite values (NaN and Inf), `N >= 2`, positive masses. Do not use a silent fallback. Raise a clear error or set a status bit.
- After a kernel change, run `compute-sanitizer` on a GPU machine. Build with `-lineinfo`. Run `memcheck` first (out-of-bounds access, leaks). Then run `racecheck` (shared-memory hazards), `initcheck` (reads of uninitialized memory) and `synccheck` (wrong `__syncthreads`).
- **[project]** Before you change a shared function, use `grep` to find all callers. Fix the cause in the shared function. Do not fix the symptom in one caller.

## 4. C++ pitfalls

- **[project]** The line `std::vector<int> v(size_t(n));` is a function declaration (most vexing parse). It broke the build one time. Write `std::vector<int> v(n);` instead.
- **[project]** Do not mix signed and unsigned values in indexes without a reason. For products such as `N * x`, use `int64_t` or `size_t`. This prevents `int` overflow.
- Use RAII for memory. Each `cudaMalloc` needs a free on all exit paths. This includes exceptions.
- The public API must not expose CUDA types. The only dependencies are the CUDA toolkit (CUB, Thrust) and the C++ standard library (constitution, principles III and V).
- Put a `ponytail:` comment on each deliberate shortcut that has a known limit. Name the limit and the upgrade path in the comment.

## 5. Before you say "done"

1. Build the code in the container. Use the command in the plan, or ask the session that owns the build. Code that is not compiled is not finished.
2. Run all tests that need no GPU (`ctest -L cpu`) and `h4nb_mkdisk`.
3. State what you only compiled. State what you ran. Do not write "works" after a compile-only check. GPU runs happen on the testers' machines (`specs/001-hermite-nbody-lib/quickstart.md`).
4. Keep diffs small. Do not refactor code that you do not need to change. Do not commit or push unless the user asks. Send a message to the other session before you edit a file that it edits.

## 6. Large-scale computing

- **Profile in two steps.** Use Nsight Systems first. Look for GPU idle gaps, transfers and launch overhead. Then use Nsight Compute on the important kernels. Look at roofline, occupancy and memory throughput. Profile again after each change. The bottleneck can move.
- **Scaling.** Measure strong scaling (fixed N, more GPUs) and weak scaling (N grows with the GPU count). Report the speed-up against one GPU. Do not report only the wall time. Keep the traffic between devices proportional to the active work (here O(N_active) for each block step).
- **Reproducibility.** Record these items with each result: hardware, driver, CUDA version, compiler flags, `CMAKE_CUDA_ARCHITECTURES`, commit, input and seed. Put them in `docs/results.md`. Nobody can check a result without them.
- **Checkpoints.** A long run needs restart files. Write them at a fixed interval. Write to a temporary name, then rename the file. At large scale a checkpoint costs more. Then use asynchronous writes or multi-level schemes (example: the SCR library). The v1 snapshots do not hold `a, j, t, level`. A restart computes them again (plan, O8).
- **Scientific code.** Write for people first. Keep inputs and outputs under version control. Make runs scriptable. Test against analytic cases (Wilson et al., 2014 and 2017).

## 7. Sources and confidence

Checked against official NVIDIA documentation (good confidence):

- [CUDA C++ Best Practices Guide](https://docs.nvidia.com/cuda/cuda-c-best-practices-guide/index.html): memory, transfers, streams, occupancy, control flow, math.
- [Floating Point and IEEE 754 for NVIDIA GPUs](https://docs.nvidia.com/cuda/floating-point/index.html): FMA, order of summation, CPU and GPU differences.
- [Compute Sanitizer](https://docs.nvidia.com/compute-sanitizer/ComputeSanitizer/index.html): the four tools.
- [Grid-stride loops](https://developer.nvidia.com/blog/cuda-pro-tip-write-flexible-kernels-grid-stride-loops/).
- [Nsight Compute roofline](https://developer.nvidia.com/blog/accelerating-hpc-applications-with-nsight-compute-roofline-analysis).

Weaker sources (blogs, forums, papers). They are useful but not official:

- Predication and divergence: [Mohamed Elashri](https://blog.melashri.net/branching-on-gpus), [NVIDIA forum](https://forums.developer.nvidia.com/t/solved-ptx-isa-predicated-execution-and-the-warp-divergence-issue/31957).
- Float atomics and determinism: [arXiv 2408.05148](https://arxiv.org/pdf/2408.05148), [NVIDIA Warp](https://nvidia.github.io/warp/v1.15/_sources/user_guide/deterministic_execution.rst.txt).
- Checkpoint and restart at scale: [Sandia](https://sandia.gov/ccr/publications/details/keeping-checkpoint-restart-viable-for-exascale-systems-2011-09-01).
- Scientific computing: [Wilson et al.](https://econpapers.repec.org/RePEc:plo:pcbi00:1005510). Only summaries were read.

Not checked: the Programming Guide pages on SIMT, atomics and cooperative groups. Multi-node (MPI) practice is also not checked.
