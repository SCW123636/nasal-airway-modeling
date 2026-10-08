"""Publish offline evidence for existing scope proposals without promoting gates."""
import argparse
import base64
from collections import Counter
import html
import json
from pathlib import Path
import shutil
import tempfile
import threading
from types import SimpleNamespace
import zipfile

import numpy as np
from PIL import Image
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
import vtk
from vtk.util.numpy_support import numpy_to_vtk, vtk_to_numpy

from boundary_preview import VIEWS, plane_basis, render_panel, slice_grid
from build_reviewed_surface_drafts import candidate_inputs, load_adopted
from ct_case_pipeline import read_json, sha256, write_json
from export_candidate_preview import read_image_local, triangle_arrays
from medical_review import MedicalReviewStore
from partitioned_surface import clip_and_cap, topology

OPENINGS = ('nostril_L', 'nostril_R', 'nasopharynx_outlet')
COLORS = {'wall': (180, 193, 199), 'nostril_L': (45, 211, 129),
          'nostril_R': (77, 165, 255), 'nasopharynx_outlet': (255, 197, 68)}


def edge_components(faces):
    """Separate triangle regions by shared edges, including isolated triangles."""
    edges = np.sort(np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]],
                                    faces[:, [2, 0]])), axis=1)
    _, inverse, counts = np.unique(edges, axis=0, return_inverse=True, return_counts=True)
    if np.any(counts > 2):
        raise ValueError('Component audit requires manifold edges')
    order = np.argsort(inverse, kind='stable')
    starts = np.r_[0, np.cumsum(counts)[:-1]][counts == 2]
    face_ids = np.tile(np.arange(len(faces)), 3)[order]
    a, b = face_ids[starts], face_ids[starts + 1]
    graph = coo_matrix((np.ones(len(a)), (a, b)), shape=(len(faces), len(faces))).tocsr()
    return connected_components(graph, directed=False)


def component_audit(points, faces, patches):
    count, components = edge_components(faces)
    records = []
    for index in range(count):
        selected = faces[components == index]
        vertices = points[np.unique(selected)]
        reference = vertices.mean(axis=0)
        xyz = points[selected] - reference
        volume = float(np.einsum('ij,ij->i', xyz[:, 0],
                                np.cross(xyz[:, 1], xyz[:, 2])).sum() / 6)
        records.append({'triangles': len(selected), 'signed_volume_mm3': volume,
                        'patch_triangle_counts': dict(Counter(patches[components == index].tolist())),
                        'bounds_lps_mm': {'min': vertices.min(axis=0).tolist(),
                                          'max': vertices.max(axis=0).tolist()}})
    records.sort(key=lambda value: value['triangles'], reverse=True)
    patch_regions = {}
    for name in OPENINGS:
        chosen = faces[patches == name]
        patch_regions[name] = edge_components(chosen)[0] if len(chosen) else 0
    common = [i for i, entry in enumerate(records)
              if all(entry['patch_triangle_counts'].get(name, 0) for name in OPENINGS)]
    return {'connectivity': 'shared triangle edges', 'surface_components': count,
            'components': records, 'patch_connected_regions': patch_regions,
            'components_containing_all_three_patches': common,
            'self_intersections': 'not_checked', 'anatomical_scope': 'pending',
            'patient_solver_allowed': False}


def read_surface(path, *, labelled=False):
    reader = vtk.vtkXMLPolyDataReader()
    reader.SetFileName(str(path))
    reader.Update()
    poly = vtk.vtkPolyData()
    poly.DeepCopy(reader.GetOutput())
    points, faces = triangle_arrays(poly)
    labels = np.full(len(faces), 'wall', dtype=object)
    if labelled:
        values = poly.GetCellData().GetAbstractArray('boundary_patch')
        if values is None or values.GetNumberOfValues() != len(faces):
            raise ValueError('Missing surface patch labels')
        labels = np.array([values.GetValue(i) for i in range(len(faces))], dtype=object)
        if set(labels) != set(COLORS):
            raise ValueError('Expected wall and all three opening labels')
    return poly, points, faces, labels


