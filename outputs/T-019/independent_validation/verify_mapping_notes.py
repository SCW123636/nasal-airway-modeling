"""Read source configuration as AST; never execute conversion code or print paths."""
import ast
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'资料'/'4例演示ct'
DELIVERY=HERE.parent
NAMES={'case_a':'（患者a）鼻中隔+鼻甲消融+其他','case_b':'（患者b）鼻甲消融','case_medial':'鼻甲内移','case_lateral':'鼻甲外移'}

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def eligible(path):
    return '__MACOSX' not in path.parts and not path.name.startswith('._')

def dcms(root):
    return [p for p in root.rglob('*') if p.is_file() and eligible(p) and p.suffix.lower()=='.dcm']

def main():
    mapping=json.loads((DELIVERY/'candidate_mapping.json').read_text(encoding='utf-8'))
    tree=ast.parse((ROOT/'work'/'lib'/'ts_step1_convert.py').read_text(encoding='utf-8-sig'))
    assignment=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='PATIENTS' for t in n.targets))
    configured={ast.literal_eval(k):ROOT/ast.literal_eval(v.args[1]) for k,v in zip(assignment.value.keys,assignment.value.values)}
    roots={key:next(p for p in SOURCE.rglob('*') if p.is_dir() and eligible(p) and p.name==name) for key,name in NAMES.items()}
    records=[]
    for row in mapping['records']:
        alias=row['current_case']
        if alias=='p0':
            originals=[p for p in dcms(roots[row['source_case']]) if any(part.startswith('ISO_Bone_0.35mm_part') for part in p.parts)]
            current=dcms(ROOT/'work'/'00_dicom'/'bone')
        else:
            series=next(p for p in roots[row['source_case']].rglob('*') if p.is_dir() and eligible(p) and p.name==row['series'])
            originals=dcms(series)
            current=dcms(configured[alias])
        a={p.name:p for p in originals}
        b={p.name:p for p in current}
        shared=sorted(set(a)&set(b))
        samples=[]
        for sample in row['samples']:
            name=shared[sample['shared_filename_sort_index_0based']]
            ha,hb=digest(a[name]),digest(b[name])
            samples.append({'index_0based':sample['shared_filename_sort_index_0based'],'source_sha_matches':ha==sample['source_sha256'],'current_sha_matches':hb==sample['current_sha256'],'equality_matches':(ha==hb)==sample['complete_file_hash_equal'],'files_equal':ha==hb})
        records.append({'current_case':alias,'source_case':row['source_case'],'source_count_matches':len(originals)==row['source_dicom_count'],'current_count_matches':len(current)==row['current_dicom_count'],'shared_filename_count_matches':len(shared)==row['shared_filenames_count'],'configured_series_label_matches':alias=='p0' or configured[alias].name==row['series'],'samples':samples})
    note_records=[]
    for p in SOURCE.rglob('*'):
        if not p.is_file() or not eligible(p) or p.suffix.lower()!='.txt':
            continue
        text=p.read_text(encoding='utf-8-sig')
        note_records.append({'sha256':digest(p),'sha_present_in_mapping':digest(p) in mapping['readme_sha256'],'contains_0_67mm':bool(re.search(r'0\.67\s*mm',text,re.I)),'contains_0_35mm':bool(re.search(r'0\.35\s*mm',text,re.I)),'contains_206_layers':bool(re.search(r'206\s*层',text)),'contains_394_layers':bool(re.search(r'394\s*层',text)),'contains_resampling_term':'重采样' in text,'contains_B_spline':bool(re.search(r'B\s*样条|B[ -]?spline',text,re.I)),'contains_cubic_order_term':bool(re.search(r'三次|cubic|3\s*阶|order\s*[=:]?\s*3',text,re.I))})
    snapshots={name:digest(DELIVERY/name) for name in ('已有处理效果核对.md','inventory.json','previews.json','heterogeneous_frames.json','candidate_mapping.json','audit_reference.py')}
    conclusion=ROOT/'knowledge'/'结论卡'/'20261015-T-019-四例目标参考.md'
    snapshots['knowledge_conclusion']=digest(conclusion)
    result={'schema':'T019_independent_mapping_note_check/v1','checked_local':datetime.now().astimezone().isoformat(),'mapping_checks':records,'note_checks':note_records,'final_delivery_sha256':snapshots,'boundaries':['Raw conversion scripts were parsed as AST and never executed.','Mapping remains candidate-only; sample equality is limited to the sampled files.','Source notes are documentary assertions, not verification of original acquisition resolution.']}
    (HERE/'mapping_note_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))

if __name__=='__main__':
    main()
