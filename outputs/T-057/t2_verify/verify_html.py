import sys
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8769/workspace/pro/artifacts/streamlines_b15_oroext_t600.html"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
OUT_PNG = r"D:/项目/鼻腔建模/outputs/T-057/t2_verify/streamlines_render.png"

errors = []
console_errs = []

with sync_playwright() as p:
    browser = p.chromium.launch(
        executable_path=CHROME,
        headless=True,
        args=["--use-gl=swiftshader", "--no-sandbox",
              "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist",
              "--disable-dev-shm-usage"],
    )
    page = browser.new_page(viewport={"width": 1280, "height": 860})
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: console_errs.append((m.type, m.text)) if m.type in ("error", "warning") else None)
    page.goto(URL, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(3500)  # 给 WebGL 渲染与动画循环时间

    res = page.evaluate(
        """() => {
            const out = {};
            out.hasData = (typeof DATA !== 'undefined');
            out.nLines = (typeof DATA !== 'undefined') ? DATA.LINE_DATA.length : -1;
            out.canvases = document.querySelectorAll('canvas').length;
            // 主 3D canvas 是否拿到 WebGL 上下文并真的画了像素
            const cv = document.querySelector('#view canvas');
            out.mainCanvas = !!cv;
            if (cv) {
                const gl = cv.getContext('webgl2') || cv.getContext('webgl');
                out.hasWebGL = !!gl;
                out.canvasW = cv.width; out.canvasH = cv.height;
                // 通过 toDataURL 估计非空白（背景是 eef3f1 浅色，线/壁面是彩色）
                const url = cv.toDataURL('image/png');
                out.dataUrlLen = url.length;
            }
            // 页面文字里应出现 111 / 10 等读数
            out.bodyHas111 = document.body.innerText.includes('111');
            out.bodyHas10 = document.body.innerText.includes('10');
            return out;
        }"""
    )
    page.screenshot(path=OUT_PNG, full_page=False)
    browser.close()

print("=== 独立渲染核验 ===")
for k, v in res.items():
    print(f"{k}: {v}")
print("=== JS pageerror 数:", len(errors))
for e in errors:
    print("  PAGEERROR:", e)
print("=== console error/warning 数:", len(console_errs))
for t, m in console_errs[:20]:
    print(f"  {t}: {m}")
