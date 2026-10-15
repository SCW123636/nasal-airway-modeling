"""Verify final author commit/source matches the independently inspected files."""
from pathlib import Path
import argparse, ast, datetime, hashlib, json, subprocess, sys

ROOT = Path(r'D:\项目\鼻腔建模')
SCOPE = ROOT / 'outputs/T-033'
COMMIT = 'e6874b314b0b7edb05092847cf8a9985c7a06b6c'
SITE = Path(r'C:\Users\lenovo\.workbuddy\binaries\python\envs\nasal-cfd\Lib\site-packages\totalsegmentator')

def digest(data):
    return hashlib.sha256(data).hexdigest()

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--out', required=True); args = parser.parse_args()
    out = Path(args.out).resolve()
    if not out.is_relative_to(SCOPE.resolve()):
        raise ValueError('evidence outside T-033 scope')
    out.mkdir(parents=True, exist_ok=False)
    result = {'created': datetime.datetime.now().astimezone().isoformat(), 'author_commit': COMMIT, 'checks': [], 'snapshots': {}}
    def check(name, actual, expected=True):
        result['checks'].append({'name': name, 'actual': actual, 'expected': expected, 'pass': actual == expected})
    previous = read_json(SCOPE / 'runs/02_independent_raw_audit/independent-audit.json')
    check('direct_array_verification_passed', previous['summary']['failures'], 0)
    for path, expected in previous['source_snapshot'].items():
        check('reviewed_source_still_same_' + path, digest(Path(path).read_bytes()), expected)
    paths = subprocess.check_output(['git', '-c', 'core.quotePath=false', 'ls-tree', '-r', '--name-only', COMMIT, '--', 'outputs/T-032'], cwd=ROOT).decode('utf-8').splitlines()
    for path in paths:
        frozen = subprocess.check_output(['git', 'show', COMMIT + ':' + path], cwd=ROOT)
        actual = (ROOT / path).read_bytes()
        record = {'frozen_sha256': digest(frozen), 'disk_sha256': digest(actual), 'exact_bytes': frozen == actual}
        result['snapshots'][path] = record
        if path.endswith(('.py', '.json', '.jsonl', '.log')):
            check('exact_frozen_bytes_' + path, actual, frozen)
            # Store compact digests rather than binary content in JSON.
            result['checks'][-1]['actual'] = digest(actual)
            result['checks'][-1]['expected'] = digest(frozen)
        else:
            check('frozen_text_' + path, actual.replace(b'\r\n', b'\n'), frozen.replace(b'\r\n', b'\n'))
            result['checks'][-1]['actual'] = digest(actual.replace(b'\r\n', b'\n'))
            result['checks'][-1]['expected'] = digest(frozen.replace(b'\r\n', b'\n'))
    result['snapshots']['author_preview_lower_MPR'] = {'sha256': digest((ROOT / 'outputs/T-032/runs/01_lower_coverage/five_case_lower_mpr.png').read_bytes())}
    result['snapshots']['author_preview_new_old'] = {'sha256': digest((ROOT / 'outputs/T-032/runs/02_p2_no_crop_result/p2_real_no_crop_comparison.png').read_bytes())}
    status = read_json(ROOT / 'outputs/T-032/runs/02_p2_no_crop_result/run_status.json')
    configs = {}
    source = SITE / 'map_tasks_config.py'
    for node in ast.parse(source.read_text(encoding='utf-8-sig')).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ('DEFAULT_CONFIG', 'TASK_CONFIGS'):
                    configs[target.id] = ast.literal_eval(node.value)
    # Actual installed builder filters disallow_fast/commercial/info_msg from
    # standard task updates. Execute only this extracted config helper, never
    # importing or calling any prediction/model code.
    api_source = SITE / 'python_api.py'
    function = next(n for n in ast.parse(api_source.read_text(encoding='utf-8-sig')).body if isinstance(n, ast.FunctionDef) and n.name == 'get_task_config')
    namespace = dict(configs)
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(api_source), 'exec'), namespace)
    installed = namespace['get_task_config']('head_glands_cavities')
    check('installed_task_cfg_matches_run', installed, status['installed_task_config'])
    for key in ('task_id', 'trainer', 'model', 'resample', 'folds'):
        check('effective_task_cfg_' + key, status['inference_parameters'][key], installed[key])
    check('model_config_skull_crop', installed['crop'], ['skull'])
    check('isolated_effective_crop_none', status['inference_parameters']['crop'], None)
    result['snapshots']['installed_config_source'] = {'path': str(source), 'sha256': digest(source.read_bytes())}
    result['snapshots']['installed_config_builder'] = {'path': str(api_source), 'sha256': digest(api_source.read_bytes()), 'line': function.lineno}
    report = (ROOT / 'outputs/T-032/交付与缺口.md').read_text(encoding='utf-8-sig')
    for name, phrase in [('no_nonempty_hypopharynx', '仍未得到下咽'), ('no_absence_claim', '不能仅凭模型空输出证明'),
                         ('no_workbench_surface', '没有可以加入工作台的新下咽表面'), ('class12_not_hypopharynx', '绿色始终是口咽'),
                         ('scope_limited_to_p2', '只限该p2输入与该775权重'), ('CPU_monitor_limit_disclosed', '不作运行期CPU实测证据')]:
        check('report_scope_' + name, phrase in report)
    check('raw_run_identity_unknown', status['symptom_patient_mapping'], 'unknown')
    check('raw_run_CFD_not_admitted', status['cfd_admission'], False)
    result['summary'] = {'checks': len(result['checks']), 'failures': sum(not row['pass'] for row in result['checks'])}
    (out / 'final-freeze-check.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result['summary'], ensure_ascii=False))
    if result['summary']['failures']:
        print(json.dumps([row for row in result['checks'] if not row['pass']], ensure_ascii=False))
        sys.exit(1)

if __name__ == '__main__':
    main()