def surface_image(poly, labels, path, direction, up):
    colors = np.array([COLORS[name] for name in labels], dtype=np.uint8)
    data = numpy_to_vtk(colors, deep=True, array_type=vtk.VTK_UNSIGNED_CHAR)
    data.SetName('display_patch_color')
    poly.GetCellData().SetScalars(data)
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(poly)
    mapper.SetScalarModeToUseCellData()
    mapper.SetColorModeToDirectScalars()
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetInterpolationToFlat()
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(.965, .975, .98)
    renderer.AddActor(actor)
    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(720, 720)
    window.SetMultiSamples(0)
    window.AddRenderer(renderer)
    center = np.array(poly.GetCenter())
    camera = renderer.GetActiveCamera()
    camera.SetFocalPoint(*center)
    camera.SetPosition(*(center + np.asarray(direction) * 150))
    camera.SetViewUp(*up)
    camera.ParallelProjectionOn()
    renderer.ResetCamera()
    renderer.ResetCameraClippingRange()
    try:
        window.Render()
        capture = vtk.vtkWindowToImageFilter()
        capture.SetInput(window)
        capture.SetInputBufferTypeToRGB()
        capture.ReadFrontBufferOff()
        capture.Update()
        values = vtk_to_numpy(capture.GetOutput().GetPointData().GetScalars()).reshape(720, 720, 3)
        if np.count_nonzero(np.ptp(values, axis=(0, 1)) > 10) < 2:
            raise ValueError('Blank surface render')
        Image.fromarray(values[::-1]).save(path)
    finally:
        window.Finalize()
    return {'camera_position_lps_mm': list(camera.GetPosition()),
            'camera_focus_lps_mm': list(camera.GetFocalPoint()),
            'camera_up_lps': list(camera.GetViewUp()), 'parallel_projection': True,
            'surface_decimated': False}


def embedded_image(path):
    return 'data:image/png;base64,' + base64.b64encode(path.read_bytes()).decode('ascii')


def evidence_html(records, root):
    esc = html.escape
    sections = []
    for record in records:
        case = record['case']
        status = '技术通过' if record['technical_status'] == 'pass' else '技术失败'
        audit = record['surface_audit']
        facts = (f'表面连通分量：{audit["surface_components"]}；'
                 f'含全部三端标签的分量数：{len(audit["components_containing_all_three_patches"])}。')
        images = []
        for output in record['images']:
            images.append('<figure><img loading="lazy" src="' + embedded_image(root / output['path'])
                          + '" alt="' + esc(output['title']) + '"><figcaption>'
                          + esc(output['title']) + '</figcaption></figure>')
        sections.append(f'<section id="{case}"><h2>{case} · {status}</h2>'
                        f'<p>{esc(record.get("reason", "三端联合裁切和封盖通过拓扑检查"))}</p>'
                        f'<p>{esc(facts)}</p><p>三端颜色：左鼻孔绿色、右鼻孔蓝色、鼻咽出口黄色；壁面灰色。</p>'
                        '<details><summary>连通分量与冲突详情</summary><pre>'
                        + esc(json.dumps({'audit': audit,
                                  'failure': record.get('failure_details')}, ensure_ascii=False, indent=2))
                        + '</pre></details><div class="images">' + ''.join(images) + '</div></section>')
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
            'img-src data:; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">'
            '<title>五例边界范围证据</title><style>'
            '*{box-sizing:border-box;letter-spacing:0}body{margin:0;background:#f5f7f8;color:#243036;'
            'font:14px/1.65 system-ui,"Microsoft YaHei",sans-serif}header,section{padding:20px max(16px,calc((100% - 1400px)/2));'
            'border-bottom:1px solid #ccd4d8}header{background:white}h1{font-size:24px}h2{font-size:20px}'
            'nav{display:flex;gap:24px;flex-wrap:wrap}a{color:#226858}.images{display:grid;'
            'grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}figure{margin:12px 0;min-width:0}'
            'img{display:block;width:100%;height:auto;border:1px solid #ccd4d8}figcaption{font-size:13px}'
            'pre{font:12px/1.6 Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere}'
            'details{margin:12px 0}summary{cursor:pointer}p{overflow-wrap:anywhere}'
            '@media(max-width:750px){.images{grid-template-columns:1fr}}</style>'
            '<header><h1>五例边界范围证据</h1><p>阶段：范围提议；医学审核待记录；患者求解锁定。</p>'
            '<p>切片青色为候选空气域，彩色线为切平面，彩色空气域为范围内拟删除侧。'
            '三维失败病例展示原始表面，通过病例展示范围提议表面。</p>'
            '<p>待核对：三端保留范围、额外轮廓与连通分量、口腔排除、鼻窦策略及最终表面。'
            '口腔/鼻窦排除掩膜和自相交检查证据尚未提供。</p><nav>'
            + ''.join(f'<a href="#{r["case"]}">{r["case"]}</a>' for r in records)
            + '</nav></header>' + ''.join(sections) + '</html>')


