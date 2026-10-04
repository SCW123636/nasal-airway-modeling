# -*- coding: utf-8 -*-
"""
ParaView 6.2 崩溃深度诊断
上一轮只拿到 0xC0000142，stderr 空。本轮换手段：
  1. 列出 bin 下全部 exe
  2. 逐个执行，记录 err code + 完整 stdout/stderr（含无缓冲）
  3. 检查 api-ms-win-crt-* 系列 DLL 的实际存在情况（这是 0xC0000142 的典型原因）
  4. 检查 VC 运行库
  5. 用 dumpbin 风格：读 PE 头找导入表里缺失的 DLL（无 dumpbin 则用纯 Python 解析）
"""
import os, json, subprocess, glob, struct

BIN = r"D:\项目\鼻腔建模\软件\ParaView 6.2\bin"
OUT = r"C:\nasal_probe"
os.makedirs(OUT, exist_ok=True)
rep = {"bin": BIN}

exes = sorted(glob.glob(os.path.join(BIN, "*.exe")))
rep["exes"] = [os.path.basename(e) for e in exes]

results = []
for exe in exes:
    name = os.path.basename(exe)
    # 用 --version 触发一次正常启动（有的 exe 不认这个参数，但至少能触发加载期）
    try:
        p = subprocess.run([exe, "--version"], capture_output=True, timeout=25)
        results.append({
            "exe": name,
            "returncode": p.returncode,
            "hex": hex(p.returncode & 0xFFFFFFFF),
            "stdout": p.stdout.decode("utf-8", "replace")[:400],
            "stderr": p.stderr.decode("utf-8", "replace")[:400],
        })
    except subprocess.TimeoutExpired:
        results.append({"exe": name, "returncode": "TIMEOUT"})
    except Exception as e:
        results.append({"exe": name, "returncode": f"EXC:{e}"})
rep["run_results"] = results

# ---- 3. api-ms-win-crt 系列 ----
sys32 = r"C:\Windows\System32"
crt_patterns = ["api-ms-win-crt-*.dll", "ucrtbase.dll", "vcruntime140*.dll",
                "msvcp140*.dll"]
crt = {}
for pat in crt_patterns:
    crt[pat] = {
        "in_system32": sorted(os.path.basename(x) for x in glob.glob(os.path.join(sys32, pat))),
        "in_paraview_bin": sorted(os.path.basename(x) for x in glob.glob(os.path.join(BIN, pat))),
    }
rep["runtime_dlls"] = crt

# ---- 4. 读 PE 导入表，找 ParaView 主 exe 依赖的 DLL ----
def pe_imports(path):
    """极简 PE 导入表解析（只取 DLL 名字符串）"""
    try:
        with open(path, "rb") as f:
            data = f.read()
        if data[:2] != b"MZ":
            return ["NOT_PE"]
        e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
        if data[e_lfanew:e_lfanew + 4] != b"PE\0\0":
            return ["NO_PE_SIG"]
        coff = e_lfanew + 4
        n_sections = struct.unpack_from("<H", data, coff + 2)[0]
        opt_size = struct.unpack_from("<H", data, coff + 16)[0]
        opt_off = coff + 20
        magic = struct.unpack_from("<H", data, opt_off)[0]
        is_pe32p = magic == 0x20B
        # data directory offset
        dd_off = opt_off + (112 if is_pe32p else 96)
        imp_rva, imp_sz = struct.unpack_from("<II", data, dd_off + 1 * 8)
        if imp_rva == 0:
            return []
        # section table
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

        names = []
        off = rva2off(imp_rva)
        if off is None:
            return []
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
        return names
    except Exception as e:
        return [f"ERR:{e}"]


main_exe = os.path.join(BIN, "paraview.exe")
if not os.path.exists(main_exe):
    cands = [e for e in exes if "paraview" in os.path.basename(e).lower()]
    main_exe = cands[0] if cands else None
rep["pe_target"] = main_exe
if main_exe:
    imps = pe_imports(main_exe)
    rep["pe_imports"] = imps
    missing = []
    for d in imps:
        if d.startswith(("ERR", "NOT_PE", "NO_PE")):
            continue
        if os.path.exists(os.path.join(BIN, d)) or os.path.exists(os.path.join(sys32, d)):
            continue
        missing.append(d)
    rep["pe_missing"] = missing

with open(os.path.join(OUT, "paraview_diag.json"), "w", encoding="utf-8") as f:
    json.dump(rep, f, ensure_ascii=False, indent=2)
print("DONE ->", os.path.join(OUT, "paraview_diag.json"))
print("missing:", rep.get("pe_missing"))
