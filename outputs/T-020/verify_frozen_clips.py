"""Bounded production replay, fixed T-013 inputs/planes; never a N6 override."""
import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'work/lib'))
import numpy as np
import vtk
from connectivity_opened_surface import flood_mask
from export_candidate_preview import triangle_arrays
from partitioned_surface import clip_and_cap, SurfaceClipError
from test_partitioned_surface import cube, plane


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def trial(fn, p, f, planes, masks):
    start = time.monotonic()
    try:
        p, f, labels, qc = fn(p, f, planes, selectors=masks)
        return {'passed': True, 'report': qc,
                'array_sha256': {k: hashlib.sha256(a.tobytes()).hexdigest() for k, a in
                                 [('points', p), ('faces', f), ('labels', labels.astype('U'))]},
                'elapsed_s': time.monotonic()-start}
    except ValueError as exc:
        return {'passed': False, 'exception': type(exc).__name__, 'error': str(exc),
                'details': getattr(exc, 'details', None), 'elapsed_s': time.monotonic()-start}


def baseline_module():
    # Freeze the exact pre-change repository implementation locally; no copy of
    # the clipping algorithm is authored by this probe.
    source = subprocess.check_output(['git', 'show', 'ca9c939:work/lib/partitioned_surface.py'], cwd=ROOT)
    path = OUT / 'source_versions/partitioned_surface_before.py'
    path.parent.mkdir(exist_ok=True)
    if path.exists() and path.read_bytes() != source:
        raise RuntimeError('Refuse to overwrite an existing baseline source')
    path.write_bytes(source)
    spec = importlib.util.spec_from_file_location('clip_before_t020', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, path


def baseline_answer():
    module, path = baseline_module()
    p, f = cube()
    planes = {'bottom': plane([0,0,2], [0,0,1]), 'side': plane([2,0,0], [1,0,0])}
    masks = {k: flood_mask(p, f, s)[0] for k,s in planes.items()}
    before, after = trial(module.clip_and_cap,p,f,planes,masks), trial(clip_and_cap,p,f,planes,masks)
    assert 'outside cutting plane or ROI' in before['error'], before
    assert after['details']['strictly_crossing_plane_triangles'] > 0, after
    write('lifecycle_before_after.json', {'baseline_revision':'ca9c939', 'baseline_source_sha256':sha(path),
        'answer':'z=2 cap spans x=0..4; x=2 must reject cap deletion before off-plane topology',
        'before':before,'after':after})


def real(cases):
    original = json.loads((ROOT / 'outputs/T-013/real_cases_results.json').read_text(encoding='utf-8'))
    files = [Path(__file__), *(ROOT / 'work/lib' / x for x in
              ('partitioned_surface.py','outlet_selection_lineage.py','connectivity_opened_surface.py'))]
    for case in cases:
        files.extend(Path(p) for p in original['cases'][case]['frozen_inputs'])
    fingerprints = {str(p):sha(p) for p in files}
    for case in cases:
        for path, expected in original['cases'][case]['frozen_inputs'].items():
            assert sha(path) == expected, ('frozen input changed',path)
    write('start_fingerprints.json', {'at':datetime.now(timezone.utc).isoformat(), 'files':fingerprints,
        'thread_limits':{x:os.environ.get(x) for x in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS')},
        'scope':'one sequential production clip per case; no N6 process, mesh or solver'})
    before_module, before_path=baseline_module()
    import shapely
    result={'scope':'fixed planes; original masks transported by source lineage; N6 not bypassed',
            'environment':{'python':sys.version,'numpy':np.__version__,'vtk':vtk.vtkVersion.GetVTKVersion(),
                           'shapely':shapely.__version__, 'geos':shapely.geos_version_string},
            'baseline_source_sha256':sha(before_path),'cases':{}}
    begun=time.monotonic()
    for case in cases:
        if time.monotonic()-begun > 270:
            raise RuntimeError('Bounded 5-minute lane limit approaching; stop before next case')
        old=original['cases'][case]
        path=next(Path(p) for p in old['frozen_inputs'] if Path(p).name == 'source_surface.vtp')
        reader=vtk.vtkXMLPolyDataReader(); reader.SetFileName(str(path)); reader.Update()
        p,f=triangle_arrays(reader.GetOutput())
        planes=old['planes']
        masks={k:flood_mask(p,f,s)[0] for k,s in planes.items()}
        current=trial(clip_and_cap,p,f,planes,masks)
        baseline_now=trial(before_module.clip_and_cap,p,f,planes,masks)
        entry={'inputs':old['frozen_inputs'],'planes':planes,'offset_source':old['offset_source'],
               'actual':current, 'frozen_baseline_current_environment':baseline_now}
        result['cases'][case]=entry
        write('fixed_clip_results.json',result)
        if case=='p0':
            assert not current['passed'] and current['details']['collision_kind']=='selection_covers_earlier_cap', current
            assert current['details']['strictly_crossing_plane_triangles']==0, current
            assert current['details']['fully_in_delete_halfspace_triangles']==774, current
            entry['answer']='774 earlier-cap triangles wholly in delete halfspace; true cap refusal required'
        else:
            assert current['passed'], current
            entry['arrays_equal_historical_T013']=current['array_sha256']==old['baseline']['array_sha256']
            entry['arrays_equal_frozen_baseline_current_environment']=current['array_sha256']==baseline_now['array_sha256']
            assert entry['arrays_equal_frozen_baseline_current_environment'], entry
            entry['areas_equal_T013_baseline']={k:current['report']['caps'][k]['area_mm2']-
                old['baseline']['qc']['caps'][k]['area_mm2'] for k in planes}
            entry['areas_equal_frozen_baseline_current_environment']={k:current['report']['caps'][k]['area_mm2']-
                baseline_now['report']['caps'][k]['area_mm2'] for k in planes}
            assert all(x==0 for x in entry['areas_equal_frozen_baseline_current_environment'].values()), entry
        result['cases'][case]=entry
        write('fixed_clip_results.json',result)
        print(json.dumps({'case':case,'passed':current['passed'],'elapsed_s':current['elapsed_s'],
                          'arrays_equal':entry.get('arrays_equal_frozen_baseline_current_environment'),
                          'historical_arrays_equal':entry.get('arrays_equal_historical_T013'),
                          'error':current.get('error')},ensure_ascii=False),flush=True)
    end={p:sha(p) for p in fingerprints}
    write('end_fingerprints.json',{'at':datetime.now(timezone.utc).isoformat(),'files':end,
                                  'unchanged':end==fingerprints,'elapsed_s':time.monotonic()-begun})
    assert end==fingerprints


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--cases',nargs='*');parser.add_argument('--baseline',action='store_true')
    args=parser.parse_args()
    if args.baseline:baseline_answer()
    if args.cases:real(args.cases)
