# -*- coding: utf-8 -*-
"""T-058 工作台改版验收：①「咽部扩展」栏已移除；②「对比」两侧为三维模型并排（非各病例界面）。

用法：系统 py3.10 + playwright + 本机 Chrome（同 outputs/T-056/check_p3.py 配方）。
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
PRO = "http://127.0.0.1:8769/workspace/pro/index.html"
LEGACY = "http://127.0.0.1:8769/workspace/index.html"
res = {"errors": [], "external": [], "checks": {}}

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                          headless=True, args=["--use-gl=angle", "--use-angle=swiftshader"])
    page = b.new_page(viewport={"width": 1560, "height": 960})
    page.on("pageerror", lambda e: res["errors"].append(str(e)))
    page.on("request", lambda r: res["external"].append(r.url)
            if not r.url.startswith(("file://", "http://127.0.0.1", "data:")) else None)
    page.goto(PRO)
    page.wait_for_timeout(2600)

    # C1 视图标签：咽部扩展已移除，其余四项在
    tabs = [t.strip() for t in page.locator(".vtab").all_text_contents()]
    res["checks"]["view_tabs"] = tabs
    res["checks"]["has_airway_tab"] = page.locator(".vtab", has_text="咽部扩展").count()
    res["checks"]["airway_iframe"] = page.locator('iframe[src*="upper-airway"]').count()
    page.screenshot(path=str(HERE / "pro_tabs_after.png"))

    # C2 对比视图：V2 配对 → 单画布双视口 3D
    page.locator(".vtab", has_text="对比").click()
    page.wait_for_timeout(900)
    page.locator(".cmp-bar .vtab", has_text="V2").click()
    page.wait_for_timeout(1200)
    res["checks"]["cmp_hint"] = page.locator(".cmp-hint").first.text_content()
    frame = page.locator('.cmp-stage iframe')
    res["checks"]["cmp_stage_iframe"] = frame.count()
    src = frame.first.get_attribute("src") if frame.count() else None
    res["checks"]["cmp_iframe_src"] = src
    res["checks"]["cmp_src_is_cmp_page"] = bool(src and "t058_cmp.html" in src)
    res["checks"]["sel_options"] = [o.strip() for o in page.locator(".cmp-bar select").nth(0).all_text_contents()] \
        if page.locator(".cmp-bar select").count() else []
    # 等三维加载（两例各 ~1.5MB JSON）
    page.wait_for_timeout(6000)
    sub = [f for f in page.frames if "t058_cmp.html" in (f.url or "")]
    res["checks"]["cmp_frame_loaded"] = len(sub) > 0
    if sub:
        fr_ = sub[0]
        res["checks"]["tagA"] = fr_.locator("#tagA").text_content()
        res["checks"]["tagB"] = fr_.locator("#tagB").text_content()
        res["checks"]["cmp_canvas"] = fr_.locator("#stage canvas").count()
        res["checks"]["cmp_canvas_size"] = fr_.eval_on_selector("#stage canvas",
            "c => [c.width, c.height]")
        res["checks"]["cmp_view_btns"] = fr_.locator("#viewBtns button").count()
        res["checks"]["cmp_frame_errors"] = []
    page.screenshot(path=str(HERE / "pro_compare_pair_after.png"))

    # C3 换 B 侧模型 → iframe 地址随之变化（选择模型放进对应一侧）
    if page.locator(".cmp-bar select").count() >= 2:
        sel_b = page.locator(".cmp-bar select").nth(1)
        options = [o.get_attribute("value") for o in sel_b.locator("option").all()]
        target = next((v for v in options if v and v != (src or "").split("b=")[-1].split("&")[0]), None)
        if target:
            sel_b.select_option(value=target)
            page.wait_for_timeout(1500)
            new_src = page.locator('.cmp-stage iframe').first.get_attribute("src")
            res["checks"]["b_swap_new_src"] = new_src
            res["checks"]["b_swap_changed"] = new_src != src
            page.wait_for_timeout(5000)
            page.screenshot(path=str(HERE / "pro_compare_pair_swapped.png"))

    # C4 遗留工作台：导航不再有咽部扩展
    page2 = b.new_page(viewport={"width": 1440, "height": 900})
    page2.on("pageerror", lambda e: res["errors"].append("legacy: " + str(e)))
    page2.goto(LEGACY)
    page2.wait_for_timeout(2200)
    nav = [t.strip().replace("\n", " ") for t in page2.locator(".process-sidebar nav a").all_text_contents()]
    res["checks"]["legacy_nav"] = nav
    res["checks"]["legacy_has_airway"] = page2.locator('[data-step="upper-airway"]').count()
    page2.screenshot(path=str(HERE / "legacy_nav_after.png"))
    b.close()

res["ok"] = (not res["errors"]) and (not res["external"]) \
    and res["checks"].get("has_airway_tab") == 0 \
    and res["checks"].get("airway_iframe") == 0 \
    and res["checks"].get("legacy_has_airway") == 0 \
    and res["checks"].get("cmp_src_is_cmp_page") \
    and res["checks"].get("cmp_frame_loaded") \
    and res["checks"].get("cmp_canvas") == 1
(HERE / "pro_t058_cmp_check.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(res, ensure_ascii=False, indent=2))
