# -*- coding: utf-8 -*-
"""
决定性测试：qwindows.dll (Qt Windows platform plugin) 能否加载
  若不能 → 根因锁定在 Qt 平台插件层
  同时解析其导入表，列出缺失依赖
  并测试 Qt6 核心模块的加载顺序，定位第一个 DllMain 失败点
"""
import os, json, ctypes, struct

BIN = r"D:\项目\鼻腔建模\软件\ParaView 6.2\bin"
SYS32 = r"C:\Windows\System32"
DL = r"C:\Windows\System32\downlevel"
OUT = r"C:\nasal_probe"
rep = {}

DIRS = [BIN, SYS32, DL]

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
k32.SetDllDirectoryW.restype = ctypes.c_bool
k32.LoadLibraryExW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint32]
k32.LoadLibraryExW.restype = ctypes.c_void_p

k32.SetDllDirectoryW(BIN)
R = 0x8  # LOAD_WITH_ALTERED_SEARCH_PATH


def try_load(p):
    h = k32.LoadLibraryExW(p, None, R)
    err = 0 if h else ctypes.get_last_error()
    return bool(h), err


# 1. 平台插件
qw = os.path.join(BIN, "platforms", "qwindows.dll")
rep["qwindows_exists"] = os.path.exists(qw)
if os.path.exists(qw):
    ok, err = try_load(qw)
    rep["qwindows_load"] = {"ok": ok, "err": err, "hex": hex(err & 0xFFFFFFFF)}

    # 解析其导入
    def pe_imports(path):
        try:
            with open(path, "rb") as f:
                data = f.read()
            if data[:2] != b"MZ":
                return ["NOT_PE"]
            e = struct.unpack_from("<I", data, 0x3C)[0]
            if data[e:e + 4] != b"PE\0\0":
                return ["NO_SIG"]
            coff = e + 4
            nsec = struct.unpack_from("<H", data, coff + 2)[0]
            optsz = struct.unpack_from("<H", data, coff + 16)[0]
            optoff = coff + 20
            magic = struct.unpack_from("<H", data, optoff)[0]
            dd = optoff + (112 if magic == 0x20B else 96)
            imp_rva, _ = struct.unpack_from("<II", data, dd + 8)
            secoff = optoff + optsz
            secs = []
            for i in range(nsec):
                b = secoff + i * 40
                secs.append((struct.unpack_from("<I", data, b + 12)[0],
                             struct.unpack_from("<I", data, b + 16)[0],
                             struct.unpack_from("<I", data, b + 20)[0]))

            def r2o(rva):
                for va, sz, ptr in secs:
                    if va <= rva < va + sz:
                        return ptr + (rva - va)
                return None
            if imp_rva == 0:
                return []
            off = r2o(imp_rva)
            names = []
            while off:
                ent = data[off:off + 20]
                if len(ent) < 20:
                    break
                _, _, _, nrva, ft = struct.unpack("<IIIII", ent)
                if nrva == 0 and ft == 0:
                    break
                no = r2o(nrva)
                if no is None:
                    break
                end = data.index(b"\0", no)
                names.append(data[no:end].decode("ascii", "replace"))
                off += 20
            return names
        except Exception as ex:
            return [f"ERR:{ex}"]

    qw_imports = pe_imports(qw)
    rep["qwindows_imports"] = qw_imports
    rep["qwindows_missing"] = []
    for d in qw_imports:
        if d.startswith(("ERR", "NOT_PE", "NO_SIG")):
            continue
        found = any(os.path.exists(os.path.join(x, d)) for x in DIRS)
        if not found:
            rep["qwindows_missing"].append(d)

# 2. 按依赖顺序测 Qt6 模块
ORDER = ["Qt6Core.dll", "Qt6Network.dll", "Qt6Gui.dll", "Qt6Widgets.dll",
         "Qt6OpenGL.dll", "Qt6OpenGLWidgets.dll", "Qt6Svg.dll", "Qt6Sql.dll",
         "Qt6Help.dll", "Qt6Core5Compat.dll"]
q = []
for d in ORDER:
    p = os.path.join(BIN, d)
    if not os.path.exists(p):
        q.append({"dll": d, "exists": False})
        continue
    ok, err = try_load(p)
    q.append({"dll": d, "exists": True, "ok": ok, "err": err,
              "hex": hex(err & 0xFFFFFFFF) if err else None})
rep["qt6_load_order"] = q

# 3. VTK 层
VTK = ["vtksys-pv6.2.dll", "vtkCommonCore-pv6.2.dll",
       "vtkRemotingCore-pv6.2.dll", "vtkPVVTKExtensionsCore-pv6.2.dll",
       "vtkGUISupportQt-pv6.2.dll", "vtkRemotingServerManager-pv6.2.dll"]
v = []
for d in VTK:
    p = os.path.join(BIN, d)
    if not os.path.exists(p):
        v.append({"dll": d, "exists": False})
        continue
    ok, err = try_load(p)
    v.append({"dll": d, "exists": True, "ok": ok, "err": err,
              "hex": hex(err & 0xFFFFFFFF) if err else None})
rep["vtk_load_order"] = v

# 4. pq 层（已知失败）
PQ = ["pqWidgets-pv6.2.dll", "pqCore-pv6.2.dll", "pqComponents-pv6.2.dll",
      "pqPython-pv6.2.dll", "pqApplicationComponents-pv6.2.dll"]
pq = []
for d in PQ:
    p = os.path.join(BIN, d)
    if not os.path.exists(p):
        pq.append({"dll": d, "exists": False})
        continue
    ok, err = try_load(p)
    pq.append({"dll": d, "exists": True, "ok": ok, "err": err,
               "hex": hex(err & 0xFFFFFFFF) if err else None})
rep["pq_load_order"] = pq

with open(os.path.join(OUT, "paraview_diag3.json"), "w", encoding="utf-8") as f:
    json.dump(rep, f, ensure_ascii=False, indent=2)

print("qwindows_load:", rep.get("qwindows_load"))
print("qwindows_missing:", rep.get("qwindows_missing"))
print("--- Qt6 ---")
for x in q:
    print(" ", x)
print("--- VTK ---")
for x in v:
    print(" ", x)
print("--- pq ---")
for x in pq:
    print(" ", x)
print("DONE")
