"""Outer controller for a common-inlet-static-pressure CFD run.

The callback represents one fully converged OpenFOAM evaluation at a common
inlet pressure.  It must return signed inlet/outlet fluxes and engineering
quality flags.  This module does not alter PDE boundary conditions and does
not treat a failed run as a usable point for interpolation.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import math
from typing import Any, Callable, Dict, List


class PressureFeedbackError(RuntimeError):
    """Raised when the target cannot be bracketed or a run is invalid."""


def signed_patch_fluxes(
    patch_phi: Dict[str, float],
    inlet_patches: List[str],
    outlet_patches: List[str],
) -> Dict[str, Any]:
    """Convert OpenFOAM outward-normal ``phi`` sums into physical flows.

    Inhalation through a nostril has negative outward flux; exhalation through
    the nasopharynx has positive outward flux.  The signs are checked rather
    than hidden with ``abs`` so a reversed or mixed-flow run stops visibly.
    """
    missing = [name for name in inlet_patches + outlet_patches if name not in patch_phi]
    if missing:
        raise PressureFeedbackError("missing patch flux: " + ", ".join(missing))
    inlet_signed = {name: float(patch_phi[name]) for name in inlet_patches}
    outlet_signed = {name: float(patch_phi[name]) for name in outlet_patches}
    if any(not math.isfinite(value) for value in list(inlet_signed.values()) + list(outlet_signed.values())):
        raise PressureFeedbackError("non-finite patch flux")
    if any(value >= 0 for value in inlet_signed.values()):
        raise PressureFeedbackError("inlet patch has no inward signed flux")
    if any(value <= 0 for value in outlet_signed.values()):
        raise PressureFeedbackError("outlet patch has no outward signed flux")
    q_in_by_patch = {name: -value for name, value in inlet_signed.items()}
    q_out_by_patch = {name: value for name, value in outlet_signed.items()}
    q_in = sum(q_in_by_patch.values())
    q_out = sum(q_out_by_patch.values())
    return {
        "q_in_by_patch": q_in_by_patch,
        "q_out_by_patch": q_out_by_patch,
        "q_in_m3_s": q_in,
        "q_out_m3_s": q_out,
        "mass_imbalance_frac": abs(q_in - q_out) / q_in if q_in else math.inf,
    }


@dataclass(frozen=True)
class FlowEvaluation:
    pressure_pa: float
    q_left_m3_s: float
    q_right_m3_s: float
    q_out_m3_s: float
    converged: bool = True
    mesh_quality_passed: bool = True
    mass_imbalance_frac: float = 0.0
    residuals_passed: bool = True

    @property
    def q_total_m3_s(self) -> float:
        return self.q_left_m3_s + self.q_right_m3_s

    def validate(self, target_m3_s: float, max_mass_imbalance: float) -> None:
        values = (self.pressure_pa, self.q_left_m3_s, self.q_right_m3_s,
                  self.q_out_m3_s, self.mass_imbalance_frac)
        if not all(math.isfinite(value) for value in values):
            raise PressureFeedbackError("non-finite pressure/flux evaluation")
        if self.pressure_pa < 0:
            raise PressureFeedbackError("negative common inlet pressure is not allowed")
        if self.q_left_m3_s < 0 or self.q_right_m3_s < 0 or self.q_out_m3_s < 0:
            raise PressureFeedbackError("reverse flow at an inlet/outlet")
        if not self.converged or not self.mesh_quality_passed or not self.residuals_passed:
            raise PressureFeedbackError(
                "evaluation did not pass solver quality gates: "
                f"converged={self.converged}, "
                f"mesh_quality_passed={self.mesh_quality_passed}, "
                f"residuals_passed={self.residuals_passed}"
            )
        if self.mass_imbalance_frac > max_mass_imbalance:
            raise PressureFeedbackError("mass imbalance exceeds controller limit")
        if self.q_total_m3_s <= 0:
            raise PressureFeedbackError("evaluation has zero total inlet flow")


@dataclass(frozen=True)
class FeedbackConfig:
    target_m3_s: float = 2.5e-4
    initial_pressure_pa: float = 1.0
    pressure_upper_pa: float = 200.0
    max_bracket_evaluations: int = 30
    max_iterations: int = 20
    relative_flow_tolerance: float = 0.01
    max_mass_imbalance: float = 5e-3


def _record(evaluation: FlowEvaluation, target: float) -> Dict[str, Any]:
    item = asdict(evaluation)
    item["q_total_m3_s"] = evaluation.q_total_m3_s
    item["relative_flow_error"] = abs(evaluation.q_total_m3_s - target) / target
    item["left_fraction"] = evaluation.q_left_m3_s / evaluation.q_total_m3_s
    return item


def solve_common_pressure(
    evaluate: Callable[[float], FlowEvaluation],
    config: FeedbackConfig = FeedbackConfig(),
) -> Dict[str, Any]:
    """Find a common inlet pressure producing the requested total flow.

    The first phase brackets the target by doubling pressure.  The second
    phase uses secant interpolation while the bracket remains valid, falling
    back to bisection when the secant leaves the bracket or stalls.
    """
    if config.target_m3_s <= 0 or config.pressure_upper_pa <= 0:
        raise ValueError("target flow and pressure upper bound must be positive")
    if not 0 < config.relative_flow_tolerance < 1:
        raise ValueError("relative_flow_tolerance must be between zero and one")

    history: List[Dict[str, Any]] = []

    def run(pressure: float) -> FlowEvaluation:
        evaluation = evaluate(float(pressure))
        evaluation.validate(config.target_m3_s, config.max_mass_imbalance)
        history.append(_record(evaluation, config.target_m3_s))
        return evaluation

    # A zero-pressure run is not needed to establish the lower side of the
    # bracket and can be numerically singular for a pressure inlet.  Treat it
    # as the physical zero-flow lower bound and only call the solver at
    # positive pressures.
    p_low = 0.0
    e_low = FlowEvaluation(0.0, 0.0, 0.0, 0.0)

    p_high = max(config.initial_pressure_pa, 1e-9)
    e_high = run(p_high)
    bracket_count = 2
    while e_high.q_total_m3_s < config.target_m3_s:
        if bracket_count >= config.max_bracket_evaluations or p_high >= config.pressure_upper_pa:
            raise PressureFeedbackError("failed to bracket target flow before pressure limit")
        p_low, e_low = p_high, e_high
        p_high = min(config.pressure_upper_pa, p_high * 2.0)
        e_high = run(p_high)
        bracket_count += 1

    best = e_high
    for _ in range(config.max_iterations):
        if abs(best.q_total_m3_s - config.target_m3_s) / config.target_m3_s <= config.relative_flow_tolerance:
            return {
                "status": "converged",
                "target_m3_s": config.target_m3_s,
                "pressure_pa": best.pressure_pa,
                "q_total_m3_s": best.q_total_m3_s,
                "q_left_m3_s": best.q_left_m3_s,
                "q_right_m3_s": best.q_right_m3_s,
                "q_out_m3_s": best.q_out_m3_s,
                "left_fraction": best.q_left_m3_s / best.q_total_m3_s,
                "iterations": history,
                "bracket": [p_low, p_high],
            }

        denominator = e_high.q_total_m3_s - e_low.q_total_m3_s
        if denominator > 0:
            p_trial = p_low + (config.target_m3_s - e_low.q_total_m3_s) * (p_high - p_low) / denominator
        else:
            p_trial = math.nan
        if not math.isfinite(p_trial) or not p_low < p_trial < p_high:
            p_trial = 0.5 * (p_low + p_high)
        e_trial = run(p_trial)
        if e_trial.q_total_m3_s < config.target_m3_s:
            p_low, e_low = p_trial, e_trial
        else:
            p_high, e_high = p_trial, e_trial
        best = min((best, e_trial), key=lambda e: abs(e.q_total_m3_s - config.target_m3_s))

    raise PressureFeedbackError("pressure feedback did not reach target flow tolerance")
