# -*- coding: utf-8 -*-
"""quick check: natsplit streamline html renders with data."""
import pathlib
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
target = HERE / "streamlines_b15_natsplit_lam052_t600.html"
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                          headless=True)
    pg = b.new_page(viewport={"width": 1400, "height": 900})
    pg.goto(target.as_uri())
    pg.wait_for_timeout(4500)
    n = pg.evaluate("() => (typeof DATA !== 'undefined' && DATA.LINE_DATA) ? DATA.LINE_DATA.length : -1")
    title = pg.title()
    print("lines in page:", n, "| title:", title)
    pg.screenshot(path=str(HERE / "natsplit_html_check.png"))
    b.close()
