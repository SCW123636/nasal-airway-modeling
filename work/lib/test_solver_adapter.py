"""Synthetic solver-adapter tests: in-process responses only, no solver runs."""
import copy
import unittest

import cfd_contract as contract
import pressure_feedback as pf
import solver_adapter


TARGET = 2.5e-4  # 15 L/min, the contract default volumetric target


def reviewed_geometry():
    """Test metadata only; this does not describe an existing patient or review."""
    return {"kind": "patient", "case_id": "SYNTHETIC_TEST_ONLY",
            "source_file": "synthetic_geometry.vtp", "sha256": "a"*64,
            "units": "mm", "solver_units": "m", "scale_to_m": .001,
            "coordinate_system": "LPS", "review": {
                "status": "confirmed", "method": "human", "reviewer": "TEST_FIXTURE",
                "reviewed_at": "TEST_FIXTURE_NOT_A_REAL_REVIEW", "record_file": "test_review.json",
                "reviewed_geometry_sha256": "a"*64,
                "confirmed_boundaries": ["nostril_L", "nostril_R", "nasopharynx_outlet"],
                "oral_exclusion_confirmed": True, "sinus_boundary_policy_confirmed": True}}


def linear_response(conductance=1e-4, left_fraction=0.5, **flags):
    return solver_adapter.SyntheticFlowResponse(
        lambda pressure: conductance * pressure, left_fraction=left_fraction, **flags)


def step_response(low_scale, high_scale, threshold_pa=5.0):
    """Two-level synthetic response; neither level needs to sit inside tolerance."""
    def flow_of_pressure(pressure):
        return TARGET * (high_scale if pressure >= threshold_pa else low_scale)
    return solver_adapter.SyntheticFlowResponse(flow_of_pressure)


class SyntheticResponseTests(unittest.TestCase):
    def test_linear_response_converges_to_target(self):
        adapter = solver_adapter.CommonPressureAdapter(linear_response(), target_m3_s=TARGET)
        result = adapter.run()
        self.assertEqual(result["status"], "converged")
        self.assertAlmostEqual(result["pressure_pa"], 2.5, places=9)
        self.assertAlmostEqual(result["q_total_m3_s"], TARGET, places=15)
        self.assertLessEqual(result["relative_flow_error"], 0.01)
        self.assertEqual(result["left_fraction"], 0.5)
        self.assertGreaterEqual(result["evaluation_count"], 1)

    def test_asymmetric_bilateral_split_is_reported_not_prescribed(self):
        adapter = solver_adapter.CommonPressureAdapter(
            linear_response(left_fraction=0.7), target_m3_s=TARGET)
        result = adapter.run()
        self.assertEqual(result["status"], "converged")
        self.assertAlmostEqual(result["left_fraction"], 0.7, places=12)
        self.assertAlmostEqual(result["q_left_m3_s"] + result["q_right_m3_s"], TARGET, places=15)

    def test_nonlinear_response_still_converges(self):
        exponent = 0.9
        conductance = TARGET / 10.0**exponent
        adapter = solver_adapter.CommonPressureAdapter(
            solver_adapter.SyntheticFlowResponse(lambda p: conductance * p**exponent),
            target_m3_s=TARGET, relative_flow_tolerance=1e-4)
        result = adapter.run()
        self.assertEqual(result["status"], "converged")
        self.assertLessEqual(result["relative_flow_error"], 1e-4)
        self.assertAlmostEqual(result["pressure_pa"], 10.0, delta=0.01)

    def test_tolerance_edge_is_inclusive(self):
        # 1.01*target sits exactly at the tolerance; exact halves keep
        # q_left + q_right == 1.01*target in binary floating point.
        high = 1.01 * TARGET
        tolerance = abs(high - TARGET) / TARGET
        adapter = solver_adapter.CommonPressureAdapter(
            step_response(0.9, 1.01), target_m3_s=TARGET,
            relative_flow_tolerance=tolerance)
        result = adapter.run()
        self.assertEqual(result["status"], "converged")
        self.assertEqual(result["q_total_m3_s"], high)
        self.assertLessEqual(result["relative_flow_error"], tolerance)

    def test_error_beyond_tolerance_never_converges(self):
        adapter = solver_adapter.CommonPressureAdapter(
            step_response(0.9, 1.1), target_m3_s=TARGET)
        with self.assertRaises(pf.PressureFeedbackError) as ctx:
            adapter.run()
        self.assertIn("did not reach target flow tolerance", str(ctx.exception))


