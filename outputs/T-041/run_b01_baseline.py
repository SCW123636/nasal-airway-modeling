import subprocess, sys

WSL = ["wsl.exe", "-d", "Ubuntu-22.04", "--"]
SOLVER = "/mnt/d/项目/鼻腔建模/work/07_cfd_pipeline/solver/run_openfoam_case.py"
CASE = "/home/lenovo2/t041_b01/b01_h1p0"


def wsl(args, timeout=None):
    return subprocess.run(WSL + args, timeout=timeout)


print("--- copy case to WSL native FS ---", flush=True)
print(wsl(["mkdir", "-p", "/home/lenovo2/t041_b01"]).returncode, flush=True)
print(wsl(["rm", "-rf", CASE]).returncode, flush=True)
print(wsl(["cp", "-r", "/mnt/c/ts_work/t041_b01/b01_h1p0", "/home/lenovo2/t041_b01/"]).returncode, flush=True)
print(wsl(["ls", CASE]).stdout.decode("utf-8", "replace") if False else "", flush=True)

print("--- run full chain ---", flush=True)
cmd = WSL + ["env", "WM_PROJECT_DIR=/usr/share/openfoam", "FOAM_ETC=/usr/share/openfoam/etc",
             "WM_PROJECT_VERSION=v1912", "python3", SOLVER, "--case", CASE,
             "--steps", "blockMesh,snappyHexMesh,checkMesh,simpleFoam,foamToVTK"]
r = subprocess.run(cmd)
print("RC", r.returncode, flush=True)
