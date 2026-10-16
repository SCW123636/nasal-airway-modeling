# -*- coding: utf-8 -*-
"""遗留页面配色复核：/workspace/index.html（总览步）、/boundary-review/、/viewer/。
用法：python shot_legacy.py <前缀>
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent
PRE = sys.argv[1] if len(sys.argv) > 1 else "legacy"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
BASE = "http://127.0.0.1:8769"

PAGES = [
    ("legacy_workspace", "/workspace/index.html"),
    ("legacy_boundary", "/boundary-review/index.html"),
    ("legacy_viewer", "/viewer/index.html"),
]

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=True,
                          args=["--use-gl=angle", "--use-angle=swiftshader"])
    errs = []
    for name, url in PAGES:
        pg = b.new_page(viewport={"width": 1560, "height": 1000})
        pg.on("pageerror", lambda e, n=name: errs.append(n + ":" + str(e)))
        try:
            pg.goto(BASE + url, wait_until="networkidle", timeout=25000)
        except Exception as ex:
            errs.append(name + ":goto:" + str(ex)[:120])
        pg.wait_for_timeout(2000)
        pg.screenshot(path=str(OUT / f"{PRE}_{name}.png"), full_page=True)
        pg.close()
    print("pageerrors:", errs)
    b.close()
