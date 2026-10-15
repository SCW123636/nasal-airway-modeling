"""Known-answer real OS mutual exclusion fixture; never performs CPU work."""
import json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(r'D:\项目\鼻腔建模')
sys.path.insert(0,str(ROOT/'work/lib'))
from ct_case_pipeline import execution_lock
base=ROOT/'outputs/T-018/lock_fixture'
base.mkdir(exist_ok=True)
token=str(time.time_ns())
attempt=base/(token+'_attempt.json');acquire=base/(token+'_acquire.json')
child='''import json,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from ct_case_pipeline import execution_lock
Path(sys.argv[3]).write_text(json.dumps({"attempt":time.time()}))
with execution_lock(Path(sys.argv[2])):
 Path(sys.argv[4]).write_text(json.dumps({"acquire":time.time()}))
'''
with execution_lock(base):
    process=subprocess.Popen([sys.executable,'-B','-c',child,str(ROOT/'work/lib'),str(base),str(attempt),str(acquire)],env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
    deadline=time.time()+10
    while not attempt.exists() and time.time()<deadline:time.sleep(.03)
    if not attempt.exists():raise RuntimeError('child did not attempt lock')
    time.sleep(.2)
    blocked=not acquire.exists()
    released_at=time.time()
code=process.wait(timeout=10)
acquired=json.loads(acquire.read_text())['acquire'] if acquire.exists() else None
report={'fixture':'actual execution_lock, two OS processes, isolated output directory','blocked_while_parent_holds_lock':blocked,'release_at':released_at,'child_acquired_at':acquired,'exit_code':code,'passed':blocked and code==0 and acquired>=released_at,'scope':'Verifies shared implementation exclusion, no CFD or workload scheduler run.'}
(ROOT/'outputs/T-018/lock_review.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report));sys.exit(not report['passed'])
