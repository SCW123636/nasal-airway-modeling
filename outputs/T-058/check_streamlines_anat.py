"""T-058 解剖切流线接入验收：工作台「流线」页应显示解剖切产物（b15），零 pageerror。

配方（项目约定，勿改）：系统 py3.10 + playwright + 本机 Chrome + swiftshader。
"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent
URL = 'http://127.0.0.1:8769/workspace/pro/index.html'
ART = 'http://127.0.0.1:8769/workspace/pro/artifacts/streamlines_b15_anat_t600.html'
CHROME = r'C:\Program Files\Google\Chrome\Application\chrome.exe'

report = {'url': URL, 'artifact_url': ART, 'items': [], 'pageerrors': [], 'console_errors': []}

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=True,
                          args=['--use-gl=angle', '--use-angle=swiftshader'])
    page = b.new_page(viewport={'width': 1500, 'height': 940})
    page.on('pageerror', lambda e: report['pageerrors'].append(str(e)))
    page.on('console', lambda m: report['console_errors'].append(m.text)
            if m.type == 'error' else None)

    page.goto(URL, wait_until='domcontentloaded')
    page.wait_for_timeout(2500)

    # 选 b15（树节点）
    node = page.locator('#proj-tree .tnode:not(.child)', has_text='b15').first
    node.click()
    page.wait_for_timeout(1200)

    # 切「流线」页
    page.locator('.vtab', has_text='流线').first.click()
    page.wait_for_timeout(7000)
    f = page.locator('#view-body iframe')
    src = f.get_attribute('src') if f.count() else None
    note = page.inner_text('#view-body')
    report['items'].append({
        'iframe': src,
        'ok': bool(src and 'streamlines_b15_anat_t600.html' in src),
        'note_has_anat': ('解剖斜切' in note),
    })
    page.screenshot(path=str(OUT / 'pro_streamlines_anat.png'), timeout=120000)

    # 直开产物页
    page2 = b.new_page(viewport={'width': 1280, 'height': 840})
    page2.on('pageerror', lambda e: report['pageerrors'].append('artifact: ' + str(e)))
    page2.goto(ART, wait_until='domcontentloaded')
    page2.wait_for_timeout(7000)
    page2.screenshot(path=str(OUT / 'streamlines_anat_page.png'), timeout=120000)
    report['artifact_title'] = page2.title()

    b.close()

report['all_ok'] = (not report['pageerrors'] and all(i['ok'] for i in report['items']))
(OUT / 'check_streamlines_anat.json').write_text(
    json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=1))
sys.exit(0 if report['all_ok'] else 1)
