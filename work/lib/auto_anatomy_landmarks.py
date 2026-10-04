"""Anatomy-constrained landmark PROPOSALS; no automatic clinical confirmation.

Uses physical LPS coordinates, a palate-based frame, air-to-air semantic
interfaces, and anterior/inferior CT air rays. Outputs measurements,
threshold stability, Slicer markups and a compact review queue. Does not edit
input masks or apply any crop. Constants are engineering hypotheses.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import SimpleITK as sitk
from scipy import ndimage as ndi
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[2]
NAMES = ['nasal_cavity_left', 'nasal_cavity_right', 'nasopharynx',
         'oropharynx', 'hard_palate', 'soft_palate']
PARAMETERS = {
    'thresholds_HU': [-300, -350, -400],
    'nostril_anterior_fraction': .25, 'nostril_inferior_fraction': .65,
    'outward_ray_angles_deg': [15, 30, 45, 60, 75, 90],
    'ray_length_mm': 12., 'ray_step_mm': .5,
    'minimum_patch_samples': 20, 'max_plane_rms_mm': 1.5,
    'max_threshold_drift_mm': 1., 'max_threshold_normal_angle_deg': 15.,
    'max_secondary_patch_ratio': .35, 'semantic_departure_mm': .8,
    'note': 'Uncalibrated engineering checks, not medical accuracy or confidence probabilities.'
}
S6 = ndi.generate_binary_structure(3, 1)
S26 = ndi.generate_binary_structure(3, 3)


def unit(v):
    v = np.asarray(v, float)
    n = np.linalg.norm(v)
    if not np.isfinite(n) or n < 1e-9:
        raise ValueError('Degenerate direction')
    return v / n


def geometry_matches(a, b):
    return a.GetSize() == b.GetSize() and all(np.allclose(x, y, atol=1e-5, rtol=0)
        for x, y in [(a.GetSpacing(), b.GetSpacing()), (a.GetOrigin(), b.GetOrigin()),
                     (a.GetDirection(), b.GetDirection())])


def affine(image):
    a = np.eye(4)
    a[:3, :3] = np.asarray(image.GetDirection()).reshape(3, 3) @ np.diag(image.GetSpacing())
    a[:3, 3] = image.GetOrigin()
    return a


def physical(zyx, a):
    return np.asarray(zyx)[..., ::-1] @ a[:3, :3].T + a[:3, 3]


def indices(points, a):
    return ((np.asarray(points) - a[:3, 3]) @ np.linalg.inv(a[:3, :3]).T)[..., ::-1]


def sample(arr, points, a, order=1, outside=np.nan):
    ix = indices(points, a)
    return ndi.map_coordinates(arr, ix.reshape(-1, 3).T, order=order,
                               mode='constant', cval=outside).reshape(ix.shape[:-1])


def fit_plane(points, inward):
    if len(points) < 3:
        return None
    center = np.mean(points, axis=0)
    q = points - center
    _, ss, vv = np.linalg.svd(q, full_matrices=False)
    if ss[1] < 1e-5:
        return None
    normal = vv[-1]
    if normal @ inward < 0:
        normal = -normal
    residuals = q @ normal
    return {'point_lps_mm': center.tolist(), 'normal_lps': normal.tolist(),
            'samples': len(points), 'rms_mm': float(np.sqrt(np.mean(residuals ** 2))),
            'p95_residual_mm': float(np.percentile(np.abs(residuals), 95)),
            'planarity_ratio': float(ss[-1] / ss[1]),
            'roi_lps_mm': {'min': (points.min(0)-2).tolist(), 'max': (points.max(0)+2).tolist()}}


def contact_faces(a_mask, b_mask, a):
    """Shared faces on a doubled index lattice; edge-only voxel contact is excluded."""
    centers, axes, areas = [], [], []
    for axis in range(3):
        low = [slice(None)] * 3; high = [slice(None)] * 3
        low[axis] = slice(None, -1); high[axis] = slice(1, None)
        for ma, mb in [(a_mask, b_mask), (b_mask, a_mask)]:
            xyz = np.argwhere(ma[tuple(low)] & mb[tuple(high)]).astype(float)
            if not len(xyz):
                continue
            xyz[:, axis] += .5
            centers.append(np.rint(2*xyz).astype(int))
            axes.extend([axis]*len(xyz))
            # This is voxel-face area, not an oblique physical cross-section.
            cols = [i for i in range(3) if i != 2-axis]
            areas.extend([np.linalg.norm(np.cross(a[:3, cols[0]], a[:3, cols[1]]))]*len(xyz))
    return (np.concatenate(centers) if centers else np.empty((0, 3), dtype=int),
            np.asarray(axes, dtype=int), np.asarray(areas, dtype=float))


def face_patches(centers, axes):
    """Group voxel faces sharing a complete edge, not merely a corner."""
    parent = list(range(len(centers)))
    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    edges = {}
    for i, (center, axis) in enumerate(zip(centers, axes)):
        u, v = [j for j in range(3) if j != axis]
        corners = []
        for du, dv in [(-1,-1), (-1,1), (1,1), (1,-1)]:
            q = center.copy(); q[u] += du; q[v] += dv
            corners.append(tuple(int(x) for x in q))
        for j in range(4):
            edge = tuple(sorted((corners[j], corners[(j+1)%4])))
            if edge in edges:
                parent[root(i)] = root(edges[edge])
            else:
                edges[edge] = i
    return np.asarray([root(i) for i in range(len(parent))], dtype=int)


def contact_points(a_mask, b_mask, a):
    centers, _, areas = contact_faces(a_mask, b_mask, a)
    return physical(centers/2., a), float(areas.sum())


def build_frame(masks, ct, a):
    bone = masks['hard_palate'] & (ct > 200)
    if bone.sum() < 50:
        bone = masks['hard_palate']
    pts = physical(np.argwhere(bone), a)
    if len(pts) < 50:
        raise ValueError('Hard palate missing or too small for a reference frame')
    pts = pts[::max(1, len(pts)//30000)]
    palate = fit_plane(pts, np.array([0., 0., 1.]))
    if palate is None:
        raise ValueError('Hard palate is degenerate; no reference plane can be fitted')
    up = unit(palate['normal_lps'])
    palate_center = np.asarray(palate['point_lps_mm'])
    left_center = physical(np.argwhere(masks['nasal_cavity_left']).mean(0), a)
    right_center = physical(np.argwhere(masks['nasal_cavity_right']).mean(0), a)
    nasal_midline = (left_center + right_center) / 2.
    # The origin is reproducible across scans: the bilateral nasal midpoint
    # projected onto the fitted hard-palate plane, rather than the scan box.
    center = nasal_midline - up * ((nasal_midline - palate_center) @ up)
    nasal = masks['nasal_cavity_left'] | masks['nasal_cavity_right']
    nc = physical(np.argwhere(nasal).mean(0), a)
    pc = physical(np.argwhere(masks['nasopharynx']).mean(0), a)
    posterior = pc - nc
    posterior = unit(posterior - up * (posterior @ up))
    left = unit(np.cross(posterior, up))
    if left[0] < 0:
        left = -left
    return {'origin_lps_mm': center.tolist(), 'superior_lps': up.tolist(),
            'posterior_lps': posterior.tolist(), 'left_lps': left.tolist(),
            'origin_definition': 'bilateral nasal cavity midpoint projected onto hard-palate fit plane',
            'nasal_midline_reference_lps_mm': nasal_midline.tolist(),
            'palate_fit': palate,
            'note': 'Palate plane defines coordinates only; it is not an oral barrier.'}


def local_center(mask, a, p, radius=8.):
    xyz = physical(np.argwhere(mask), a)
    if not len(xyz):
        return None
    loc = xyz[np.linalg.norm(xyz-p, axis=1) <= radius]
    return (loc if len(loc) else xyz).mean(0)


def interface_candidate(mask1, mask2, a, frame):
    centers, axes, areas = contact_faces(mask1, mask2, a)
    if len(centers) < 3:
        return None
    groups = face_patches(centers, axes)
    unique = np.unique(groups)
    ranked = sorted([(float(areas[groups == g].sum()), int(g)) for g in unique], reverse=True)
    area, largest = ranked[0]
    pts = physical(centers[groups == largest]/2., a)
    if len(pts) < 3:
        return None
    p = pts.mean(0)
    inward = local_center(mask1, a, p) - local_center(mask2, a, p)
    fit = fit_plane(pts, unit(inward))
    if fit is None:
        return None
    fit['face_contact_area_mm2'] = area
    fit['total_face_contact_area_mm2'] = float(areas.sum())
    fit['patch_count'] = len(ranked)
    fit['secondary_patch_ratio'] = ranked[1][0]/area if len(ranked) > 1 else 0.
    fit['patch_area_mm2_descending'] = [r[0] for r in ranked]
    fit['patch_connectivity'] = 'shared full face edge, not corner; largest physical face-area patch fitted'
    fit['evidence_type'] = 'CT-air shared faces between two anatomical labels'
    fit['points'] = pts
    return fit


def nostril_candidate(side, all_flow, ct, a, frame, threshold, prior=None):
    airside = side & (ct < threshold)
    surface = airside & ~ndi.binary_erosion(airside, structure=S6)
    ijk = np.argwhere(surface)
    if len(ijk) < 20:
        return None
    pts = physical(ijk, a)
    posterior = np.asarray(frame['posterior_lps']); up = np.asarray(frame['superior_lps'])
    ctr = np.asarray(frame['origin_lps_mm'])
    ap, sup = (pts-ctr) @ posterior, (pts-ctr) @ up
    selected = ((ap <= np.quantile(ap, PARAMETERS['nostril_anterior_fraction'])) &
                (sup <= np.quantile(sup, PARAMETERS['nostril_inferior_fraction'])))
    pts, ijk = pts[selected], ijk[selected]
    if not len(pts):
        return None
    search_mode = 'full_anatomical_search'
    if prior and prior.get('status') == 'search_prior':
        from coarse_anatomy_prior import in_search_box
        local = in_search_box(pts, prior, frame)
        if local.sum() >= PARAMETERS['minimum_patch_samples']:
            pts, ijk = pts[local], ijk[local]
            search_mode = 'coarse_prior_local_search'
    t = np.arange(PARAMETERS['ray_step_mm'], PARAMETERS['ray_length_mm']+.01, PARAMETERS['ray_step_mm'])
    directions = [-np.cos(np.deg2rad(d))*posterior - np.sin(np.deg2rad(d))*up
                  for d in PARAMETERS['outward_ray_angles_deg']]
    visible = np.zeros(len(pts), bool)
    votes = np.zeros((len(pts), len(directions)), bool)
    # Need immediate departure from semantic mask AND an all-air CT ray.
    # A truncated ray is rejected instead of treating out-of-FOV as external air.
    all_flow_u8 = all_flow.astype(np.uint8)
    departed = t >= PARAMETERS['semantic_departure_mm']
    for j, direction in enumerate(directions):
        for start in range(0, len(pts), 1024):
            q = pts[start:start+1024, None, :] + t[None, :, None]*direction
            hu = sample(ct, q, a, order=1)
            semantic = sample(all_flow_u8, q[:, departed], a, order=0, outside=1) > 0
            ok = np.all(np.isfinite(hu) & (hu < threshold), axis=1) & ~semantic.any(1)
            votes[start:start+len(ok), j] = ok
    visible = votes.any(1)
    patch = np.zeros_like(side)
    if visible.any():
        patch[tuple(ijk[visible].T)] = True
    cc, count = ndi.label(patch, S26)
    sizes = np.bincount(cc.ravel()); sizes[0] = 0
    if not count or sizes.max() < 3:
        return None
    order = np.argsort(sizes)[::-1]
    first = order[0]
    take = visible & (cc[tuple(ijk.T)] == first)
    outwards = np.asarray(directions)[votes[take].sum(0).argmax()]
    fit = fit_plane(pts[take], -outwards)
    if fit is None:
        return None
    fit.update({'points': pts[take], 'surface_patch_voxels': int(take.sum()),
                'visible_surface_voxels': int(visible.sum()), 'patch_count': int(count),
                'secondary_patch_ratio': float(sizes[order[1]]/sizes[first]) if count > 1 else 0.,
                'ray_success_directions': int(np.count_nonzero(votes[take].sum(0))),
                'evidence_type': 'anterior-inferior nasal label surface + finite in-FOV CT air rays without semantic re-entry',
                'external_air_independently_established': False,
                'search_mode': search_mode,
                'boundary_definition': 'finite air-ray proposal; neither exterior endpoint nor true alar rim independently labelled'})
    return fit


def nostril_with_prior(side, all_flow, ct, a, frame, threshold, prior):
    """Local search keeps the same CT evidence; a failed search retries globally."""
    candidate = nostril_candidate(side, all_flow, ct, a, frame, threshold, prior)
    if prior and prior.get('status') == 'search_prior' and (candidate is None or
            candidate['samples'] < PARAMETERS['minimum_patch_samples'] or
            candidate['rms_mm'] > PARAMETERS['max_plane_rms_mm'] or
            candidate.get('secondary_patch_ratio', 1.) > PARAMETERS['max_secondary_patch_ratio']):
        candidate = nostril_candidate(side, all_flow, ct, a, frame, threshold)
        if candidate is not None:
            candidate['search_mode'] = 'global_fallback_after_local_search'
    return candidate


def result_record(key, cn, en, variants, extra_reasons=None):
    valid = [v for v in variants if v is not None]
    base = variants[0]
    record = {'label_zh': cn, 'label_en': en, 'status': 'unavailable', 'point_lps_mm': None,
              'normal_lps': None, 'evidence': {}, 'consistency_checks': {},
              'review_reasons': list(extra_reasons or []), 'overlay_png': 'review.png',
              'clinical_validation': 'not_validated', 'confidence_probability': None}
    if base is None:
        record['review_reasons'].append('T300 下没有满足关系约束的有限接触面/向外空气通道')
        return record
    p, n = np.asarray(base['point_lps_mm']), np.asarray(base['normal_lps'])
    drift = max(float(np.linalg.norm(np.asarray(v['point_lps_mm'])-p)) for v in valid)
    tilt = max(float(np.rad2deg(np.arccos(np.clip(np.dot(unit(v['normal_lps']), unit(n)),-1,1)))) for v in valid)
    checks = {'all_three_thresholds_found': len(valid) == 3,
              'enough_patch_samples': all(v['samples'] >= PARAMETERS['minimum_patch_samples'] for v in valid),
              'plane_residual_within_engineering_limit': all(v['rms_mm'] <= PARAMETERS['max_plane_rms_mm'] for v in valid),
              'threshold_position_stable': drift <= PARAMETERS['max_threshold_drift_mm'],
              'threshold_direction_stable': tilt <= PARAMETERS['max_threshold_normal_angle_deg'],
              'no_competing_large_patch': all(v.get('secondary_patch_ratio', float('inf')) <= PARAMETERS['max_secondary_patch_ratio'] for v in valid)}
    record.update({k:base[k] for k in ['point_lps_mm','normal_lps','roi_lps_mm']})
    record['consistency_checks'] = checks
    record['evidence'] = {k:v for k,v in base.items() if k not in ['points','point_lps_mm','normal_lps','roi_lps_mm']}
    record['evidence'].update({'threshold_drift_mm': drift, 'threshold_normal_change_deg': tilt,
        'minimum_samples_across_thresholds': min(v['samples'] for v in valid),
        'maximum_rms_across_thresholds_mm': max(v['rms_mm'] for v in valid),
        'threshold_variants': [{k:v for k,v in x.items() if k!='points'} if x else None for x in variants]})
    record['review_reasons'] += [k for k,v in checks.items() if not v]
    record['status'] = 'proposed' if all(checks.values()) else 'needs_review'
    record['acceptance_meaning'] = 'automatic localization proposal only; not anatomy approval or CFD permission'
    return record


def markups(report, path):
    # Documented Slicer Markups JSON: Fiducial points in LPS, millimetres.
    control = []
    for key, value in report['landmarks'].items():
        if value['point_lps_mm'] is None:
            continue
        control.append({'id': str(len(control)+1), 'label': key, 'description': value['status'],
                        'associatedNodeID': '', 'position': value['point_lps_mm'],
                        'orientation': [1,0,0,0,1,0,0,0,1], 'selected': True,
                        'locked': True, 'visibility': True, 'positionStatus': 'defined'})
    obj = {'@schema': 'https://raw.githubusercontent.com/Slicer/Slicer/master/Modules/Loadable/Markups/Resources/Schema/markups-schema-v1.0.3.json',
           'markups': [{'type':'Fiducial','coordinateSystem':'LPS','coordinateUnits':'mm',
                        'locked':True,'labelFormat':'%N-%d','controlPoints':control,'measurements':[]}]}
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')


def plane_slice_line(point_zyx, normal_lps, a, axes, fixed_index, half_width_vox):
    """Intersection with the actual displayed integer-index slice, in voxel coordinates."""
    q = np.asarray(point_zyx, float)
    xaxis, yaxis = axes
    fixed = next(i for i in range(3) if i not in axes)
    coeff = (np.asarray(normal_lps) @ a[:3, :3])[::-1]
    offset = coeff[fixed] * (fixed_index-q[fixed])
    if abs(coeff[yaxis]) >= abs(coeff[xaxis]) and abs(coeff[yaxis]) > 1e-10:
        xx = np.array([q[xaxis]-half_width_vox[0], q[xaxis]+half_width_vox[0]])
        yy = q[yaxis] - (coeff[xaxis]*(xx-q[xaxis])+offset)/coeff[yaxis]
    elif abs(coeff[xaxis]) > 1e-10:
        yy = np.array([q[yaxis]-half_width_vox[1], q[yaxis]+half_width_vox[1]])
        xx = q[xaxis] - (coeff[yaxis]*(yy-q[yaxis])+offset)/coeff[xaxis]
    else:
        return None
    return xx, yy


def plot_review(ct, masks, a, report, out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties
    font = FontProperties(fname='C:/Windows/Fonts/msyh.ttc') if Path('C:/Windows/Fonts/msyh.ttc').exists() else None
    rows = [(k,v) for k,v in report['landmarks'].items() if v['point_lps_mm'] is not None]
    if not rows:
        fig, ax = plt.subplots(figsize=(9, 3)); ax.axis('off')
        ax.text(.05, .5, report['case']+' | 无可显示候选；请查看失败原因', fontproperties=font)
        fig.savefig(out, dpi=125); plt.close(fig)
        return
    # Export enough pixels for the browser review view.  The source CT is sampled
    # at sub-millimetre spacing, so the raster must not become the limiting factor.
    review_dpi = 200
    fig, axs = plt.subplots(len(rows), 3, figsize=(13, max(3, len(rows)*3.1)), squeeze=False)
    rgb = np.zeros(ct.shape+(3,), dtype=np.uint8)
    for name,col in [('nasal_cavity_left',(255,140,30)),('nasal_cavity_right',(30,190,220)),
                     ('nasopharynx',(230,80,100)),('oropharynx',(130,90,235)),
                     ('hard_palate',(230,205,80)),('soft_palate',(90,200,100))]:
        rgb[masks[name]]=col
    for row,(key,lm) in enumerate(rows):
        q=indices(np.asarray(lm['point_lps_mm']),a); iz,iy,ix=np.round(q).astype(int)
        slices=[(ct[iz],rgb[iz],q[2],q[1],(2,1),iz),
              (ct[:,iy,:],rgb[:,iy,:],q[2],q[0],(2,0),iy),(ct[:,:,ix],rgb[:,:,ix],q[1],q[0],(1,0),ix)]
        for ax,(im,co,x,y,axes,fixed_index) in zip(axs[row],slices):
            sp=np.linalg.norm(a[:3,:3],axis=0)[::-1]
            ax.imshow(im,cmap='gray',vmin=-1000,vmax=800,origin='lower',
                      aspect=sp[axes[1]]/sp[axes[0]], interpolation='bilinear')
            alpha=(co.max(-1)>0)*.35
            # Anti-alias the color layer at review zoom; the underlying binary masks
            # remain unchanged and are still carried as the source of geometry.
            ax.imshow(co,alpha=alpha,origin='lower',aspect=sp[axes[1]]/sp[axes[0]],
                      interpolation='bilinear')
            ax.plot(x,y,'+',color='lime',ms=14,mew=1.5)
            # Plane intersection with the current image slice in voxel coordinates.
            line = plane_slice_line(q,lm['normal_lps'],a,axes,fixed_index,
                                    (25/sp[axes[0]],25/sp[axes[1]]))
            if line is not None:
                ax.plot(*line,'--',color='lime',lw=.8)
            ax.set_xlim(max(0,x-25/sp[axes[0]]), min(im.shape[1]-1,x+25/sp[axes[0]]))
            ax.set_ylim(max(0,y-25/sp[axes[1]]), min(im.shape[0]-1,y+25/sp[axes[1]]))
            ax.set_xticks([]); ax.set_yticks([])
        axs[row,0].set_ylabel(lm['label_zh']+'\n'+lm['status'],fontproperties=font)
    for ax,title in zip(axs[0],['轴向索引切面','冠状索引切面','矢状索引切面']):
        ax.set_title(title,fontproperties=font)
    fig.suptitle(report['case']+' | 候选点与平面，尚未医学验证；实际物理比例',fontproperties=font)
    fig.tight_layout()
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    from matplotlib.transforms import Bbox
    row_boxes = [Bbox.union([ax.get_tightbbox(renderer) for ax in axs[row]])
                 for row in range(len(rows))]
    scale = review_dpi/fig.dpi
    fig.savefig(out,dpi=review_dpi); plt.close(fig)
    # Dedicated three-view image per landmark keeps the review page readable.
    from PIL import Image
    with Image.open(out) as overview:
        height, width = overview.height, overview.width
        for row, (key, _) in enumerate(rows):
            box = row_boxes[row]
            top = max(0, int(height-box.y1*scale)-5)
            bottom = min(height, int(height-box.y0*scale)+5)
            left = max(0, int(box.x0*scale)-5)
            right = min(width, int(box.x1*scale)+5)
            overview.crop((left, top, right, bottom)).save(Path(out).parent / f'{key}.png')


def run_case(key, data_base, out_base, reference_library=None, reference_patient_id=None):
    data=Path(data_base)/key; out=Path(out_base)/key; out.mkdir(parents=True,exist_ok=True)
    img=sitk.ReadImage(str(data/'ct.nii.gz')); full_ct=sitk.GetArrayFromImage(img)
    arrays={}; bounds=[]; truncated={}
    for name in NAMES:
        mi=sitk.ReadImage(str(data/'masks'/f'{name}.nii.gz'))
        if not geometry_matches(img,mi):
            raise ValueError(f'{key}/{name}: CT geometry mismatch')
        m=sitk.GetArrayFromImage(mi)>0
        c=np.argwhere(m)
        if not len(c):
            raise ValueError(f'{key}/{name}: required reference is empty')
        bounds.append((c.min(0),c.max(0)))
        truncated[name]=bool(np.any(c.min(0)==0) or np.any(c.max(0)==np.asarray(m.shape)-1))
        arrays[name]=m
    # Crop only for compute/QA. Reconstruct exact affine including crop origin.
    margin=np.ceil(18/np.asarray(img.GetSpacing())[::-1]).astype(int)
    lo=np.maximum(0,np.min([v[0] for v in bounds],0)-margin)
    hi=np.minimum(full_ct.shape,np.max([v[1] for v in bounds],0)+margin+1)
    sl=tuple(slice(x,y) for x,y in zip(lo,hi))
    ct=full_ct[sl].astype(np.float32); del full_ct
    masks={k:v[sl].copy() for k,v in arrays.items()}; del arrays
    a=affine(img); a[:3,3]=physical(lo,a)
    frame=build_frame(masks,ct,a)
    from coarse_anatomy_prior import (DEFAULT_LIBRARY, build_prior, compare_candidates,
                                     describe, patient_id, sha256)
    descriptor = None
    try:
        descriptor = describe(masks, a, frame, truncated)
        prior = build_prior(descriptor, reference_library or DEFAULT_LIBRARY, key,
                            reference_patient_id or patient_id(key), sha256(data/'ct.nii.gz'), img)
    except ValueError as error:
        # The optional prepositioning step cannot make an otherwise usable
        # image-evidence detector fail, e.g. with a very small nasal label.
        prior = {'schema': 'coarse_anatomy_prior/v1', 'coordinate_system': 'LPS', 'unit': 'mm',
                 'status': 'unavailable', 'reason': str(error), 'landmarks': {},
                 'reviewed_reference_count': 0, 'reference_library_sha256': None}
    landmarks={}
    all_flow=masks['nasal_cavity_left']|masks['nasal_cavity_right']|masks['nasopharynx']
    for side,tag,cn in [('left','L','左'),('right','R','右')]:
        print(f'{key}: {side} nostril rays',flush=True)
        rough = prior['landmarks'].get('nostril_'+tag)
        variants=[nostril_with_prior(masks['nasal_cavity_'+side],all_flow,ct,a,frame,t,rough) for t in PARAMETERS['thresholds_HU']]
        landmarks['nostril_'+tag]=result_record('nostril_'+tag,cn+'鼻孔入口',side+' nostril',variants)
        variants=[interface_candidate(masks['nasal_cavity_'+side]&(ct<t),masks['nasopharynx']&(ct<t),a,frame) for t in PARAMETERS['thresholds_HU']]
        landmarks['posterior_choana_'+tag]=result_record('posterior_choana_'+tag,cn+'后鼻孔候选','posterior choana '+tag,variants)
    variants=[interface_candidate(masks['nasopharynx']&(ct<t),masks['oropharynx']&(ct<t),a,frame) for t in PARAMETERS['thresholds_HU']]
    outlet=result_record('nasopharynx_outlet','鼻咽出口候选','nasopharynx outlet',variants)
    if truncated['soft_palate']:
        outlet['review_reasons'].append('软腭(soft palate)标签触及扫描边界，需检查参考结构是否完整；接触边界本身不证明解剖截断')
        outlet['status']='needs_review' if outlet['point_lps_mm'] else 'unavailable'
    outlet['evidence']['boundary_policy']='nasopharynx/oropharynx semantic interface; not proof of soft-palate free-edge level'
    landmarks['nasopharynx_outlet']=outlet
    soft_points=physical(np.argwhere(masks['soft_palate']),a)
    if outlet['point_lps_mm']:
        outlet['evidence']['nearest_soft_palate_mm']=float(cKDTree(soft_points).query(outlet['point_lps_mm'])[0])
    compare_candidates(prior, landmarks, frame)
    from coarse_anatomy_prior import build_coarse_adjustment
    coarse_adjustment = (build_coarse_adjustment(key, descriptor, prior, landmarks)
                         if descriptor is not None else {
                             'schema': 'coarse_anatomy_adjustment/v1', 'case': key,
                             'status': 'unavailable', 'reason': prior.get('reason', 'descriptor unavailable'),
                             'landmarks': {name: {'coarse': None, 'refined': None, 'delta': None}
                                           for name in ('nostril_L', 'nostril_R',
                                                        'posterior_choana_L', 'posterior_choana_R',
                                                        'nasopharynx_outlet')}})
    for landmark_key, lm in landmarks.items():
        if lm['point_lps_mm'] is not None:
            lm['overlay_png'] = landmark_key + '.png'
    report={'schema':'auto_anatomy_landmarks/v2','case':key,'coordinate_system':'LPS','unit':'mm',
            'status':'proposals_not_clinically_validated','anatomy_frame':frame,'parameters':PARAMETERS,
            'source_ct':str(data/'ct.nii.gz'),'source_geometry':{'affine_4x4_LPS':affine(img).tolist(),
                 'size_xyz':list(img.GetSize()),'spacing_xyz_mm':list(img.GetSpacing())},
            'fov_truncated_labels':truncated,'landmarks':landmarks,'coarse_localization':prior,
            'coarse_adjustment':coarse_adjustment,
            'review_queue':[], 'notes':[
                'Four patients, five scans; the two p3 timepoints are not independent patients.',
                'Threshold stability tests repeatability, not accuracy; no physician truth labels were available.',
                'HU>0=0 after HU intersection is a construction property, not independent validation.',
                'No input masks were changed; no proposed point or plane is automatically confirmed.',
                'Nasal valve (鼻阀), limen nasi (鼻阈), olfactory cleft (嗅裂) and sinus ostia remain unresolved; missing anatomy labels are not guessed.',
                'Outlet and oral exclusion refer to the same boundary; do not count two independent confirmations.']}
    for k,lm in landmarks.items():
        if lm['status']!='proposed':
            report['review_queue'].append({'landmark':k,'priority':'high','reasons':lm['review_reasons']})
    # Persistent content identity for the review UI.
    identity={k:{x:lm.get(x) for x in ['point_lps_mm','normal_lps','status','evidence']} for k,lm in landmarks.items()}
    report['proposal_hash']=hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    for lm in landmarks.values():
        lm['proposal_hash']=report['proposal_hash']
    review={'schema':'anatomy_barrier_review/v2','coordinate_system':'LPS','unit':'mm',
            'generated_by':'auto_anatomy_landmarks','proposal_hash':report['proposal_hash'],
            'planes_lps':{},'openings':{},'sinus_ostia':{},'review_checklist':{},
            'note':'Proposed planes only. Loading this config into the existing barrier tool performs no crop.'}
    for k in ['nostril_L','nostril_R','nasopharynx_outlet']:
        lm=landmarks[k]
        review['planes_lps'][k]={'status':lm['status'] if lm['point_lps_mm'] else 'unknown',
            'point_lps_mm':lm['point_lps_mm'],'normal_lps':lm['normal_lps'],
            'roi_lps_mm':lm.get('roi_lps_mm',{'min':None,'max':None}),'keep_positive':True,
            'localization_checks':lm['consistency_checks'],'source_proposal_hash':report['proposal_hash']}
        review['openings'][k]={'status':'unknown','localization_status':lm['status']}
    review['planes_lps']['oral_exclusion']={'status':'unknown','same_boundary_as':'nasopharynx_outlet'}
    for fname,obj in [('landmarks.json',report),('review_config_proposed.json',review),
                      ('coarse_localization.json',prior),
                      ('coarse_adjustment.json',coarse_adjustment)]:
        (out/fname).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
    markups(report,out/'landmarks.mrk.json')
    plot_review(ct,masks,a,report,out/'review.png')
    return {'case':key,'landmarks':{k:{'status':v['status'],'point_lps_mm':v['point_lps_mm'],
                'review_reasons':v['review_reasons']} for k,v in landmarks.items()},'out':str(out)}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('cases',nargs='*',default=['p0'])
    ap.add_argument('--data-base',default='C:/ts_work'); ap.add_argument('--out-base',default=str(ROOT/'work'/'06_auto_landmarks'))
    from coarse_anatomy_prior import DEFAULT_LIBRARY
    ap.add_argument('--reference-library',default=str(DEFAULT_LIBRARY))
    ap.add_argument('--patient-id', help='Anonymous patient group for a single case')
    args=ap.parse_args(); results=[]
    if args.patient_id and len(args.cases) != 1:
        ap.error('--patient-id requires exactly one case')
    for key in args.cases:
        try: results.append(run_case(key,args.data_base,args.out_base,args.reference_library,args.patient_id))
        except Exception as e:
            results.append({'case':key,'status':'failed','error':str(e)})
            print(f'{key} FAILED: {e}',file=sys.stderr,flush=True)
    Path(args.out_base).mkdir(parents=True,exist_ok=True)
    Path(args.out_base,'batch_summary.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False,indent=2))
    return int(any(r.get('status')=='failed' for r in results))


if __name__=='__main__':
    raise SystemExit(main())
