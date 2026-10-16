# -*- coding: utf-8 -*-
"""工作台配色审计截图：中栏三视图 + 两个顶栏跳转页（改前 / 改后同一脚本，参数化输出前缀）。

用法：python shot_surfaces.py <前缀>   例：python shot_surfaces.py before
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
PRE = sys.argv[1] if len(sys.argv) > 1 else "shot"
BASE = "http://127.0.0.1:8769"
PRO = BASE + "/workspace/pro/index.html"

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                          headless=True, args=["--use-gl=angle", "--use-angle=swiftshader"])

    # 中栏：三维检查 / 流线 / 对比
    pg = b.new_page(viewport={"width": 1560, "height": 960}, device_scale_factor=1)
    errs = []
    pg.on("pageerror", lambda e: errs.append("pro:" + str(e)))
    pg.goto(PRO); pg.wait_for_timeout(2600)
    # 选一个带模型的病例再进三维检查
    node = pg.locator("#proj-tree > li.tnode", has_text="b15 · 解剖斜切")
    if node.count():
        node.first.click(); pg.wait_for_timeout(600)
    pg.locator(".vtab", has_text="三维检查").click(); pg.wait_for_timeout(7000)
    pg.screenshot(path=str(HERE / f"{PRE}_geometry.png"))
    pg.locator(".vtab", has_text="流线").click(); pg.wait_for_timeout(7000)
    pg.screenshot(path=str(HERE / f"{PRE}_streamlines.png"))
    pg.locator(".vtab", has_text="对比").click(); pg.wait_for_timeout(900)
    pg.locator(".cmp-bar .vtab", has_text="V2").click(); pg.wait_for_timeout(9000)
    pg.screenshot(path=str(HERE / f"{PRE}_compare.png"))

    # 顶栏跳转页
    for name, url in [("progress_cards", "/workspace/progress-cards.html"),
                      ("progress_overview", "/progress/index.html")]:
        p2 = b.new_page(viewport={"width": 1560, "height": 960})
        p2.on("pageerror", lambda e: errs.append(name + ":" + str(e)))
        p2.goto(BASE + url); p2.wait_for_timeout(2500)
        p2.screenshot(path=str(HERE / f"{PRE}_{name}.png"))
        p2.close()

    print("pageerrors:", errs)
    b.close()
