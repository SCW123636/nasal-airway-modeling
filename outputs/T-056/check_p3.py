# -*- coding: utf-8 -*-
"""T-056 PRO 工作台栏位精简与归位 · 无头验收
左=患者项目树（master-detail）｜中=图形/数据视图｜右=属性面板三级详情
"""
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

    # C1 左栏 = 患者项目树：顶层节点数 = /api/cases + jobs 合成；旧件全清
    res["checks"]["proj_nodes"] = page.locator("#proj-tree > li.tnode").count()
    res["checks"]["proj_count_label"] = page.locator("#proj-count").text_content()
    res["checks"]["no_proj_card"] = page.locator(".proj-card").count()          # 旧项目卡片视图已删
    res["checks"]["no_pipe_view"] = page.locator(".pipe-node").count()          # 旧中间链路视图已删
    res["checks"]["no_case_dropdown"] = page.locator("#case-select").count()    # 顶栏病例下拉已删
    res["checks"]["no_legacy_link"] = page.locator(".legacy").count()           # 旧版入口已删
    res["checks"]["no_chips"] = page.locator("#chip-cases, #chip-jobs").count() # 计数 chip 已删
    res["checks"]["top_chips"] = page.locator(".top .chip").count()             # 顶栏仅剩临床口径
    res["checks"]["tabs"] = [t.strip() for t in page.locator(".vtab").all_text_contents()]

    # C2 点 b15_engineering 项目 → 展开 8 节点处理链（source~mesh ◇，config/post/report ✓）
    #    注意：树里还有 b15_engineering_t029a 变体，用完整标签文本精确区分
    b15 = page.locator("#proj-tree > li.tnode", has_text="b15_engineering仿真项目")
    res["checks"]["b15_found"] = b15.count() > 0
    res["checks"]["b15_variant_visible"] = page.locator("#proj-tree > li.tnode", has_text="b15_engineering_").count()
    if b15.count():
        b15.first.click()
        page.wait_for_timeout(800)
        res["checks"]["flow_children"] = page.locator("#proj-tree li.tnode.child").count()
        res["checks"]["flow_norec"] = page.locator("#proj-tree li.tnode.child .st.norec").count()
        res["checks"]["flow_done"] = page.locator("#proj-tree li.tnode.child .st.done").count()
        page.screenshot(path=str(HERE / "t056_tree_b15.png"))

        # C3 点「04 几何」子节点 → 属性面板出节点详情 + 视图跳三维
        geo = page.locator("#proj-tree li.tnode.child", has_text="04 几何")
        geo.click()
        page.wait_for_timeout(800)
        prop = page.locator("#prop-body").text_content() or ""
        res["checks"]["prop_has_dep"] = "上游依赖" in prop
        res["checks"]["prop_has_state"] = "节点状态" in prop
        res["checks"]["view_geometry_on"] = page.locator(".vtab.on").text_content()
        page.screenshot(path=str(HERE / "t056_geometry_node.png"))

        # C4 项目级属性（无节点选中时）：再点项目节点 → 回项目属性
        page.locator("#proj-tree > li.tnode", has_text="b15_engineering仿真项目").first.click()
        page.wait_for_timeout(600)
        prop2 = page.locator("#prop-body").text_content() or ""
        res["checks"]["prop_project_level"] = ("患者项目" in prop2) and ("临床状态" in prop2 or "已核验功能指标" in prop2)

    # C5 任务控制台：刷新按钮在视图头部；点行 → 属性面板任务详情
    page.locator(".vtab", has_text="任务控制台").click()
    page.wait_for_timeout(800)
    res["checks"]["jobs_refresh_btn"] = page.locator(".jobs-head .icon-btn").count()
    rows = page.locator(".jobs-table tr").count()
    res["checks"]["jobs_rows"] = rows
    if rows > 1:
        page.locator(".jobs-table tbody tr, .jobs-table tr").nth(1).click()
        page.wait_for_timeout(600)
        prop3 = page.locator("#prop-body").text_content() or ""
        res["checks"]["prop_job_level"] = ("任务 ID" in prop3) and ("退出码" in prop3)
    page.screenshot(path=str(HERE / "t056_jobs.png"))

    # C6 对比视图：V1/V2 切换仍在
    page.locator(".vtab", has_text="对比").click()
    page.wait_for_timeout(800)
    res["checks"]["compare_modes"] = page.locator(".cmp-bar .vtab").count()
    page.screenshot(path=str(HERE / "t056_compare.png"))

    b.close()

res["ok"] = (not res["errors"]) and (not res["external"]) \
    and res["checks"].get("proj_nodes", 0) >= 8 \
    and res["checks"].get("no_proj_card") == 0 and res["checks"].get("no_pipe_view") == 0 \
    and res["checks"].get("no_case_dropdown") == 0 and res["checks"].get("no_legacy_link") == 0 \
    and res["checks"].get("top_chips") == 1 \
    and res["checks"].get("flow_children") == 8 \
    and res["checks"].get("prop_has_dep") and res["checks"].get("prop_project_level") \
    and res["checks"].get("jobs_refresh_btn") == 1 and res["checks"].get("prop_job_level") \
    and res["checks"].get("compare_modes") == 2
(HERE / "t056_check.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(res, ensure_ascii=False, indent=2))