class RejectionPathTests(unittest.TestCase):
    def _run(self, response, **kwargs):
        adapter = solver_adapter.CommonPressureAdapter(response, target_m3_s=TARGET, **kwargs)
        with self.assertRaises(pf.PressureFeedbackError) as ctx:
            adapter.run()
        return str(ctx.exception)

    def test_positive_outward_inlet_phi_is_rejected(self):
        with self.assertRaises(pf.PressureFeedbackError) as ctx:
            pf.signed_patch_fluxes(
                {"nostril_L": 1e-4, "nostril_R": -1e-4, "nasopharynx_outlet": 2e-4},
                list(solver_adapter.DEFAULT_INLET_PATCHES),
                list(solver_adapter.DEFAULT_OUTLET_PATCHES))
        self.assertIn("inward", str(ctx.exception))

    def test_negative_outward_outlet_phi_is_rejected(self):
        with self.assertRaises(pf.PressureFeedbackError) as ctx:
            pf.signed_patch_fluxes(
                {"nostril_L": -1e-4, "nostril_R": -1.5e-4, "nasopharynx_outlet": -2.5e-4},
                list(solver_adapter.DEFAULT_INLET_PATCHES),
                list(solver_adapter.DEFAULT_OUTLET_PATCHES))
        self.assertIn("outward", str(ctx.exception))

    def test_well_formed_signed_fluxes_are_conserved(self):
        signed = pf.signed_patch_fluxes(
            {"nostril_L": -1e-4, "nostril_R": -1.5e-4, "nasopharynx_outlet": 2.5e-4},
            list(solver_adapter.DEFAULT_INLET_PATCHES),
            list(solver_adapter.DEFAULT_OUTLET_PATCHES))
        self.assertAlmostEqual(signed["q_in_m3_s"], 2.5e-4, places=15)
        self.assertAlmostEqual(signed["q_out_m3_s"], 2.5e-4, places=15)
        self.assertEqual(signed["mass_imbalance_frac"], 0.0)

    def test_reverse_physical_inlet_flow_is_rejected(self):
        message = self._run(linear_response(conductance=-1e-4))
        self.assertIn("reverse flow", message)

    def test_non_finite_evaluation_is_rejected(self):
        def broken(_pressure):
            return pf.FlowEvaluation(float("nan"), 1e-4, 1.5e-4, 2.5e-4)
        message = self._run(broken)
        self.assertIn("non-finite", message)

    def test_unconverged_quality_gate_is_rejected(self):
        message = self._run(linear_response(converged=False))
        self.assertIn("quality gates", message)

    def test_failed_mesh_quality_gate_is_rejected(self):
        message = self._run(linear_response(mesh_quality_passed=False))
        self.assertIn("mesh_quality_passed=False", message)

    def test_failed_residuals_gate_is_rejected(self):
        message = self._run(linear_response(residuals_passed=False))
        self.assertIn("residuals_passed=False", message)

    def test_mass_imbalance_above_limit_is_rejected(self):
        message = self._run(linear_response(mass_imbalance_frac=0.01))
        self.assertIn("mass imbalance", message)

    def test_bracket_failure_at_pressure_ceiling_is_rejected(self):
        # Even at the 200 Pa ceiling the synthetic response stays far below target.
        message = self._run(linear_response(conductance=1e-8))
        self.assertIn("failed to bracket", message)

    def test_zero_total_flow_is_rejected(self):
        message = self._run(linear_response(conductance=0.0))
        self.assertIn("zero total inlet flow", message)


