"""Export exact labelled surface inputs for native OpenFOAM surface checks.

No component selection, repair, volume mesh, solver or medical promotion.
"""
import argparse
from pathlib import Path
import re
import subprocess

import numpy as np

from build_scope_evidence import component_audit, read_surface
from ct_case_pipeline import read_json, sha256, write_json
from partitioned_surface import topology
from surface_to_case import parse_stl_ascii, parse_vtp_regions, write_patch_stl
import vtk
from export_candidate_preview import set_triangle_arrays


def export_surface(source, output, expected_hash, *, labelled=True):
    if sha256(source) != expected_hash:
        raise ValueError('Source surface identity mismatch')
    if output.exists():
        raise FileExistsError('Keep previous preflight evidence')
    poly, points, faces, labels = read_surface(source, labelled=labelled)
    qc, _ = topology(points, faces)
    if labelled:
        solids = parse_vtp_regions(source)
    else:
        solids = {'wall': points[faces].tolist()}
    output.mkdir(parents=True)
    pieces = []
    patch_reports = {}
    for name, triangles in solids.items():
        path = output / (name + '.stl')
        write_patch_stl(path, name, triangles)
        restored = parse_stl_ascii(path)[name]
        np.testing.assert_allclose(restored, np.asarray(triangles) * .001, atol=1e-15, rtol=1e-13)
        pieces.append(path.read_text(encoding='ascii'))
        patch_reports[name] = {'triangles': len(triangles), 'sha256': sha256(path)}
    combined = output / 'combined.stl'
    combined.write_text(''.join(pieces), encoding='ascii')
    restored = parse_stl_ascii(combined)
    if {k: len(v) for k, v in restored.items()} != {k: v['triangles'] for k, v in patch_reports.items()}:
        raise ValueError('Combined STL lost patch identity')
    if sha256(source) != expected_hash:
        raise ValueError('Source changed during export')
    report = {'schema': 'surface_preflight/v1', 'source_sha256': expected_hash,
              'source_unit': 'mm', 'output_unit': 'm', 'coordinate_system': 'LPS',
              'all_components_retained': True, 'surface_qc': qc,
              'component_audit': component_audit(points, faces, labels),
              'patches': patch_reports, 'combined_sha256': sha256(combined),
              'surface_check': 'not_run', 'medical_review': 'pending',
              'volume_mesh_generated': False, 'patient_solver_allowed': False,
              'patient_cfd_results': 0}
    write_json(output / 'manifest.json', report)
    return report


def wsl_path(path):
    path = Path(path).resolve()
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def interpret_surface_check(log, exit_code, expected):
    """A zero exit code is not a surfaceCheck geometry acceptance."""
    def one(pattern, cast=int):
        hits = re.findall(pattern, log, re.MULTILINE)
        return cast(hits[0]) if len(hits) == 1 else None
    intersections = one(r'Surface is self-intersecting at (\d+) locations\.')
    if intersections is None and 'Surface is not self-intersecting' in log:
        intersections = 0
    end = bool(re.search(r'^End\s*$', log, re.MULTILINE))
    triangles = one(r'^Triangles\s*:\s*(\d+) in \d+ region\(s\)')
    regions = {name: one(r'^' + re.escape(name) + r'\s+(\d+)\s*$') for name in expected}
    closed = 'Surface is closed. All edges connected to two faces.' in log
    illegal_free = 'Surface has no illegal triangles.' in log
    complete = (exit_code == 0 and end and intersections is not None
                and triangles == sum(expected.values()) and regions == expected)
    reasons = []
    if not complete:
        reasons.append('Incomplete run or triangle/patch identity mismatch')
    if not closed:
        reasons.append('Closure not demonstrated')
    if not illegal_free:
        reasons.append('Illegal-triangle check not passed')
    if intersections is not None and intersections > 0:
        reasons.append('Native edge-triangle self-intersection hits')
    return {'status': 'fail' if reasons else 'native_checks_pass', 'reasons': reasons,
            'normal_end': end, 'closed': closed, 'illegal_triangle_check_pass': illegal_free,
            'triangles': triangles, 'patch_triangle_counts': regions,
            'edge_triangle_intersection_hits': intersections,
            'unconnected_parts': one(r'^Number of unconnected parts\s*:\s*(\d+)'),
            'minimum_triangle_quality': one(r'^\s*min ([\deE.+-]+) for triangle \d+', float),
            'minimum_edge_m': one(r'^\s*min ([\deE.+-]+) for edge \d+', float),
            'coplanar_overlap_coverage': 'not_exhaustively_checked_by_native_edge_query',
            'meshing_ready': False, 'patient_solver_allowed': False}


