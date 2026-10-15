"""Hand-written arrays/physical coordinates verify the small diagnostic helpers."""
import importlib.util
from pathlib import Path
import tempfile,unittest,hashlib
import numpy as np
import SimpleITK as sitk

def load(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+'.py'))
    obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj);return obj

coverage=load('inspect_lower_coverage')
semantic=load('run_isolated_semantic')

class KnownAnswers(unittest.TestCase):
    def image(self):
        img=sitk.Image([3,4,5],sitk.sitkInt16);img.SetSpacing((2,3,4));img.SetOrigin((-10,20,30));return img
    def test_physical_centers(self):
        g=coverage.geometry(self.image())
        self.assertEqual(g['index0_center_lps_mm'],[-10,20,30])
        self.assertEqual(g['last_center_lps_mm'],[-6,29,46])
    def test_physical_rotation(self):
        img=self.image();img.SetDirection((0,-1,0,1,0,0,0,0,1))
        self.assertEqual(coverage.geometry(img)['last_center_lps_mm'],[-19,24,46])
    def test_bbox_axis_order_and_inferior(self):
        a=np.zeros((5,4,3),bool);a[0,1,2]=True;a[2,3,0]=True
        d=coverage.label_info(a,self.image())
        self.assertEqual(d['voxels'],2)
        self.assertEqual(d['bbox_ijk_xyz'],[(0,1,0),(2,3,2)])
        self.assertEqual(d['bbox_centers_lps_mm'],[(-10,23,30),(-6,29,38)])
        self.assertEqual(d['inferior_face_voxels'],1)
    def test_empty_has_no_bbox(self):
        d=coverage.label_info(np.zeros((5,4,3)),self.image())
        self.assertEqual(d,{'voxels':0,'bbox_ijk_xyz':None,'bbox_centers_lps_mm':None})
    def test_semantic_and_strict_air(self):
        ct=np.array([-1000,-300,-301,-1000,-1000]);cl=np.array([13,13,13,12,0])
        self.assertEqual(semantic.semantic_air(ct,cl).tolist(),[True,False,True,False,False])
    def test_empty_cannot_become_candidate(self):
        self.assertFalse(semantic.semantic_air(np.full((2,2),-1000),np.zeros((2,2))).any())
    def test_grid_size_mismatch_rejected(self):
        with self.assertRaises(ValueError):semantic.semantic_air(np.zeros((2,2)),np.zeros((3,3)))
    def test_sha_known_abc(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'abc';p.write_bytes(b'abc')
            expected='ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'
            self.assertEqual(semantic.sha(p),expected);self.assertEqual(coverage.sha(p),expected)

if __name__=='__main__':unittest.main(verbosity=2)
