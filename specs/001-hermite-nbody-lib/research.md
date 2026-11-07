# Research: h4nb, new STE input and configuration

**Date**: 2026-11-07. **Input**: the second STE from Pavlo (2026-11-07), Pavlo's request for configurable parameters, `docs/superpowers/plans/2026-11-07-h4nb.md` (D1–D11), `docs/multi-node-design.md`.

The earlier decisions D1 to D11 stay valid. This file records only the new decisions. Each entry has the decision, the reason and the rejected alternatives.

## R1. Configuration: one key table, five sources

- **Decision**: one table of keys in `tools/settings.hpp`. Sources in this order (later wins): defaults, `preset=`, `config=<file>`, `H4NB_<KEY>`, command line. Strict validation. `config.used` is written for each run.
- **Reason**: Pavlo asked for flexible, configurable parameters. The multi-node design (section 3.1) already uses the same sources for MPI launches. One table gives one place for the name, the type, the range, the default and the help text of each key. `h4nb_run --help` can print the table.
- **Rejected**: YAML with sections (as in the STE example). It needs a parser library (constitution V) or a large parser. Sections add no value when each key name is unique. An INI file was rejected by the user on 2026-11-07.
- **Rejected**: a parser in the library. Plan D1: configuration files belong to the application. Library users fill `h4nb::Config` directly.

## R2. Softening is set as ε, with presets

- **Decision**: the key `eps` holds ε. The tool computes `eps2 = eps * eps`. `h4nb_run` already does this (`tools/h4nb_run.cpp` line 30). The new parts are the presets and the check that `eps` and `eps2` are not both set. `preset=agn` gives ε = 0.01. `preset=stellar` gives ε = 0.0001. Default ε = 0. The library keeps `Config::eps2`, because the kernel needs ε² (one add per pair).
- **Reason**: the STE requires that the parameter is ε and not ε². Users think in ε. The kernel already applies ε² in the force (`accumulate`) and in the potential (`potential_kernel`). So the energy check uses the same softened model as the integrator. This was checked in `src/hermite.cuh` line 48 and `src/kernels.cu` line 109.
- **Note**: the values 0.01 and 0.0001 differ by a factor of 100. They change the dynamics of close encounters. Each report states ε. Constitution I: softening is a model choice. It is not a fix for an energy error.

## R3. Kernel launch shape is a run parameter

- **Decision**: make the force and potential kernels templates over the tile size `BI`. Compile `BI` = 64, 128 and 256. `Config::tile` selects one at run time. `Config::blocks_per_sm` replaces the constant 4 in `split()` (`src/simulation.cu` line 34).
- **Reason**: plan O2 tunes `BI` and the blocks per SM. Today each value needs a rebuild. The GPU owners run the measurements. A run-time key lets `h4nb_bench` sweep all values in one call. The RTX 4070 Ti (8.9) and the GH200 (9.0) have different register files, shared memory and FP64 rates. The best value can differ.
- **Cost**: three template instances. The binary grows by a few hundred kB. No arithmetic changes. The shared memory per block is `2 × BI × 32` bytes: 4 kB, 8 kB or 16 kB.
- **Determinism**: `tile` and `blocks_per_sm` change the source split (`nj`, `chunk`). So the order of the partial sums changes. Bit-identical results hold only for the same values. `config.used` records them (constitution IV).
- **Rejected**: an auto-tuner inside the library. It makes the results depend on timing. That breaks determinism.

## R4. Multi-node with MPI

- **Decision**: follow `docs/multi-node-design.md` without change. One rank per GPU. j-parallel layout (D2). CUDA-aware MPI. Ordered sums in rank order. Optional build with `H4NB_MPI=ON`.
- **Reason**: the STE names MPI as the main mechanism and 4–8 GH200 as the production target. A GH200 superchip has one GPU. 4 to 8 of them are usually on 1 to 2 nodes (for example 4 per node in a quad-GH200 node).
- **STE difference**: the STE proposes replicated sources and distributed targets. The plan keeps D2 (split sources, all targets on each GPU). The reason is in D2: N_active is 10² to 10⁴ in block steps, so split targets leave each GPU with too few threads. D2 also keeps the traffic for each step at O(N_active).
- **Gate**: the constitution amendment to 2.0.0 must be applied first.

