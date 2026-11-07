# h4nb acceptance results

Copy this file to `docs/results.md` on your machine. Fill it in.
Follow the steps in `specs/001-hermite-nbody-lib/quickstart.md`.
Fill in every field.
If a run does not meet an expected value, do not change the value.
Write the measured number. Write the cause that you found.

## 1. Hardware and build

- Date:
- Tester:
- Host OS and kernel:
- GPU model and count:
- Driver version (`nvidia-smi`):
- CUDA toolkit version (`nvcc --version`):
- CMake version:
- h4nb commit or tag:
- Build command and `CMAKE_CUDA_ARCHITECTURES`:

## 2. Benchmark (TZ 12, last line)

Run: `build/h4nb_bench n=16384,65536,131072,262144,524288,1024000 devices=0`.
Run it again with `devices=0,1` or with all GPUs.

| N | devices | wall time | GFLOP/s (60 FLOP/pair) | % of FP64 peak |
|---|---|---|---|---|
|   |   |   |   |   |

Speed-up with 2 GPUs, for N ≥ 131072. Expected value: at least 1.8.

## 3. Choice of η (TZ 11.3, 15.4)

Mean period used. Source: `quickstart.md`.

| frac | T | diag | η | max \|ΔE/E₀\| | ≤ 1e-8? |
|---|---|---|---|---|---|
| 0.1 |   |   |   |   |   |
| 0.5 |   |   |   |   |   |
| 1.0 |   |   |   |   |   |

Largest η with max \|ΔE/E₀\| ≤ 1e-8:

## 4. Run with 1 024 000 particles (TZ 11.4)

- Command:
- max \|ΔE/E₀\|:
- Wall time:
- GPU memory used (`nvidia-smi --query-gpu=memory.used --format=csv`):
- Scaling from 1 GPU to all GPUs:
- Levels from `timesteps.dat`:

## 5. CPU, 1 GPU and 2 GPUs (TZ 11.5)

Paste the output of `build/h4nb_gpu_vs_cpu` here:

```
```

## 6. Long-term drift (TZ 15.1)

Run 10 periods with the chosen η.
Record the max relative error of each period. Source: `energy.dat`.

| period | max \|ΔE/E₀\| |
|---|---|
|   |   |

Is the drift linear? Answer yes or no. Add notes.

## 7. TZ section 12: pass or fail

| # | Requirement | Result | Evidence |
|---|---|---|---|
| 1 | Hermite 4th order | pass / fail |   |
| 2 | Individual block time steps | pass / fail |   |
| 3 | Up to 1 024 000 particles | pass / fail |   |
| 4 | Central body is a full N-body participant | pass / fail |   |
| 5 | Double precision | pass / fail |   |
| 6 | max \|ΔE/E₀\| ≤ 1e-8 over a characteristic period | pass / fail |   |
| 7 | Momentum control | pass / fail |   |
| 8 | Angular-momentum control | pass / fail |   |
| 9 | One or more NVIDIA GPUs | pass / fail |   |
| 10 | Work split between GPUs | pass / fail |   |
| 11 | Energy and time-step diagnostics written | pass / fail |   |
| 12 | Snapshots at the given times | pass / fail |   |
| 13 | Reproducibility: same input, same output | pass / fail |   |

## 8. Problems and deviations

List each problem. Include the measured numbers.
Do not hide a problem.
