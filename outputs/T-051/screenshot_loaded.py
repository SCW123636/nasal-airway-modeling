# -*- coding: utf-8 -*-
"""工作台计算页带数据状态截图（选病例+选任务）"""
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent
BASE = "http://127.0.0.1:8769"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=True,
                          args=["--use-gl=angle", "--use-angle=swiftshader"])
    page = b.new_page(viewport={"width": 1500, "height": 950}, device_scale_factor=1)
    page.goto(BASE + "/workspace/index.html#validation")
    page.wait_for_timeout(6000)
    # 选第一个任务记录（若有）
    rows = page.locator(".simulation-job-row")
    n = rows.count()
    print("job rows:", n)
    if n:
        rows.first.click()
        page.wait_for_timeout(4000)
    page.screenshot(path=str(OUT / "base_validation_loaded.png"), full_page=True)
    b.close()
print("done")
