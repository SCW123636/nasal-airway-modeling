"""T-058 工作台接入验收：患者树含 b01/b02、三维检查页回退到解剖切检视页、零 pageerror。

配方（项目约定，勿改）：系统 py3.10 + playwright + 本机 Chrome + swiftshader；
WebGL 走软件渲染，page.screenshot 需放宽超时。
"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent
URL = 'http://127.0.0.1:8769/workspace/pro/index.html'
CHROME = r'C:\Program Files\Google\Chrome\Application\chrome.exe'

report = {'url': URL, 'tree': [], 'steps': [], 'pageerrors': [], 'console_errors': []}

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=True,
                          args=['--use-gl=angle', '--use-angle=swiftshader'])
    page = b.new_page(viewport={'width': 1500, 'height': 940})
    page.on('pageerror', lambda e: report['pageerrors'].append(str(e)))
    page.on('console', lambda m: report['console_errors'].append(m.text)
            if m.type == 'error' else None)

    page.goto(URL, wait_until='domcontentloaded')
    page.wait_for_timeout(2500)

    # 1) 患者树条目
    report['tree'] = page.eval_on_selector_all(
        '#proj-tree .tnode', 'els => els.map(e => e.innerText.replace(/\\n/g, " | "))')
    page.screenshot(path=str(OUT / 'pro_tree.png'), timeout=120000)

    def pick(label):
        """点选树中标签含 label 的项目节点（非子节点）"""
        node = page.locator('#proj-tree .tnode:not(.child)',
                            has_text=label).first
        node.click()
        page.wait_for_timeout(1200)

    def iframe_src():
        f = page.locator('#view-body iframe')
        return f.get_attribute('src') if f.count() else None

    # 2) 逐个患者 → 三维检查页应指向解剖切检视页
    for case, want in [('b15 · 解剖斜切', 'case=b15'),
                       ('b01 · 解剖斜切', 'case=b01'),
                       ('b02 · 解剖斜切', 'case=b02')]:
        pick(case)
        tab = page.locator('.vtab', has_text='三维检查').first
        tab.click()
        page.wait_for_timeout(2500)
        src = iframe_src()
        rec = {'case': case, 'iframe': src,
               'ok': bool(src and 't058_cut.html' in src and want in src and 'embedded=1' in src)}
        # 属性面板是否出现搬运清单
        rec['prop_has_manifest'] = '已核验搬运清单' in page.inner_text('#prop-body')
        rec['prop_has_metrics'] = '已核验功能指标' in page.inner_text('#prop-body')
        report['steps'].append(rec)

    # 3) b15 三维检视页截图（含嵌入的 WebGL 场景）
    pick('b15 · 解剖斜切')
    page.locator('.vtab', has_text='三维检查').first.click()
    page.wait_for_timeout(6000)
    page.screenshot(path=str(OUT / 'pro_geometry_b15.png'), timeout=120000)

    # 4) 对比页：b02 是否可选
    page.locator('.vtab', has_text='对比').first.click()
    page.wait_for_timeout(1200)
    opts = page.eval_on_selector_all('.cmp-bar select option', 'els => els.map(e => e.value)')
    report['compare_options'] = opts
    page.screenshot(path=str(OUT / 'pro_compare.png'), timeout=120000)

    b.close()

report['all_ok'] = (not report['pageerrors']
                    and all(s['ok'] for s in report['steps']))
(OUT / 'pro_workbench_check.json').write_text(
    json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')

print(json.dumps(report, ensure_ascii=False, indent=1))
sys.exit(0 if report['all_ok'] else 1)
