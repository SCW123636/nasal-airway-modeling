"""Evidence audit separates closed shells, patch islands and medical approval."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import vtk

import build_scope_evidence as module
from build_scope_evidence import build_bundle, component_audit, evidence_html, surface_image
from ct_case_pipeline import sha256
from export_candidate_preview import set_triangle_arrays
from partitioned_surface import clip_and_cap, SurfaceClipError
from test_partitioned_surface import cube, plane


class ScopeEvidenceTests(unittest.TestCase):
    def test_disconnected_closed_shell_not_hidden_by_global_topology(self):
        points, faces = cube()
        points = np.vstack((points, points + [20, 0, 0]))
        faces = np.vstack((faces, faces + 8))
        labels = np.full(len(faces), 'wall', dtype=object)
        labels[:3] = ['nostril_L', 'nostril_R', 'nasopharynx_outlet']
        audit = component_audit(points, faces, labels)
        self.assertEqual(audit['surface_components'], 2)
        self.assertEqual(sorted(x['triangles'] for x in audit['components']), [12, 12])
        self.assertEqual(len(audit['components_containing_all_three_patches']), 1)
        self.assertEqual(audit['self_intersections'], 'not_checked')
        self.assertFalse(audit['patient_solver_allowed'])

    def test_one_patch_can_have_multiple_islands_on_one_surface(self):
        points, faces = cube()
        labels = np.full(len(faces), 'wall', dtype=object)
        labels[[0, 2]] = 'nostril_L'
        audit = component_audit(points, faces, labels)
        self.assertEqual(audit['surface_components'], 1)
        self.assertEqual(audit['patch_connected_regions']['nostril_L'], 2)

    def test_cap_collision_exposes_patch_and_physical_bounds(self):
        points, faces = cube()
        with self.assertRaises(SurfaceClipError) as raised:
            clip_and_cap(points, faces, {'first': plane([0, 0, 2], [0, 0, 1]),
                                        'second': plane([2, 0, 0], [1, 0, 0])})
        details = raised.exception.details
        self.assertIn('earlier cap', str(raised.exception))
        self.assertEqual(details['plane'], 'second')
        self.assertEqual(set(details['earlier_patch_counts']), {'first'})
        self.assertGreater(details['conflicting_triangles'], 0)
        self.assertTrue(all(abs(center[2] - 2) < 1e-7
                            for center in details['triangle_centers_lps_mm']))

    def test_real_surface_render_and_html_escaping(self):
        from PIL import Image
        points, faces = cube()
        poly = vtk.vtkPolyData()
        set_triangle_arrays(poly, points, faces)
        labels = np.full(len(faces), 'wall', dtype=object)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'cube.png'
            meta = surface_image(poly, labels, path, [0, -1, 0], [0, 0, 1])
            self.assertFalse(meta['surface_decimated'])
            values = np.array(Image.open(path))
            self.assertGreater(np.count_nonzero(values.max(axis=2) - values.min(axis=2) > 10), 100)
            record = {'case': 'p0', 'technical_status': 'fail', 'reason': '<script>bad</script>',
                      'surface_audit': component_audit(points, faces, labels),
                      'images': [{'path': 'cube.png', 'title': '<unsafe>'}]}
            page = evidence_html([record], Path(temp))
            self.assertIn('data:image/png;base64,', page)
            self.assertIn('&lt;script&gt;bad&lt;/script&gt;', page)
            self.assertNotIn('<script>bad</script>', page)

    def test_earlier_case_change_refuses_publication_and_cleans_stage(self):
        for changed in ('ct', 'surface'):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                drafts, proposals, output = root / 'drafts', root / 'proposals', root / 'output'
                ct = root / 'ct'
                ct.write_text('original')
                for case in ('p0', 'p1', 'p2', 'p3', 'p3t1'):
                    (drafts / case).mkdir(parents=True)
                    (proposals / case).mkdir(parents=True)
                    (drafts / case / 'source_surface.vtp').write_text('surface')
                    (drafts / case / 'report.json').write_text('{}')
                    (proposals / case / 'proposal.json').write_text('{}')

                def generate(store, case, source, proposal, directory):
                    record = {'case': case, 'surface_kind': 'source', 'images': [],
                              'inputs': {'ct': sha256(ct)}, 'surface_audit': {'surface_components': 1},
                              'source_draft_report_sha256': sha256(drafts / case / 'report.json'),
                              'source_surface_sha256': sha256(drafts / case / 'source_surface.vtp'),
                              'surface_sha256': sha256(drafts / case / 'source_surface.vtp'),
                              'proposal_sha256': sha256(proposals / case / 'proposal.json')}
                    if case == 'p3t1':
                        target = ct if changed == 'ct' else drafts / 'p0' / 'source_surface.vtp'
                        target.write_text('changed while rendering a later case')
                    return record

                with patch.object(module, 'build_case', side_effect=generate), \
                        patch.object(module, 'load_adopted', return_value=({}, ct)), \
                        patch.object(module, 'candidate_inputs', side_effect=lambda *args:
                                     (None, None, None, {'ct': sha256(ct)})), \
                        patch.object(module, 'evidence_html', return_value='<html></html>'):
                    with self.assertRaisesRegex(ValueError, 'earlier'):
                        build_bundle(drafts, proposals, output, root / 'cases')
                self.assertFalse(output.exists())
                self.assertEqual(list(root.glob('.scope_evidence_*')), [])


if __name__ == '__main__':
    unittest.main()