def build_case(store, case, drafts, proposals, output):
    work = Path(__file__).resolve().parents[1]
    config, config_path = load_adopted(store, case)
    _, mask_path, ct_path, inputs = candidate_inputs(case, work / '05_ts_seg', config, config_path)
    previous = read_json(drafts / case / 'report.json')
    proposal_path = proposals / case / 'proposal.json'
    proposal = read_json(proposal_path)
    proposal_hash = sha256(proposal_path)
    source_path = drafts / case / 'source_surface.vtp'
    if (inputs != previous['inputs'] or inputs != proposal['inputs']
            or sha256(source_path) != previous['artifacts']['source_surface.vtp']
            or sha256(source_path) != proposal['source_sha256']):
        raise ValueError('Draft, proposal or current inputs differ')
    for name in OPENINGS:
        original, proposed = config['planes_lps'][name], proposal['controls'][name]
        if any(original[key] != proposed[key] for key in ('point_lps_mm', 'normal_lps', 'keep_positive')):
            raise ValueError('Proposal changed reviewed plane')
    surface_path = (proposals / case / 'scope_proposal.vtp'
                    if proposal['technical_status'] == 'pass' else source_path)
    expected_hash = (proposal['surface_sha256'] if proposal['technical_status'] == 'pass'
                     else proposal['source_sha256'])
    if sha256(surface_path) != expected_hash:
        raise ValueError('Proposal surface changed')
    poly, points, faces, labels = read_surface(surface_path, labelled=proposal['technical_status'] == 'pass')
    qc, _ = topology(points, faces)
    if proposal['technical_status'] == 'pass' and qc != proposal['surface_qc']['technical_qc']:
        raise ValueError('Saved surface differs from recorded topology')
    output.mkdir()
    report = {'case': case, 'schema': 'scope_evidence_case/v1', 'inputs': inputs,
              'source_surface_sha256': proposal['source_sha256'],
              'source_draft_report_sha256': sha256(drafts / case / 'report.json'),
              'proposal_sha256': proposal_hash, 'surface_sha256': expected_hash,
              'surface_kind': 'proposal' if proposal['technical_status'] == 'pass' else 'source',
              'technical_status': proposal['technical_status'], 'surface_qc': qc,
              'surface_audit': component_audit(points, faces, labels), 'images': [],
              'scope_review': 'pending', 'oral_exclusion_review': 'pending',
              'sinus_policy_review': 'pending', 'final_geometry_review': 'pending',
              'patient_solver_allowed': False, 'patient_cfd_results': 0}
    if proposal['technical_status'] == 'fail':
        report['reason'] = proposal['reason']
        report['failure_details'] = proposal.get('failure_details')
        if report['failure_details'] is None:
            try:
                clip_and_cap(points, faces, proposal['controls'])
            except ValueError as exc:
                if str(exc) != proposal['reason']:
                    raise ValueError('Failure no longer reproduces') from exc
                report['failure_details'] = getattr(exc, 'details', None)
            else:
                raise ValueError('Recorded failure unexpectedly passes')
    ct, mask = read_image_local(ct_path), read_image_local(mask_path)
    def add_image(path, title, metadata):
        report['images'].append({'path': f'{case}/{path.name}', 'sha256': sha256(path),
                                 'title': title, 'metadata': metadata})
    for name in OPENINGS:
        original, proposed = config['planes_lps'][name], proposal['controls'][name]
        field = min(150., max(40., float(np.max(np.array(proposed['roi_lps_mm']['max'])
                       - proposed['roi_lps_mm']['min'])) + 15))
        axes = dict(VIEWS) | {'normal': plane_basis(original['normal_lps'])}
        for view, basis in axes.items():
            grid = slice_grid(original['point_lps_mm'], *basis, pixels=513, field_mm=field)
            panels, metas = [], []
            for label, control in (('Original ROI', original), ('Proposed ROI', proposed)):
                panel, meta = render_panel(ct, mask, None, grid, {name: control},
                                          f'{case} / {name} / {view} / {label}')
                panels.append(panel)
                metas.append(meta | {'control': control})
            image = Image.new('RGB', (panels[0].width * 2, panels[0].height))
            image.paste(panels[0], (0, 0))
            image.paste(panels[1], (panels[0].width, 0))
            path = output / f'{name}_{view}.png'
            image.save(path)
            add_image(path, f'{name} / {view} · 左：原范围；右：提议范围', {'panels': metas})
    failure = report.get('failure_details')
    if failure:
        center = (np.array(failure['bounds_lps_mm']['min']) + failure['bounds_lps_mm']['max']) / 2
        for view, basis in VIEWS.items():
            grid = slice_grid(center, *basis, pixels=513, field_mm=40)
            panel, meta = render_panel(ct, mask, None, grid, proposal['controls'],
                                      f'{case} / conflict bounds center / {view}')
            path = output / f'conflict_{view}.png'
            panel.save(path)
            add_image(path, f'冲突包围盒中心 / {view}', meta)
    for title, direction, up in [('front', (0, -1, 0), (0, 0, 1)),
                                  ('left', (1, 0, 0), (0, 0, 1)),
                                  ('inferior', (0, 0, -1), (0, 1, 0))]:
        path = output / f'surface_{title}.png'
        meta = surface_image(poly, labels, path, direction, up)
        add_image(path, f'表面 / {title} / {report["surface_kind"]}', meta)
    if (sha256(source_path) != proposal['source_sha256'] or sha256(surface_path) != expected_hash
            or sha256(proposal_path) != proposal_hash
            or inputs != candidate_inputs(case, work / '05_ts_seg', config, config_path)[3]):
        raise ValueError('Inputs changed while rendering')
    load_adopted(store, case)
    write_json(output / 'manifest.json', report)
    return report


