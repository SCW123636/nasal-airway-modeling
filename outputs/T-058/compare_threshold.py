"""Compare b15 surface build reports between -300 and -400 HU thresholds."""
import json

a = json.load(open('C:/ts_work/t058_oroext_surfaces/surface_build.json', encoding='utf-8'))
b = json.load(open('C:/ts_work/t058_m400_surfaces/surface_build.json', encoding='utf-8'))
ra = a['cases']['b15'] if 'cases' in a else a
rb = b['cases']['b15'] if 'cases' in b else b
print('=== b15: -300 vs -400 ===')
for k in ('air_voxels', 'union_voxels', 'points', 'triangles', 'boundary', 'watertight', 'ok'):
    va, vb = ra.get(k), rb.get(k)
    if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and va:
        print('%-16s -300=%-10s -400=%-10s delta=%+.2f%%' % (k, va, vb, (vb - va) / va * 100))
    else:
        print('%-16s -300=%-10s -400=%-10s' % (k, va, vb))
pl = ra.get('per_label_voxels') or {}
ql = rb.get('per_label_voxels') or {}
if pl or ql:
    print('--- per_label_voxels ---')
    for k in sorted(set(pl) | set(ql)):
        print('  %-22s %s -> %s' % (k, pl.get(k), ql.get(k)))
