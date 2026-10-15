"""Reproduce A/baseline late-window statistics from the preserved actual timelines.

This reads evidence only. It never reads/writes a runtime case or launches a solver.
Existing late-window-trends.json is treated as immutable and compared in full.
"""
import hashlib
import json
import math
from pathlib import Path

OUT = Path(__file__).resolve().parent


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mean(values):
    return sum(values) / len(values)


def slope(xs, ys):
    xmean, ymean = mean(xs), mean(ys)
    return sum((x - xmean) * (y - ymean) for x, y in zip(xs, ys)) / sum(
        (x - xmean) ** 2 for x in xs
    )


def metrics_for(row):
    residuals = row['residuals']
    pressure = [initial for field, initial, final in residuals if field == 'p']
    velocity = [initial for field, initial, final in residuals if field in ('Ux', 'Uy', 'Uz')]
    assert len(pressure) == 3 and len(velocity) == 3, row['time']
    return {
        'continuity_local': row['continuity'][0],
        'Qout_m3_s': row['flow_m3_s']['nasopharynx_outlet'],
        'U_initial_residual_max': max(velocity),
        'p_first_solve_initial_residual': pressure[0],
        'p_last_solve_initial_residual': pressure[-1],
    }


def build():
    # Independent known answers for the statistic used below.
    assert slope([1, 2, 3], [2, 4, 6]) == 2
    assert abs(slope([1, 2, 3], [math.log(math.exp(x)) for x in (1, 2, 3)]) - 1) < 1e-15
    windows = []
    for case, filename in (
        ('original_failed_baseline', 'iteration_timeline.json'),
        ('upwind_bounded_A', 'trial_timeline.json'),
    ):
        timeline = json.loads((OUT / filename).read_text(encoding='utf-8'))
        indexed = {row['time']: row for row in timeline}
        assert len(indexed) == len(timeline), 'duplicate iteration'
        for first, last in ((101, 120), (81, 120)):
            xs = list(range(first, last + 1))
            samples = [metrics_for(indexed[step]) for step in xs]
            statistics = []
            for metric in samples[0]:
                ys = [sample[metric] for sample in samples]
                assert all(math.isfinite(y) for y in ys)
                statistics.append({
                    'metric': metric,
                    'first': ys[0], 'last': ys[-1],
                    'minimum': min(ys), 'maximum': max(ys), 'mean': mean(ys),
                    'ols_slope_per_step': slope(xs, ys),
                    'log_ols_slope_per_step': slope(xs, [math.log(y) for y in ys]) if all(y > 0 for y in ys) else None,
                    'last_to_first_ratio': ys[-1] / ys[0] if ys[0] else None,
                    'first_10_mean': mean(ys[:10]), 'last_10_mean': mean(ys[-10:]),
                    # Equal sample counts cancel; retain the original summation order.
                    'last10_to_first10_mean_ratio': sum(ys[-10:]) / sum(ys[:10]) if sum(ys[:10]) else None,
                })
            windows.append({'case': case, 'steps': [first, last], 'count': len(xs), 'metrics': statistics})
    return {
        'scope': 'descriptive trend of actual same-step samples; not a forecast or proof of cause',
        'windows': windows,
        'interpretation': 'A reaches120 with finite data and End but late continuity/flow increase; no extension to300 recommended; unchanged quality gates reject it',
    }


if __name__ == '__main__':
    calculated = build()
    evidence = OUT / 'late-window-trends.json'
    assert calculated == json.loads(evidence.read_text(encoding='utf-8')), 'existing statistics do not reproduce'
    receipt = {
        'schema': 'nasal_t029_late_window_reproduction/v1',
        'input_sha256': {name: sha256(OUT / name) for name in ('iteration_timeline.json', 'trial_timeline.json')},
        'script_sha256': sha256(Path(__file__)),
        'existing_result_sha256': sha256(evidence),
        'exact_structural_equality': True,
        'known_answers': ['OLS([1,2,3],[2,4,6])=2', 'OLS([1,2,3],ln(exp([1,2,3])))=1 within 1e-15'],
        'windows': [[101, 120], [81, 120]],
        'formula': 'sum((x-mean(x))*(y-mean(y))) / sum((x-mean(x))**2)',
        'pressure_selection': 'first and last of the three p solves are reported separately',
        'scope': 'descriptive statistics; no extrapolation, diagnosis or acceptance threshold change',
    }
    target = OUT / 'late-window-reproduction.json'
    if target.exists():
        assert json.loads(target.read_text(encoding='utf-8')) == receipt, 'prior reproduction receipt differs'
    else:
        target.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
