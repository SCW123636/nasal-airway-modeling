"""Synthetic positive/negative controls for native self-intersection diagnosis."""
import argparse
from pathlib import Path

import numpy as np

from build_reviewed_surface_drafts import write_surface
from ct_case_pipeline import sha256, write_json
from prepare_surface_preflight import export_surface, native_check
from test_partitioned_surface import cube


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    records = []
    for name in ('clean', 'crossing'):
        points, faces = cube()
        if name == 'crossing':
            points = np.vstack((points, points + [2, 2, 3]))
            faces = np.vstack((faces, faces + 8))
        source = args.output / (name + '.vtp')
        write_surface(source, points, faces)
        report = export_surface(source, args.output / name, sha256(source), labelled=False)
        native_check(args.output / name, report)
        native = report['surface_check']['interpretation']
        expected = (native['status'] == 'native_checks_pass' if name == 'clean'
                    else native['status'] == 'fail' and native['edge_triangle_intersection_hits'] > 0)
        records.append({'name': name, 'expected_result_met': expected, 'report': report})
    write_json(args.output / 'validation.json', {'controls': records,
                'all_expected_results_met': all(x['expected_result_met'] for x in records),
                'patient_cfd_results': 0})
    if not all(x['expected_result_met'] for x in records):
        raise ValueError('Native detection failed a synthetic control')


if __name__ == '__main__':
    main()
