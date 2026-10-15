"""Known frozen textual inputs and a complete synthetic versioned package."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'work/lib'))
from test_patient_cfd_admission import AdmissionTests
spec = importlib.util.spec_from_file_location('t029_provision', Path(__file__).with_name('provision_b15_engineering_t029a.py'))
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


class TrialTests(unittest.TestCase):
    def test_exact_scheme_and_top_level_budget_only(self):
        scheme = 'header\n' + trial.OLD_SCHEME + '\ndiv(phi,k) bounded Gauss limitedLinear 1;\n'
        self.assertEqual(trial.single_replacement(scheme, trial.OLD_SCHEME, trial.NEW_SCHEME), scheme.replace(trial.OLD_SCHEME, trial.NEW_SCHEME))
        text = 'endTime 1500;\nwriteInterval 200;\nfunctions {\n writeInterval 1;\n}\n'
        self.assertEqual(trial.budget_controls(text), 'endTime 120;\nwriteInterval 20;\nfunctions {\n writeInterval 1;\n}\n')
        for value in ('missing', trial.OLD_SCHEME + trial.OLD_SCHEME):
            with self.assertRaises(ValueError):
                trial.single_replacement(value, trial.OLD_SCHEME, trial.NEW_SCHEME)
        with self.assertRaises(ValueError):
            trial.budget_controls(text.replace('1500', '900'))

    def test_full_synthetic_package_and_no_overwrite(self):
        fixture = AdmissionTests('test_frozen_package_admits_engineering_without_claiming_clinical')
        fixture.setUp()
        try:
            system = fixture.template / 'system'
            system.mkdir()
            (fixture.template / '0').mkdir()
            (system / 'fvSchemes').write_text(trial.OLD_SCHEME)
            (system / 'controlDict').write_text('endTime 1500;\nwriteInterval 200;\n')
            source_dir = fixture.case / 'sources'
            source_dir.mkdir()
            (fixture.case / 'source.msh').rename(source_dir / 'source.msh')
            fixture.data['frozen_sources']['mesh']['file'] = 'sources/source.msh'
            (fixture.case / 'admission.json').write_text(json.dumps(fixture.data))
            destination = fixture.root / trial.CASE_ID
            result = trial.provision(fixture.case, destination, fixture.root / 'evidence')
            self.assertTrue(result['passed'])
            before = trial.tree_identity(destination)
            with self.assertRaises(FileExistsError):
                trial.provision(fixture.case, destination, fixture.root / 'evidence')
            self.assertEqual(trial.tree_identity(destination), before)
        finally:
            fixture.tearDown()


if __name__ == '__main__':
    unittest.main()
