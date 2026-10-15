"""Independent raw phi sums, dimensions and native/export identity."""
import hashlib,json,math,pathlib,re,subprocess,sys
ROOT=pathlib.Path(__file__).resolve().parents[2];OUT=pathlib.Path(__file__).resolve().parent
BASE=ROOT/'outputs/T-021/reference_split_run'
source=json.loads((OUT/'t021_raw_reference_result.json').read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def block(s,n):return re.search(r'\b'+re.escape(n)+r'\s*\{([^{}]*)\}',s,re.S).group(1)
checks=[];extra_hashes={}
for scenario,item in source['scenarios'].items():
    for case in item['evaluations']:
        d=BASE/case['case'];t=str(int(case['time']))
        phifile=d/t/'phi';pfile=d/t/'p';ufile=d/t/'U'
        phi=phifile.read_text();p=pfile.read_text();u=ufile.read_text()
        assert re.search(r'dimensions\s*\[\s*0\s+3\s+-1\s+0\s+0\s+0\s+0\s*\]',phi)
        assert re.search(r'dimensions\s*\[\s*0\s+2\s+-2\s+0\s+0\s+0\s+0\s*\]',p)
        assert re.search(r'dimensions\s*\[\s*0\s+1\s+-1\s+0\s+0\s+0\s+0\s*\]',u)
        boundary=(d/'constant/polyMesh/boundary').read_text()
        values={}
        for name,key,sign in [('inlet_L','q_left_m3_s',-1),('inlet_R','q_right_m3_s',-1),('outlet','q_out_m3_s',1)]:
            b=block(phi,name);m=re.search(r'value\s+nonuniform\s+List<scalar>\s+(\d+)\s*\((.*?)\)\s*;',b,re.S)
            assert m,(case['case'],name)
            numbers=[float(n) for n in m.group(2).split()]
            assert len(numbers)==int(m.group(1))==int(re.search(r'nFaces\s+(\d+)',block(boundary,name)).group(1))
            assert all(x*sign>0 for x in numbers)
            total=math.fsum(numbers);values[name]=total
            assert math.isclose(total,case[key]*sign,rel_tol=1e-10,abs_tol=1e-15)
        for file in [phifile,pfile,ufile,d/'constant/polyMesh/boundary']:
            extra_hashes[file.relative_to(BASE).as_posix()]=sha(file)
        checks.append({'case':case['case'],'final_field_time':t,'signed_patch_phi_sums':values})

# Hash the actual Linux directory; no solver commands or native writes.
hashes=source['artifact_sha256']|extra_hashes
native_code="""import hashlib,json,pathlib,sys
base=pathlib.Path('/home/lenovo2/nasal_t021_split_20261015')
relpaths=json.loads(sys.argv[1])
print(json.dumps({p:hashlib.sha256((base/p).read_bytes()).hexdigest() for p in relpaths},sort_keys=True))
"""
raw=subprocess.check_output(['wsl.exe','-d','Ubuntu-22.04','--','python3','-c',native_code,json.dumps(list(hashes))])
native=json.loads(raw.decode('utf-8-sig'))
assert native==hashes,[(k,v,native.get(k)) for k,v in hashes.items() if native.get(k)!=v]
source_match={}
for scenario in source['scenarios']:
    fp=json.loads((BASE/scenario/'evaluations/input_fingerprint.json').read_text())
    for key,file in [('adapter_sha256',ROOT/'work/lib/openfoam_pressure_adapter.py'),
                     ('solver_sha256',ROOT/'work/07_cfd_pipeline/solver/run_openfoam_case.py'),
                     ('controller_sha256',ROOT/'work/lib/pressure_feedback.py')]:
        source_match[scenario+'/'+key]={'recorded':fp[key],'actual':sha(file),'equal':fp[key]==sha(file)}
        assert fp[key]==sha(file)
out={'passed':True,'raw_phi_cases':checks,'native_artifact_count':len(hashes),
     'native_hashes_match_export':True,'artifact_sha256':hashes,'source_fingerprint_matches':source_match,
     'command':'python outputs/T-023/audit_t021_phi_native.py; internally wsl.exe Ubuntu-22.04 python3 read/hash only'}
target=OUT/'t021_phi_native_result.json';assert not target.exists();target.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'passed':True,'raw_phi_case_count':len(checks),'native_artifact_count':len(hashes),'source_fingerprint_matches':all(x['equal'] for x in source_match.values())}))
