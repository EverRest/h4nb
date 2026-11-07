# Feature Specification: Direct N-body Gravity Integrator (h4nb)

**Feature Directory**: `specs/001-hermite-nbody-lib`

**Created**: 2026-11-07

**Status**: Draft

**Input**: User description: "High-performance GPU code for direct N-body simulation of gravitational systems with a 4th-order Hermite integrator and adaptive individual time steps. Systems: one massive central body plus 128k–1024k lighter particles whose total mass can approach the central mass. Energy accuracy |ΔE/E₀| ≤ 1e-8 over one mean orbital period must be proven by measured runs, with automated convergence studies over the accuracy parameter η, the maximum time step and the integration length. Source: `~/code/spec.txt`. The full original TZ is in `docs/superpowers/specs/2026-11-07-h4nb-tz-original.md`."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Accurate integration of a small system with a proven reference (Priority: P1)

A researcher runs a two-body system and a three-body system. The researcher checks the integrator against known answers: the Kepler orbit, the conservation laws, and the expected fourth-order error behaviour. Every later claim depends on this check.

**Why this priority**: Results on large systems cannot be trusted without a validated integrator on small systems. This is also the cheapest part, and it is a viable minimum product on its own.

**Independent Test**: Integrate a central body and one particle for several orbits. Compare the result with the analytic solution. Halve the maximum time step three times and check the error ratio. Run a three-body system with a moving central body. Check the total momentum and the total angular momentum.

**Acceptance Scenarios**:

1. **Given** a central body and one particle on a Kepler orbit, **When** the system is integrated for several orbital periods. **Then** the positions match the analytic solution within the stated tolerance. The energy and the angular momentum stay within tolerance.
2. **Given** the same system and maximum steps h, h/2, h/4 and h/8, **When** the error against a high-accuracy reference is measured. **Then** the error ratio e(h)/e(h/2) is close to 16 in the asymptotic regime.
3. **Given** a three-body system with comparable masses, **When** it is integrated. **Then** the central body moves. The total momentum and the total angular momentum are conserved within tolerance.

---

### User Story 2 - Energy accuracy proven on a 128k-particle system (Priority: P1)

A researcher simulates one central body with 128 000 particles on near-Kepler orbits. The total particle mass is 10 % to 100 % of the central mass. The simulation runs for several characteristic orbital periods. The researcher receives a measured energy-error report.

**Why this priority**: This is the main acceptance criterion of the project. The 1e-8 requirement must be shown by a measurement. It must not be set as a parameter.

**Independent Test**: Run the control system and read the report. Compare the maximum relative energy deviation over one mean orbital period with 1e-8.

**Acceptance Scenarios**:

1. **Given** the 128k control system, **When** one mean orbital period is integrated. **Then** the maximum relative energy deviation over the period is at most 1e-8. The report shows this value.
2. **Given** a particle mass ratio from 10 % to 100 % of the central mass, **When** the system is integrated. **Then** the central body is integrated as a full participant. Its kinetic energy is part of the total energy.
3. **Given** a run that is longer than one period, **When** the run ends. **Then** the report shows the long-term energy drift and the maximum deviation per period.

---

### User Story 3 - Automatic convergence study (Priority: P1)

A researcher runs an automatic study. The study changes the accuracy parameter η, the maximum time step and the integration length. The result is a table of measured energy errors. The table shows which settings meet 1e-8.

**Why this priority**: The TZ requires that numerical tests confirm the accuracy goal. The study also gives the researcher a measured value of η for the researcher's system.

**Independent Test**: Start the study on a small system. The study runs a grid of settings without manual steps. It writes one result table.

**Acceptance Scenarios**:

1. **Given** ranges for η, the maximum step and the duration, **When** the study runs. **Then** each combination gives a recorded energy error and a run cost.
2. **Given** a finished study, **When** the researcher reads the table. **Then** the researcher can select the cheapest settings that meet the energy tolerance for the studied system.
3. **Given** the recommended η range of 0.001–0.02, **When** the study covers this range. **Then** no value in the range is assumed to meet 1e-8 without a measured result.

---

### User Story 4 - Run a 1M-particle system with measured performance (Priority: P2)

A researcher integrates a system with 1 024 000 particles. The researcher receives the same accuracy report and a performance report.

