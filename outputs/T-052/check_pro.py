# -*- coding: utf-8 -*-
"""PRO 外壳验收（T-052 判据 C1–C4）"""
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
    res["flow_nodes"] = page.locator("#flow-tree .tnode").count()
    res["job_nodes"] = page.locator("#job-tree .tnode").count()
    res["external_requests"] = reqs
    # 视图切换：任务控制台
    page.locator(".vtab", has_text="任务控制台").click()
    page.wait_for_timeout(1500)
    res["jobs_rows"] = page.locator(".jobs-table tr").count() - 1
    page.screenshot(path=str(OUT / "pro_shell_jobs.png"), full_page=True)
    # 选一个任务 → 属性面板
    page.locator(".jobs-table tr").nth(1).click()
    page.wait_for_timeout(800)
    page.screenshot(path=str(OUT / "pro_shell_props.png"), full_page=True)
    # 总览视图
    page.get_by_role("button", name="总览", exact=True).click()
    page.wait_for_timeout(2500)
    page.screenshot(path=str(OUT / "pro_shell_dash.png"), full_page=True)
    # 窄屏
    page.set_viewport_size({"width": 900, "height": 800})
    page.wait_for_timeout(800)
    page.screenshot(path=str(OUT / "pro_shell_narrow.png"), full_page=True)
    res["js_errors"] = errors
    b.close()
(OUT / "pro_shell_check.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), "utf-8")
print(json.dumps(res, ensure_ascii=False, indent=2))
