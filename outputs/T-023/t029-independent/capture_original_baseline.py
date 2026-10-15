"""Check the already frozen original b15 files without touching them."""
from pathlib import Path
import datetime as dt
import hashlib
import json
import sys

HERE = Path(__file__).resolve().parent
T023 = HERE.parent


def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main(output):
    frozen = read(T023/'patient_terminal_watch_contract_v2.json')
    review = read(T023/'patient-terminal-failure-review/raw-review.json')
    inputs = {path: sha(path) for path in frozen['input_file_sha256']}
    assert inputs == frozen['input_file_sha256'], 'original controlled input changed'
    export = Path(frozen['job_root'])/'export'/frozen['job_id']
    exports = {rel: sha(export/rel) for rel in review['native_export_sha256_equal']}
    assert exports == review['native_export_sha256_equal'], 'original failed export evidence changed'
    protected = {path: sha(path) for path in review['protected_after_sha256']}
    assert protected == review['protected_after_sha256'], 'original watcher/audit/job changed'
    data = {'schema': 't023_t029_original_baseline/v1', 'at': dt.datetime.now(dt.timezone.utc).isoformat(),
            'script_sha256': sha(__file__), 'original_job': frozen['job_id'],
            'original_input_file_sha256': inputs, 'original_failed_export_sha256': exports,
            'original_watcher_audit_job_sha256': protected,
            'original_source_version_reference': {'backend_commit': frozen['backend_commit'],
                 'viewer_commit': frozen['viewer_commit'], 'archived_source_sha256': frozen['production_and_verifier_sha256'],
                 'note': 'These are the old frozen source identities, not a claim that T029 production workspace is unchanged.'},
            'original_inputs_and_failed_evidence_unchanged': True,
            't029_job_bound': False, 'monitor_started': False, 'patient_numerical_accepted': False}
    output = Path(output).resolve()
    assert output.is_relative_to(HERE)
    with output.open('x', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')
    print(json.dumps({'output': str(output), 'original_input_count': len(inputs), 'original_failed_export_count': len(exports),
                      'protected_count': len(protected), 'all_unchanged': True}, ensure_ascii=False))


if __name__ == '__main__':
    main(sys.argv[1])
