# -*- coding: utf-8 -*-
"""查已装 VC++ Redist + 再次确认缺失的 API set 到底是什么"""
import os, json, glob

OUT = r"C:\nasal_probe"
rep = {}

# ---- 1. 注册表查 VC++ Redist ----
try:
    import winreg
    found = []
    for hive, path in [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]:
        try:
            k = winreg.OpenKey(hive, path)
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(k, i)
                    i += 1
                    sk = winreg.OpenKey(k, sub)
                    try:
                        name = winreg.QueryValueEx(sk, "DisplayName")[0]
                        ver = winreg.QueryValueEx(sk, "DisplayVersion")[0]
                        if "Visual C++" in name or "C++" in name:
                            found.append({"name": name, "version": ver})
                    except FileNotFoundError:
                        pass
                    winreg.CloseKey(sk)
                except OSError:
                    break
            winreg.CloseKey(k)
        except FileNotFoundError:
            pass
    rep["vcpp_redist"] = found
except Exception as e:
    rep["vcpp_redist"] = f"ERR:{e}"

# ---- 2. 系统里 api-ms-win-* 的完整分布 ----
dist = {}
for d in [r"C:\Windows\System32", r"C:\Windows\System32\downlevel",
          r"C:\Windows\SysWOW64", r"C:\Windows\SysWOW64\downlevel"]:
    if os.path.isdir(d):
        files = [f for f in os.listdir(d) if f.lower().startswith("api-ms-win-")]
        dist[d] = {"n": len(files), "sample": sorted(files)[:8]}
    else:
        dist[d] = {"n": 0, "exists": False}
rep["apiset_distribution"] = dist

# ---- 3. 那 3 个缺失的 API set，Windows 上真正的实现 DLL 是什么 ----
# 查 ApiSetSchema 太复杂；直接用已知映射：
APISET_HINT = {
    "api-ms-win-shcore-scaling-l1-1-1.dll": "shcore.dll",
    "api-ms-win-core-winrt-string-l1-1-0.dll": "api-ms-win-core-winrt-string → combase/WinTypes",
    "api-ms-win-core-winrt-l1-1-0.dll": "combase.dll (WinRT core)",
}
check = {}
for k, hint in APISET_HINT.items():
    real = hint.split()[0]
    p = os.path.join(r"C:\Windows\System32", real)
    check[k] = {"real_dll": real, "exists": os.path.exists(p)}
# combase
check["combase.dll"] = {"exists": os.path.exists(r"C:\Windows\System32\combase.dll")}
check["shcore.dll"] = {"exists": os.path.exists(r"C:\Windows\System32\shcore.dll")}
rep["apisethint_check"] = check

# ---- 4. 再确认 downlevel 里有没有这些 ----
dl = r"C:\Windows\System32\downlevel"
dlfiles = os.listdir(dl) if os.path.isdir(dl) else []
rep["downlevel_all"] = sorted(dlfiles)
rep["downlevel_shcore_winrt"] = [f for f in dlfiles
                                 if "shcore" in f.lower() or "winrt" in f.lower()]

with open(os.path.join(OUT, "sysdiag.json"), "w", encoding="utf-8") as f:
    json.dump(rep, f, ensure_ascii=False, indent=2)

print("VC++ Redist:", json.dumps(rep["vcpp_redist"], ensure_ascii=False))
print("api-ms dist:", json.dumps(rep["apiset_distribution"], ensure_ascii=False))
print("apisethint:", json.dumps(check, ensure_ascii=False))
print("downlevel shcore/winrt:", rep["downlevel_shcore_winrt"])
print("DONE")
