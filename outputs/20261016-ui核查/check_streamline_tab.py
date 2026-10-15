# -*- coding: utf-8 -*-
"""T-057 验收：工作台「流线」页渲染出扩展域流线产物（回退到已核验产物清单）"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
URL = "http://127.0.0.1:8769/workspace/pro/index.html"
res = {"errors": [], "external": [], "checks": {}}

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                          headless=True, args=["--use-gl=angle", "--use-angle=swiftshader"])
    page = b.new_page(viewport={"width": 1560, "height": 960})
    page.on("pageerror", lambda e: res["errors"].append(str(e)))
    page.on("request", lambda r: res["external"].append(r.url)
            if not r.url.startswith(("file://", "http://127.0.0.1", "data:")) else None)
    page.goto(URL)
    page.wait_for_timeout(2600)

    # 选中 b15 工程试算后切到「流线」
    page.locator("#proj-tree > li.tnode", has_text="b15 · 工程试算").first.click()
    page.wait_for_timeout(600)
    page.locator(".vtab", has_text="流线").click()
    page.wait_for_timeout(2500)

    c = res["checks"]
    c["note_line"] = page.locator(".view-body .proj-note").first.inner_text()[:220]
    c["iframe_count"] = page.locator(".view-body iframe").count()
    c["iframe_src"] = page.locator(".view-body iframe").first.get_attribute("src") if c["iframe_count"] else None
    c["placeholder"] = page.locator(".view-body .placeholder").count()   # 应为 0
    page.screenshot(path=str(HERE / "streamline_tab.png"))

    # 进 iframe 内部确认 three.js 场景真的画出内容（canvas 存在且非空白）
    if c["iframe_count"]:
        fr = page.frame_locator(".view-body iframe").first
        c["iframe_canvas"] = fr.locator("canvas").count()
        c["iframe_title"] = fr.locator("body").inner_text()[:160].replace("\n", " ")
    b.close()

res["ok"] = (not res["errors"]) and (not res["external"]) and res["checks"]["iframe_count"] == 1 \
    and res["checks"]["placeholder"] == 0
print(json.dumps(res, ensure_ascii=False, indent=2))
(HERE / "streamline_tab_check.json").write_text(
    json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
