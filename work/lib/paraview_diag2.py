# -*- coding: utf-8 -*-
"""
ParaView 0xC0000142 更深诊断：
  手段 A：读 Windows 应用程序事件日志（最近 10 分钟的 Error 事件）
  手段 B：用 ctypes 手动 LoadLibrary 各个依赖 DLL，定位第一个失败的
  手段 C：检查是否有 apphelp / 兼容性 shim 干扰

手段 B 是最直接的：把 PE 导入表里的 DLL 逐个 LoadLibraryEx 加载，
第一个抛错的即是元凶。
"""
import os, json, ctypes, datetime

BIN = r"D:\项目\鼻腔建模\软件\ParaView 6.2\bin"
OUT = r"C:\nasal_probe"
rep = {}

# ---- B. 逐 DLL 加载测试 ----
IMPORTS = [
    "pqApplicationComponents-pv6.2.dll",
    "Qt6Widgets.dll",
    "pqComponents-pv6.2.dll",
    "pqPython-pv6.2.dll",
    "pqCore-pv6.2.dll",
    "pqWidgets-pv6.2.dll",
    "Qt6Gui.dll",
    "Qt6Core.dll",
    "vtkqttesting-pv6.2.dll",
    "vtkGUISupportQt-pv6.2.dll",
    "vtkRemotingServerManager-pv6.2.dll",
    "vtkRemotingSettings-pv6.2.dll",
    "vtkRemotingCore-pv6.2.dll",
    "vtkPVVTKExtensionsCore-pv6.2.dll",
    "vtkPythonInterpreter-pv6.2.dll",
    "vtkCommonCore-pv6.2.dll",
    "vtksys-pv6.2.dll",
    "MSVCP140.dll",
    "VCRUNTIME140.dll",
    "VCRUNTIME140_1.dll",
    "api-ms-win-crt-heap-l1-1-0.dll",
    "api-ms-win-crt-string-l1-1-0.dll",
    "api-ms-win-crt-runtime-l1-1-0.dll",
    "api-ms-win-crt-locale-l1-1-0.dll",
    "api-ms-win-crt-math-l1-1-0.dll",
    "api-ms-win-crt-stdio-l1-1-0.dll",
]

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
k32.SetDllDirectoryW.restype = ctypes.c_bool
k32.LoadLibraryExW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint32]
k32.LoadLibraryExW.restype = ctypes.c_void_p
k32.GetLastError.restype = ctypes.c_uint32

# 把 bin 加入 DLL 搜索目录（复现 paraview.exe 的行为）
ok = k32.SetDllDirectoryW(BIN)
rep["set_dll_directory"] = bool(ok)

LOAD_WITH_ALTERED_SEARCH_PATH = 0x8
loads = []
for d in IMPORTS:
    p = os.path.join(BIN, d)
    exists = os.path.exists(p)
    if not exists:
        # 试系统路径
        h = k32.LoadLibraryExW(d, None, 0)
    else:
        h = k32.LoadLibraryExW(p, None, LOAD_WITH_ALTERED_SEARCH_PATH)
    err = ctypes.get_last_error() if h == 0 or h is None else 0
    loads.append({
        "dll": d,
        "in_bin": exists,
        "loaded": bool(h),
        "winerr": err,
        "winerr_hex": hex(err & 0xFFFFFFFF) if err else None,
    })
rep["dll_loads"] = loads

rep["first_failure"] = next((x for x in loads if not x["loaded"]), None)
rep["n_failed"] = sum(1 for x in loads if not x["loaded"])

# ---- A. 事件日志 ----
try:
    import subprocess
    ps = (
        "Get-WinEvent -FilterHashtable @{LogName='Application';Level=1,2,3;"
        "StartTime=(Get-Date).AddHours(-3)} -MaxEvents 40 -ErrorAction SilentlyContinue | "
        "Select-Object TimeCreated,Id,ProviderName,Message | ConvertTo-Json -Depth 2"
    )
    p = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, timeout=90)
    rep["eventlog_raw"] = p.stdout.decode("utf-8", "replace")[:6000]
    rep["eventlog_err"] = p.stderr.decode("utf-8", "replace")[:500]
except Exception as e:
    rep["eventlog_err"] = f"EXC:{e}"

with open(os.path.join(OUT, "paraview_diag2.json"), "w", encoding="utf-8") as f:
    json.dump(rep, f, ensure_ascii=False, indent=2)

print("set_dll_directory:", rep["set_dll_directory"])
print("n_failed:", rep["n_failed"])
print("first_failure:", rep["first_failure"])
for x in loads:
    if not x["loaded"]:
        print("  FAIL", x["dll"], x["winerr_hex"])
print("DONE")
