# -*- coding: utf-8 -*-
"""底部日志面板移除后验收：零 JS 报错 / 无残留引用 / 三栏仍在 / 任务控制台仍可用"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
URL = "http://127.0.0.1:8769/workspace/pro/index.html"
res = {"errors": [], "checks": {}}

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                          headless=True, args=["--use-gl=angle", "--use-angle=swiftshader"])
    page = b.new_page(viewport={"width": 1560, "height": 960})
    page.on("pageerror", lambda e: res["errors"].append(str(e)))
    page.on("console", lambda m: res["errors"].append("console:" + m.text) if m.type == "error" else None)
    page.goto(URL)
    page.wait_for_timeout(2600)

    c = res["checks"]
    c["footer_panel"] = page.locator("footer.log-panel").count()          # 应为 0
    c["log_body"] = page.locator("#log-body").count()                      # 应为 0
    c["log_count"] = page.locator("#log-count").count()                    # 应为 0
    c["log_lines"] = page.locator(".log-line").count()                     # 应为 0
    c["proj_nodes"] = page.locator("#proj-tree > li.tnode").count()        # 左栏仍在
    c["tabs"] = [t.strip() for t in page.locator(".vtab").all_text_contents()]
    c["prop_placeholder"] = page.locator("#prop-body").inner_text()[:40]

    # 选中项目 → 属性面板与处理链正常
    page.locator("#proj-tree > li.tnode", has_text="b15 · 工程试算").first.click()
    page.wait_for_timeout(800)
    c["flow_children_after_select"] = page.locator("#proj-tree > li.tnode.child").count()
    c["prop_has_id"] = page.locator("#prop-body").inner_text().count("项目 ID") > 0

    # 任务控制台（任务数据唯一入口）仍可用
    page.locator(".vtab", has_text="任务控制台").click()
    page.wait_for_timeout(700)
    c["jobs_rows"] = page.locator(".jobs-table tr").count()
    c["jobs_refresh_btn"] = page.locator(".jobs-head .icon-btn").count()

    page.screenshot(path=str(HERE / "after_remove_full.png"))
    page.locator(".vtab", has_text="三维检查").click()
    page.wait_for_timeout(600)
    page.screenshot(path=str(HERE / "after_remove_geometry.png"))
    b.close()

res["ok"] = (not res["errors"]) and all(
    res["checks"][k] == 0 for k in ("footer_panel", "log_body", "log_count", "log_lines"))
print(json.dumps(res, ensure_ascii=False, indent=2))
(HERE / "after_remove_check.json").write_text(
    json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
