"""Start one persistent native Linux reference suite; never touch prior cases."""
from pathlib import Path
import json
import subprocess

output = Path(__file__).resolve().parent
command = ['wsl.exe','-d','Ubuntu-22.04','--','env','OMP_NUM_THREADS=1',
           'OPENBLAS_NUM_THREADS=1','MKL_NUM_THREADS=1','taskset','-c','0','nice','-n','10',
           'python3','/mnt/d/项目/鼻腔建模/work/lib/openfoam_pressure_adapter.py',
           '--work-dir','/home/lenovo2/nasal_t021_split_20261015',
           '--export-dir','/mnt/d/项目/鼻腔建模/outputs/T-021/reference_split_run']
with (output / 'reference_suite_execution.log').open('ab') as log:
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        stdin=subprocess.DEVNULL, close_fds=True)
(output / 'reference_run_launch.json').write_text(json.dumps({'worker_pid':process.pid,'command':command,
    'native_case':'/home/lenovo2/nasal_t021_split_20261015','affinity':'one of twenty-four logical CPUs',
    'entry_load_average':[.53,.14,.05]}, indent=2), encoding='utf-8')
print(process.pid)