**Why this priority**: The system size is the reason the project exists. This story depends on the validated behaviour of stories 1 to 3.

**Independent Test**: Run the 1M control system. Check the accuracy report and the performance report. The performance report contains the throughput, the device load, the memory use and the step stability.

**Acceptance Scenarios**:

1. **Given** 1 024 000 particles, **When** the system is integrated. **Then** the run completes without a numerical failure. The run reports the accuracy and the performance.
2. **Given** the number of active particles changes from step to step, **When** the run progresses. **Then** the distribution of time steps is recorded.

---

### User Story 5 - Use several GPUs (Priority: P2)

A researcher runs the same system on one GPU and on several GPUs. The results are equivalent. The run time is shorter on more GPUs.

**Why this priority**: Several GPUs give the throughput that long runs of large systems need.

**Independent Test**: Run a small system on 1 GPU and on 2 GPUs. Compare the results. Then measure the run time per step for 1, 2 and more GPUs on a large system.

**Acceptance Scenarios**:

1. **Given** a small system, **When** it runs on one GPU and on two GPUs. **Then** the coordinates, the velocities, the total energy, the momentum and the angular momentum agree within the expected numerical error.
2. **Given** a large system, **When** the number of GPUs increases. **Then** the run time per step decreases. The report shows the scaling.
3. **Given** the number of active particles changes, **When** the work is spread over the GPUs. **Then** each GPU does the same number of pair evaluations. The sources are split evenly by construction. No GPU uses stale data from another GPU.

---

### User Story 6 - Reproducible runs and saved results (Priority: P2)

A researcher repeats a run with the same input. The researcher gets the same output. The researcher collects the diagnostics and the snapshots for analysis.

**Why this priority**: Reproducibility is acceptance requirement 13. It makes debugging possible.

**Independent Test**: Run the same configuration twice. Compare all output files.

**Acceptance Scenarios**:

1. **Given** the same initial conditions, configuration, device list and build, **When** the run is repeated. **Then** the output files are identical.
2. **Given** a set diagnostic interval and set snapshot times, **When** the run proceeds. **Then** the energy, momentum, angular momentum, time step and performance records are written. Snapshots are written at the requested times.

---

### Edge Cases

- Two particles come very close: the local step becomes smaller. The minimum distance is tracked. A possible collision is reported.
- A time step becomes smaller than the allowed minimum: the run reports it. The run does not continue silently.
- Invalid values appear (NaN, Inf or zero separation): the run detects them and stops with a clear message.
- The initial momentum or the initial angular momentum is zero: the relative change is still defined. Scales from the initial state are used.
- The central body is not the first object, or the file has fewer objects than configured: the input is rejected with a clear message.
- Softening is enabled: the report states that the physical model has changed. The energy result is not compared with the unsoftened criterion.
- The total particle mass approaches the central mass: the central-body motion is kept. The orbital period estimate is flagged as approximate.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST integrate a gravitational N-body system with a 4th-order Hermite scheme. The steps are: predict, evaluate the acceleration and its time derivative, correct.
- **FR-002**: The system MUST use direct summation of all pairs. The system MUST NOT use a spatial approximation.
- **FR-003**: The system MUST support individual adaptive time steps. The Aarseth criterion chooses each step. The user sets the accuracy parameter η. Each step is rounded to a power-of-two block of a maximum step.
- **FR-004**: The system MUST also offer a global time step mode. The researcher uses this mode to check accuracy and to compare with reference runs.
- **FR-005**: The system MUST predict all particles to the current global time before it evaluates the forces of the active particles. Then no stale coordinates are used.
- **FR-006**: The central body MUST be a full participant of the system. It has its own position, velocity, acceleration, derivative and time step. It moves under the field of all other particles. A fixed-centre mode MAY exist for tests and comparisons only.
- **FR-007**: All physical quantities (positions, velocities, masses, accelerations, derivatives, time steps and energy) MUST use double precision. The system MUST NOT use fast-math optimisation.
- **FR-008**: Plummer softening MUST be an optional parameter. It is off by default. The parameter is the softening length ε, not ε². Presets give ε = 0.01 for gas clouds in AGN and ε = 0.0001 for stellar systems.
- **FR-009**: The system MUST support 128 000 to 1 024 000 particles. The position and mass distributions are arbitrary. The total particle mass can be comparable to the central mass.
- **FR-010**: The system MUST run on one or several NVIDIA GPUs. The source particles (j-particles) are split across the GPUs. All active target particles (i-particles) are sent to every GPU. Each GPU computes the partial force of its own sources on all targets. The owner GPU of each target adds the partial forces in a fixed device order. The load is balanced by construction: each GPU does the same number of pair evaluations. No dynamic balancing is needed. Reason: with block steps, the active count is typically 10² to 10⁴. If the targets were split, each GPU would get too few threads. (Plan design decision D2. TZ 5.1 proposed the opposite layout. The user confirmed D2 on 2026-11-07.) The GPUs may be on one or several nodes. Each GPU is one MPI rank. The exchange of the active targets and of the partial forces uses MPI. The owner adds the partial forces in rank order.
- **FR-011**: After each step, all GPUs MUST agree on the positions, the velocities, the active set and the global time. Only then does the next step start.
- **FR-012**: The system MUST compute the total energy of all bodies. The kinetic energy of the central body is included. The system MUST use accurate summation.
  - The system MUST report the initial energy and the current energy.
  - The system MUST report the absolute change and the relative change.
  - The system MUST report the maximum deviation and the mean deviation over the period.
  - The system MUST report the integration time.
