"""Reconcile the three T-058 extended-domain cases against known answers.

b15 -> T-054 opening-stage known answers (80.040 / 80.060 / 111.00, cut_info)
b01 -> T-047 opening-stage known answers (80.08 / 80.08 / 148.93)
b02 -> fresh case, no prior answer (records the new baseline)
"""
import json

CASES = {
    'b15': {'nostril_L': 80.040, 'nostril_R': 80.060, 'oropharynx_truncation_outlet': 111.00,
            'src': 'T-054 (opening stage)'},
    'b01': {'nostril_L': 80.08, 'nostril_R': 80.08, 'oropharynx_truncation_outlet': 148.93,
            'src': 'T-047 (opening stage)'},
    'b02': None,
}

for case, known in CASES.items():
    r = json.load(open(f'C:/ts_work/t058_oroext_opening/{case}.json', encoding='utf-8'))
    a = r.get('patch_areas_mm2') or {}
    print(f'=== {case} ===  decision={r.get("decision")}  escalations={r.get("escalations")}')
    print('  areas:', json.dumps(a, ensure_ascii=False))
    if known:
        ok = True
        for k, v in known.items():
            got = a.get(k)
            if got is None or abs(got - v) > 0.005:
                ok = False
                print(f'  MISMATCH {k}: known={v} got={got}')
        print(f'  reconcile vs {known["src"]}: {"BIT-EXACT" if ok else "FAILED"}')
    t = r.get('truncation_outlet')
    if t:
        print('  truncation:', json.dumps(t, ensure_ascii=False))
