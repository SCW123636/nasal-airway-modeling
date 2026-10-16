# -*- coding: utf-8 -*-
"""对比页本体直开核验（只读截图）：t058_cmp.html 双例 + 双侧流线。"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:8769/workspace/t058_cmp.html"
ART = "/workspace/pro/artifacts"
res = {"errors": [], "shots": [], "console_err": []}

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                          headless=True, args=["--use-gl=angle", "--use-angle=swiftshader"])
    page = b.new_page(viewport={"width": 1500, "height": 860})
    page.on("pageerror", lambda e: res["errors"].append(str(e)))
    page.on("console", lambda m: res["console_err"].append(m.text) if m.type == "error" else None)

    for tag, other in (("b01", "b01"), ("b02", "b02")):
        url = (f"{BASE}?a=b15&b={other}"
               f"&sa={ART}%2Fstreamlines_b15_anat_t600.lines.json"
               f"&sb={ART}%2Fstreamlines_{other}_anat_t600.lines.json&embedded=1")
        page.goto(url)
        page.wait_for_timeout(7000)
        info = page.evaluate("""() => ({
            slots: [...document.querySelectorAll('canvas')].length,
            title: document.title,
            badges: [...document.querySelectorAll('.cmp-badge,.badge,[class*=badge]')].map(e=>e.textContent.trim()).slice(0,6),
        })""")
        res[f"cmp_{tag}"] = info
        page.screenshot(path=str(HERE / f"cmp_direct_b15_vs_{tag}.png"))
        res["shots"].append(f"cmp_direct_b15_vs_{tag}.png")
    b.close()

res["pass"] = not res["errors"]
(HERE / "cmp_direct_check.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(res, ensure_ascii=False, indent=1))