def native_check(output, report):
    combined = output / 'combined.stl'
    if sha256(combined) != report['combined_sha256']:
        raise ValueError('Exported surface changed before native check')
    command = ['wsl', '-d', 'Ubuntu-22.04', '--cd', wsl_path(output), '--', 'env',
               'WM_PROJECT_DIR=/usr/share/openfoam', 'FOAM_ETC=/usr/share/openfoam/etc',
               'WM_PROJECT_VERSION=v1912', 'surfaceCheck', '-checkSelfIntersection',
               '-outputThreshold', '1', 'combined.stl']
    process = subprocess.run(command, capture_output=True, timeout=600)
    (output / 'surfaceCheck.log').write_bytes(process.stdout)
    (output / 'surfaceCheck.stderr').write_bytes(process.stderr)
    interpretation = interpret_surface_check(process.stdout.decode('utf-8', errors='replace'),
                                process.returncode, {k: v['triangles'] for k, v in report['patches'].items()})
    report['surface_check'] = {'command': command, 'exit_code': process.returncode,
                               'log_sha256': sha256(output / 'surfaceCheck.log'),
                               'stderr_sha256': sha256(output / 'surfaceCheck.stderr'),
                               'interpretation': interpretation,
                               'generator_sha256': sha256(Path(__file__))}
    diagnostic = output / 'selfInterPoints.obj'
    if diagnostic.is_file():
        report['surface_check']['intersection_points_sha256'] = sha256(diagnostic)
        locations = np.array([[float(n) for n in line.split()[1:]]
                              for line in diagnostic.read_text().splitlines() if line.startswith('v ')])
        if len(locations):
            report['surface_check']['hit_coordinates_m'] = {
                'count': len(locations), 'unique_coordinates': len(np.unique(locations, axis=0)),
                'bounds': {'min': locations.min(axis=0).tolist(), 'max': locations.max(axis=0).tolist()}}
            # Report proximity, not a claimed triangle-pair classification.
            near = {}
            for name in report['patches']:
                restored = parse_stl_ascii(output / (name + '.stl'))[name]
                xyz = np.array(restored)
                poly = vtk.vtkPolyData()
                set_triangle_arrays(poly, xyz.reshape(-1, 3), np.arange(xyz.size // 3).reshape(-1, 3))
                locator = vtk.vtkStaticCellLocator()
                locator.SetDataSet(poly)
                locator.BuildLocator()
                distances = []
                for point in locations:
                    closest = [0., 0., 0.]
                    cell, sub, distance = vtk.reference(0), vtk.reference(0), vtk.reference(0.)
                    locator.FindClosestPoint(point, closest, cell, sub, distance)
                    distances.append(float(distance) ** .5)
                near[name] = {'within_1e-8_m': int(np.count_nonzero(np.array(distances) <= 1e-8)),
                              'minimum_distance_m': float(min(distances))}
            report['surface_check']['hit_point_patch_proximity'] = near
            report['surface_check']['hit_point_proximity_note'] = (
                'OBJ coordinates are rounded by the native tool; these distances '
                'do not identify intersecting triangle pairs or count confirmed defects')
    if sha256(combined) != report['combined_sha256']:
        raise ValueError('Exported surface changed during native check')
    write_json(output / 'manifest.json', report)
    print(str(output.name) + ': ' + interpretation['status'] + '; edge-triangle hits='
          + str(interpretation['edge_triangle_intersection_hits']), flush=True)
    return process.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proposals', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--native-check', action='store_true')
    parser.add_argument('--source-drafts', type=Path, help='Compare the same-case pre-cut source when supplied')
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Use a new preflight output directory')
    args.output.mkdir(parents=True)
    records = []
    for case in ('p2', 'p3t1'):
        proposal_path = args.proposals / case / 'proposal.json'
        proposal_hash = sha256(proposal_path)
        proposal = read_json(proposal_path)
        if proposal['technical_status'] != 'pass':
            raise ValueError('Preflight requires a technically generated surface')
        report = export_surface(args.proposals / case / 'scope_proposal.vtp',
                                args.output / case, proposal['surface_sha256'])
        report['proposal_sha256'] = proposal_hash
        if args.native_check:
            native_check(args.output / case, report)
        if sha256(proposal_path) != proposal_hash:
            raise ValueError('Proposal changed during preflight')
        if sha256(args.proposals / case / 'scope_proposal.vtp') != proposal['surface_sha256']:
            raise ValueError('Proposal surface changed during native check')
        write_json(args.output / case / 'manifest.json', report)
        records.append({'case': case, 'report': report})
        if args.source_drafts:
            draft = read_json(args.source_drafts / case / 'report.json')
            if draft['inputs'] != proposal['inputs']:
                raise ValueError('Pre-cut comparison uses different inputs')
            baseline = export_surface(args.source_drafts / case / 'source_surface.vtp',
                         args.output / (case + '_source'), proposal['source_sha256'], labelled=False)
            if args.native_check:
                native_check(args.output / (case + '_source'), baseline)
            if sha256(args.source_drafts / case / 'source_surface.vtp') != proposal['source_sha256']:
                raise ValueError('Pre-cut source changed during native check')
            records.append({'case': case + '_source', 'report': baseline})
    for entry in records:
        case = entry['case'].removesuffix('_source')
        proposal = read_json(args.proposals / case / 'proposal.json')
        source = (args.source_drafts / case / 'source_surface.vtp' if entry['case'].endswith('_source')
                  else args.proposals / case / 'scope_proposal.vtp')
        if sha256(source) != entry['report']['source_sha256']:
            raise ValueError('An earlier surface changed before summary publication')
        if 'proposal_sha256' in entry['report'] and sha256(args.proposals / case / 'proposal.json') != entry['report']['proposal_sha256']:
            raise ValueError('An earlier proposal changed before summary publication')
    write_json(args.output / 'summary.json', {'cases': records, 'patient_cfd_results': 0})


if __name__ == '__main__':
    main()
