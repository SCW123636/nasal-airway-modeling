# T-063 验收：三维检查合并 tab + 对比页流线叠加
# 场景A: pro 页 geometry tab = 上下两栏（模型+流线），tab 数=3，零 JS 报错
# 场景B: cmp 页带 sa 参数 → 流线层加载（图例出现 + 截图可见线）
# 场景C: cmp 页无 sa → 无流线（图例隐藏，诚实降级）
import json, sys
from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
OUT = r"D:\项目\鼻腔建模\outputs\20261016-ui核查"
result = {"checks": {}, "errors": []}

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=True,
                          args=["--use-gl=swiftshader", "--no-sandbox"])

    # --- 场景 A：pro 页 ---
    pg = b.new_page(viewport={"width": 1500, "height": 950})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)[:200]))
    pg.goto("http://127.0.0.1:8769/workspace/pro/index.html", wait_until="networkidle", timeout=25000)
    pg.wait_for_timeout(600)
    tabs = pg.eval_on_selector_all("#view-tabs button", "els => els.map(e => e.textContent)")
    result["checks"]["tab_count"] = len(tabs)
    result["checks"]["tab_labels"] = tabs
    # 点 b15 树节点（含「已核验」的那个）
    nodes = pg.query_selector_all("li.tnode")
    picked = False
    for n in nodes:
        t = (n.inner_text() or "").strip()
        if "b15" in t and "已核验" in t:
            n.click(); picked = True; break
    if not picked:
        for n in nodes:
            t = (n.inner_text() or "").strip()
            if t.endswith("b15") or "\nb15 " in "\n" + t:
                n.click(); picked = True; break
    result["checks"]["b15_picked"] = picked
    pg.wait_for_timeout(500)
    # 确保 geometry tab 激活
    on = pg.eval_on_selector_all("#view-tabs button", "els => els.map(e => e.textContent)")
    if "三维检查" in on:
        for btn in pg.query_selector_all("#view-tabs button"):
            if btn.inner_text() == "三维检查": btn.click(); break
        pg.wait_for_timeout(500)
    stack = pg.query_selector(".geo-stack")
    cells = pg.query_selector_all(".geo-cell")
    ifrs = pg.query_selector_all(".geo-cell iframe")
    result["checks"]["geo_stack"] = bool(stack)
    result["checks"]["geo_cells"] = len(cells)
    result["checks"]["geo_iframes"] = len(ifrs)
    if stack:
        stack.screenshot(path=OUT + r"\t063_geo_stack.png")
    pg.screenshot(path=OUT + r"\t063_pro_full.png")
    if errs: result["errors"].append({"page": "pro", "msgs": errs})
    pg.close()

    # --- 场景 B：cmp 页带流线 ---
    pg2 = b.new_page(viewport={"width": 1400, "height": 800})
    errs2, cons = [], []
    pg2.on("pageerror", lambda e: errs2.append(str(e)[:200]))
    pg2.on("console", lambda m: cons.append(m.text) if m.type == "error" else None)
    url_b = ("http://127.0.0.1:8769/workspace/t058_cmp.html?a=b15&b=b01"
             "&sa=/workspace/pro/artifacts/streamlines_b15_anat_t600.lines.json&embedded=1")
    pg2.goto(url_b, wait_until="networkidle", timeout=30000)
    pg2.wait_for_timeout(2500)
    wrap_vis = pg2.eval_on_selector("#wrapLines", "e => e.style.display !== 'none'")
    leg_txt = pg2.eval_on_selector("#legSpd", "e => e.textContent") if wrap_vis else ""
    canvas = pg2.query_selector("#stage canvas")
    result["checks"]["cmp_lines_toggle_visible"] = bool(wrap_vis)
    result["checks"]["cmp_legend_text"] = leg_txt
    result["checks"]["cmp_canvas"] = bool(canvas)
    pg2.screenshot(path=OUT + r"\t063_cmp_with_lines.png")
    if errs2: result["errors"].append({"page": "cmp-lines", "msgs": errs2})
    # 50x50 中心取样检查画布非纯背景（线已画）
    if canvas:
        colors = pg2.evaluate("""() => {
          const cv = document.querySelector('#stage canvas');
          const gl = cv.getContext('webgl2') || cv.getContext('webgl');
          const px = new Uint8Array(4 * 400);
          gl.readPixels(Math.floor(gl.drawingBufferWidth*0.25), Math.floor(gl.drawingBufferHeight*0.5), 20, 20, gl.RGBA, gl.UNSIGNED_BYTE, px);
          const set = new Set(); for (let i=0;i<px.length;i+=4) set.add(px[i]+','+px[i+1]+','+px[i+2]);
          return set.size;
        }""")
        result["checks"]["cmp_pixel_variety_left"] = colors
    pg2.close()

    # --- 场景 C：cmp 页无流线（降级） ---
    pg3 = b.new_page(viewport={"width": 1400, "height": 800})
    pg3.goto("http://127.0.0.1:8769/workspace/t058_cmp.html?a=b15&b=b01&embedded=1",
             wait_until="networkidle", timeout=30000)
    pg3.wait_for_timeout(2000)
    wrap3 = pg3.eval_on_selector("#wrapLines", "e => e.style.display")
    result["checks"]["degraded_legend_hidden"] = wrap3 == "none"
    pg3.screenshot(path=OUT + r"\t063_cmp_no_lines.png")
    pg3.close()
    b.close()

result["ok"] = (not result["errors"]) and result["checks"].get("tab_count") == 3 \
    and result["checks"].get("geo_iframes") == 2 and result["checks"].get("cmp_lines_toggle_visible")
print(json.dumps(result, ensure_ascii=False, indent=1))
sys.exit(0 if result["ok"] else 2)