## R5. Input validation

- **Decision**: `load_text` and `read_snapshot` check: unique IDs, m > 0, finite values in all seven floating-point fields, N ≥ 2. The tool checks the count against `n=` when the key is set. The tool checks that particle 0 has `central_id` (default 0). Each error names the file, the line and the field.
- **Reason**: the STE requires these checks. Today `src/io.cpp` only checks the field count. The central body stays the first record of the file. The program never adds it a second time.

## R6. Cost estimates for the listed hardware

The plan cost model is 60 FP64 FLOP per pair. One full force pass at N = 1 024 000 is 1.05e12 pairs, or 6.3e13 FLOP. With η = 5e-4, one mean period needs about 3e14 pairs, or 1.8e16 FLOP.

| Card | FP64 peak (spec sheet) | Assumed reach (50 %) | One full force pass at 1M | One mean period at 1M |
|---|---|---|---|---|
| RTX 4070 Ti | about 0.6 TFLOP/s | 0.3 TFLOP/s | about 210 s | about 17 h |
| GTX 1060 | about 0.14 TFLOP/s | 0.07 TFLOP/s | about 15 min | about 3 days |
| GH200 (H100 GPU) | about 34 TFLOP/s (vector) | 17 TFLOP/s | about 3.7 s | about 18 min |
| 8 × GH200 | — | 0.85 × 8 × 17 TFLOP/s | about 0.5 s | about 2.7 min |

These are estimates, not measurements. `h4nb_bench` measures the real values (constitution II). Consequence: use the RTX 4070 Ti for N ≤ 131 072 and for the correctness runs. Use the GH200 for the 1M acceptance runs.

## R7. Dissipation

- **Decision** (Pavlo, 2026-11-07: "flexible, or changeable through the configuration"): a configurable hook. `Config::dissipation` is an enum (`Off`, `LinearDrag`). The tool key is `dissipation=off|linear_drag`. The default is `off`.
- **Model `linear_drag`**: a_diss = −(v − v_bg)/τ for each particle except the central body. Keys: `drag_tau` (τ > 0) and `drag_vbg` (v_bg, default 0,0,0). The Hermite corrector also needs the time derivative: j_diss = −(a_total)/τ, with the total acceleration at the same time. Both terms are per particle (O(N_active) for each block step). The force kernel does not change.
- **Where**: one `__host__ __device__` function `dissipation_term()` in `src/hermite.cuh`. The correct kernel and the CPU reference call it. A new model is a new enum value and a new branch in this function. With `Off`, the function returns zero and the compiler removes it (template parameter). So the default path stays bit-identical.
- **Energy balance**: with a model on, the library integrates W_diss = ∫ Σ m_i v_i · a_diss,i dt per particle step with the trapezoid rule. `Diagnostics` gets the field `W_diss`. The verdict uses |E − E₀ − W_diss| / |E₀| (STE section 4). With `off`, W_diss = 0.
- **Rejected**: a virtual `DissipationModel` class (STE section 4). Virtual calls do not work well in a CUDA kernel. An enum and a switch are simpler and fast.
- **Note**: block steps, adaptive η and the Aarseth criterion stay the same. The 1e-8 goal applies only with `dissipation=off` (constitution I).

## R8. Build targets

- **Decision**: the default `CMAKE_CUDA_ARCHITECTURES` stays `native`. Example configure lines for `89` (RTX 4070 Ti) and `90` (GH200) go into the quickstart. A build for both uses `-DCMAKE_CUDA_ARCHITECTURES="89;90"`.
- **Reason**: GH200 nodes are aarch64. The code has no x86-only parts. The constitution text names x86_64 only. The amendment to 2.0.0 should add aarch64.
