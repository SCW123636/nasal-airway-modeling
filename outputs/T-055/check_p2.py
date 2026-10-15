# -*- coding: utf-8 -*-
"""T-055 PRO 工作台无头验收 v2：修正 C5 选 B、C7 区分节点/项目属性"""
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

    # C1 项目总览（8 导入 + 5 仿真合成）
    res["checks"]["project_cards"] = page.locator(".proj-card").count()
    res["checks"]["synthetic_cards"] = page.locator(".proj-card .notice").count()

    # C2 选 b15 仿真项目
    sel = page.locator("#case-select option")
    n = sel.count()
    b15_val = None
    for i in range(n):
        t = sel.nth(i).get_attribute("value") or ""
        if t.startswith("b15"):
            b15_val = t
            break
    page.select_option("#case-select", b15_val or "")
    page.wait_for_timeout(1200)
    res["checks"]["b15_case_value"] = b15_val

    # C3 处理链路：8 节点（source~mesh 应为 ◇ 工作台无记录，config/post/report ✓）
    res["checks"]["pipeline_nodes"] = page.locator(".pipe-node").count()
    res["checks"]["pipeline_norec"] = page.locator(".pipe-node.norec").count()
    res["checks"]["pipeline_done"] = page.locator(".pipe-node.done").count()
    page.locator(".pipe-node").nth(6).click()   # 后处理
    page.wait_for_timeout(600)
    res["checks"]["pipeline_detail"] = page.locator(".pipe-detail").count()
    res["checks"]["props_node_view"] = "处理节点" in page.locator("#prop-body").inner_text()
    page.screenshot(path=str(HERE / "p2_pipeline.png"), full_page=True)

    # C4 对比 V1（b15 个体 vs 参考带）
    page.locator(".vtab", has_text="对比").click()
    page.wait_for_timeout(1000)
    page.locator(".vtab", has_text="V1 · 个体 vs 参考带").click()
    page.wait_for_timeout(1000)
    body_txt = page.locator("#view-body").inner_text()
    res["checks"]["compare_ref_rows"] = page.locator(".cmp-table tr").count()
    res["checks"]["compare_ref_iscoana"] = "ISCOANA" in body_txt
    res["checks"]["compare_ref_low"] = "低于参考值" in body_txt
    res["checks"]["compare_ref_domain"] = "short" in body_txt
    page.screenshot(path=str(HERE / "p2_compare_ref.png"), full_page=True)

    # C5 对比 V2（A=b15, B=u_0ff4，验证表+附录+域差异提示逻辑）
    page.locator(".vtab", has_text="V2 · 配对对照").click()
    page.wait_for_timeout(800)
    sels = page.locator(".cmp-bar select")
    a_opts = sels.nth(0).locator("option").evaluate_all("els => els.map(e => e.value)")
    b_opts = sels.nth(1).locator("option").evaluate_all("els => els.map(e => e.value)")
    a_val = next((v for v in a_opts if v.startswith("b15")), "")
    b_val = next((v for v in b_opts if v.startswith("u_")), "")
    if a_val: sels.nth(0).select_option(a_val)
    page.wait_for_timeout(600)
    if b_val: sels.nth(1).select_option(b_val)
    page.wait_for_timeout(1200)
    res["checks"]["compare_pair_panes"] = page.locator(".cmp-pane").count()
    res["checks"]["compare_pair_rows"] = page.locator(".cmp-table tr").count()
    res["checks"]["compare_pair_appendix"] = page.locator(".cmp-appendix").count()
    res["checks"]["compare_pair_dash"] = "—" in page.locator("#view-body").inner_text()
    page.screenshot(path=str(HERE / "p2_compare_pair.png"), full_page=True)

    # C6 任务控制台回归
    page.locator(".vtab", has_text="任务控制台").click()
    page.wait_for_timeout(1000)
    res["checks"]["jobs_rows"] = page.locator(".jobs-table tr").count() - 1
    page.screenshot(path=str(HERE / "p2_jobs.png"), full_page=True)

    # C7 项目属性面板（清 sel：先选全部再选 b15）
    page.select_option("#case-select", "")
    page.wait_for_timeout(600)
    page.select_option("#case-select", b15_val or "")
    page.wait_for_timeout(900)
    prop_txt = page.locator("#prop-body").inner_text()
    res["checks"]["props_case_metrics"] = "已核验功能指标" in prop_txt
    res["checks"]["props_clinical"] = "generalisation_test_only" in prop_txt
    res["checks"]["props_domain"] = "short" in prop_txt

    b.close()

(HERE / "p2_check.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(res, ensure_ascii=False, indent=2))
