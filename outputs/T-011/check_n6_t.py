"""T-011 A.2 - N6 gate re-check for a threshold-axis surface/opening pair.
Reuses the project's own gate_report (work/lib/nasal_pipeline.py) verbatim so the
threshold cells are judged by the SAME gate code as the baseline.

Usage: python check_n6_t.py <opening_json> <surface_vtp> <landmarks_json>
Prints one JSON line: {"gate":..., "ok":..., "areas_mm2":..., "provenance":...}
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path('D:/项目/鼻腔建模')
sys.path.insert(0, str(ROOT / 'work' / 'lib'))
from nasal_pipeline import gate_report  # noqa: E402


def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    opening_json, surface_vtp, landmarks_json = sys.argv[1:4]
    s_sha = sha256(surface_vtp)
    l_sha = sha256(landmarks_json)
    rep = gate_report('p0', Path(opening_json), surface_sha=s_sha, plane_sha=l_sha)
    print(json.dumps({
        'gate': rep.get('gate'),
        'ok': rep.get('ok'),
        'decision': rep.get('decision'),
        'areas_mm2': rep.get('areas_mm2'),
        'outside_band': rep.get('outside_band'),
        'provenance': rep.get('provenance'),
        'surface_sha256': s_sha,
        'landmarks_sha256': l_sha,
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
