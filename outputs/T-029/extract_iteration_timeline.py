"""Reproduce the failed timeline from frozen raw logs; no solver invocation."""
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
BASE = HERE / 'failed_actual'


def main():
    flows = {}
    for patch in ['nostril_L', 'nostril_R', 'nasopharynx_outlet']:
        path = BASE / 'postProcessing' / ('flow_' + patch) / '0/surfaceFieldValue.dat'
        flows[patch] = {int(float(line.split()[0])): float(line.split()[1])
                        for line in path.read_text().splitlines()
                        if line.strip() and not line.lstrip().startswith('#')}
    text = (BASE / 'log.simpleFoam').read_text(errors='replace')
    records = []
    for block in re.split(r'(?m)^Time = ', text)[1:]:
        time = int(float(block.splitlines()[0]))
        continuity = re.findall(r'time step continuity errors : sum local = ([^,]+), global = ([^,]+), cumulative = ([^\n]+)', block)
        records.append({'time': time,
            'residuals': [[field, float(initial), float(final)] for field, initial, final in
                re.findall(r'Solving for (\w+), Initial residual = ([\deE+.-]+), Final residual = ([\deE+.-]+)', block)],
            'continuity': list(map(float, continuity[0])) if continuity else None,
            'flow_m3_s': {name: values.get(time) for name, values in flows.items()}})
    previous = json.loads((HERE / 'iteration_timeline.json').read_text())
    assert records == previous, 'Frozen raw evidence does not reproduce recorded timeline'
    result = {'schema': 't029_timeline_reproduction/v1', 'steps': len(records),
              'last_complete_monitor_step': max(flows['nostril_L']),
              'last_attempted_solver_step': records[-1]['time'],
              'matches_original_extraction': True,
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'raw_log_sha256': hashlib.sha256((BASE / 'log.simpleFoam').read_bytes()).hexdigest()}
    path = HERE / 'timeline_reproduction.json'
    if path.exists() and json.loads(path.read_text()) != result:
        raise RuntimeError('Prior reproduction evidence differs; keep original')
    if not path.exists():
        path.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
