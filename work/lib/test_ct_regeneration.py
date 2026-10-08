"""A scheme update publishes new review identities and preserves old artifacts."""
import copy
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ct_case_pipeline as pipeline
from build_auto_landmark_review import build_review
from confirm_landmark_review import load_proposal_bundle


class RegenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ct_regeneration_')
        self.manager = pipeline.CaseManager(Path(self.temp.name))
        case = self.manager.create({'kind':'dicom','files':[{'name':'synthetic.dcm','size':2}]})['id']
        self.manager.upload(case, 0, io.BytesIO(b'CT'), 2)
        self.directory = Path(self.temp.name)/case
        (self.directory/'ct.nii.gz').write_bytes(b'synthetic input, never used for inference')
        public = self.directory/'public'
        self.report = {'case':case,'coordinate_system':'LPS','unit':'mm','proposal_hash':'old-proposal',
                       'landmarks':{'nostril_L':{'status':'proposed','point_lps_mm':[1,2,3],'normal_lps':[0,1,0]}}}
        pipeline.write_json(public/'review'/case/'landmarks.json',self.report)
        build_review(public/'review',cases=[case])
        pipeline.write_json(public/'preview'/case/'viewer_mesh.json',{'synthetic_surface':'unchanged'})
        pipeline.write_json(public/'viewer.json',{'cases':[{'id':case,'landmarks':[], 'mesh_url':'original',
                             'result':{'fields':{'velocity':None,'pressure':None,'turbulence_intensity':None}}}]})
        hashes={str(p.relative_to(public)).replace('\\','/'):pipeline.sha256(p) for p in public.rglob('*') if p.is_file()}
        pipeline.write_json(self.directory/'receipt.json',{'output_sha256':hashes,'identity':self.identity()})
        pipeline.update(self.directory,status='awaiting_review',worker_pid=None,active_stage='review',
                        stages={s:'waiting' if s=='review' else 'pending' for s in pipeline.STAGES},
                        artifacts={'viewer':'old-viewer','review':'old-review'})
        self.original = {str(p.relative_to(public)):p.read_bytes() for p in public.rglob('*') if p.is_file()}
        self.old_decisions = self.decisions(public/'review/index.html')

    def tearDown(self):
        self.manager.pool.shutdown(wait=True)
        self.temp.cleanup()

    def identity(self, *args, **kwargs):
        return {'input_sha256':{'ct.nii.gz':pipeline.sha256(self.directory/'ct.nii.gz')}}

    def decisions(self, html):
        bundle = load_proposal_bundle(html)
        case=bundle['cases'][0]; lm=case['landmarks'][0]
        return {'artifact_type':'landmark_review_decisions','coordinate_system':'LPS','unit':'mm','reviewer':'Synthetic QA',
                'proposal_bundle_sha256':bundle['proposal_bundle_sha256'],
                'cases':[{'case':case['case'],'source_sha256':case['source_sha256'],
                'decisions':[{'landmark_id':lm['id'],'proposal_sha256':lm['proposal_sha256'],
                              'original_point_lps_mm':lm['proposal']['point_lps_mm'],
                              'original_normal_lps':lm['proposal']['normal_lps'],'decision':'pending'}]}]}

    def generate(self, directory, name, command):
        out=Path(command[command.index('--out-base')+1])
        report=copy.deepcopy(self.report);report['landmarks']['nostril_L']['point_lps_mm']=[4,5,6]
        report['proposal_hash']='new-proposal'
        pipeline.write_json(out/directory.name/'landmarks.json',report)

    def regenerate(self):
        with patch('run_auto_anatomy.input_identity',side_effect=self.identity),patch.object(pipeline,'run_command',side_effect=self.generate):
            return pipeline.regenerate_artifacts(self.directory)

    def test_new_bundle_old_review_rejected_and_surface_reused(self):
        self.manager.save_review(self.directory.name,self.old_decisions)
        old_review=(self.directory/'review_decisions.json').read_bytes()
        self.assertEqual(self.regenerate(),0)
        data=self.manager.get(self.directory.name)
        public,private,_=pipeline.verify_case_artifacts(self.directory,data)
        self.assertEqual(data['status'],'awaiting_review')
        self.assertEqual(data['stages']['solver'],'pending')
        for relative,contents in self.original.items():self.assertEqual((self.directory/'public'/relative).read_bytes(),contents)
        self.assertEqual((self.directory/'review_decisions.json').read_bytes(),old_review)
        self.assertFalse((private/'review_decisions.json').exists())
        viewer=pipeline.read_json(public/'viewer.json')
        self.assertEqual(viewer['cases'][0]['landmarks'][0]['point_lps_mm'],[4,5,6])
        self.assertIsNone(viewer['cases'][0]['result']['fields']['velocity'])
        with self.assertRaises(ValueError):self.manager.save_review(self.directory.name,self.old_decisions)
        self.manager.save_review(self.directory.name,self.decisions(public/'review/index.html'))
        self.assertTrue((private/'review_decisions.json').is_file())
        self.assertEqual(self.manager.get(self.directory.name)['stages']['solver'],'pending')

    def test_failure_preserves_published_result_and_status(self):
        pipeline.update(self.directory, status='review_recorded')
        before=self.manager.get(self.directory.name)
        with patch('run_auto_anatomy.input_identity',side_effect=self.identity),patch.object(pipeline,'run_command',side_effect=RuntimeError('synthetic failure')):
            self.assertEqual(pipeline.regenerate_artifacts(self.directory),1)
        after=self.manager.get(self.directory.name)
        self.assertEqual(after['artifacts'],before['artifacts'])
        self.assertEqual(after['status'],'review_recorded')
        self.assertNotIn('current_revision',after)
        self.assertEqual(len(after.get('versions',[])),0)
        pipeline.verify_case_artifacts(self.directory,after)

    def test_changed_input_rejected_before_generating(self):
        (self.directory/'ct.nii.gz').write_bytes(b'changed')
        with patch.object(pipeline,'run_command') as command:
            self.assertEqual(pipeline.regenerate_artifacts(self.directory),1)
            command.assert_not_called()
        self.assertNotIn('current_revision',self.manager.get(self.directory.name))

    def test_regeneration_does_not_restart_import_or_segmentation(self):
        with patch.object(self.manager.pool,'submit') as submit:
            data=self.manager.regenerate(self.directory.name)
        self.assertEqual(data['status'],'queued')
        submit.assert_called_once_with(self.manager._run,self.directory.name,True)
        self.assertEqual(data['artifacts']['viewer'],'old-viewer')
        with self.assertRaises(ValueError):self.manager.regenerate(self.directory.name)

    def test_success_invalidates_old_boundary_preview_and_keeps_record(self):
        previous = {'status': 'generated', 'revision': 'original',
                    'draft_id': 'd_0123456789abcdef', 'sha256': 'a' * 64}
        pipeline.update(self.directory, boundary_preview=previous,
                        boundary_review={'status': 'confirmed', 'sha256': 'b' * 64})
        self.assertEqual(self.regenerate(), 0)
        current = self.manager.get(self.directory.name)
        self.assertEqual(current['boundary_preview'], previous | {'status': 'stale'})
        self.assertEqual(current['boundary_review']['status'], 'stale')
        self.assertEqual(current['stages']['solver'], 'pending')


if __name__=='__main__':unittest.main()
