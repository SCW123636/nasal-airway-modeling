# -*- coding: utf-8 -*-
"""工作台现状截图（优化前基线）"""
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent
BASE = "http://127.0.0.1:8769"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=True,
                          args=["--use-gl=angle", "--use-angle=swiftshader"])
    page = b.new_page(viewport={"width": 1500, "height": 950}, device_scale_factor=1)
    for name, url in (("home", "/workspace/index.html"),
                      ("validation", "/workspace/index.html#validation"),
                      ("geometry", "/workspace/index.html#geometry"),
                      ("upper-airway", "/workspace/index.html#upper-airway")):
        page.goto(BASE + url)
        page.wait_for_timeout(2500)
        page.screenshot(path=str(OUT / f"base_{name}.png"), full_page=True)
    page.set_viewport_size({"width": 800, "height": 900})
    page.goto(BASE + "/workspace/index.html#validation")
    page.wait_for_timeout(2000)
    page.screenshot(path=str(OUT / "base_narrow.png"), full_page=True)
    b.close()
print("done")
