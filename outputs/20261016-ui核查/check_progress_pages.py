# -*- coding: utf-8 -*-
"""进度页重建验收：cards 页 + 总览页渲染截图 + 关键内容断言。"""
import json, sys, pathlib
from playwright.sync_api import sync_playwright

OUT = "D:/项目/鼻腔建模/outputs/20261016-ui核查"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PAGES = [
    ("cards", "http://127.0.0.1:8769/workspace/progress-cards.html", False),
    # 总览页经 embed.js 的 tool-presentation 设计：非嵌入访问会跳进 /workspace/index.html#overview，
    # 故用本地 wrapper iframe + ?embedded=1 验证真实渲染路径
    ("dashboard", str(pathlib.Path(f"{OUT}/embed_wrapper.html").resolve().as_uri()), True),
]
EXPECT = {
    "cards": ["T-057", "T-058", "T-043", "VERIFIED", "不一致 0"],
    "dashboard": ["T-057", "T-058", "T-043"],
}

result = {"ok": False, "errors": [], "checks": {}}
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=True,
                          args=["--use-gl=swiftshader", "--no-sandbox"])
    for name, url, embedded in PAGES:
        pg = b.new_page(viewport={"width": 1600, "height": 1000})
        msgs = []
        pg.on("pageerror", lambda e: msgs.append(str(e)[:200]))
        resp = pg.goto(url, wait_until="networkidle", timeout=25000)
        pg.wait_for_timeout(1200)
        code = resp.status if resp else 0
        if embedded:
            fr = pg.frame_locator("#f")
            fr.locator("body").evaluate("() => document.querySelectorAll('details').forEach(d => d.open = true)")
            pg.wait_for_timeout(300)
            txt = fr.locator("body").inner_text() or ""
        else:
            txt = pg.inner_text("body") or ""
        pg.screenshot(path=f"{OUT}/progress_{name}.png", full_page=False)
        result["checks"][f"{name}_http"] = code
        result["checks"][f"{name}_text_ok"] = all(e in txt for e in EXPECT[name])
        if msgs:
            result["errors"].append({"page": name, "msgs": msgs})
        pg.close()
    b.close()

result["ok"] = (not result["errors"]) and all(
    v for k, v in result["checks"].items() if k.endswith("_text_ok")) and all(
    v == 200 for k, v in result["checks"].items() if k.endswith("_http"))
print(json.dumps(result, ensure_ascii=False, indent=1))
with open(f"{OUT}/progress_rebuild_check.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=1)
sys.exit(0 if result["ok"] else 2)
