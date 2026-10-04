# -*- coding: utf-8 -*-
"""
ParaView 修复：补 6 个 UCRT API Set 存根到 bin/

背景（已确证）：
  paraview.exe 的 PE 导入表要求 6 个 api-ms-win-crt-*.dll，
  它们不在 bin/ 也不在 System32/，但在 System32/downlevel/ 中存在。
  而 bin/ 里另有一批旧版 api-ms-win-core-*.dll 存根，
  推测是它们干扰了 loader 对 downlevel 的解析 → 0xC0000142。

修复：把这 6 个 DLL 从 downlevel 复制到 bin/（可逆，仅新增文件）

本脚本先做 dry-run 记录，再执行，然后逐个 exe 复测。
"""
import os, json, shutil, subprocess, glob

BIN = r"D:\项目\鼻腔建模\软件\ParaView 6.2\bin"
DL = r"C:\Windows\System32\downlevel"
OUT = r"C:\nasal_probe"

NEED = [
    "api-ms-win-crt-heap-l1-1-0.dll",
    "api-ms-win-crt-string-l1-1-0.dll",
    "api-ms-win-crt-runtime-l1-1-0.dll",
    "api-ms-win-crt-locale-l1-1-0.dll",
    "api-ms-win-crt-math-l1-1-0.dll",
    "api-ms-win-crt-stdio-l1-1-0.dll",
]

rep = {"bin": BIN, "before": [], "copied": [], "after": []}

# ---- 1. 记录修复前状态 ----
for n in NEED:
    src = os.path.join(DL, n)
    dst = os.path.join(BIN, n)
    rep["before"].append({
        "name": n,
        "in_downlevel": os.path.exists(src),
        "already_in_bin": os.path.exists(dst),
        "src_size": os.path.getsize(src) if os.path.exists(src) else None,
    })

# ---- 2. 复制 ----
for n in NEED:
    src = os.path.join(DL, n)
    dst = os.path.join(BIN, n)
    if not os.path.exists(src):
        rep["copied"].append({"name": n, "ok": False, "why": "src missing"})
        continue
    if os.path.exists(dst):
        rep["copied"].append({"name": n, "ok": True, "why": "already exists"})
        continue
    try:
        shutil.copy2(src, dst)
        rep["copied"].append({"name": n, "ok": True, "size": os.path.getsize(dst)})
    except Exception as e:
        rep["copied"].append({"name": n, "ok": False, "why": str(e)})

# ---- 3. 复测 ----
for exe in sorted(glob.glob(os.path.join(BIN, "*.exe"))):
    name = os.path.basename(exe)
    if name in ("uv.exe", "vrpn_print_devices.exe", "vrpn_server.exe"):
        continue
    try:
        p = subprocess.run([exe, "--version"], capture_output=True, timeout=40)
        rep["after"].append({
            "exe": name,
            "returncode": p.returncode,
            "hex": hex(p.returncode & 0xFFFFFFFF),
            "stdout": p.stdout.decode("utf-8", "replace")[:500],
            "stderr": p.stderr.decode("utf-8", "replace")[:500],
        })
    except subprocess.TimeoutExpired:
        rep["after"].append({"exe": name, "returncode": "TIMEOUT"})
    except Exception as e:
        rep["after"].append({"exe": name, "returncode": f"EXC:{e}"})

with open(os.path.join(OUT, "paraview_fix.json"), "w", encoding="utf-8") as f:
    json.dump(rep, f, ensure_ascii=False, indent=2)
print("DONE")
for r in rep["after"]:
    print(r["exe"], r.get("hex"), r.get("stdout", "")[:120].replace("\n", " | "))
