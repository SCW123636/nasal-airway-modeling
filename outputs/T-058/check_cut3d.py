# -*- coding: utf-8 -*-
"""T-058 解剖斜切三维检视页（既定渲染栈）· 无头验收：截图 + 面板数值 + 报错捕获"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
URL = "http://127.0.0.1:8769/workspace/t058_cut.html"
res = {"errors": [], "checks": {}}

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                          headless=True, args=["--use-gl=angle", "--use-angle=swiftshader"])
    page = b.new_page(viewport={"width": 1440, "height": 900})
    page.on("pageerror", lambda e: res["errors"].append(str(e)))
    page.goto(URL)
    page.wait_for_timeout(5000)

    res["checks"]["case_buttons"] = page.locator("#caseBar button").all_text_contents()
    res["checks"]["nums_b15"] = page.locator("#nums").inner_text()
    page.screenshot(path=str(HERE / "cut3d_v_default.png"), timeout=120000)

    page.locator("#bBottom").click(); page.wait_for_timeout(1500)
    page.screenshot(path=str(HERE / "cut3d_v_b15_bottom.png"), timeout=120000)

    page.locator("#cb01").click(); page.wait_for_timeout(2000)
    res["checks"]["nums_b01"] = page.locator("#nums").inner_text()
    page.screenshot(path=str(HERE / "cut3d_v_b01_default.png"), timeout=120000)

    page.locator("#bBottom").click(); page.wait_for_timeout(1500)
    page.screenshot(path=str(HERE / "cut3d_v_b01_bottom.png"), timeout=120000)

    page.locator("#cb02").click(); page.locator("#bPersp").click(); page.wait_for_timeout(2000)
    page.screenshot(path=str(HERE / "cut3d_v_b02_persp.png"), timeout=120000)

    # 全域视角 + 隐藏幽灵/切面，看干净壁面
    page.locator("#cb15").click(); page.wait_for_timeout(1500)
    page.locator("#cGhost").uncheck(); page.locator("#cPlanes").uncheck()
    page.locator("#cFocus").uncheck(); page.wait_for_timeout(1500)
    page.locator("#bPersp").click(); page.wait_for_timeout(1500)
    page.screenshot(path=str(HERE / "cut3d_v_b15_full.png"), timeout=120000)
    b.close()

(HERE / "cut3d_check.json").write_text(json.dumps(res, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
print(json.dumps(res, ensure_ascii=False, indent=1))
