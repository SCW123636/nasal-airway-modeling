# -*- coding: utf-8 -*-
"""整页截图：任务卡进度独立页 + 进度总览（经 embed wrapper 走真实嵌入路径，details 全展开）。
用法：python shot_progress_full.py <前缀>
"""
import sys, pathlib
from playwright.sync_api import sync_playwright

OUT = pathlib.Path(__file__).resolve().parent
PRE = sys.argv[1] if len(sys.argv) > 1 else "full"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
BASE = "http://127.0.0.1:8769"

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=True,
                          args=["--use-gl=angle", "--use-angle=swiftshader"])
    errs = []

    # ① 任务卡进度独立页（无 embed，直接整页）
    pg = b.new_page(viewport={"width": 1560, "height": 1000})
    pg.on("pageerror", lambda e: errs.append("cards:" + str(e)))
    pg.goto(BASE + "/workspace/progress-cards.html", wait_until="networkidle")
    pg.wait_for_timeout(800)
    pg.screenshot(path=str(OUT / f"{PRE}_progress_cards_full.png"), full_page=True)
    pg.close()

    # ② 进度总览。embed.js 在非嵌入访问时会把 /progress/index.html 重定向到
    #    /workspace/index.html#overview（tool-presentation 设计）。为整页审阅原始
    #    渲染，这里拦截 embed.js 返回空体；嵌入态另见 check_progress_pages.py。
    pg = b.new_page(viewport={"width": 1560, "height": 1000})
    pg.on("pageerror", lambda e: errs.append("overview:" + str(e)))
    pg.route("**/workspace/embed.js", lambda r: r.fulfill(
        status=200, content_type="application/javascript", body=""))
    pg.goto(BASE + "/progress/index.html", wait_until="networkidle")
    pg.wait_for_timeout(600)
    h = pg.evaluate("() => document.body.scrollHeight")
    pg.set_viewport_size({"width": 1560, "height": min(6000, int(h) + 60)})
    pg.wait_for_timeout(300)
    pg.screenshot(path=str(OUT / f"{PRE}_progress_overview_full.png"), full_page=True)
    pg.close()

    print("pageerrors:", errs)
    b.close()
