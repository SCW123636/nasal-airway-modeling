# -*- coding: utf-8 -*-
"""T-064 三维检查单视口合并（模型+流线同框）· 无头验收
判据：
  P1 三维检查页只有一个 iframe（不再上下两栏），且 src 带 &sl=（b15 有流线）
  P2 t058_cut 内部：cLines 开关可见、图例带速度范围、场景里流线组可见（截图目视同框）
  P3 b01/b02 项目同样挂上各自 sl（点树切换核 iframe src）
  P4 直开 t058_cut.html?case=b02&sl=... 图例出现（诚实降级链路通）
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
URL = "http://127.0.0.1:8769/workspace/pro/index.html"
res = {"errors": [], "checks": {}, "shots": []}

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                          headless=True, args=["--use-gl=angle", "--use-angle=swiftshader"])
    page = b.new_page(viewport={"width": 1560, "height": 960})
    page.on("pageerror", lambda e: res["errors"].append(str(e)))
    page.goto(URL)
    page.wait_for_timeout(2500)

    # P1 选中 b15 → 三维检查 tab → 单 iframe 且带 sl
    b15 = page.locator("#proj-tree > li.tnode", has_text="b15 · 解剖斜切")
    b15.first.click()
    page.wait_for_timeout(600)
    geo_tab = page.locator(".vtab", has_text="三维检查")
    geo_tab.click()
    page.wait_for_timeout(4000)
    frames_src = page.evaluate("""() => [...document.querySelectorAll('#view-body iframe')].map(f => f.src)""")
    res["checks"]["iframe_count"] = len(frames_src)
    res["checks"]["has_sl_param"] = any("sl=" in s for s in frames_src)
    res["checks"]["sl_url"] = next((s for s in frames_src if "sl=" in s), "")
    page.screenshot(path=str(HERE / "t064_geo_b15.png")); res["shots"].append("t064_geo_b15.png")

    # P2 iframe 内部：流线开关可见 + 图例文字
    fr = page.frame_locator("#view-body iframe").first
    res["checks"]["cLines_visible"] = fr.locator("#wrapLines").is_visible()
    res["checks"]["legend_text"] = (fr.locator("#legSpd").text_content() or "").strip()
    page.wait_for_timeout(1500)
    page.screenshot(path=str(HERE / "t064_geo_b15_settled.png")); res["shots"].append("t064_geo_b15_settled.png")

    # P3 切到 b01 / b02 → 各自 sl
    for case in ("b01 · 解剖斜切", "b02 · 解剖斜切"):
        node = page.locator("#proj-tree > li.tnode", has_text=case)
        node.first.click()
        page.wait_for_timeout(4500)
        srcs = page.evaluate("""() => [...document.querySelectorAll('#view-body iframe')].map(f => f.src)""")
        key = case.split(" ")[0]
        res["checks"][key + "_iframe_n"] = len(srcs)
        res["checks"][key + "_sl"] = next((s.split("sl=")[1].split("&")[0] for s in srcs if "sl=" in s), "")
        page.screenshot(path=str(HERE / ("t064_geo_%s.png" % key)))
        res["shots"].append("t064_geo_%s.png" % key)

    # P4 直开 t058_cut 带 sl（b02）→ 图例 + 开关
    page2 = b.new_page(viewport={"width": 1400, "height": 900})
    page2.on("pageerror", lambda e: res["errors"].append("p2:" + str(e)))
    page2.goto("http://127.0.0.1:8769/workspace/t058_cut.html?case=b02&sl=/workspace/pro/artifacts/streamlines_b02_anat_t600.lines.json")
    page2.wait_for_timeout(6000)
    res["checks"]["direct_wrapLines_visible"] = page2.locator("#wrapLines").is_visible()
    res["checks"]["direct_legend"] = (page2.locator("#legSpd").text_content() or "").strip()
    page2.screenshot(path=str(HERE / "t064_direct_b02.png")); res["shots"].append("t064_direct_b02.png")

    b.close()

res["pass"] = (not res["errors"]
               and res["checks"].get("iframe_count") == 1
               and res["checks"].get("has_sl_param")
               and res["checks"].get("cLines_visible")
               and bool(res["checks"].get("legend_text"))
               and res["checks"].get("b01_sl", "").endswith("streamlines_b01_anat_t600.lines.json")
               and res["checks"].get("b02_sl", "").endswith("streamlines_b02_anat_t600.lines.json")
               and res["checks"].get("direct_wrapLines_visible"))
(HERE / "t064_check.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(res, ensure_ascii=False, indent=2))
print("PASS" if res["pass"] else "FAIL")
