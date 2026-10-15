# -*- coding: utf-8 -*-
"""T-056b PRO 工作台项目树为人重做 · 无头验收
左=患者项目树（分组/可读标签/强化选中）｜metricKeyOf 前缀回退已删（变体不得继承指标）
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

    # C1 左栏 = 患者项目树：分组 / 可读标签 / 无裸 UUID
    res["checks"]["proj_nodes"] = page.locator("#proj-tree > li.tnode").count()
    res["checks"]["groups"] = [g.strip() for g in page.locator("#proj-tree > li.tgroup").all_text_contents()]
    tree_text = page.locator("#proj-tree").text_content() or ""
    res["checks"]["tree_has_ct_import"] = "CT 导入" in tree_text
    res["checks"]["tree_no_raw_uuid"] = "u_0" not in tree_text and "u_f" not in tree_text
    res["checks"]["tree_has_b15_label"] = "b15 · 工程试算" in tree_text
    res["checks"]["tree_has_t029a_label"] = "T-029a" in tree_text
    res["checks"]["import_failed_visible"] = "导入失败" in tree_text
    res["checks"]["proj_count_label"] = page.locator("#proj-count").text_content()

    # C2 b15_engineering（唯一「已核验指标」子行）→ 展开 8 节点（5◇+3✓）
    b15 = page.locator("#proj-tree > li.tnode", has_text="已核验指标")
    res["checks"]["b15_found"] = b15.count() == 1
    if b15.count():
        b15.first.click()
        page.wait_for_timeout(800)
        res["checks"]["flow_children"] = page.locator("#proj-tree li.tnode.child").count()
        res["checks"]["flow_norec"] = page.locator("#proj-tree li.tnode.child .st.norec").count()
        res["checks"]["flow_done"] = page.locator("#proj-tree li.tnode.child .st.done").count()

        # C3 点「04 几何」子节点 → 属性面板节点详情 + 视图跳三维
        page.locator("#proj-tree li.tnode.child", has_text="04 几何").click()
        page.wait_for_timeout(800)
        prop = page.locator("#prop-body").text_content() or ""
        res["checks"]["prop_has_dep"] = "上游依赖" in prop
        res["checks"]["view_geometry_on"] = page.locator(".vtab.on").text_content()

    # C2b T-029a 变体（唯一标签定位；注意 reference_channel 也可能显示「求解失败」）：
    # 求解失败 → config ✗ + post/report ⊘（stale），且不得显示 b15 指标
    t029a = page.locator("#proj-tree > li.tnode", has_text="T-029a")
    res["checks"]["t029a_found"] = t029a.count() == 1
    if t029a.count():
        t029a.first.click()
        page.wait_for_timeout(800)
        res["checks"]["t029a_children"] = page.locator("#proj-tree li.tnode.child").count()
        res["checks"]["t029a_norec"] = page.locator("#proj-tree li.tnode.child .st.norec").count()
        res["checks"]["t029a_fail"] = page.locator("#proj-tree li.tnode.child .st.fail").count()
        res["checks"]["t029a_stale"] = page.locator("#proj-tree li.tnode.child .st.stale").count()
        prop_t = page.locator("#prop-body").text_content() or ""
        res["checks"]["t029a_no_metrics_leak"] = ("已核验功能指标" not in prop_t) and ("0.0411" not in prop_t)
        res["checks"]["t029a_prop_project"] = "患者项目" in prop_t
        page.screenshot(path=str(HERE / "t056b_tree.png"))

    # C4 回 b15 → 项目级属性含已核验指标
    page.locator("#proj-tree > li.tnode", has_text="已核验指标").first.click()
    page.wait_for_timeout(600)
    prop2 = page.locator("#prop-body").text_content() or ""
    res["checks"]["prop_project_level"] = ("患者项目" in prop2) and ("已核验功能指标" in prop2)
    page.screenshot(path=str(HERE / "t056b_b15_props.png"))

    # C5 任务控制台：刷新按钮在视图头部；点行 → 任务属性
    page.locator(".vtab", has_text="任务控制台").click()
    page.wait_for_timeout(800)
    res["checks"]["jobs_refresh_btn"] = page.locator(".jobs-head .icon-btn").count()
    rows = page.locator(".jobs-table tr").count()
    if rows > 1:
        page.locator(".jobs-table tr").nth(1).click()
        page.wait_for_timeout(600)
        prop3 = page.locator("#prop-body").text_content() or ""
        res["checks"]["prop_job_level"] = ("任务 ID" in prop3) and ("退出码" in prop3)

    # C6 对比视图：V1/V2 仍在
    page.locator(".vtab", has_text="对比").click()
    page.wait_for_timeout(800)
    res["checks"]["compare_modes"] = page.locator(".cmp-bar .vtab").count()

    b.close()

res["ok"] = (not res["errors"]) and (not res["external"]) \
    and res["checks"].get("proj_nodes") == 13 \
    and len(res["checks"].get("groups", [])) == 3 \
    and res["checks"].get("tree_has_ct_import") \
    and res["checks"].get("tree_no_raw_uuid") \
    and res["checks"].get("tree_has_b15_label") \
    and res["checks"].get("tree_has_t029a_label") \
    and res["checks"].get("import_failed_visible") \
    and res["checks"].get("b15_found") \
    and res["checks"].get("flow_children") == 8 \
    and res["checks"].get("flow_norec") == 5 and res["checks"].get("flow_done") == 3 \
    and res["checks"].get("prop_has_dep") and res["checks"].get("view_geometry_on") == "三维检查" \
    and res["checks"].get("t029a_found") \
    and res["checks"].get("t029a_children") == 8 \
    and res["checks"].get("t029a_norec") == 5 \
    and res["checks"].get("t029a_fail") == 1 and res["checks"].get("t029a_stale") == 2 \
    and res["checks"].get("t029a_no_metrics_leak") \
    and res["checks"].get("prop_project_level") \
    and res["checks"].get("jobs_refresh_btn") == 1 and res["checks"].get("prop_job_level") \
    and res["checks"].get("compare_modes") == 2
(HERE / "t056b_check.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(res, ensure_ascii=False, indent=2))
