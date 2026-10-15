# T-029 bounded engineering trial authorization

Source: tasks/T-029.md Lead execution record, approved on 2026-10-15; original M1/M2 engineering authorization retained.
Origin b15_engineering; new numerical trial identity b15_engineering_t029a. Original geometry, mesh, source hashes and clinical review pending status remain.
Approved sole numerical variable: div(phi,U) bounded Gauss upwind. All pressure boundaries, units, rho/nu, laminar model, relaxation and quality gates remain.
Execution budget: endTime 120, writeInterval 20; stop on FPE/nonfinite values or this bound, no automatic continuation.
Formal 8769 creates one new isolated native-Linux job after source/input freeze and CPU-lane check.
This authorizes an engineering stability observation only; Failed 2 mesh checks, no patient clinical approval, no asserted target flow or split.
