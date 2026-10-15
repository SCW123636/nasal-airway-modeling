"""Serve project artifacts only on loopback; optional local review-page route."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit
import urllib.request
import webbrowser
import re

from ct_case_pipeline import CaseManager, case_dir
from medical_review import MedicalReviewStore
from cfd_workspace_jobs import SimulationJobs

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'work'/'07_cfd_pipeline'
REVIEW=ROOT/'work'/'06_auto_landmarks'
PROGRESS=ROOT/'work'/'进度总览.html'
METHOD=ROOT/'work'/'08_method_explanation'
BOUNDARY_REVIEW=BASE/'workspace'/'boundary-review'
CASE_ROOT=Path('C:/ts_work/project_cases')
CASE_MANAGER=None
MEDICAL_REVIEW=None
SIMULATION_JOBS=None


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False).encode('utf-8')


def case_asset_path(path):
    parts = path.split('/')
    if len(parts) < 3 or parts[0] != 'case-assets' or not CASE_MANAGER:
        return None
    case = parts[1]
    if not re.fullmatch(r'u_[0-9a-f]{16}', case):
        return None
    root = case_dir(CASE_ROOT, case) / 'public'
    relative = Path(*parts[2:])
    result = (root / relative).resolve()
    return result if result.is_relative_to(root.resolve()) and result.is_file() else None


def boundary_asset_path(path):
    parts = path.split('/')
    if len(parts) != 4 or parts[0] != 'boundary-assets' or not CASE_MANAGER:
        return None
    case, draft, name = parts[1:]
    if not re.fullmatch(r'u_[0-9a-f]{16}', case) or not re.fullmatch(r'd_[0-9a-f]{16}', draft):
        return None
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', name):
        return None
    try:
        return CASE_MANAGER.boundary_preview_asset(case, draft, name)
    except (FileNotFoundError, ValueError, KeyError):
        return None


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self,path):
        path=unquote(urlsplit(path).path)
        if path == '/progress/index.html':
            return str(PROGRESS)
        if path == '/m2_closure/declaration.json':
            return str(ROOT/'outputs'/'M2收口'/'m2_run_declaration.json')
        if path in ('/', '/index.html'):
            return str(BASE/'workspace'/'index.html')
        if path.startswith('/case-assets/'):
            asset = case_asset_path(path.lstrip('/'))
            return str(asset or BASE/'__not_found__')
        if path.startswith('/boundary-assets/'):
            asset = boundary_asset_path(path.lstrip('/'))
            return str(asset or BASE/'__not_found__')
        if path.startswith('/simulation-assets/'):
            parts = path.strip('/').split('/')
            try:
                asset = SIMULATION_JOBS.asset(parts[1], parts[2]) if len(parts) == 3 and SIMULATION_JOBS else None
            except (ValueError, FileNotFoundError, KeyError):
                asset = None
            return str(asset or BASE/'__not_found__')
        if path.startswith('/landmark-review/'):
            base, relative = REVIEW, path[len('/landmark-review/'):]
        elif path.startswith('/boundary-review/'):
            base, relative = BOUNDARY_REVIEW, path[len('/boundary-review/'):]
        elif path.startswith('/method/'):
            base, relative = METHOD, path[len('/method/'):]
        else:
            base, relative = BASE, path.lstrip('/')
        resolved=(base/relative).resolve()
        return str(resolved if resolved.is_relative_to(base.resolve()) else base/'__not_found__')
    def list_directory(self,path):
        self.send_error(404,'Directory browsing is disabled')
        return None
    def end_headers(self):
        self.send_header('Cache-Control','no-store')
        super().end_headers()
    def do_GET(self):
        path = urlsplit(self.path).path
        try:
            if path == '/health.json':
                self.reply({'service': 'nasal-cfd-local-workspace/v1', 'ct_import': True,
                            'simulation_jobs': SIMULATION_JOBS is not None})
            elif path == '/api/simulation/catalog':
                self.reply(SIMULATION_JOBS.catalog())
            elif path == '/api/simulation/jobs':
                self.reply({'jobs': SIMULATION_JOBS.list()})
            elif re.fullmatch(r'/api/simulation/jobs/s_[0-9a-f]{24}', path):
                self.reply(SIMULATION_JOBS.get(path.split('/')[-1]))
            elif path.startswith('/api/simulation/'):
                self.reply({'error': '计算接口不存在'}, 404)
            elif path == '/api/cases':
                self.reply({'cases': CASE_MANAGER.list()})
            elif path == '/api/medical-review/catalog':
                self.reply(MEDICAL_REVIEW.catalog())
            elif re.fullmatch(r'/api/cases/(p[0-3]|p3t1|u_[0-9a-f]{16})/medical-feedback', path):
                case = path.split('/')[3]
                self.reply(MEDICAL_REVIEW.list_feedback(case))
            elif re.fullmatch(r'/api/cases/(p[0-3]|p3t1|u_[0-9a-f]{16})/medical-review-export', path):
                from urllib.parse import parse_qs
                case = path.split('/')[3]
                stage = parse_qs(urlsplit(self.path).query).get('stage', ['landmarks'])[0]
                payload, digest = MEDICAL_REVIEW.export(case, stage)
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Disposition', f'attachment; filename="medical_review_{case}_{stage}.html"')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            elif re.fullmatch(r'/api/cases/u_[0-9a-f]{16}/boundary-preview/d_[0-9a-f]{16}', path):
                preview_match = re.fullmatch(r'/api/cases/(u_[0-9a-f]{16})/boundary-preview/(d_[0-9a-f]{16})', path)
                case, draft = preview_match.groups()
                self.reply(CASE_MANAGER.load_boundary_preview_manifest(case, draft))
            elif re.fullmatch(r'/api/cases/u_[0-9a-f]{16}/boundary-preview', path):
                case = path.split('/')[3]
                data = CASE_MANAGER.get(case)
                preview = data.get('boundary_preview') or {}
                if preview.get('status') == 'generated':
                    manifest = CASE_MANAGER.load_boundary_preview_manifest(case, preview['draft_id'])
                    self.reply(CASE_MANAGER.public(data) | {'boundary_preview_manifest': manifest})
                else:
                    self.reply(CASE_MANAGER.public(data))
            elif path.startswith('/api/cases/'):
                self.reply(CASE_MANAGER.public(CASE_MANAGER.get(path[len('/api/cases/'):])) )
            else:
                super().do_GET()
        except (ValueError, FileNotFoundError, KeyError) as exc:
            self.reply({'error': str(exc)}, 404)

    def reply(self, value, status=200):
        data = json_bytes(value)
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def check_local_write(self):
        hosts = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        if self.headers.get('Host') not in hosts:
            raise ValueError('写入仅允许本机工作台')
        origin = self.headers.get('Origin')
        if origin and origin not in {f'http://{host}' for host in hosts}:
            raise ValueError('写入必须来自本机工作台页面')
        if self.headers.get('Transfer-Encoding'):
            raise ValueError('不支持分块请求编码')
        self.connection.settimeout(120)

    def payload(self):
        if self.headers.get_content_type() != 'application/json':
            raise ValueError('需要 JSON 请求')
        size = int(self.headers.get('Content-Length', '0'))
        if not 0 < size <= 10 * 1024**2:
            raise ValueError('请求大小无效')
        value = json.loads(self.rfile.read(size))
        if not isinstance(value, dict):
            raise ValueError('需要 JSON 对象')
        return value

    def do_POST(self):
        try:
            self.connection.settimeout(30)
            path = urlsplit(self.path).path
            payload = self.payload()
            self.check_local_write()
            if path == '/api/simulation/jobs':
                self.reply(SIMULATION_JOBS.start(payload), 202)
                return
            if path == '/api/medical-review/export':
                archive = MEDICAL_REVIEW.export_batch(payload.get('cases'), payload.get('stages'))
                self.send_response(200)
                self.send_header('Content-Type', 'application/zip')
                self.send_header('Content-Disposition', 'attachment; filename="medical_review_batch.zip"')
                self.send_header('Content-Length', str(len(archive)))
                self.end_headers()
                self.wfile.write(archive)
                return
            if path == '/api/cases':
                self.reply(CASE_MANAGER.create(payload), 201)
                return
            match = re.fullmatch(r'/api/cases/(u_[0-9a-f]{16})/(start|review|regenerate)', path)
            boundary = re.fullmatch(r'/api/cases/(u_[0-9a-f]{16})/(boundary-preview|boundary-review)', path)
            external_feedback = re.fullmatch(r'/api/cases/(p[0-3]|p3t1|u_[0-9a-f]{16})/medical-feedback', path)
            export_feedback = re.fullmatch(r'/api/cases/(p[0-3]|p3t1|u_[0-9a-f]{16})/medical-feedback/(f_[0-9a-f]{24})/decisions', path)
            if external_feedback:
                case = external_feedback[1]
                self.reply(MEDICAL_REVIEW.import_feedback(case, payload), 201)
                return
            if export_feedback:
                case, record_id = export_feedback.groups()
                decisions = MEDICAL_REVIEW.decisions(case, record_id, payload.get('items'))
                self.reply(decisions)
                return
            if boundary:
                case, action = boundary.groups()
                if action == 'boundary-preview':
                    self.reply(CASE_MANAGER.generate_boundary_preview(case, payload), 201)
                else:
                    self.reply(CASE_MANAGER.save_boundary_review(case, payload.get('draft_id'), payload.get('record')))
                return
            if not match:
                self.reply({'error': '接口不存在'}, 404)
                return
            case, action = match.groups()
            if action == 'start':
                self.reply(CASE_MANAGER.start(case, payload.get('series')), 202)
            elif action == 'regenerate':
                self.reply(CASE_MANAGER.regenerate(case), 202)
            else:
                self.reply(CASE_MANAGER.save_review(case, payload))
        except FileNotFoundError as exc:
            self.reply({'error': str(exc)}, 404)
        except (ValueError, TypeError, KeyError) as exc:
            self.reply({'error': str(exc)}, 400)
        except Exception:
            self.reply({'error': '本机处理出错，请检查服务日志'}, 500)

    def do_PUT(self):
        try:
            self.check_local_write()
            mask = re.fullmatch(r'/api/cases/(u_[0-9a-f]{16})/boundary-mask', urlsplit(self.path).path)
            if mask:
                if self.headers.get_content_type() != 'application/octet-stream':
                    raise ValueError('鼻窦掩膜必须使用二进制请求')
                length = int(self.headers.get('Content-Length', '0'))
                self.reply(CASE_MANAGER.upload_boundary_mask(mask[1], self.rfile, length))
                return
            match = re.fullmatch(r'/api/cases/(u_[0-9a-f]{16})/files/(\d+)', urlsplit(self.path).path)
            if not match or self.headers.get_content_type() != 'application/octet-stream':
                raise ValueError('上传接口或文件类型无效')
            length = int(self.headers.get('Content-Length', '0'))
            self.reply(CASE_MANAGER.upload(match[1], int(match[2]), self.rfile, length))
        except FileNotFoundError as exc:
            self.reply({'error': str(exc)}, 404)
        except (ValueError, TypeError) as exc:
            self.reply({'error': str(exc)}, 400)
        except Exception:
            self.reply({'error': '文件上传中断，可重试'}, 500)

    def do_DELETE(self):
        try:
            self.check_local_write()
            match = re.fullmatch(r'/api/cases/(u_[0-9a-f]{16})', urlsplit(self.path).path)
            if not match:
                self.reply({'error': '接口不存在'}, 404)
                return
            self.reply(CASE_MANAGER.delete(match[1]))
        except FileNotFoundError as exc:
            self.reply({'error': str(exc)}, 404)
        except (ValueError, TypeError) as exc:
            self.reply({'error': str(exc)}, 400)
        except Exception:
            self.reply({'error': '本机删除出错，请稍后重试'}, 500)


def main():
    global CASE_MANAGER, CASE_ROOT, MEDICAL_REVIEW, SIMULATION_JOBS
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8768)
    parser.add_argument('--open',action='store_true')
    parser.add_argument('--case-root',type=Path,default=CASE_ROOT,help='Private ASCII directory for uploaded CT cases')
    args=parser.parse_args();url=f'http://127.0.0.1:{args.port}/workspace/index.html'
    try:
        server=ThreadingHTTPServer(('127.0.0.1',args.port),partial(Handler,directory=str(BASE)))
    except OSError:
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{args.port}/health.json',timeout=2) as response:
                own=json.load(response).get('service')=='nasal-cfd-local-workspace/v1'
        except Exception:
            own=False
        if not own:
            raise RuntimeError('Port is occupied by another service; choose another --port')
        print('Workspace is already running: '+url,flush=True)
        if args.open:webbrowser.open(url)
        return
    CASE_ROOT=args.case_root.resolve()
    CASE_MANAGER=CaseManager(CASE_ROOT)
    MEDICAL_REVIEW=MedicalReviewStore(CASE_MANAGER, REVIEW)
    SIMULATION_JOBS=SimulationJobs(CASE_MANAGER, REVIEW)
    print('Local workspace: '+url,flush=True)
    if args.open:webbrowser.open(url)
    server.serve_forever()


if __name__=='__main__':main()
