"""Controller tests use synthetic conductances, never patient data."""
import unittest

from pressure_feedback import (
    FeedbackConfig,
    FlowEvaluation,
    PressureFeedbackError,
    signed_patch_fluxes,
    solve_common_pressure,
)


class PressureFeedbackTests(unittest.TestCase):
    def test_unequal_branch_conductance_reaches_target_and_preserves_split(self):
        # The right branch has one third of the conductance.  The controller
        # should recover the natural 3:1 flow ratio without imposing it.
        def evaluate(pressure):
            q_left = 2.0e-6 * pressure
            q_right = (2.0e-6 / 3.0) * pressure
            return FlowEvaluation(pressure, q_left, q_right, q_left + q_right)

        result = solve_common_pressure(
            evaluate,
            FeedbackConfig(target_m3_s=2.5e-4, initial_pressure_pa=1.0,
                           relative_flow_tolerance=1e-5, max_iterations=12),
        )
        self.assertEqual(result["status"], "converged")
        self.assertAlmostEqual(result["q_total_m3_s"], 2.5e-4, delta=2.5e-4 * 1e-5)
        self.assertAlmostEqual(result["q_left_m3_s"] / result["q_right_m3_s"], 3.0, places=8)
        self.assertAlmostEqual(result["left_fraction"], 0.75, places=8)
        self.assertLess(result["pressure_pa"], 200.0)

    def test_signed_flux_is_converted_to_positive_inlet_and_outlet_flow(self):
        values = signed_patch_fluxes(
            {"nostril_L": -1.0e-4, "nostril_R": -0.5e-4, "nasopharynx": 1.5e-4},
            ["nostril_L", "nostril_R"], ["nasopharynx"],
        )
        self.assertAlmostEqual(values["q_in_m3_s"], 1.5e-4)
        self.assertAlmostEqual(values["q_out_m3_s"], 1.5e-4)
        self.assertAlmostEqual(values["mass_imbalance_frac"], 0.0)
        with self.assertRaisesRegex(PressureFeedbackError, "inlet"):
            signed_patch_fluxes(
                {"nostril_L": 1.0e-4, "nostril_R": -0.5e-4, "nasopharynx": 0.5e-4},
                ["nostril_L", "nostril_R"], ["nasopharynx"],
            )

    def test_failed_quality_gate_stops_without_using_bad_point(self):
        seen = []

        def evaluate(pressure):
            seen.append(pressure)
            return FlowEvaluation(pressure, 1e-4, 1e-4, 2e-4, mesh_quality_passed=False)

        with self.assertRaisesRegex(PressureFeedbackError, "quality"):
            solve_common_pressure(evaluate)
        self.assertEqual(len(seen), 1)

    def test_unbracketed_target_fails_at_pressure_limit(self):
        def evaluate(pressure):
            q = 1e-9 * pressure
            return FlowEvaluation(pressure, q / 2, q / 2, q)

        with self.assertRaisesRegex(PressureFeedbackError, "bracket"):
            solve_common_pressure(
                evaluate,
                FeedbackConfig(target_m3_s=2.5e-4, pressure_upper_pa=10.0,
                               max_bracket_evaluations=6),
            )


if __name__ == "__main__":
    unittest.main()
