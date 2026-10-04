"""Run TotalSegmentator from Python with Windows-safe temporary cleanup."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import tempfile


def safe_cleanup(self, original):
    try:
        original(self)
    except PermissionError:
        # nnUNet may release a NIfTI handle just after TemporaryDirectory's
        # context exits. The directory is case-local and can be cleaned later.
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--task', default='head_glands_cavities')
    parser.add_argument('--device', default='cpu')
    parser.add_argument('--temp', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    args.temp.mkdir(parents=True, exist_ok=True)
    os.environ['TMP'] = str(args.temp)
    os.environ['TEMP'] = str(args.temp)
    os.environ['TMPDIR'] = str(args.temp)
    original = tempfile.TemporaryDirectory.cleanup
    tempfile.TemporaryDirectory.cleanup = lambda self: safe_cleanup(self, original)
    from totalsegmentator.python_api import totalsegmentator
    totalsegmentator(input=args.input, output=args.output, task=args.task,
                     device=args.device, nr_thr_resamp=1, nr_thr_saving=1,
                     quiet=False, verbose=False)
    required = ('nasal_cavity_left.nii.gz', 'nasal_cavity_right.nii.gz',
                'nasopharynx.nii.gz', 'oropharynx.nii.gz',
                'hard_palate.nii.gz', 'soft_palate.nii.gz')
    missing = [name for name in required if not (args.output / name).is_file()]
    if missing:
        raise RuntimeError('分割完成但缺少鼻腔所需标签：' + ', '.join(missing))
    print('SEGMENTATION_OK', flush=True)


if __name__ == '__main__':
    main()
