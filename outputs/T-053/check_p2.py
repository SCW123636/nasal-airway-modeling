# -*- coding: utf-8 -*-
"""T-053 验收：项目总览 / 项目子集化 / 对比视图（判据 C1–C4）"""
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
    page = b.new_page(viewport={"width": 1560, "height": 960}, device_scale_factor=1)
    errors, reqs = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append("console." + m.type + ": " + m.text) if m.type == "error" else None)
    page.on("request", lambda r: reqs.append(r.url) if not (r.url.startswith(BASE) or r.url.startswith("data:")) else None)
    page.goto(BASE + "/workspace/pro/index.html")
    page.wait_for_timeout(3500)

    # C1 项目总览：8 卡（含 2 失败导入如实标注）
    res["proj_cards"] = page.locator(".proj-card").count()
    res["proj_error_cards"] = page.locator(".proj-card.is-error").count()
    res["first_card_text"] = page.locator(".proj-card").first.inner_text()[:200]
    page.screenshot(path=str(OUT / "p2_projects.png"), full_page=True)

    # C2 进入项目 → 工作流树子集化 + 任务过滤
    page.locator(".proj-open").first.click()
    page.wait_for_timeout(2500)
    res["flow_nodes_in_project"] = page.locator("#flow-tree .tnode").count()
    res["job_nodes_in_project"] = page.locator("#job-tree .tnode").count()
    page.screenshot(path=str(OUT / "p2_in_project.png"), full_page=True)

    # C3 对比视图：选 A/B
    page.locator(".vtab", has_text="对比").click()
    page.wait_for_timeout(1000)
    opts = page.locator(".cmp-bar select").first.locator("option")
    val1 = opts.nth(1).get_attribute("value")
    val2 = opts.nth(2).get_attribute("value")
    page.locator(".cmp-bar select").first.select_option(val1)
    page.wait_for_timeout(800)
    page.locator(".cmp-bar select").nth(1).select_option(val2)
    page.wait_for_timeout(3000)
    res["cmp_panes"] = page.locator(".cmp-pane").count()
    res["cmp_iframes"] = page.locator(".cmp-pane iframe").count()
    res["cmp_rows"] = page.locator(".cmp-table tr").count() - 1
    page.screenshot(path=str(OUT / "p2_compare.png"), full_page=True)

    res["js_errors"] = errors
    res["external_requests"] = reqs
    b.close()
(OUT / "p2_check.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), "utf-8")
print(json.dumps(res, ensure_ascii=False, indent=2))
