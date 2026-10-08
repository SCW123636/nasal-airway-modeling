"""Immutable binary-mask history, currently an isolated engineering component.

No patient directory, editor API, anatomical approval or solver is connected.
The caller supplies matched CT identity and LPS image geometry explicitly.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

import numpy as np

from ct_case_pipeline import execution_lock, now, read_json, sha256, write_json


def _digest(record):
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode('utf-8')).hexdigest()


def _binary(values):
    array = np.asarray(values)
    if (array.ndim != 3 or array.dtype.kind not in 'biuf' or not np.isfinite(array).all()
            or not np.isin(array, (0, 1)).all() or not array.any()):
        raise ValueError('Expected a nonempty binary 3D mask')
    return array.astype(np.uint8, copy=True)


def _geometry(geometry, shape):
    if geometry.get('coordinate_system') != 'LPS' or geometry.get('unit') != 'mm':
        raise ValueError('Geometry must use LPS millimetres')
    spacing = np.asarray(geometry.get('spacing_mm'), dtype=float)
    origin = np.asarray(geometry.get('origin_lps_mm'), dtype=float)
    axes = np.asarray(geometry.get('axis_dirs'), dtype=float)
    if (tuple(geometry.get('shape_zyx', ())) != shape or spacing.shape != (3,)
            or origin.shape != (3,) or axes.shape != (3, 3)
            or not np.isfinite(spacing).all() or np.any(spacing <= 0)
            or not np.isfinite(origin).all() or not np.isfinite(axes).all()
            or not np.allclose(axes @ axes.T, np.eye(3), atol=1e-6, rtol=0)):
        raise ValueError('Invalid or mismatched image geometry')
    return {'coordinate_system': 'LPS', 'unit': 'mm', 'shape_zyx': list(shape),
            'spacing_mm': spacing.tolist(), 'origin_lps_mm': origin.tolist(), 'axis_dirs': axes.tolist()}


class MaskRevisionStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def load(self, revision=None):
        if revision is None:
            revision = read_json(self.root / 'current.json')['revision']
        if not isinstance(revision, str) or not re.fullmatch(r'm_[0-9a-f]{64}', revision):
            raise ValueError('Invalid mask revision')
        directory = self.root / 'versions' / revision
        if directory.resolve().parent != (self.root / 'versions').resolve():
            raise ValueError('Revision escaped storage')
        record = read_json(directory / 'record.json')
        if 'm_' + _digest(record) != revision:
            raise ValueError('Mask record content hash changed')
        masks = {}
        for name in ('main', 'candidate'):
            path = directory / (name + '.npy')
            if sha256(path) != record['mask_sha256'][name]:
                raise ValueError('Mask content hash changed')
            masks[name] = _binary(np.load(path, allow_pickle=False))
        _geometry(record['geometry'], masks['main'].shape)
        if masks['candidate'].shape != masks['main'].shape or np.any(masks['main'] > masks['candidate']):
            raise ValueError('Main mask must be contained in candidate mask')
        return revision, record, masks

    def commit(self, main, candidate, *, ct_sha256, geometry, expected_revision,
               action='edit', reviewer, restored_from=None):
        if not isinstance(ct_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', ct_sha256):
            raise ValueError('CT content hash is required')
        if not isinstance(reviewer, str) or not reviewer.strip() or action not in ('initial', 'edit', 'undo', 'reset'):
            raise ValueError('Reviewer and valid action are required')
        main, candidate = _binary(main), _binary(candidate)
        if candidate.shape != main.shape or np.any(main > candidate):
            raise ValueError('Main mask must be contained in candidate mask')
        geometry = _geometry(geometry, main.shape)
        with execution_lock(self.root):
            pointer = self.root / 'current.json'
            current = self.load() if pointer.exists() else None
            if expected_revision != (current[0] if current else None):
                raise ValueError('Stale mask revision; reload before editing or undoing')
            if current and (ct_sha256 != current[1]['ct_sha256'] or geometry != current[1]['geometry']):
                raise ValueError('CT identity or image geometry changed')
            if (current is None) != (action == 'initial'):
                raise ValueError('Initial action requires an empty store')
            if (action in ('undo', 'reset')) != (restored_from is not None):
                raise ValueError('Restore actions require a source revision')
            if restored_from is not None:
                _, source, values = self.load(restored_from)
                if source['ct_sha256'] != ct_sha256 or source['geometry'] != geometry:
                    raise ValueError('Restore source identity changed')
                if not all(np.array_equal(values[key], value) for key, value in
                           (('main', main), ('candidate', candidate))):
                    raise ValueError('Restore arrays do not match source revision')
            versions = self.root / 'versions'
            versions.mkdir(exist_ok=True)
            temporary = Path(tempfile.mkdtemp(prefix='.pending-', dir=versions))
            try:
                np.save(temporary / 'main.npy', main, allow_pickle=False)
                np.save(temporary / 'candidate.npy', candidate, allow_pickle=False)
                record = {
                    'schema': 'mask_revision/v1', 'created_at': now(),
                    'parent': expected_revision, 'sequence': current[1]['sequence'] + 1 if current else 1,
                    'action': action, 'reviewer': reviewer.strip(), 'restored_from': restored_from,
                    'ct_sha256': ct_sha256, 'geometry': geometry,
                    'mask_sha256': {key: sha256(temporary / (key + '.npy')) for key in ('main', 'candidate')},
                    'changed_voxels': {key: int(np.count_nonzero(value != current[2][key])) if current else 0
                                       for key, value in (('main', main), ('candidate', candidate))},
                    'review_status': 'pending', 'external_air_validation': 'pending',
                    'downstream_status': {key: 'stale' for key in ('surface', 'mesh', 'solver', 'results', 'report')},
                    'patient_solver_allowed': False,
                }
                revision = 'm_' + _digest(record)
                write_json(temporary / 'record.json', record)
                destination = versions / revision
                os.replace(temporary, destination)
                self.load(revision)
                # Only this pointer commits the generation; failures leave old versions usable.
                write_json(pointer, {'schema': 'mask_current/v1', 'revision': revision})
                return revision
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)

    def restore(self, target_revision, *, expected_revision, reviewer, action='undo'):
        if action not in ('undo', 'reset'):
            raise ValueError('Restore action must be undo or reset')
        _, record, masks = self.load(target_revision)
        return self.commit(masks['main'], masks['candidate'], ct_sha256=record['ct_sha256'],
                           geometry=record['geometry'], expected_revision=expected_revision,
                           action=action, reviewer=reviewer, restored_from=target_revision)
