import unittest
import numpy as np
from test_partitioned_surface import cube, plane
from partitioned_surface import clip_and_cap
from outlet_selection_constraints import (selection_binding, target_loop_catalog,
                                          constrained_target_selector, SelectionConstraintError)


class ConstraintTests(unittest.TestCase):
    def test_connected_negative_region_couples_two_known_u_shape_rims(self):
        import SimpleITK as sitk
        from export_candidate_preview import mask_surface, triangle_arrays
        values=np.zeros((20,8,20),np.uint8)
        values[2:16,2:6,2:6]=1
        values[2:16,2:6,12:16]=1
        values[2:7,2:6,2:16]=1
        poly,_=mask_surface(sitk.GetImageFromArray(values));p,f=triangle_arrays(poly)
        spec=plane([0,0,10.25],[0,0,1]);catalog=target_loop_catalog(p,f,spec)
        self.assertEqual(len(catalog['loops']),2)
        self.assertEqual(catalog['loops'][0]['coupled_loop_ids'],[0,1])
        with self.assertRaisesRegex(SelectionConstraintError,'inseparable'):
            constrained_target_selector(p,f,spec,[0],expected_binding=catalog['binding'])
        constrained_target_selector(p,f,spec,[0,1],expected_binding=catalog['binding'])

    def test_bound_explicit_loop_keeps_analytic_cube_cap_and_volume(self):
        p,f=cube(); spec=plane([0,0,2],[0,0,1])
        catalog=target_loop_catalog(p,f,spec)
        self.assertEqual(len(catalog['loops']),1)
        self.assertAlmostEqual(catalog['loops'][0]['area_mm2'],16)
        mask,note=constrained_target_selector(p,f,spec,[0],expected_binding=catalog['binding'])
        _,_,_,report=clip_and_cap(p,f,{'end':spec},selectors={'end':mask})
        self.assertAlmostEqual(report['caps']['end']['area_mm2'],16)
        self.assertAlmostEqual(report['technical_qc']['signed_volume_mm3'],96)
        self.assertFalse(note['anatomy_approved'])

    def test_protected_or_partial_allowed_negative_component_refuses_instead_of_trimming(self):
        p,f=cube(); spec=plane([0,0,2],[0,0,1]); binding=selection_binding(p,f,spec)
        protected=np.zeros(len(p),bool);protected[0]=True
        allowed=np.ones(len(p),bool);allowed[0]=False
        for kwargs in ({'protected_vertices':protected},{'allowed_delete_vertices':allowed}):
            with self.assertRaises(SelectionConstraintError) as ctx:
                constrained_target_selector(p,f,spec,[0],expected_binding=binding,**kwargs)
            self.assertIn(0,ctx.exception.details['conflicting_source_vertex_ids'])

    def test_other_closed_component_can_be_unselected_without_roi_guess(self):
        p,f=cube(); p=np.vstack((p,p+[10,0,0]));f=np.vstack((f,f+8))
        spec=plane([0,0,2],[0,0,1]); catalog=target_loop_catalog(p,f,spec)
        self.assertEqual(len(catalog['loops']),2)
        left=next(x['id'] for x in catalog['loops'] if max(v[0] for v in x['contour_lps_mm'])<5)
        mask,_=constrained_target_selector(p,f,spec,[left],expected_binding=catalog['binding'])
        self.assertFalse(mask[8:].any())
        protected=np.zeros(len(p),bool);protected[8:]=True
        constrained_target_selector(p,f,spec,[left],expected_binding=catalog['binding'],protected_vertices=protected)

    def test_stale_source_or_plane_binding_and_invalid_ids_refuse(self):
        p,f=cube();spec=plane([0,0,2],[0,0,1]);binding=selection_binding(p,f,spec)
        for wrong_p,wrong_spec in ((p+[1,0,0],spec),(p,plane([0,0,3],[0,0,1]))):
            with self.assertRaisesRegex(ValueError,'binding'):
                constrained_target_selector(wrong_p,f,wrong_spec,[0],expected_binding=binding)
        for ids in ([],[0,0],[True],[7]):
            with self.assertRaisesRegex(ValueError,'IDs'):
                constrained_target_selector(p,f,spec,ids,expected_binding=binding)


if __name__=='__main__':
    unittest.main()
