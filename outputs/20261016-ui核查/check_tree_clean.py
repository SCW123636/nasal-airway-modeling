# -*- coding: utf-8 -*-
"""工作台残留清除验收：CT 导入组与 u_* 条目应全部消失，其余患者树不受影响。

用法：系统 py3.10 + playwright + 本机 Chrome（同 outputs/T-056/check_p3.py 配方）。
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

    texts = page.locator("#proj-tree li").all_text_contents()
    labels = [t.strip() for t in texts]
    res["checks"]["all_nodes"] = labels
    res["checks"]["group_headers"] = [t.strip() for t in page.locator("#proj-tree > li.tgroup").all_text_contents()]
    res["checks"]["ct_import_header"] = page.locator("#proj-tree > li.tgroup", has_text="CT 导入").count()
    res["checks"]["ct_import_nodes"] = page.locator("#proj-tree > li.tnode", has_text="CT 导入 ·").count()
    res["checks"]["u_entries"] = sum(1 for t in labels if "u_" in t)
    res["checks"]["proj_count_label"] = page.locator("#proj-count").text_content()
    res["checks"]["proj_nodes"] = page.locator("#proj-tree > li.tnode").count()

    page.screenshot(path=str(HERE / "tree_after_cleanup.png"))
    # 左树单独截图（看清条目）
    tree = page.locator("#proj-tree")
    if tree.count():
        tree.screenshot(path=str(HERE / "tree_after_cleanup_left.png"))
    b.close()

res["ok"] = (not res["errors"]) and (not res["external"]) \
    and res["checks"]["ct_import_header"] == 0 \
    and res["checks"]["ct_import_nodes"] == 0 \
    and res["checks"]["u_entries"] == 0
(HERE / "tree_cleanup_check.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(res, ensure_ascii=False, indent=2))
