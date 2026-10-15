# -*- coding: utf-8 -*-
"""
T-050 · 车道空闲监视启动器：等 maxh04（或任何 simpleFoam）退出后自动启动 kOmegaSST 试算。
纪律：绝不双跑——只有 WSL 内 simpleFoam 进程为 0 且 load1<0.8 才启动。
状态每轮写 outputs/T-050/launch_status.json（跨会话可续读）。
"""
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATUS = HERE / "launch_status.json"
CASE = "/home/lenovo2/t050_b15_komsst"
DISTRO = "Ubuntu-22.04"
POLL_S = 60
MAX_HOURS = 12


def wsl(*args, timeout=30):
    r = subprocess.run(["wsl.exe", "-d", DISTRO, "--"] + list(args),
                       capture_output=True, text=True, timeout=timeout,
                       encoding="utf-8", errors="replace")
    return r.stdout.strip()


def solver_running():
    return wsl("pgrep", "-cx", "simpleFoam") not in ("", "0")


def load1():
    try:
        return float(wsl("bash", "-lc", "cat /proc/loadavg").split()[0])
    except (ValueError, IndexError):
        return 99.0


def write(state):
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    STATUS.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")


def main():
    t0 = time.time()
    state = {"phase": "queued", "case": CASE, "waiting_for": "simpleFoam-free lane"}
    write(state)
    while True:
        if time.time() - t0 > MAX_HOURS * 3600:
            write({**state, "phase": "timeout_still_queued"})
            return
        if not solver_running() and load1() < 0.8:
            break
        time.sleep(POLL_S)

    out = wsl("bash", "-lc",
              f"cd {CASE} && nohup simpleFoam > log.simpleFoam 2>&1 & echo $!")
    pid = out.splitlines()[-1] if out else "?"
    state = {"phase": "launched", "pid": pid, "case": CASE,
             "launched_at": datetime.now().isoformat(timespec="seconds")}
    write(state)

    # 轻监护：进程消失或日志出现 End/FATAL 即收尾
    while True:
        time.sleep(120)
        alive = wsl("bash", "-lc", f"kill -0 {pid} 2>/dev/null && echo ALIVE || echo GONE")
        tail = wsl("bash", "-lc", f"tail -5 {CASE}/log.simpleFoam 2>/dev/null | tr -d '\\000'")
        state["alive"] = alive
        state["log_tail"] = tail[-800:]
        if "End" in tail or "FATAL" in tail or "GONE" in alive:
            state["phase"] = "finished" if "End" in tail else (
                "failed" if "FATAL" in tail else "gone_without_end")
            write(state)
            return
        write(state)


if __name__ == "__main__":
    main()
