# -*- coding: utf-8 -*-
from playwright.sync_api import sync_playwright
JS = """() => {
  const t = [...document.querySelectorAll('#proj-tree > li.tnode')].map(li => li.innerText.split('\\n').join(' | ').slice(0, 90));
  return {top: t, tabs: [...document.querySelectorAll('.vtab')].map(x => x.textContent)};
}"""
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                          headless=True, args=["--use-gl=angle", "--use-angle=swiftshader"])
    page = b.new_page(viewport={"width": 1560, "height": 960})
    page.goto("http://127.0.0.1:8769/workspace/pro/index.html")
    page.wait_for_timeout(2500)
    r = page.evaluate(JS)
    print("top nodes:", len(r["top"]))
    for n in r["top"]:
        print(repr(n))
    print("tabs:", r["tabs"])
    b.close()