class AdapterInterfaceTests(unittest.TestCase):
    def test_total_flow_lpm_conversion_is_density_independent(self):
        self.assertEqual(solver_adapter.total_flow_lpm_to_m3_s(15.), contract.flow_lpm_to_m3_s(15.))
        self.assertAlmostEqual(solver_adapter.total_flow_lpm_to_m3_s(15.), TARGET)

    def test_from_config_reads_contract_defaults(self):
        adapter = solver_adapter.CommonPressureAdapter.from_config(
            contract.make_config(), linear_response())
        self.assertEqual(adapter.target_m3_s, TARGET)
        self.assertEqual(adapter.inlet_patches, ("nostril_L", "nostril_R"))
        self.assertEqual(adapter.outlet_patches, ("nasopharynx_outlet",))
        self.assertEqual(adapter.feedback_config.max_mass_imbalance, 0.005)
        self.assertEqual(adapter.run()["status"], "converged")

    def test_from_config_accepts_manifest_patch_map(self):
        patch_map = {"nostril_L": "inlet", "nostril_R": "inlet",
                     "nasopharynx_outlet": "outlet", "sinus_wall": "wall"}
        adapter = solver_adapter.CommonPressureAdapter.from_config(
            contract.make_config(), linear_response(), patch_map=patch_map)
        self.assertEqual(adapter.inlet_patches, ("nostril_L", "nostril_R"))
        self.assertEqual(adapter.outlet_patches, ("nasopharynx_outlet",))

    def test_from_config_rejects_pressure_driven_mode(self):
        with self.assertRaises(solver_adapter.AdapterError):
            solver_adapter.CommonPressureAdapter.from_config(
                contract.make_config(mode="static_pressure_difference"), linear_response())

    def test_from_config_rejects_imposed_equal_split_baseline(self):
        with self.assertRaises(solver_adapter.AdapterError):
            solver_adapter.CommonPressureAdapter.from_config(
                contract.make_config(split_policy="imposed_equal_split_baseline"), linear_response())

    def test_patch_map_without_inlet_or_outlet_is_rejected(self):
        with self.assertRaises(solver_adapter.AdapterError):
            solver_adapter.patches_from_patch_map({"nostril_L": "wall", "nasopharynx_outlet": "wall"})

    def test_run_reports_identity_history_and_provenance(self):
        adapter = solver_adapter.CommonPressureAdapter(
            linear_response(), target_m3_s=TARGET,
            name="unit_test_adapter", version="9.9.9")
        result = adapter.run()
        self.assertEqual(result["adapter"]["name"], "unit_test_adapter")
        self.assertEqual(result["adapter"]["version"], "9.9.9")
        self.assertEqual(result["adapter"]["desired_strategy"],
                         "common_inlet_pressure_feedback")
        self.assertEqual(result["adapter"]["flow_target_role"],
                         "outer_iteration_objective_not_simultaneous_PDE_flow_boundary")
        self.assertEqual(result["evaluation_backend"], "injected_callback_not_a_solver")
        self.assertEqual(result["target_basis"],
                         "volumetric_total_inspiratory_flow_kinematic_density_independent")
        self.assertEqual(result["evaluation_count"], len(result["iterations"]))
        self.assertEqual(result["iterations"][-1]["q_total_m3_s"], result["q_total_m3_s"])
        for item in result["iterations"]:
            for key in ("pressure_pa", "q_total_m3_s", "relative_flow_error",
                        "left_fraction", "converged"):
                self.assertIn(key, item)
        self.assertEqual(len(result["bracket_pa"]), 2)

    def test_run_propagates_pressure_feedback_error_unwrapped(self):
        adapter = solver_adapter.CommonPressureAdapter(
            linear_response(conductance=0.0), target_m3_s=TARGET)
        with self.assertRaises(pf.PressureFeedbackError) as ctx:
            adapter.run()
        self.assertNotIsInstance(ctx.exception, solver_adapter.AdapterError)
        self.assertIn("zero total inlet flow", str(ctx.exception))

    def test_non_callable_evaluate_is_rejected(self):
        with self.assertRaises(solver_adapter.AdapterError):
            solver_adapter.CommonPressureAdapter("not-a-callback", target_m3_s=TARGET)


