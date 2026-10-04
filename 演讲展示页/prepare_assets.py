"""Copy presentation dependencies and package a read-only display model."""
from pathlib import Path
import array
import hashlib
import json
import shutil
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ASSETS = HERE / 'assets'
ASSETS.mkdir(exist_ok=True)
VENDOR = ASSETS / 'vendor'
VENDOR.mkdir(exist_ok=True)
for name in ('three.module.js', 'three.core.js', 'OrbitControls.js', 'THREE_LICENSE.txt'):
    shutil.copy2(ROOT / 'work/07_cfd_pipeline/viewer/vendor' / name, VENDOR / name)

source = ROOT / 'work/07_cfd_pipeline/preview/p0/viewer_mesh.json'
data = json.loads(source.read_text(encoding='utf-8'))
assert data['display_geometry_only'] and data['cfd_ready'] is False
verts = data['geometry']['vertices']
faces = data['geometry']['indices']
mins = [min(verts[k::3]) for k in range(3)]
maxs = [max(verts[k::3]) for k in range(3)]
center = [(a + b) / 2 for a, b in zip(mins, maxs)]
scale = 2.7 / max(b - a for a, b in zip(mins, maxs))
positions = array.array('f')
for x, y, z in zip(verts[::3], verts[1::3], verts[2::3]):
    positions.extend(((x-center[0])*scale, (z-center[2])*scale, -(y-center[1])*scale))
indices = array.array('I', faces)
if sys.byteorder != 'little':
    positions.byteswap()
    indices.byteswap()
(ASSETS / 'airway-positions.bin').write_bytes(positions.tobytes())
(ASSETS / 'airway-indices.bin').write_bytes(indices.tobytes())
lm = json.loads((ROOT / 'work/06_auto_landmarks/p0/landmarks.json').read_text(encoding='utf-8'))
points = []
for key, item in lm['landmarks'].items():
    x, y, z = item['point_lps_mm']
    points.append({'key': key, 'label': item['label_zh'], 'status': item['status'],
                   'position': [(x-center[0])*scale, (z-center[2])*scale, -(y-center[1])*scale]})
meta = {'case': 'p0', 'status': 'unreviewed_candidate_preview', 'display_geometry_only': True,
        'cfd_ready': False, 'vertices': len(verts)//3, 'triangles': len(faces)//3,
        'positions': 'airway-positions.bin', 'indices': 'airway-indices.bin', 'landmarks': points,
        'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'display_transform': {'source_coordinate_system': 'LPS', 'source_unit': 'mm',
                              'center_lps_mm': center, 'uniform_scale': scale,
                              'mapping': '(x-center_x, z-center_z, -(y-center_y))*scale'},
        'note': 'Display mesh, unreviewed; all added particle paths are concept animation, not CFD.'}
(ASSETS / 'model.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
report = json.loads((ROOT / 'work/07_cfd_pipeline/solver_reference/results/poiseuille_v1912_verified/validation.json').read_text(encoding='utf-8'))
chart = [{'label': c['level'], 'cells': c['cells'], 'pressure_error_percent': c['boundary_delta_p_relative_error']*100,
          'velocity_error_percent': c['interior_Ux_relative_L2_error']*100} for c in report['cases']]
(ASSETS / 'evidence.json').write_text(json.dumps({'patient_results': 0, 'patient_data': False, 'chart': chart}, indent=2), encoding='utf-8')
print(json.dumps({'vertices': meta['vertices'], 'triangles': meta['triangles'], 'packaged_bytes': len(positions)*4+len(indices)*4}))
