# -*- coding: utf-8 -*-
"""2026-10-16 肉眼核查：渲染 PRO 工作台 UI 并截图（左树/中视图/右属性/底日志区）"""
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
URL = "http://127.0.0.1:8769/workspace/pro/index.html"

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                          headless=True, args=["--use-gl=angle", "--use-angle=swiftshader"])
    page = b.new_page(viewport={"width": 1560, "height": 960})
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(URL)
    page.wait_for_timeout(2800)

    page.screenshot(path=str(HERE / "ui_full.png"), full_page=False)

    # 底部区域（用户指认的「对话区」= 消息与日志）
    foot = page.locator("footer.log-panel")
    foot.screenshot(path=str(HERE / "ui_bottom.png"))

    # 左栏项目树 + 右栏属性（点开 b15 工程试算后再截）
    page.locator("#proj-tree > li.tnode", has_text="b15 · 工程试算").first.click()
    page.wait_for_timeout(900)
    page.screenshot(path=str(HERE / "ui_b15_selected.png"))
    page.locator("aside.tree-panel").screenshot(path=str(HERE / "ui_left_tree.png"))
    page.locator("aside.prop-panel").screenshot(path=str(HERE / "ui_right_props.png"))

    # 中栏：任务控制台（唯一任务入口）
    page.locator(".vtab", has_text="任务控制台").click()
    page.wait_for_timeout(700)
    page.screenshot(path=str(HERE / "ui_jobs.png"))

    print("errors:", errs)
    print("bottom text:", page.locator("#log-body").inner_text()[:600])
    b.close()
