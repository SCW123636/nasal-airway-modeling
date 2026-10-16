# -*- coding: utf-8 -*-
"""20261016 对比页独立核验（只读）：对比 tab 两侧模型+流线是否同框。
配方 = outputs/T-056/check_p3.py 同款（系统 py3.10 + playwright + 本机 Chrome swiftshader）。
本脚本不写工作台任何文件，只截图到本目录。"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
URL = "http://127.0.0.1:8769/workspace/pro/index.html"
res = {"errors": [], "checks": {}, "shots": []}

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                          headless=True, args=["--use-gl=angle", "--use-angle=swiftshader"])
    page = b.new_page(viewport={"width": 1560, "height": 960})
    page.on("pageerror", lambda e: res["errors"].append(str(e)))
    page.goto(URL)
    page.wait_for_timeout(2500)

    b15 = page.locator("#proj-tree > li.tnode", has_text="b15 · 解剖斜切")
    b15.first.click()
    page.wait_for_timeout(600)
    page.locator(".vtab", has_text="对比").click()
    page.wait_for_timeout(800)

    sels = page.locator("#view-body select")
    n = sels.count()
    res["checks"]["select_count"] = n
    opts = sels.nth(0).locator("option").all_text_contents()
    res["checks"]["a_options_sample"] = [o for o in opts if "b0" in o][:6]

    def pick(idx, label):
        sels.nth(idx).select_option(label=label)
        page.wait_for_timeout(5000)
        srcs = page.evaluate("""() => [...document.querySelectorAll('#view-body iframe')].map(f => f.src)""")
        return srcs

    for tag, other in (("b01", "b01_engineering"), ("b02", "b02_engineering")):
        pick(0, "b15_engineering")
        srcs = pick(1, other)
        res["checks"][f"cmp_{tag}_iframes"] = len(srcs)
        res["checks"][f"cmp_{tag}_sa"] = "sa=" in (srcs[0] if srcs else "")
        res["checks"][f"cmp_{tag}_sb"] = "sb=" in (srcs[1] if len(srcs) > 1 else "")
        page.screenshot(path=str(HERE / f"cmp_b15_vs_{tag}.png"))
        res["shots"].append(f"cmp_b15_vs_{tag}.png")

    b.close()

res["pass"] = not res["errors"] and all(
    v for k, v in res["checks"].items()
    if k.startswith("cmp_") and (k.endswith("_iframes") or k.endswith("_sa") or k.endswith("_sb"))
)
(HERE / "cmp_check.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(res, ensure_ascii=False, indent=1))
