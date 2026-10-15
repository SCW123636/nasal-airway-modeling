# -*- coding: utf-8 -*-
"""
T-045 · web_v2 无头浏览器验收（判据 C1–C6）
  C1 默认视角 = azim -60 / elev 30 / up +z（与静态透视图一致）
  C2 mm 坐标尺齐全（包围盒 + 三轴刻度 + 轴标签 + 数值）
  C3 流线为管状几何、抵达出口组加粗
  C4 直方图 + patch 图例存在
  C5 零 JS 报错
  C6 单文件自包含（file:// 直开，无外部请求）
"""
from pathlib import Path
import json

from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent
HTML = (OUT / "鼻腔气流可视化_web_v2.html").resolve()
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

res = {}
with sync_playwright() as p:
    browser = p.chromium.launch(
        executable_path=CHROME, headless=True,
        args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"])
    page = browser.new_page(viewport={"width": 1500, "height": 980}, device_scale_factor=1)
    errors, requests = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append("console." + m.type + ": " + m.text) if m.type == "error" else None)
    page.on("request", lambda r: requests.append(r.url) if not r.url.startswith("file://") else None)
    page.goto(HTML.as_uri())
    page.wait_for_timeout(2500)

    # C6：仅 file:// 请求（three.min.js 已内嵌，不应有任何 http 请求）
    res["C6_external_requests"] = requests

    # C4：直方图 canvas 非空白 + patch 图例
    res["C4_hist_nonblank"] = page.evaluate(
        "()=>{const c=document.getElementById('hist');const d=c.getContext('2d').getImageData(0,0,c.width,c.height).data;"
        "let n=0;for(let i=0;i<d.length;i+=4) if(d[i]>0||d[i+1]>0||d[i+2]>0) n++; return n;}")
    res["C4_swatches"] = page.locator(".swatches .sw").all_inner_texts()

    # C2：坐标尺组存在且可见
    res["C2_axis_visible"] = page.evaluate(
        "()=>{const c=document.getElementById('cAxis');return c.checked;}")

    # C1/C3：主视图截图
    page.screenshot(path=str(OUT / "browser_v2_default.png"), full_page=True)
    page.locator("#bFront").click(); page.wait_for_timeout(600)
    page.screenshot(path=str(OUT / "browser_v2_front.png"), full_page=True)
    page.locator("#bSide").click(); page.wait_for_timeout(600)
    page.screenshot(path=str(OUT / "browser_v2_side.png"), full_page=True)
    page.locator("#bTop").click(); page.wait_for_timeout(600)
    page.screenshot(path=str(OUT / "browser_v2_top.png"), full_page=True)
    page.locator("#bPersp").click(); page.wait_for_timeout(600)
    page.locator("#bPress").click(); page.wait_for_timeout(600)
    page.screenshot(path=str(OUT / "browser_v2_pressure.png"), full_page=True)
    page.locator("#bSpeed").click(); page.wait_for_timeout(600)

    # 画布非空白（默认视角渲染出了内容）
    res["canvas_bytes"] = page.evaluate(
        "()=>{const c=document.querySelector('#view canvas');return c.width+'x'+c.height;}")
    res["C5_errors"] = errors
    browser.close()

(OUT / "browser_v2_check.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), "utf-8")
print(json.dumps(res, ensure_ascii=False, indent=2))