- **FR-013**: The system MUST compute the total momentum and the total angular momentum. It MUST compute their relative changes. It MUST use scales from the initial state, so that no division by zero occurs.
- **FR-014**: The system MUST determine a characteristic orbital period (mean, median or mass-weighted). The user MUST be able to set the period by hand.
- **FR-015**: The system MUST provide an automatic convergence study over η, the maximum time step and the integration length. The system MUST write the measured energy errors of all combinations to a result table.
- **FR-016**: The system MUST provide an automatic fourth-order convergence check. It uses the maximum steps h, h/2, h/4 and h/8, and it compares them with a high-accuracy reference.
- **FR-017**: The system MUST detect close approaches. It MUST track the minimum distance and report possible collisions. In the first version, the system treats particles as point masses. Merging is not included in v1.
- **FR-018**: The system MUST detect and report invalid numerical values and too-small time steps.
- **FR-019**: The system MUST read the initial conditions: ID, mass, position and velocity of each object. The central body is the first object. The system MUST check the input: unique IDs, positive masses, finite values, and the expected count when it is set. The system MUST take all run settings as `key=value` pairs. The tools read them from defaults, a preset, a file of `key=value` lines (`config=<path>`), environment variables `H4NB_<KEY>` and the command line. Later sources win. An unknown key is an error. Each run writes the final values to `config.used`. The settings cover the simulation, the integrator, the gravity, the GPU, the diagnostics and the output. The system MUST NOT read an INI-style configuration file. This is a deviation from TZ 10.2 (plan design decision D1). The system is a library. Configuration files belong to the application.
- **FR-020**: The system MUST write energy, momentum, time step and performance records. The system MUST write snapshots of positions, velocities and masses at set times. The snapshot format MUST allow partial reading. `performance.dat` holds the wall time, the block steps, the active count and the pair rate for each output interval. It MUST NOT hold kernel or transfer times per GPU. This is a deviation from TZ 10.3 (plan decision D9). Per-GPU timings are taken with a profiler, such as `nsys`. Event timers are added only when they are requested.
- **FR-021**: The diagnostic interval MUST be a setting. Energy checks MUST NOT run after every step.
- **FR-022**: For the same input, configuration, device list, rank count and build, the results MUST be identical bit for bit. Runs with different rank counts are compared with a written tolerance.
- **FR-023**: The system MUST NOT use mixed precision or tensor-core arithmetic for the main force computation.
- **FR-024**: The system MUST provide benchmark results for several particle counts.
- **FR-025**: The kernel launch shape (targets per block and blocks per SM) MUST be a run parameter. The benchmark tool MUST measure the allowed values.
- **FR-026**: The system MUST have a configurable dissipation term. The key `dissipation` selects the model. The default is `off`. With `off`, the results are the same as without the term. When a model is on, the system MUST record the work W_diss of the dissipative forces and MUST report the energy balance E − E₀ − W_diss. The 1e-8 goal applies only with `off`.

