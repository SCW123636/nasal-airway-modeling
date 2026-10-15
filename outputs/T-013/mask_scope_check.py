"""Supplementary real-API check: distinguish live and dead original vertices."""
import hashlib
import inspect
import json
import sys
from pathlib import Path

import numpy as np

ROOT=Path(r'D:\项目\鼻腔建模')
OUT=ROOT/'outputs'/'T-013'
sys.path.insert(0,str(OUT))
from production_probe import load_mesh, load_planes, flood_mask, OPENINGS
from partitioned_surface import clip_and_cap, SurfaceClipError


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ScopeSelector(dict):
    def __init__(self,masks):
        super().__init__(masks)
        self.trace=[]

    def get(self,name,default=None):
        frame=inspect.currentframe().f_back
        assert frame.f_code is clip_and_cap.__code__
        local=frame.f_locals
        p,f=local['points'],local['faces']
        mask,_=flood_mask(p,f,local['spec'])
        old=super().get(name)
        live=np.zeros(len(p),bool)
        live[np.unique(f)]=True
        diff=mask[:len(old)]!=old
        self.trace.append({'plane':name,'original_mask_true':int(old.sum()),
                           'current_mask_true':int(mask.sum()),
                           'appended_selected':int(mask[len(old):].sum()),
                           'original_changed_total':int(diff.sum()),
                           'original_changed_live':int((diff & live[:len(old)]).sum()),
                           'original_changed_dead':int((diff & ~live[:len(old)]).sum()),
                           'old_true_new_false_live':int((old & ~mask[:len(old)] & live[:len(old)]).sum()),
                           'old_false_new_true_live':int((~old & mask[:len(old)] & live[:len(old)]).sum())})
        return mask


paths=[Path(__file__),OUT/'production_probe.py',
       ROOT/'work'/'lib'/'partitioned_surface.py',
       ROOT/'work'/'lib'/'auto_opening_pipeline.py',
       ROOT/'work'/'lib'/'connectivity_opened_surface.py',
       Path('C:/ts_work/batch27_surfaces/p0/source_surface.vtp'),
       ROOT/'work'/'06_auto_landmarks'/'p0'/'landmarks.json']
before={str(p):sha(p) for p in paths}
planes,_,_,_=load_planes(ROOT/'work'/'06_auto_landmarks',None,'p0',True)
_,(points,faces)=load_mesh(paths[-2])
masks={k:flood_mask(points,faces,planes[k])[0] for k in OPENINGS}
selectors=ScopeSelector(masks)
try:
    clip_and_cap(points,faces,planes,selectors=selectors)
    outcome={'unexpected_pass':True}
except SurfaceClipError as exc:
    outcome={'exception':type(exc).__name__,'error':str(exc)}
after={str(p):sha(p) for p in paths}
assert before==after
assert selectors.trace[-1]['original_changed_live']==0
result={'purpose':'supplement existing real clip control; identify dead original vertices',
        'fingerprints_before':before,'fingerprints_after':after,
        'inputs_unchanged':before==after,'trace':selectors.trace,'outcome':outcome}
(OUT/'mask_scope_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
