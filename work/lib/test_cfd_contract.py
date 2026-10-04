"""Synthetic contract tests: never interpreted as patient CFD output."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

import cfd_contract as contract


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


def result_fixture(kind="analytic_reference", model="laminar"):
    result = {"schema": contract.RESULT_SCHEMA, "type": kind,
              "geometry": {"kind": "idealized", "case_id": None},
              "clinical_validation": "not_validated",
              "physics": {"turbulence_model": model, "rho_kg_m3": 1.2, "mu_Pa_s": 1.81e-5},
              "provenance": {"method": "analytic_solution", "equation": "synthetic contract fixture only"},
              "fields": {
                  "velocity": {"unit": "m/s", "association": "point", "values": [[1., 0., 0.], [0., 0., 0.]]},
                  "pressure": {"unit": "Pa", "association": "point", "values": [0., -1.],
                               "quantity": "static", "reference": "gauge", "source_unit": "Pa", "source_field": "p"},
                  "turbulence_intensity": None},
              "turbulence_intensity_status": "not_applicable" if model == "laminar" else "modeled_field"}
    if model == "kOmegaSST":
        result["fields"]["turbulence_intensity"] = contract.compute_turbulence_intensity(
            [[1., 0., 0.], [0., 0., 0.]], [.015, .015], model="kOmegaSST", low_speed_threshold_m_s=.05)
    if kind == "cfd_result":
        result.update(numerical_validation="unchecked", diagnostics={"mass_imbalance_fraction": .001,
                      "monitor_relative_change": .001, "residual_max": 1e-6})
        result["provenance"] = {"method": "cfd_solver", "solver_name": "TEST_FIXTURE",
                                "solver_version": "TEST_FIXTURE", "run_id": "TEST_FIXTURE",
                                "run_log": "test_only.log", "config_id": "TEST_FIXTURE"}
    return result


class ConfigurationTests(unittest.TestCase):
    def test_15_lpm_is_2_5e_minus4_m3_s(self):
        self.assertAlmostEqual(contract.flow_lpm_to_m3_s(15.), 2.5e-4)
        self.assertAlmostEqual(contract.inlet_mean_speed_m_s(contract.flow_lpm_to_m3_s(7.5), 25.), 5.)

    def test_all_templates_are_valid_but_none_can_execute(self):
        with tempfile.TemporaryDirectory(prefix="nasal_cfd_contract_test_") as tmp:
            catalog = contract.write_templates(tmp)
            self.assertEqual(len(catalog["configs"]), 8)
            for entry in catalog["configs"]:
                config = json.loads(Path(entry["file"]).read_text(encoding="utf-8"))
                checked = contract.validate_config(config)
                self.assertTrue(checked["valid"], checked)
                self.assertFalse(checked["execution_allowed"])
                self.assertFalse(contract.validate_config(config, require_execution_ready=True)["valid"])

    def test_three_mesh_levels_and_six_cell_gap_rule_are_preserved(self):
        targets = [contract.make_config(mesh_level=level)["mesh"]["bulk_target_mm"]
                   for level in ("coarse", "medium", "fine")]
        self.assertEqual(targets, [.6, .4, .275])
        config = contract.make_config()
        config["mesh"]["minimum_cells_across_gap"] = 2
        self.assertFalse(contract.validate_config(config)["valid"])

    def test_fixed_flow_and_one_static_reference_are_valid_even_at_plus18_pa(self):
        config = contract.make_config()
        config["boundary_conditions"]["nasopharynx_pressure"]["value"] = 18.
        self.assertTrue(contract.validate_config(config)["valid"])

    def test_total_flow_plus_prescribed_inlet_pressure_is_rejected(self):
        config = contract.make_config()
        config["boundary_conditions"]["nostril_pressure"] = {
            "value": 18., "unit": "Pa", "quantity": "static", "reference": "gauge"}
        self.assertFalse(contract.validate_config(config)["valid"])

    def test_pressure_driven_case_cannot_also_prescribe_total_flow(self):
        config = contract.make_config(mode="static_pressure_difference")
        config["boundary_conditions"]["total_inspiratory_flow_m3_s"] = 2.5e-4
        self.assertFalse(contract.validate_config(config)["valid"])

    def test_static_delta_has_explicit_correct_sign_and_same_pressure_kind(self):
        config = contract.make_config(mode="static_pressure_difference")
        bc = config["boundary_conditions"]
        self.assertEqual(bc["nostril_pressure"]["value"]-bc["nasopharynx_pressure"]["value"], 18.)
        bc["nostril_pressure"]["quantity"] = "total"
        self.assertFalse(contract.validate_config(config)["valid"])

    def test_recording_configuration_is_not_called_static_18pa_drop(self):
        config = contract.make_config(mode="recording_total0_staticplus18")
        bc = config["boundary_conditions"]
        self.assertEqual(bc["nostril_pressure"]["quantity"], "total")
        self.assertEqual(bc["nasopharynx_pressure"]["value"], 18.)
        self.assertIsNone(bc["static_pressure_difference_Pa"])
        bc["static_pressure_difference_Pa"] = 18.
        self.assertFalse(contract.validate_config(config)["valid"])

    def test_pressure_feedback_target_is_not_a_simultaneous_pde_flow_boundary(self):
        config = contract.make_config()
        self.assertEqual(config["solver_adapter"]["desired_strategy"], "common_inlet_pressure_feedback")
        self.assertIsNone(config["boundary_conditions"]["flow_split"]["left_fraction"])
        config["solver_adapter"]["flow_target_role"] = "PDE_flow_boundary"
        self.assertFalse(contract.validate_config(config)["valid"])

    def test_equal_split_must_remain_imposed_baseline(self):
        config = contract.make_config(split_policy="imposed_equal_split_baseline")
        self.assertTrue(contract.validate_config(config)["valid"])
        config["boundary_conditions"]["flow_split"]["interpretation"] = "patient_flow_distribution"
        self.assertFalse(contract.validate_config(config)["valid"])

    def test_mm_geometry_cannot_skip_or_double_the_metre_scale(self):
        for scale in (1., 1e-6):
            with self.subTest(scale=scale):
                config = contract.make_config()
                config["geometry"]["scale_to_m"] = scale
                self.assertFalse(contract.validate_config(config)["valid"])

    def test_pending_patient_geometry_cannot_execute_even_with_implemented_adapter(self):
        config = contract.make_config()
        config["solver_adapter"]["status"] = "implemented_and_verified"
        checked = contract.validate_config(config, require_execution_ready=True)
        self.assertFalse(checked["valid"])
        self.assertTrue(any("human confirmed" in error for error in checked["errors"]))

    def test_mismatched_review_hash_invalidates_execution_metadata(self):
        config = contract.make_config()
        config["geometry"] = reviewed_geometry()
        config["geometry"]["review"]["reviewed_geometry_sha256"] = "b"*64
        config["solver_adapter"]["status"] = "implemented_and_verified"
        self.assertFalse(contract.validate_config(config, require_execution_ready=True)["valid"])

    def test_unknown_extra_velocity_boundary_is_rejected(self):
        config = contract.make_config(mode="static_pressure_difference")
        config["boundary_conditions"]["fixed_inlet_velocity_m_s"] = 1.
        self.assertFalse(contract.validate_config(config)["valid"])

    def test_sst_one_and_five_percent_are_stored_as_fractions(self):
        for fraction in (.01, .05):
            config = contract.make_config(model="kOmegaSST", inlet_intensity_fraction=fraction)
            self.assertTrue(contract.validate_config(config)["valid"])
            self.assertEqual(config["turbulence"]["inlet_intensity_fraction"], fraction)
        config["turbulence"]["inlet_intensity_fraction"] = 5.
        self.assertFalse(contract.validate_config(config)["valid"])


class PressureConversionTests(unittest.TestCase):
    def test_kinematic_pressure_requires_density(self):
        with self.assertRaises(contract.ContractError):
            contract.pressure_to_pa([1., -2.], "m2/s2")

    def test_density_conversion_preserves_negative_gauge_and_zero(self):
        np.testing.assert_allclose(contract.pressure_to_pa([0., 15., -15.], "m2/s2", rho_kg_m3=1.2), [0., 18., -18.])

    def test_pa_values_are_not_rescaled_again(self):
        self.assertEqual(contract.pressure_to_pa(18., "Pa", rho_kg_m3=1.2), 18.)

    def test_p_rgh_cannot_be_recovered_by_density_scaling_alone(self):
        with self.assertRaises(contract.ContractError):
            contract.pressure_to_pa([1.], "m2/s2", rho_kg_m3=1.2, source_field="p_rgh")


class TurbulenceFieldTests(unittest.TestCase):
    def test_laminar_ti_is_null(self):
        self.assertIsNone(contract.compute_turbulence_intensity([[1., 0., 0.]], model="laminar"))

    def test_laminar_cannot_accept_an_sst_k_field(self):
        with self.assertRaises(contract.ContractError):
            contract.compute_turbulence_intensity([[1., 0., 0.]], [.1], model="laminar")

    def test_sst_formula_is_fraction_and_uses_velocity_magnitude(self):
        ti = contract.compute_turbulence_intensity([[3., 4., 0.]], [.375], model="kOmegaSST", low_speed_threshold_m_s=.05)
        # sqrt(2*.375/3) / sqrt(3**2+4**2) = .5/5 = .1 = 10 percent.
        self.assertAlmostEqual(ti["values"][0], .1)
        self.assertEqual(ti["unit"], "1")
        self.assertEqual(ti["valid_mask"], [True])

    def test_zero_and_threshold_speeds_are_null_not_zero_or_infinity(self):
        ti = contract.compute_turbulence_intensity([[0., 0., 0.], [.05, 0., 0.], [.1, 0., 0.]],
            [.01, .01, 0.], model="kOmegaSST", low_speed_threshold_m_s=.05)
        self.assertEqual(ti["values"], [None, None, 0.])
        self.assertEqual(ti["valid_mask"], [False, False, True])
        json.dumps(ti, allow_nan=False)

    def test_negative_k_and_missing_threshold_are_rejected(self):
        with self.assertRaises(contract.ContractError):
            contract.compute_turbulence_intensity([[1., 0., 0.]], [-.1], model="kOmegaSST", low_speed_threshold_m_s=.05)
        with self.assertRaises(contract.ContractError):
            contract.compute_turbulence_intensity([[1., 0., 0.]], [.1], model="kOmegaSST")


class ResultContractTests(unittest.TestCase):
    def test_patient_preview_accepts_geometry_but_no_flow_fields(self):
        result = {"schema": contract.RESULT_SCHEMA, "type": "patient_preview",
                  "geometry": {"kind": "patient", "case_id": "SYNTHETIC_TEST_ONLY"},
                  "clinical_validation": "not_validated", "provenance": {"method": "segmentation_surface_preview"},
                  "fields": {"velocity": None, "pressure": None, "turbulence_intensity": None}}
        self.assertTrue(contract.validate_result(result)["valid"])
        result["fields"]["velocity"] = {"unit": "m/s", "association": "point", "values": [[1., 0., 0.]]}
        self.assertFalse(contract.validate_result(result)["valid"])

    def test_analytic_reference_cannot_be_attached_to_patient_geometry(self):
        result = result_fixture()
        self.assertTrue(contract.validate_result(result)["valid"])
        result["geometry"] = reviewed_geometry()
        self.assertFalse(contract.validate_result(result)["valid"])

    def test_real_patient_cfd_requires_review_even_when_solver_metadata_exists(self):
        result = result_fixture("cfd_result")
        result["geometry"] = contract.make_config()["geometry"]
        self.assertFalse(contract.validate_result(result)["valid"])
        result["geometry"] = reviewed_geometry()
        self.assertTrue(contract.validate_result(result)["valid"])

    def test_automatic_confirmation_cannot_replace_human_review(self):
        result = result_fixture("cfd_result")
        result["geometry"] = reviewed_geometry()
        result["geometry"]["review"]["method"] = "automatic"
        self.assertFalse(contract.validate_result(result)["valid"])

    def test_laminar_zero_ti_field_is_rejected(self):
        result = result_fixture()
        result["fields"]["turbulence_intensity"] = {"unit": "1", "values": [0., 0.]}
        self.assertFalse(contract.validate_result(result)["valid"])

    def test_sst_mask_must_match_recorded_velocity_threshold(self):
        result = result_fixture(model="kOmegaSST")
        self.assertTrue(contract.validate_result(result)["valid"])
        result["fields"]["turbulence_intensity"]["valid_mask"][1] = True
        result["fields"]["turbulence_intensity"]["values"][1] = 0.
        self.assertFalse(contract.validate_result(result)["valid"])

    def test_pressure_output_cannot_silently_publish_kinematic_values_as_pa(self):
        result = result_fixture()
        result["fields"]["pressure"]["source_unit"] = "m2/s2"
        self.assertFalse(contract.validate_result(result)["valid"])
        result["fields"]["pressure"].update(rho_kg_m3=1.2, conversion="p_Pa = rho_kg_m3 * p_kinematic")
        self.assertTrue(contract.validate_result(result)["valid"])

    def test_pressure_conversion_density_must_match_fluid_density(self):
        result = result_fixture()
        result["fields"]["pressure"].update(source_unit="m2/s2", rho_kg_m3=1000., conversion="p_Pa = rho_kg_m3 * p_kinematic")
        self.assertFalse(contract.validate_result(result)["valid"])

    def test_same_association_arrays_require_matching_length(self):
        result = result_fixture()
        result["fields"]["pressure"]["values"] = [0.]
        self.assertFalse(contract.validate_result(result)["valid"])

    def test_cfd_result_requires_solver_run_provenance(self):
        result = result_fixture("cfd_result")
        del result["provenance"]["run_log"]
        self.assertFalse(contract.validate_result(result)["valid"])

    def test_claimed_numerical_pass_rejects_failed_mass_conservation(self):
        result = result_fixture("cfd_result")
        result["numerical_validation"] = "passed_engineering_screen"
        result["diagnostics"]["mass_imbalance_fraction"] = .20
        self.assertFalse(contract.validate_result(result)["valid"])

    def test_linked_template_cannot_be_used_as_execution_ready_result(self):
        config = contract.make_config()
        result = result_fixture("cfd_result")
        result["geometry"] = reviewed_geometry()
        result["provenance"]["config_id"] = config["config_id"]
        checked = contract.validate_result(result, config=config)
        self.assertFalse(checked["valid"])
        self.assertIn("linked configuration was not execution-ready", checked["errors"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
