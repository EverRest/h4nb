<!--
Sync Impact Report
- Version change: 1.0.0 → 1.1.0 (MINOR: Development Workflow now requires automated tests)
- Principles added: none
- Sections added: none
- Sections modified: Development Workflow (automated test suite added; "no automated test suite" removed)
- Removed sections: none
- Deferred TODOs: none
-->

# h4nb Constitution

## Core Principles

### I. Accuracy Is the Contract

- All physical values MUST use FP64: positions, velocities, masses, accelerations, jerks, time steps and energy.
- Builds MUST NOT enable fast-math (`--use_fast_math`, `-ffast-math`).
- The energy goal (max |ΔE/E₀| ≤ 1e-8 over one mean orbital period) MUST be shown by a measured run. A configuration value does not replace the measurement.
- Softening MUST NOT be used to hide an energy error. Softening changes the physical model.

Rationale: users trust the library because of its accuracy. A fast run with a wrong result has no value.

### II. Speed by Measurement

- The force computation (accelerations and jerks) is the hot path. Each design choice that affects it MUST be documented with a cost estimate.
- An optimisation that makes the code more complex MUST have a measured gate: a profiler or benchmark number shows the need. The same number MUST be recorded before and after the change.
- Mixed precision and Tensor Cores are forbidden in v1. Only a written amendment of this constitution can permit them.

Rationale: on GPUs, guesses about speed are often wrong. Numbers prevent work that has no value.

### III. Library First, Small API

- The product is a C++ library with one public header. Tools such as runners and benchmarks are thin clients of the public API.
- The public API MUST NOT expose CUDA types.
- A feature MUST NOT go into the public API before a user needs it.

Rationale: other people's code will link to this library. A small API is easy to keep stable.

### IV. Deterministic Results

- For the same input, configuration, device list and build, a run MUST give results that are identical bit for bit.
- Floating-point sums MUST use a fixed order. Floating-point atomics are forbidden.
- Time MUST be stored as integer ticks.

Rationale: the TZ requires reproducible runs (requirement 13). Deterministic results also make it possible to find bugs.

### V. Simplicity (YAGNI)

- The only dependencies are the CUDA toolkit (CUB and Thrust included) and the C++ standard library.
- Use the shortest correct solution. A deliberate shortcut with a known limit MUST have a `ponytail:` comment that names the limit and the upgrade path.

Rationale: a small codebase is easy to check against the physics.

## Hardware & Toolchain Constraints

- Target: Linux on x86_64, NVIDIA GPUs with compute capability ≥ 7.0, CUDA ≥ 12.0, CMake ≥ 3.24, C++17.
- v1 uses one process on one node with one or more GPUs. Multi-node work is out of scope until it is amended.
- The user's development Mac cannot build CUDA. Builds and acceptance runs happen on a CUDA machine or in CI.

## Development Workflow

- **v1 has automated tests.** They live in `tests/`. They are plain executables with CHECK/CHECK_NEAR macros (no external framework), and CTest registers them. `make test` runs them all. Tests labelled `cpu` MUST run without a GPU. Tests labelled `gpu` MUST run on a GPU machine.
- The thresholds in the tests MUST NOT be loosened to make a test pass. A failing test is a finding: find the cause, record the measured value, and report it to the user.
- The acceptance runs in `specs/001-hermite-nbody-lib/quickstart.md` are still required. They MUST be done on a GPU machine and recorded in `docs/results.md` before a release. Automated tests do not replace them.
- CI (GitHub Actions) MUST compile the library and the tools on each push and MUST run the `cpu` tests. A CI build without a GPU proves that the code compiles and that the CPU reference is correct. It does not prove that the GPU code is correct.
- Commits, pushes and pull requests are made only when the user asks for them.

## Governance

- This constitution has priority over other practices in this repository. Each plan and each review MUST check its principles.
- An amendment needs: a written change to this file, a version bump, and the user's approval.
- Versioning: MAJOR for the removal or redefinition of a principle; MINOR for a new principle or section; PATCH for wording.

**Version**: 1.1.0 | **Ratified**: 2026-11-07 | **Last Amended**: 2026-11-07
