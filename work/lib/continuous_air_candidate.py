"""Exploratory original-grid CT air connectivity; never an anatomical admission.

All seed components are retained unless an explicitly recorded barrier removes
their voxels. Threshold is strictly CT < -300 HU; connectivity is 6-neighbour.
No interpolation, closing, filling, artificial bridges, or largest-component cut.
"""
from __future__ import annotations
import numpy as np
from scipy import ndimage

THRESHOLD_HU = -300.0
STRUCTURE = ndimage.generate_binary_structure(3, 1)


def same_grid(a, b):
    return (a.GetDimension() == b.GetDimension() == 3 and a.GetSize() == b.GetSize()
            and np.allclose(a.GetSpacing(), b.GetSpacing(), atol=1e-6, rtol=0)
            and np.allclose(a.GetOrigin(), b.GetOrigin(), atol=1e-5, rtol=0)
            and np.allclose(a.GetDirection(), b.GetDirection(), atol=1e-6, rtol=0))


def index_to_lps(indices_xyz, image):
    return (np.asarray(image.GetOrigin()) +
            (np.asarray(indices_xyz, float) * image.GetSpacing()) @
            np.asarray(image.GetDirection()).reshape(3, 3).T)


def connected_air(ct, seed, allowed=None, exterior_seed=None, reject_leak=True):
    """Return every air component intersecting seeds, with explicit leak evidence.

    exterior_seed is a caller-specified, recorded domain-boundary sentinel. An
    accepted sentinel check is an engineering screen, not proof of anatomy.
    """
    ct = np.asarray(ct)
    seed = np.asarray(seed)
    if ct.ndim != 3 or ct.shape != seed.shape:
        raise ValueError('CT/seed grid shape mismatch')
    if seed.dtype != bool or (allowed is not None and np.asarray(allowed).dtype != bool):
        raise ValueError('seed and allowed must be boolean masks')
    if allowed is None:
        allowed = np.ones(ct.shape, bool)
    if np.asarray(allowed).shape != ct.shape:
        raise ValueError('allowed grid shape mismatch')
    air = (ct < THRESHOLD_HU) & allowed
    seeds = seed & air
    if not np.any(seeds):
        raise ValueError('empty eligible seed')
    labels, component_count = ndimage.label(air, structure=STRUCTURE)
    seed_ids = np.unique(labels[seeds])
    seed_ids = seed_ids[seed_ids != 0]
    candidate = np.isin(labels, seed_ids)
    exterior_ids = np.array([], dtype=labels.dtype)
    if exterior_seed is not None:
        exterior_seed = np.asarray(exterior_seed)
        if exterior_seed.shape != ct.shape or exterior_seed.dtype != bool:
            raise ValueError('exterior sentinel grid mismatch')
        exterior_ids = np.unique(labels[exterior_seed & air])
        exterior_ids = exterior_ids[exterior_ids != 0]
    leak_ids = np.intersect1d(seed_ids, exterior_ids)
    counts = np.bincount(labels.ravel())
    report = {
        'threshold_HU_strictly_less_than': THRESHOLD_HU,
        'connectivity': 6, 'air_component_count': int(component_count),
        'seed_original_voxels': int(seed.sum()),
        'eligible_seed_voxels': int(seeds.sum()),
        'seed_removed_or_nonair_voxels': int((seed & ~air).sum()),
        'candidate_voxels': int(candidate.sum()),
        'added_vs_eligible_seed_voxels': int((candidate & ~seed).sum()),
        'seed_component_ids': seed_ids.tolist(),
        'candidate_component_sizes': [int(counts[i]) for i in seed_ids],
        'exterior_component_ids': exterior_ids.tolist(),
        'leak_component_ids': leak_ids.tolist(),
        'exterior_leak_detected': bool(len(leak_ids)),
        'no_largest_component_filter': True,
    }
    if len(leak_ids) and reject_leak:
        raise ValueError('external-air sentinel connected to seed')
    return candidate, report


def face_contacts(mask):
    return {'x_low': int(mask[:, :, 0].sum()), 'x_high': int(mask[:, :, -1].sum()),
            'y_low': int(mask[:, 0, :].sum()), 'y_high': int(mask[:, -1, :].sum()),
            'z_low': int(mask[0].sum()), 'z_high': int(mask[-1].sum())}