### Key Entities

- **Particle**: one body. It has an ID, a mass, a position, a velocity, an acceleration, a derivative of the acceleration, an individual time, a time step and a step level. The central body is a particle with the same representation.
- **System**: the full set of particles. It has a gravitational constant, a softening value and a mode (self-consistent or fixed centre).
- **Configuration**: all run settings. These are the accuracy parameter, the step limits, the devices, the diagnostics and the output.
- **Diagnostics Record**: the time, the kinetic, potential and total energy, the relative and maximum energy error, the momentum and the angular momentum.
- **Snapshot**: the positions, velocities and masses of all particles at a requested time.
- **Convergence Study**: a grid of (η, maximum step, duration). For each point, it gives the measured energy error and the cost.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On the agreed 128k control system, the maximum relative energy deviation over one mean orbital period is at most 1e-8. A recorded measurement shows this value.
- **SC-002**: The same criterion is measured on the 1 024 000-particle system. The result is reported with a pass or fail verdict.
- **SC-003**: On the two-body test, the fourth-order error ratio e(h)/e(h/2) is within 16 ± 2 in the asymptotic regime.
- **SC-004**: Positions on the two-body test agree with the analytic Kepler solution within the stated tolerance over several periods.
- **SC-005**: The total momentum and the total angular momentum change by no more than the stated tolerance in the control runs.
- **SC-006**: Runs on 1 GPU and on 2 GPUs of a small system agree within the expected numerical error. On the large system, the 2-GPU run is faster per step.
- **SC-007**: Two runs with the same input, configuration, device list and build produce identical output files.
- **SC-008**: The convergence study finishes without manual steps. It produces one table that covers all requested combinations.
- **SC-009**: Benchmark results exist for at least three particle counts, from 128k up to 1 024 000.
- **SC-010**: A run on two nodes agrees with a run on one node with the same rank count, within the stated tolerance. The cluster run records the MPI stack.

## Assumptions

- Hardware (user, 2026-11-07): 2 × RTX 4070 Ti for development and runs up to 131 072 particles; 4 to 8 GH200 for the 1M runs. GTX 1060 is not supported (compute capability 6.1). The number of GH200 per node and the number of nodes are not known yet. They are set by the launcher and by the configuration. The scaling runs use 1, 2, 4 and 8 ranks.
- The units are dimensionless with G = 1. With a central mass of 1 and a radius of 1, the reference Kepler period is 2π. The reference period is a run parameter.

- The main users are researchers in computational astrophysics. They run long simulations of disks and similar systems. They need controlled accuracy more than the highest speed.
- The agreed control test for the 1e-8 criterion is a central body with 128 000 near-Kepler particles. The total particle mass is 10 % of the central mass. Other mass ratios (up to 100 %) are covered by additional runs.
- The energy criterion applies to the maximum deviation over the period. It does not apply only to the difference between the start and the end (TZ 6.2 and 15.4).
- The tolerance for the analytic comparison and for the conservation checks is chosen when the acceptance runs are defined. The tolerance is recorded with the results.
- Time is measured in the units of the input system. G is set in the configuration. The system provides no unit conversion.
- Collision merging, regularisation of close pairs, restart from a snapshot, several central bodies and tree methods are not included in v1.
- A GPU machine is required for the acceptance runs. The development Mac cannot run GPU code. The compile check and the acceptance runs happen on other machines (see the project constitution).
- The accuracy parameter needed for the 1e-8 criterion is about η ≈ 5e-4 (plan decision D11, from a model of the same algorithm). The TZ's recommended range of 0.001–0.02 is too coarse. At η = 0.001, a Kepler orbit already gives about 1.2–2.1e-8 per orbit. The default `Config::eta` is 0.01. This value does not reach 1e-8. Every 1e-8 run must therefore set η by measurement. The value found for the control system is recorded in the acceptance results. Open: user decision on the default value of `Config::eta`.
- The project constitution, version 1.1.0, requires automated tests. The tests are in `tests/`. They are plain executables with CHECK and CHECK_NEAR macros. CTest registers them. The label `cpu` marks the tests that run without a GPU. The label `gpu` marks the tests that need a GPU. The acceptance runs are still required and are recorded before a release. Open: user decision on the GPU test tolerances.