class StampTests(unittest.TestCase):
    def test_self_check_passes_for_the_shipped_adapter(self):
        self.assertEqual(solver_adapter.run_self_check(), [])

    def test_stamp_marks_config_implemented_and_verified(self):
        config = contract.make_config()
        block = solver_adapter.stamp_config(config, "unit_test_adapter", "9.9.9")
        self.assertEqual(block["status"], "implemented_and_verified")
        self.assertEqual(block["name"], "unit_test_adapter")
        self.assertEqual(block["version"], "9.9.9")
        self.assertIs(config["solver_adapter"], block)

    def test_stamp_refuses_when_self_check_fails(self):
        config = contract.make_config()
        with self.assertRaises(solver_adapter.AdapterStampError) as ctx:
            solver_adapter.stamp_config(config, "x", "y",
                                        self_check=lambda: ["synthetic self-check failure"])
        self.assertIn("synthetic self-check failure", str(ctx.exception))
        self.assertEqual(config["solver_adapter"]["status"], "not_implemented")
        self.assertIsNone(config["solver_adapter"]["name"])

    def test_stamp_refuses_strategy_identity_mismatch(self):
        config = contract.make_config()
        config["solver_adapter"]["flow_target_role"] = "PDE_flow_boundary"
        with self.assertRaises(solver_adapter.AdapterStampError):
            solver_adapter.stamp_config(config, "x", "y")
        self.assertEqual(config["solver_adapter"]["status"], "not_implemented")

    def test_stamp_refuses_imposed_equal_split_baseline_config(self):
        config = contract.make_config(split_policy="imposed_equal_split_baseline")
        with self.assertRaises(solver_adapter.AdapterStampError):
            solver_adapter.stamp_config(config, "x", "y")

    def test_stamp_requires_non_empty_name_and_version(self):
        config = contract.make_config()
        with self.assertRaises(solver_adapter.AdapterStampError):
            solver_adapter.stamp_config(config, "", "1.0.0")
        with self.assertRaises(solver_adapter.AdapterStampError):
            solver_adapter.stamp_config(config, "name", None)

    def test_stamp_does_not_touch_make_config_defaults_or_screen(self):
        stamped = contract.make_config()
        screen_before = copy.deepcopy(stamped["engineering_screen"])
        solver_adapter.stamp_config(stamped, "x", "y")
        self.assertEqual(stamped["solver_adapter"]["status"], "implemented_and_verified")
        fresh = contract.make_config()
        self.assertEqual(fresh["solver_adapter"]["status"], "not_implemented")
        self.assertIsNone(fresh["solver_adapter"]["name"])
        self.assertIsNone(fresh["solver_adapter"]["version"])
        self.assertEqual(stamped["engineering_screen"], screen_before)


class ContractIntegrationTests(unittest.TestCase):
    def test_unstamped_solver_determined_config_is_not_execution_ready(self):
        config = contract.make_config()
        ready = contract.validate_config(config, require_execution_ready=True)
        self.assertFalse(ready["valid"])
        self.assertTrue(any("solver adapter has not been implemented and verified" in error
                            for error in ready["errors"]))
        plain = contract.validate_config(config)
        self.assertTrue(plain["valid"])
        self.assertFalse(plain["execution_allowed"])
        self.assertTrue(any("solver adapter has not been implemented" in warning
                            for warning in plain["warnings"]))

    def test_stamped_config_with_reviewed_geometry_is_execution_ready(self):
        config = contract.make_config()
        config["geometry"] = reviewed_geometry()
        solver_adapter.stamp_config(config, "unit_test_adapter", "9.9.9")
        checked = contract.validate_config(config, require_execution_ready=True)
        self.assertTrue(checked["valid"], checked["errors"])
        self.assertTrue(checked["execution_allowed"])
        self.assertFalse(any("solver adapter" in warning for warning in checked["warnings"]))

    def test_strategy_strings_are_bit_exact(self):
        block = contract.make_config()["solver_adapter"]
        self.assertEqual(block["desired_strategy"], "common_inlet_pressure_feedback")
        self.assertEqual(block["flow_target_role"],
                         "outer_iteration_objective_not_simultaneous_PDE_flow_boundary")
        self.assertEqual(block["strategy_description"],
                         "Use one common nostril static pressure and fixed outlet static "
                         "pressure; an outer loop adjusts the common inlet pressure to match "
                         "the total-flow target. Do not impose a flow boundary simultaneously.")
        self.assertEqual(solver_adapter.DESIRED_STRATEGY, block["desired_strategy"])
        self.assertEqual(solver_adapter.FLOW_TARGET_ROLE, block["flow_target_role"])
        self.assertEqual(solver_adapter.STRATEGY_DESCRIPTION, block["strategy_description"])

    def test_four_engineering_screen_values_are_unchanged(self):
        screen = contract.make_config()["engineering_screen"]
        self.assertEqual(screen["maximum_mass_imbalance_fraction"], 0.005)
        self.assertEqual(screen["maximum_monitor_relative_change"], 0.005)
        self.assertEqual(screen["target_residual_max"], 1e-5)
        self.assertEqual(screen["medium_to_fine_change_screen_fraction"], 0.05)

    def test_make_config_default_adapter_block_is_unchanged(self):
        block = contract.make_config()["solver_adapter"]
        self.assertEqual(block["status"], "not_implemented")
        self.assertIsNone(block["name"])
        self.assertIsNone(block["version"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