def build_bundle(drafts, proposals, output, case_root):
    if output.exists():
        raise FileExistsError('Retain existing evidence and choose a new output directory')
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.scope_evidence_', dir=output.parent))
    try:
        # Existing-case evidence only needs storage paths; do not run recovery
        # logic that could update unrelated uploaded-case workflow states.
        manager = SimpleNamespace(root=case_root, lock=threading.RLock())
        store = MedicalReviewStore(manager, Path(__file__).resolve().parents[1] / '06_auto_landmarks')
        records = []
        for case in ('p0', 'p1', 'p2', 'p3', 'p3t1'):
            record = build_case(store, case, drafts, proposals, stage / case)
            records.append(record)
            print(f'{case}: {record["surface_audit"]["surface_components"]} components; '
                  f'{len(record["images"])} images', flush=True)
        (stage / 'index.html').write_text(evidence_html(records, stage), encoding='utf-8')
        # Recheck all earlier cases before publishing the five-case package.
        for record in records:
            case = record['case']
            config, config_path = load_adopted(store, case)
            if (record['inputs'] != candidate_inputs(case, Path(__file__).resolve().parents[1]
                                  / '05_ts_seg', config, config_path)[3]
                    or sha256(proposals / case / 'proposal.json') != record['proposal_sha256']):
                raise ValueError('An earlier case changed before bundle publication')
            surface_path = (proposals / case / 'scope_proposal.vtp' if record['surface_kind'] == 'proposal'
                            else drafts / case / 'source_surface.vtp')
            if sha256(surface_path) != record['surface_sha256']:
                raise ValueError('An earlier surface changed before bundle publication')
            source = drafts / case / 'source_surface.vtp'
            if (sha256(source) != record['source_surface_sha256']
                    or sha256(drafts / case / 'report.json') != record['source_draft_report_sha256']):
                raise ValueError('An earlier source surface changed before publication')
            for entry in record['images']:
                if sha256(stage / entry['path']) != entry['sha256']:
                    raise ValueError('Rendered evidence changed before publication')
        lib = Path(__file__).resolve().parent
        summary = {'schema': 'scope_evidence_bundle/v1', 'cases': records,
                   'html_sha256': sha256(stage / 'index.html'), 'patient_cfd_results': 0,
                   'generator_sha256': {name: sha256(lib / name) for name in
                                        ('build_scope_evidence.py', 'partitioned_surface.py',
                                         'boundary_preview.py', 'export_candidate_preview.py')},
                   'runtime': {'vtk': vtk.vtkVersion.GetVTKVersion(), 'numpy': np.__version__}}
        write_json(stage / 'summary.json', summary)
        files = sorted(path for path in stage.rglob('*') if path.is_file())
        with zipfile.ZipFile(stage / 'evidence.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                archive.write(path, path.relative_to(stage).as_posix())
        stage.rename(output)
        return summary
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-drafts', type=Path, required=True)
    parser.add_argument('--proposals', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--case-root', type=Path, default=Path('C:/ts_work/project_cases'))
    args = parser.parse_args()
    build_bundle(args.source_drafts, args.proposals, args.output, args.case_root)


if __name__ == '__main__':
    main()
