# -*- coding: utf-8 -*-
"""
递归解析 PE 导入表：找出 pqApplicationComponents / pqCore 到底缺哪个 DLL
对每个 DLL，列出其全部 import，并用「bin 目录 + System32 + downlevel」白名单判断缺失。
同时打印 APS (API Set) 解析情况：api-ms-win-* 应转发到真实 DLL。
"""
import os, json, struct, glob

BIN = r"D:\项目\鼻腔建模\软件\ParaView 6.2\bin"
SYS32 = r"C:\Windows\System32"
DL = r"C:\Windows\System32\downlevel"
APISET = r"C:\Windows\System32\ApiSetSchema.dll"
OUT = r"C:\nasal_probe"

SEARCH_DIRS = [BIN, SYS32, DL, r"C:\Windows\SysWOW64"]


def pe_imports(path):
    """解析 PE 导入表 DLL 名"""
    try:
        with open(path, "rb") as f:
            data = f.read()
        if data[:2] != b"MZ":
            return None, "NOT_PE"
        e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
        if data[e_lfanew:e_lfanew + 4] != b"PE\0\0":
            return None, "NO_PE_SIG"
        coff = e_lfanew + 4
        n_sections = struct.unpack_from("<H", data, coff + 2)[0]
        opt_size = struct.unpack_from("<H", data, coff + 16)[0]
        opt_off = coff + 20
        magic = struct.unpack_from("<H", data, opt_off)[0]
        is_p32p = magic == 0x20B
        dd_off = opt_off + (112 if is_p32p else 96)
        imp_rva, imp_sz = struct.unpack_from("<II", data, dd_off + 1 * 8)
        sec_off = opt_off + opt_size
        sections = []
        for i in range(n_sections):
            base = sec_off + i * 40
            va = struct.unpack_from("<I", data, base + 12)[0]
            raw_sz = struct.unpack_from("<I", data, base + 16)[0]
            raw_ptr = struct.unpack_from("<I", data, base + 20)[0]
            sections.append((va, raw_sz, raw_ptr))

        def rva2off(rva):
            for va, raw_sz, raw_ptr in sections:
                if va <= rva < va + raw_sz:
                    return raw_ptr + (rva - va)
            return None

        if imp_rva == 0:
            return [], None
        names = []
        off = rva2off(imp_rva)
        if off is None:
            return [], None
        while True:
            ent = data[off:off + 20]
            if len(ent) < 20:
                break
            orig, ts, fwd, name_rva, first_thunk = struct.unpack("<IIIII", ent)
            if name_rva == 0 and first_thunk == 0:
                break
            no = rva2off(name_rva)
            if no is None:
                break
            end = data.index(b"\0", no)
            names.append(data[no:end].decode("ascii", "replace"))
            off += 20
        return names, None
    except Exception as e:
        return None, f"ERR:{e}"


def resolve(dll):
    """在搜索路径里找这个 DLL，返回命中的绝对路径或 None"""
    for d in SEARCH_DIRS:
        p = os.path.join(d, dll)
        if os.path.exists(p):
            return p
    return None


TARGETS = [
    "pqApplicationComponents-pv6.2.dll",
    "pqComponents-pv6.2.dll",
    "pqCore-pv6.2.dll",
    "pqPython-pv6.2.dll",
    "pqWidgets-pv6.2.dll",
]

rep = {"targets": {}, "all_missing": {}}
all_missing = {}

for t in TARGETS:
    p = os.path.join(BIN, t)
    imps, err = pe_imports(p)
    entry = {"path": p, "exists": os.path.exists(p), "error": err}
    if imps is not None:
        found, missing = [], []
        for d in imps:
            r = resolve(d)
            (found if r else missing).append({"dll": d, "path": r})
            if not r:
                all_missing.setdefault(d, []).append(t)
        entry["n_imports"] = len(imps)
        entry["imports"] = imps
        entry["missing"] = [m["dll"] for m in missing]
    rep["targets"][t] = entry

rep["all_missing"] = {k: v for k, v in all_missing.items()}

# 对每个缺失的 DLL，若是 api-ms-win-* 则查 downlevel；否则报
extra = {}
for d in all_missing:
    cand = None
    for dd in SEARCH_DIRS:
        if os.path.exists(os.path.join(dd, d)):
            cand = os.path.join(dd, d)
            break
    extra[d] = cand
rep["missing_resolved"] = extra

with open(os.path.join(OUT, "pe_imports_tree.json"), "w", encoding="utf-8") as f:
    json.dump(rep, f, ensure_ascii=False, indent=2)

print("=== pq* DLL 缺失的依赖 ===")
for k, v in rep["all_missing"].items():
    print(f"  {k}   needed by: {v}")
if not rep["all_missing"]:
    print("  (无缺失 —— 说明静态依赖链完整，问题在运行期 DllMain)")
print("DONE")
