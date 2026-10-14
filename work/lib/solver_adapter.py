"""Contract-facing adapter for the common-inlet-pressure feedback strategy.

Scope of this card: contract identity, explicit stamping, adapter self-checks
and a synthetic in-process response adapter.  This module deliberately does
NOT implement any real solver call: the injected ``evaluate`` callback stands
for one fully converged OpenFOAM evaluation at a common inlet pressure, and
wiring that callback into work/07_cfd_pipeline/solver/run_openfoam_case.py
belongs to a later card (registered in plan/主计划.md Backlog).  No Netgen,
gmshToFoam, checkMesh or simpleFoam process is started here and no patient
flow field is produced.

Strategy (contract semantics): one common nostril static pressure with a
fixed nasopharynx outlet static pressure; an outer loop adjusts the common
inlet pressure until the volumetric total-flow target is met.  The flow
target is an outer iteration objective and is never a simultaneous PDE flow
boundary.  The target is volumetric, i.e. kinematic: density never enters
the controller (only a mass-flow target rho*q would need density, and this
contract targets volume per time).

Stamping is an explicit action performed by ``stamp_config`` only after the
adapter self-check passes; ``cfd_contract.make_config`` defaults stay
``not_implemented`` and this module never mutates them.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Sequence, Tuple

import cfd_contract as contract
import pressure_feedback as pf


class AdapterError(RuntimeError):
    """Adapter misuse: bad arguments, config, or patch map."""


class AdapterStampError(AdapterError):
    """Refusal to stamp: self-check failed or strategy identity mismatch."""


# Strategy identity.  These strings are the contract's own strings; the
# self-check compares them against cfd_contract.make_config() bit-for-bit so
# any contract-side edit breaks stamping visibly instead of silently.
DESIRED_STRATEGY = "common_inlet_pressure_feedback"
FLOW_TARGET_ROLE = "outer_iteration_objective_not_simultaneous_PDE_flow_boundary"
STRATEGY_DESCRIPTION = (
    "Use one common nostril static pressure and fixed outlet static pressure; "
    "an outer loop adjusts the common inlet pressure to match the total-flow "
    "target. Do not impose a flow boundary simultaneously."
)

# Default patch names mirror contract.BOUNDARIES = {nostril_L, nostril_R,
# nasopharynx_outlet}; a manifest-style patch_map can override them.
DEFAULT_INLET_PATCHES = ("nostril_L", "nostril_R")
DEFAULT_OUTLET_PATCHES = ("nasopharynx_outlet",)
# 15 L/min volumetric flow, the same default the contract template carries.
DEFAULT_TARGET_M3_S = 2.5e-4
# Mirrors the contract engineering-screen value; read from the config by
# from_config when present.  It gates one evaluation, it does not redefine
# the screen.
DEFAULT_MAX_MASS_IMBALANCE = 5e-3
DEFAULT_NAME = "common_inlet_pressure_feedback_adapter"
DEFAULT_VERSION = "1.0.0"


def total_flow_lpm_to_m3_s(lpm: float) -> float:
    """Convert L/min to m3/s.  Volumetric flow is kinematic: no density.

    The pressure-feedback target q [m3/s] carries no density; a mass-flow
    target (rho*q) would, and this contract does not use one.
    """
    return contract.flow_lpm_to_m3_s(lpm)


def _positive_number(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value > 0)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _strategy_identity_failures(block: Any, subject: str) -> List[str]:
    """Compare a solver_adapter block against the strings this adapter implements."""
    if not isinstance(block, dict):
        return [subject + " must be an object"]
    failures = []
    for field, expected in (("desired_strategy", DESIRED_STRATEGY),
                            ("flow_target_role", FLOW_TARGET_ROLE),
                            ("strategy_description", STRATEGY_DESCRIPTION)):
        if block.get(field) != expected:
            failures.append(subject + " field " + field
                            + " does not match the strategy this adapter implements")
    return failures


def patches_from_patch_map(patch_map: Dict[str, str]) -> Tuple[List[str], List[str]]:
    """Split a manifest-style {patch: role} map into inlet and outlet patches.

    Roles follow the pipeline convention ("inlet"/"outlet"/"wall"); unknown
    roles are ignored here and walls never enter the controller.
    """
    if not isinstance(patch_map, dict) or not patch_map:
        raise AdapterError("patch_map must be a non-empty object")
    inlet = sorted(name for name, role in patch_map.items() if role == "inlet")
    outlet = sorted(name for name, role in patch_map.items() if role == "outlet")
    if not inlet:
        raise AdapterError("patch_map declares no inlet patch")
    if not outlet:
        raise AdapterError("patch_map declares no outlet patch")
    return inlet, outlet


class SyntheticFlowResponse:
    """In-process synthetic stand-in for one OpenFOAM evaluation.

    Maps a common inlet pressure to a total volumetric flow through a
    caller-supplied ``flow_of_pressure`` callable and splits it bilaterally.
    It exists for adapter self-checks and unit tests only: no PDE is solved
    and no solver is launched.  Quality flags and the mass imbalance are
    constructor overrides so rejection paths can be exercised.
    """

    def __init__(self, flow_of_pressure: Callable[[float], float], left_fraction: float = 0.5,
                 mass_imbalance_frac: float = 0.0, converged: bool = True,
                 mesh_quality_passed: bool = True, residuals_passed: bool = True):
        if not callable(flow_of_pressure):
            raise AdapterError("flow_of_pressure must be callable")
        if not 0 <= left_fraction <= 1:
            raise AdapterError("left_fraction must lie within [0, 1]")
        if not math.isfinite(mass_imbalance_frac) or mass_imbalance_frac < 0:
            raise AdapterError("mass_imbalance_frac must be finite and nonnegative")
        self.flow_of_pressure = flow_of_pressure
        self.left_fraction = float(left_fraction)
        self.mass_imbalance_frac = float(mass_imbalance_frac)
        self.converged = bool(converged)
        self.mesh_quality_passed = bool(mesh_quality_passed)
        self.residuals_passed = bool(residuals_passed)

    def __call__(self, pressure_pa: float) -> pf.FlowEvaluation:
        pressure = float(pressure_pa)
        q_total = float(self.flow_of_pressure(pressure))
        q_left = self.left_fraction * q_total
        q_right = q_total - q_left
        q_out = q_total * (1.0 - self.mass_imbalance_frac)
        return pf.FlowEvaluation(
            pressure, q_left, q_right, q_out,
            converged=self.converged,
            mesh_quality_passed=self.mesh_quality_passed,
            mass_imbalance_frac=self.mass_imbalance_frac,
            residuals_passed=self.residuals_passed,
        )


class CommonPressureAdapter:
    """Wraps pressure_feedback.solve_common_pressure with contract semantics.

    ``evaluate`` is injected: signature ``(pressure_pa) -> FlowEvaluation``,
    representing one fully converged OpenFOAM evaluation at that common inlet
    pressure.  This card provides the interface and the synthetic response
    only; the real solver call is a later card.
    """

    def __init__(self, evaluate: Callable[[float], pf.FlowEvaluation],
                 target_m3_s: float = DEFAULT_TARGET_M3_S,
                 inlet_patches: Sequence[str] = DEFAULT_INLET_PATCHES,
                 outlet_patches: Sequence[str] = DEFAULT_OUTLET_PATCHES,
                 initial_pressure_pa: float = 1.0, pressure_upper_pa: float = 200.0,
                 max_bracket_evaluations: int = 30, max_iterations: int = 20,
                 relative_flow_tolerance: float = 0.01,
                 max_mass_imbalance: float = DEFAULT_MAX_MASS_IMBALANCE,
                 name: str = DEFAULT_NAME, version: str = DEFAULT_VERSION):
        if not callable(evaluate):
            raise AdapterError("evaluate must be a callable (pressure_pa) -> FlowEvaluation")
        if not _positive_number(target_m3_s):
            raise AdapterError("target_m3_s must be finite and positive")
        for label, value in (("initial_pressure_pa", initial_pressure_pa),
                             ("pressure_upper_pa", pressure_upper_pa)):
            if not _positive_number(value):
                raise AdapterError(label + " must be finite and positive")
        if not _positive_number(max_bracket_evaluations) or not _positive_number(max_iterations):
            raise AdapterError("evaluation budgets must be positive")
        if not 0 < relative_flow_tolerance < 1:
            raise AdapterError("relative_flow_tolerance must be between zero and one")
        if not _positive_number(max_mass_imbalance):
            raise AdapterError("max_mass_imbalance must be finite and positive")
        if not _text(name) or not _text(version):
            raise AdapterError("adapter name and version must be non-empty strings")
        if not inlet_patches or not outlet_patches:
            raise AdapterError("inlet_patches and outlet_patches must be non-empty")
        self.evaluate = evaluate
        self.target_m3_s = float(target_m3_s)
        self.inlet_patches = tuple(inlet_patches)
        self.outlet_patches = tuple(outlet_patches)
        self.name = name
        self.version = version
        self._feedback_config = pf.FeedbackConfig(
            target_m3_s=self.target_m3_s,
            initial_pressure_pa=float(initial_pressure_pa),
            pressure_upper_pa=float(pressure_upper_pa),
            max_bracket_evaluations=int(max_bracket_evaluations),
            max_iterations=int(max_iterations),
            relative_flow_tolerance=float(relative_flow_tolerance),
            max_mass_imbalance=float(max_mass_imbalance),
        )

    @classmethod
    def from_config(cls, config: Dict[str, Any], evaluate: Callable[[float], pf.FlowEvaluation],
                    patch_map: Dict[str, str] = None, **overrides: Any) -> "CommonPressureAdapter":
        """Build an adapter from a contract config (total_flow + solver_determined).

        The target is read as total_inspiratory_flow_m3_s (volumetric SI), and
        the per-evaluation mass-imbalance gate mirrors the config engineering
        screen when present.  A manifest-style patch_map, when supplied,
        overrides the default nostril/nasopharynx patch names.
        """
        if not isinstance(config, dict):
            raise AdapterError("config must be an object")
        bc = config.get("boundary_conditions")
        if not isinstance(bc, dict):
            raise AdapterError("config.boundary_conditions must be an object")
        if bc.get("mode") != "total_flow":
            raise AdapterError("common inlet pressure feedback requires boundary mode total_flow")
        split = bc.get("flow_split")
        if not isinstance(split, dict) or split.get("policy") != "solver_determined":
            raise AdapterError("common inlet pressure feedback requires the solver_determined split policy")
        target = bc.get("total_inspiratory_flow_m3_s")
        if not _positive_number(target):
            raise AdapterError("total_flow config requires positive total_inspiratory_flow_m3_s")
        failures = _strategy_identity_failures(config.get("solver_adapter") or {}, "config solver_adapter")
        if failures:
            raise AdapterError("; ".join(failures))
        if patch_map is None:
            inlet_patches: Tuple[str, ...] = DEFAULT_INLET_PATCHES
            outlet_patches: Tuple[str, ...] = DEFAULT_OUTLET_PATCHES
        else:
            inlet_patches, outlet_patches = patches_from_patch_map(patch_map)
        screen = config.get("engineering_screen")
        screen = screen if isinstance(screen, dict) else {}
        max_imbalance = screen.get("maximum_mass_imbalance_fraction", DEFAULT_MAX_MASS_IMBALANCE)
        if not _positive_number(max_imbalance):
            raise AdapterError("engineering_screen.maximum_mass_imbalance_fraction must be positive when present")
        return cls(evaluate, target_m3_s=float(target), inlet_patches=inlet_patches,
                   outlet_patches=outlet_patches, max_mass_imbalance=float(max_imbalance), **overrides)

    @property
    def feedback_config(self) -> pf.FeedbackConfig:
        return self._feedback_config

    def run(self) -> Dict[str, Any]:
        """Run the outer pressure-feedback loop with the injected evaluate callback.

        Returns the converged common inlet pressure, per-side and outlet
        volumetric flows, the left fraction, the full iteration history and
        the adapter identity.  A failed evaluation, a rejected sign, or a
        target that cannot be bracketed raises
        pressure_feedback.PressureFeedbackError unchanged - never swallowed
        and never wrapped; its message carries the failure reason.
        """
        solved = pf.solve_common_pressure(self.evaluate, self._feedback_config)
        return {
            "status": solved["status"],
            "adapter": {"name": self.name, "version": self.version,
                        "desired_strategy": DESIRED_STRATEGY,
                        "flow_target_role": FLOW_TARGET_ROLE,
                        "strategy_description": STRATEGY_DESCRIPTION},
            "evaluation_backend": "injected_callback_not_a_solver",
            "inlet_patches": list(self.inlet_patches),
            "outlet_patches": list(self.outlet_patches),
            "target_m3_s": solved["target_m3_s"],
            "target_basis": "volumetric_total_inspiratory_flow_kinematic_density_independent",
            "pressure_pa": solved["pressure_pa"],
            "q_total_m3_s": solved["q_total_m3_s"],
            "q_left_m3_s": solved["q_left_m3_s"],
            "q_right_m3_s": solved["q_right_m3_s"],
            "q_out_m3_s": solved["q_out_m3_s"],
            "left_fraction": solved["left_fraction"],
            "relative_flow_error": abs(solved["q_total_m3_s"] - solved["target_m3_s"]) / solved["target_m3_s"],
            "iterations": solved["iterations"],
            "evaluation_count": len(solved["iterations"]),
            "bracket_pa": solved["bracket"],
        }


def run_self_check() -> List[str]:
    """Adapter self-check; returns human-readable failures (empty list = OK).

    Checks: the strategy strings match the live contract bit-for-bit, the
    default patches mirror contract.BOUNDARIES, the controller converges a
    synthetic linear response inside the tolerance, and the sign gates reject
    a positive outward inlet phi as well as a negative physical inlet flow
    while still accepting well-formed signed fluxes.
    """
    failures: List[str] = []
    failures += _strategy_identity_failures(contract.make_config()["solver_adapter"],
                                            "contract reference")
    if not set(DEFAULT_INLET_PATCHES) | set(DEFAULT_OUTLET_PATCHES) <= set(contract.BOUNDARIES):
        failures.append("default adapter patches must mirror contract.BOUNDARIES")
    target = DEFAULT_TARGET_M3_S
    controller = pf.FeedbackConfig(target_m3_s=target)
    try:
        solved = pf.solve_common_pressure(
            SyntheticFlowResponse(lambda pressure: 1e-4 * pressure), controller)
        error = abs(solved["q_total_m3_s"] - target) / target
        if solved["status"] != "converged":
            failures.append("controller self-test did not converge a synthetic linear response")
        elif error > controller.relative_flow_tolerance:
            failures.append("controller self-test exceeded the relative flow tolerance")
    except Exception as exc:  # a self-check reports; it never raises
        failures.append("controller self-test raised " + type(exc).__name__ + ": " + str(exc))
    try:
        pf.FlowEvaluation(1.0, -1e-4, 2e-4, 1e-4).validate(target, DEFAULT_MAX_MASS_IMBALANCE)
        failures.append("sign gate accepted a negative inlet flow")
    except pf.PressureFeedbackError:
        pass
    try:
        pf.signed_patch_fluxes(
            {"nostril_L": 1e-4, "nostril_R": -1e-4, "nasopharynx_outlet": 2e-4},
            list(DEFAULT_INLET_PATCHES), list(DEFAULT_OUTLET_PATCHES))
        failures.append("sign gate accepted a positive outward inlet phi")
    except pf.PressureFeedbackError:
        pass
    try:
        signed = pf.signed_patch_fluxes(
            {"nostril_L": -1e-4, "nostril_R": -1.5e-4, "nasopharynx_outlet": 2.5e-4},
            list(DEFAULT_INLET_PATCHES), list(DEFAULT_OUTLET_PATCHES))
        if abs(signed["q_in_m3_s"] - 2.5e-4) > 1e-12 or abs(signed["q_out_m3_s"] - 2.5e-4) > 1e-12:
            failures.append("signed flux conversion altered well-formed values")
    except pf.PressureFeedbackError as exc:
        failures.append("signed flux conversion rejected well-formed values: " + str(exc))
    return failures


def stamp_config(config: Dict[str, Any], name: str, version: str,
                 self_check: Callable[[], List[str]] = None) -> Dict[str, Any]:
    """Explicitly stamp a config's solver_adapter block implemented_and_verified.

    Stamps only when (a) the config declares exactly the strategy this adapter
    implements and (b) the adapter self-check passes; otherwise raises
    AdapterStampError with the reasons and leaves the config untouched.  This
    is an explicit action: cfd_contract.make_config() defaults stay
    not_implemented and are never modified here.
    """
    if not isinstance(config, dict):
        raise AdapterStampError("config must be an object")
    block = config.get("solver_adapter")
    if not isinstance(block, dict):
        raise AdapterStampError("config.solver_adapter must be an object")
    if not _text(name) or not _text(version):
        raise AdapterStampError("stamp requires non-empty name and version strings")
    failures = _strategy_identity_failures(block, "config solver_adapter")
    if failures:
        raise AdapterStampError("refusing to stamp: " + "; ".join(failures))
    check = run_self_check if self_check is None else self_check
    failures = [str(item) for item in check()]
    if failures:
        raise AdapterStampError("refusing to stamp, adapter self-check failed: " + "; ".join(failures))
    block["status"] = "implemented_and_verified"
    block["name"] = name
    block["version"] = version
    return block
