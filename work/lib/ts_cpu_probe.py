"""Measure a single TS process's true CPU share, without shelling out.

Earlier attempts inferred load from machine-wide idle time and kept landing in
the wrong window (model loading, or a case that finished in 6 s). This reads
each process's CPU time directly through the Win32 API: GetProcessTimes gives
kernel+user time, and the difference over a wall interval, divided by cores,
is that process's share of the machine. No guessing from machine idle.
"""
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

k32 = ctypes.windll.kernel32
TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_SET_INFORMATION = 0x0200
CORES = 24


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [('dwSize', wt.DWORD), ('cntUsage', wt.DWORD),
                ('th32ProcessID', wt.DWORD), ('th32DefaultHeapID', ctypes.POINTER(ctypes.c_ulong)),
                ('th32ModuleID', wt.DWORD), ('cntThreads', wt.DWORD),
                ('th32ParentProcessID', wt.DWORD), ('pcPriClassBase', ctypes.c_long),
                ('dwFlags', wt.DWORD), ('szExeFile', ctypes.c_char * 260)]


def children_of(root_pid):
    """Whole descendant tree, not just direct children.

    TotalSegmentator.exe is a launcher: it starts python.exe, which starts
    another python.exe, which does the actual nnU-Net work. Sampling only the
    direct child measures a process that does no compute, which is how an
    earlier version of this probe reported 0.0% for a run that was plainly
    burning CPU for 100 s."""
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1:
        return []
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
    kids = {}
    ok = k32.Process32First(snap, ctypes.byref(entry))
    while ok:
        kids.setdefault(entry.th32ParentProcessID, []).append(entry.th32ProcessID)
        ok = k32.Process32Next(snap, ctypes.byref(entry))
    k32.CloseHandle(snap)
    out, stack = [], [root_pid]
    while stack:
        for c in kids.get(stack.pop(), []):
            out.append(c)
            stack.append(c)
    return out


def cpu_seconds(pid):
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    c, e, k, u = (wt.FILETIME(), wt.FILETIME(), wt.FILETIME(), wt.FILETIME())
    ok = k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e),
                             ctypes.byref(k), ctypes.byref(u))
    k32.CloseHandle(h)
    if not ok:
        return None
    def ft(v):
        return (v.dwHighDateTime << 32) | v.dwLowDateTime
    return (ft(k) + ft(u)) / 1e7


def tree_cpu(pid):
    total = cpu_seconds(pid) or 0.0
    for c in children_of(pid):
        total += cpu_seconds(c) or 0.0
    return total


def main():
    case, limit = sys.argv[1], sys.argv[2]
    env = dict(os.environ)
    if limit != '0':
        env.update({v: limit for v in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS',
                                       'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS')})
    cmd = ['C:/Users/lenovo/.workbuddy/binaries/python/envs/nasal-cfd/Scripts/TotalSegmentator.exe',
           '-i', f'C:/ts_work/{case}/ct.nii.gz', '-o', f'C:/ts_work/{case}/masks',
           '-ta', 'head_glands_cavities', '-d', 'cpu']
    print(f'case={case}  thread env={limit if limit != "0" else "unbounded"}', flush=True)
    t0 = time.time()
    p = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Affinity on the launcher is inherited by every descendant, which is the
    # only lever that worked: OMP_NUM_THREADS left this process at 35% of the
    # box, identical to unbounded, because nnU-Net sets its own torch threads.
    if len(sys.argv) > 3:
        cores = int(sys.argv[3])
        mask = (1 << cores) - 1
        h = k32.OpenProcess(PROCESS_SET_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION,
                            False, p.pid)
        ok = k32.SetProcessAffinityMask(h, mask) if h else 0
        print(f'affinity: {cores} cores (mask {mask}) -> {bool(ok)}', flush=True)
    peak, samples = 0.0, 0
    while p.poll() is None and time.time() - t0 < 300:
        a = tree_cpu(p.pid)
        time.sleep(6)
        b = tree_cpu(p.pid)
        share = 100.0 * (b - a) / (6.0 * CORES)
        peak = max(peak, share)
        samples += 1
        print(f'  t={time.time()-t0:5.0f}s  cpu_share={share:5.1f}%', flush=True)
    p.wait()
    print(f'RESULT {case} threads={limit if limit != "0" else "none"}: '
          f'peak {peak:.1f}% of {CORES} cores over {samples} samples, '
          f'{time.time()-t0:.0f}s wall', flush=True)


if __name__ == '__main__':
    main()
