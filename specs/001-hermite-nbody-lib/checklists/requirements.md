# Specification Quality Checklist: Direct N-body Gravity Integrator (h4nb)

**Purpose**: Check that the specification is complete and of good quality before planning.
**Created**: 2026-11-07
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs). No language, framework or API is named. The method (Hermite 4), double precision and NVIDIA GPUs stay. The TZ sets them as requirements, not as design.
- [x] Focused on user value and business needs.
- [x] Written for non-technical stakeholders. The readers are researchers. Physics terms stay. No code-level terms are used.
- [x] All mandatory sections are complete.

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain.
- [x] Requirements are testable and unambiguous.
- [x] Success criteria are measurable.
- [x] Success criteria do not depend on a technology. SC-006 names GPU counts, because the use of several GPUs is the requirement itself.
- [x] All acceptance scenarios are defined.
- [x] Edge cases are identified.
- [x] The scope is bounded. The Assumptions list what is not included in v1.
- [x] Dependencies and assumptions are identified.

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria.
- [x] User scenarios cover the main flows.
- [x] The feature meets the measurable outcomes in the Success Criteria.
- [x] No implementation details appear in the specification.

## Notes

- The numeric tolerances for the analytic comparison and the conservation checks (SC-004, SC-005) are set in the acceptance-run definition. This is recorded in Assumptions.
- Testing follows constitution version 2.0.0. Automated tests are in `tests/` and run with CTest. The labels are `cpu` and `gpu`. The acceptance runs are also required before a release.
- Deviations from the TZ. Each deviation has a reason in the plan (Design decisions):
  - FR-010: the source particles (j-particles) are split across the GPUs. The TZ 5.1 layout, with replicated sources and split targets, is not used (plan D2). The load is balanced by construction, so no dynamic balancing is needed (TZ 5.3). The user confirmed D2 on 2026-11-07. Several nodes use MPI.
  - FR-019: run settings are `key=value` pairs from defaults, presets, a `key=value` file, the environment and the command line. No INI or YAML file is used (TZ 10.2; plan D1; user decision 2026-11-07).
  - FR-020: `performance.dat` has no per-GPU kernel or transfer times (TZ 10.3; plan D9).
  - Accuracy parameter: η ≈ 5e-4 is needed for 1e-8. The TZ range of 0.001–0.02 is too coarse. `Config::eta` defaults to 0.01 (TZ 3.6, 15.4; plan D11). The example configs use `eta=0.0005` (user decision 2026-11-07).
  - FR-026: dissipation is a configurable model with the default `off`. The STE asked for no dissipation in v1 (user decision 2026-11-07).
- Next step: `/speckit-clarify` (optional), then `/speckit-plan`.
