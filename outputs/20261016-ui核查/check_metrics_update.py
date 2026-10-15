# -*- coding: utf-8 -*-
"""T-058 欠账② 验收：patient_metrics.json 扩展域口径更新 + pro.js 三处修改。
判 UI 一律先截图：本脚本渲染对比视图（b15/b01）并抓取控制台错误。"""
import json, sys
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8769/workspace/pro/index.html"
OUT = "D:/项目/鼻腔建模/outputs/20261016-ui核查"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

result = {"ok": False, "errors": [], "checks": {}}

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=True,
                          args=["--use-gl=swiftshader", "--no-sandbox"])
    pg = b.new_page(viewport={"width": 1600, "height": 1000})
    msgs = []
    pg.on("console", lambda m: msgs.append({"type": m.type, "text": m.text[:200]}))
    pg.on("pageerror", lambda e: msgs.append({"type": "pageerror", "text": str(e)[:300]}))
    pg.goto(URL, wait_until="networkidle")
    pg.wait_for_timeout(1200)

    def dump_tree():
        nodes = pg.query_selector_all("li.tnode")
        return [(n.inner_text() or "").strip().replace("\n", " ")[:70] for n in nodes]

    def pick_patient(label, prefer=None):
        # 左树：li.tnode；同标签多节点时优先含 prefer 的（b15 有 T-029a 失败项目 + 已核验指标两个）
        cands = []
        for n in pg.query_selector_all("li.tnode"):
            t = (n.inner_text() or "").strip()
            if t.replace("\n", " ").split(" ")[0].startswith(label) or ("\n" + label) in ("\n" + t):
                cands.append((n, t))
        if not cands:
            return False
        target = None
        if prefer:
            for n, t in cands:
                if prefer in t:
                    target = n
                    break
        if target is None:
            target = cands[-1][0]  # 兜底取最后一个（通常为主项目）
        target.click()
        pg.wait_for_timeout(600)
        return True

    def open_compare():
        tabs = pg.query_selector_all(".vtab, [class*='vtab'], .view-tab")
        for t in tabs:
            if "对比" in (t.inner_text() or ""):
                t.click(); pg.wait_for_timeout(500); return True
        return False

    def ensure_ref_mode():
        # V1 = 个体 vs 参考带
        btns = pg.query_selector_all("button")
        for bt in btns:
            if "参考带" in (bt.inner_text() or ""):
                bt.click(); pg.wait_for_timeout(400); return True
        return False

    def grab_table_text():
        body = pg.query_selector(".view-native, .compare-wrap, body")
        return (body.inner_text() or "") if body else ""

    # --- b15 ---
    tree = dump_tree()
    result["tree"] = tree[:20]
    ok = pick_patient("b15", prefer="已核验指标")
    open_compare(); ensure_ref_mode()
    pg.wait_for_timeout(400)
    pg.screenshot(path=f"{OUT}/metrics_b15.png", full_page=False)
    txt15 = grab_table_text()

    # --- b01 ---
    ok01 = pick_patient("b01")
    result["checks"]["b01_picked"] = ok01
    if ok01:
        open_compare(); ensure_ref_mode()
        pg.wait_for_timeout(400)
    else:
        # b01 无 API/job 记录 → 不在左树，UI 选不到（既有局限，非本卡缺陷）。
        # 改从服务端 JSON 源核验（渲染逻辑通用，b15 已在 UI 坐实）。
        import urllib.request
        txt01 = ""
        try:
            with urllib.request.urlopen("http://127.0.0.1:8769/workspace/pro/patient_metrics.json", timeout=8) as f:
                dj = json.load(f)
            b1 = dj["patients"]["b01"]
            txt01 = json.dumps(b1, ensure_ascii=False)
            result["checks"]["b01_source"] = "served_json"
        except Exception as e:
            result["checks"]["b01_source"] = "fetch_failed: %s" % e

    b.close()

result["errors"] = [m for m in msgs if m["type"] in ("pageerror", "error")]
result["checks"] = {
    "b15_picked": ok,
    "b15_R_07307": "0.07307" in txt15,
    "b15_dp_18267": "18.267" in txt15,
    "b15_outlet_11251": "112.51" in txt15,
    "b15_wss_median": "0.0682" in txt15,
    "b15_extended_label": "extended" in txt15,
    "no_choana_band_misuse": "低于参考带" not in txt15,
    "truncation_note_shown": "工程属性" in txt15 or "FOV" in txt15,
    "b01_wss_filled": "0.0537" in txt01 and "0.001331" in txt01,
    "b01_verified": "VERIFIED" in txt01,
    "temp_row_updated": "后鼻孔" in txt15 and "未产" in txt15,
}
result["ok"] = (not result["errors"]) and all(v for k, v in result["checks"].items() if isinstance(v, bool))
print(json.dumps(result, ensure_ascii=False, indent=1))
with open(f"{OUT}/metrics_update_check.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=1)
sys.exit(0 if result["ok"] else 2)
