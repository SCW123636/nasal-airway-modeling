# -*- coding: utf-8 -*-
"""皮肤验收：四页 + 窄屏 + 零 JS 报错（T-051 判据 C1–C4）"""
from pathlib import Path
import json
from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent
BASE = "http://127.0.0.1:8769"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

res = {}
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=True,
                          args=["--use-gl=angle", "--use-angle=swiftshader"])
    page = b.new_page(viewport={"width": 1500, "height": 950}, device_scale_factor=1)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    for name, url in (("home", "/workspace/index.html"),
                      ("validation", "/workspace/index.html#validation"),
                      ("geometry", "/workspace/index.html#geometry"),
                      ("upper-airway", "/workspace/index.html#upper-airway")):
        page.goto(BASE + url)
        page.wait_for_timeout(3000)
        if name == "validation":
            rows = page.locator(".simulation-job-row")
            if rows.count():
                rows.first.click()
                page.wait_for_timeout(3500)
        page.screenshot(path=str(OUT / f"pro_{name}.png"), full_page=True)
    page.set_viewport_size({"width": 800, "height": 900})
    page.goto(BASE + "/workspace/index.html#validation")
    page.wait_for_timeout(2500)
    page.screenshot(path=str(OUT / "pro_narrow.png"), full_page=True)
    res["js_errors"] = errors
    b.close()
(OUT / "pro_check.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), "utf-8")
print(json.dumps(res, ensure_ascii=False))
