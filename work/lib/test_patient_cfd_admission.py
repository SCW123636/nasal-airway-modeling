"""Known-answer package checks; fixture evidence never claims real approval."""
import copy
import json
from pathlib import Path
import tempfile
import shutil
import unittest
from unittest.mock import patch

import cfd_contract
import patient_cfd_admission as gate
from ct_case_pipeline import write_json


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.case = self.root / 'b15_engineering'
        self.case.mkdir()
        self.template = self.case / 'template'
        mesh = self.template / 'constant/polyMesh';mesh.mkdir(parents=True)
        for name in ('points','faces','owner','neighbour','boundary'):
            (mesh / name).write_text('test fixture only ' + name)
        surface = self.template / 'constant/triSurface/surface.stl';surface.parent.mkdir()
        surface.write_text('synthetic test fixture, not patient anatomy')
        self.surface = surface
        config = cfd_contract.make_config()
        config['geometry'].update(case_id='b15_engineering',source_file='surface.stl',sha256=gate.sha256(surface))
        self.config = self.template / 'config.json';write_json(self.config,config)
        self.manifest = {'patient_case_id':'b15_engineering','final_surface_sha256':gate.sha256(surface),'source_mesh_sha256':'a'*64}
        write_json(self.template / 'case_manifest.json',self.manifest)
        (self.template / 'engineering_authorization_record.md').write_text('Synthetic test fixture authorization only')
        self.authority = {'schema':'nasal_bound_engineering_authorization/v1','scope':'isolated_engineering_trial_not_clinical',
            'case_id':'b15_engineering','surface_file':'constant/triSurface/surface.stl','surface_sha256':gate.sha256(surface),
            'source_mesh_sha256':'a'*64,'config_sha256':gate.sha256(self.config),'mesh_fingerprint':gate.mesh_fingerprint(self.template),
            'record_file':'engineering_authorization_record.md','record_sha256':gate.sha256(self.template / 'engineering_authorization_record.md'),
            'source_record':'unit-test fixture; no real approval'}
        self.authpath = self.template / 'engineering_authorization.json';write_json(self.authpath,self.authority)
        (self.case / 'source.msh').write_text('source fixture')
        (self.case / 'checkMesh.log').write_text('Mesh stats\nFailed 2 mesh checks.\n')
        self.data = {'schema':'nasal_patient_engineering_admission/v1','case_id':'b15_engineering',
                     'surface':{'file':'template/constant/triSurface/surface.stl','sha256':gate.sha256(surface)},
                     'template_dir':'template','config_file':'template/config.json','config_sha256':gate.sha256(self.config),
                     'source_mesh_sha256':'a'*64,'mesh_fingerprint':gate.mesh_fingerprint(self.template),'check_mesh_log':'checkMesh.log',
                     'current_source_binding':{'kind':'frozen_standalone_sample','sample_id':'b15_engineering'},
                     'frozen_sources':{'mesh':{'file':'source.msh','sha256':gate.sha256(self.case / 'source.msh')}},
                     'engineering_authorization':{**self.authority,'record_file':'template/engineering_authorization_record.md'}}
        write_json(self.case / 'admission.json',self.data)

    def tearDown(self):
        self.temp.cleanup()

    def test_frozen_package_admits_engineering_without_claiming_clinical(self):
        result = gate.admission('b15_engineering',self.root)
        self.assertTrue(result['passed'],result)
        self.assertEqual(result['clinical_validation'],'not_validated')
        self.assertTrue(result['clinical_readiness_reasons'])

    def test_scoped_authorization_keeps_readiness_warnings(self):
        value = gate.validate_engineering_authorization(self.template,self.config,self.authpath)
        self.assertTrue(value['allowed'])
        self.assertTrue(value['readiness_warnings'])
        self.assertEqual(value['clinical_validation'],'not_validated')

    def test_changed_mesh_config_surface_and_evidence_refuse(self):
        for file in (self.surface,self.config,self.template / 'constant/polyMesh/points',self.template / 'engineering_authorization_record.md'):
            old = file.read_bytes();file.write_bytes(old + b' ')
            with self.assertRaises((ValueError,json.JSONDecodeError)):
                gate.validate_engineering_authorization(self.template,self.config,self.authpath)
            file.write_bytes(old)

    def test_configuration_errors_not_lifted_by_engineering_record(self):
        config = json.loads(self.config.read_text());config['physics']['rho_kg_m3'] = -1
        write_json(self.config,config)
        self.authority['config_sha256'] = gate.sha256(self.config);write_json(self.authpath,self.authority)
        with self.assertRaisesRegex(ValueError,'配置错误'):
            gate.validate_engineering_authorization(self.template,self.config,self.authpath)

    def test_current_uploaded_case_accepts_sixteen_hex_and_requires_current_binding(self):
        case_id = 'u_531c98ca241b4232'
        self.assertTrue(gate.CASE_RE.fullmatch(case_id))
        result = gate.admission(case_id,self.root)
        self.assertFalse(result['passed'])
        self.assertIn('最终 CFD 表面',' '.join(result['blocking_reasons']))
        old = copy.deepcopy(self.data)
        self.data['case_id'] = case_id;self.data['current_source_binding']={'ct_sha256':'b'*64}
        folder = self.root / case_id;shutil.copytree(self.case,folder)
        config = json.loads((folder/'template/config.json').read_text());config['geometry']['case_id']=case_id
        write_json(folder/'template/config.json',config)
        manifest = dict(self.manifest,patient_case_id=case_id);write_json(folder/'template/case_manifest.json',manifest)
        self.data['config_sha256']=gate.sha256(folder/'template/config.json')
        self.data['engineering_authorization'].update(case_id=case_id,config_sha256=self.data['config_sha256'])
        write_json(folder / 'admission.json',self.data)
        self.assertFalse(gate.admission(case_id,self.root)['passed'])
        self.assertFalse(gate.admission(case_id,self.root,{'ct_sha256':'c'*64})['passed'])
        self.assertTrue(gate.admission(case_id,self.root,{'ct_sha256':'b'*64})['passed'])

    def test_path_traversal_and_missing_authority_refuse(self):
        self.authority['surface_file'] = '../outside.stl';write_json(self.authpath,self.authority)
        with self.assertRaisesRegex(ValueError,'越界'):
            gate.validate_engineering_authorization(self.template,self.config,self.authpath)

    def test_patient_resume_refuses_changed_identity_without_overwriting_evidence(self):
        import patient_cfd_runner
        work = self.root / 'previous_run';work.mkdir()
        old = {'admission_sha256':'0'*64,'old_evidence':'must remain'}
        path = work/'patient_input_fingerprint.json';write_json(path,old)
        before = path.read_bytes()
        with patch.object(patient_cfd_runner,'OpenFOAMPressureEvaluator') as solver:
            with self.assertRaisesRegex(RuntimeError,'fingerprint changed'):
                patient_cfd_runner.run(self.case,work)
        solver.assert_not_called()
        self.assertEqual(path.read_bytes(),before)


if __name__ == '__main__':
    unittest.main()
