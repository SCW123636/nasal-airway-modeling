"""Short-tube controlled repeat with the corrected source-radius inlet profile.

Original baseline is retained. Mesh settings, length, diameter, flow and
acceptance thresholds are unchanged. Failed meshes are diagnostic only.
"""
import argparse
import json
from pathlib import Path
import subprocess

import phantom_validation as base

WORK_DIR_DEFAULT = r'C:\ts_work\phantom_validation_profile'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir', default=WORK_DIR_DEFAULT)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare', action='store_true')
    mode.add_argument('--run', action='store_true')
    mode.add_argument('--collect', action='store_true')
    args = parser.parse_args()
    if args.prepare:
        return base.prepare(args.work_dir)
    if args.run:
        for size in base.CELL_SIZES_MM:
            case = Path(args.work_dir)/base.case_name(size)
            result = subprocess.run(base.wsl_command(args.work_dir,case)+' --allow-failed-mesh-for-diagnostic', shell=True)
            if result.returncode:
                return result.returncode
        return 0
    status = base.collect(args.work_dir)
    if status == 2:
        return status
    path = Path(args.work_dir)/'validation.json'
    report = json.loads(path.read_text(encoding='utf-8'))
    report['experiment'] = {'kind':'source_radius_profile_diagnostic',
                            'controlled_change':'Circular inlet radius derived from source STL vertices instead of boundary face centroids.',
                            'baseline_report':'../phantom_validation/validation.json',
                            'purpose':'Isolate inlet profile implementation; failed meshes cannot receive engineering acceptance.'}
    path.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    return status


if __name__ == '__main__':
    raise SystemExit(main())
