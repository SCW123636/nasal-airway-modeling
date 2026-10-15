# -*- coding: utf-8 -*-
"""T-046 · 新排版演示页无头验收（C2 排版 / C3 零报错零外部请求）"""
from pathlib import Path
import json
from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent
HTML = (OUT / "streamlines_demo.html").resolve()
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

res = {}
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=CHROME, headless=True,
        args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"])
    page = browser.new_page(viewport={"width": 1500, "height": 980}, device_scale_factor=1)
    errors, requests = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append("console." + m.type + ": " + m.text) if m.type == "error" else None)
    page.on("request", lambda r: requests.append(r.url) if not r.url.startswith("file://") else None)
    page.goto(HTML.as_uri())
    page.wait_for_timeout(2500)
    res["external_requests"] = requests
    res["js_errors"] = errors
    res["hist_nonblank"] = page.evaluate(
        "()=>{const c=document.getElementById('hist');const d=c.getContext('2d').getImageData(0,0,c.width,c.height).data;"
        "let n=0;for(let i=0;i<d.length;i+=4) if(d[i]>0||d[i+1]>0||d[i+2]>0) n++; return n;}")
    page.screenshot(path=str(OUT / "demo_default.png"), full_page=True)
    page.locator("#bFront").click(); page.wait_for_timeout(500)
    page.screenshot(path=str(OUT / "demo_front.png"), full_page=True)
    page.locator("#bPersp").click(); page.wait_for_timeout(400)
    # 窄屏检查排版（事实表 dl 网格不应换行灾难）
    page.set_viewport_size({"width": 760, "height": 900})
    page.wait_for_timeout(600)
    page.screenshot(path=str(OUT / "demo_narrow.png"), full_page=True)
    browser.close()
(OUT / "demo_check.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), "utf-8")
print(json.dumps(res, ensure_ascii=False, indent=2))
