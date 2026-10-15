from playwright.sync_api import sync_playwright
from pathlib import Path
import json

OUT = Path(__file__).parent
BASE = 'http://127.0.0.1:8772'
result = {}
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe', headless=True, args=['--enable-webgl', '--ignore-gpu-blocklist'])
    page = browser.new_page(viewport={'width':1440,'height':1000},device_scale_factor=1)
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(BASE+'/workspace/upper-airway.html')
    page.wait_for_function("document.getElementById('message').textContent.includes('已载入真实')",timeout=30000)
    result['message']=page.locator('#message').inner_text()
    result['canvas_count']=page.locator('canvas').count()
    page.screenshot(path=str(OUT/'desktop-first.png'),full_page=True)
    first=page.locator('canvas').screenshot()
    page.locator('#front-view').click()
    result['front_changed_image']=first!=page.locator('canvas').screenshot()
    page.locator('#show-added').uncheck()
    result['added_unchecked']=not page.locator('#show-added').is_checked()
    page.locator('#airway-case').select_option('p1')
    page.wait_for_function("document.getElementById('message').textContent.includes('本例扩展候选未生成')")
    result['p1_message']=page.locator('#message').inner_text()
    result['p1_hidden']=page.locator('#candidate').is_hidden()
    result['p1_ct_src']=page.locator('#ct-preview').get_attribute('src')
    page.reload()
    page.wait_for_function("document.getElementById('message').textContent.includes('本例扩展候选未生成')")
    result['p1_reload']=page.locator('#airway-case').input_value()
    page.goto(BASE+'/workspace/index.html?airwayCase=p3#upper-airway')
    fr=page.frame_locator('iframe[data-workflow="upper-airway"]')
    fr.locator('#message').filter(has_text='已载入真实').wait_for(timeout=30000)
    page.screenshot(path=str(OUT/'workspace-desktop-first.png'),full_page=True)
    result['outer_desktop_width']=page.evaluate('({inner:innerWidth,scroll:document.documentElement.scrollWidth})')
    fr.locator('#airway-case').select_option('p0')
    fr.locator('#message').filter(has_text='本例扩展候选未生成').wait_for()
    result['outer_p0_url']=page.url
    page.reload()
    page.frame_locator('iframe[data-workflow="upper-airway"]').locator('#message').filter(has_text='p0 · 本例扩展候选未生成').wait_for()
    result['outer_p0_reload']=True
    for width in [390,320]:
        page.set_viewport_size({'width':width,'height':950})
        page.goto(BASE+'/workspace/index.html?airwayCase=p3#upper-airway')
        fr=page.frame_locator('iframe[data-workflow="upper-airway"]')
        fr.locator('#message').filter(has_text='已载入真实').wait_for(timeout=30000)
        page.screenshot(path=str(OUT/f'workspace-mobile-{width}.png'),full_page=True)
        result[f'outer_width_{width}']=page.evaluate('({inner:innerWidth,scroll:document.documentElement.scrollWidth})')
        result[f'inner_width_{width}']=fr.locator('body').evaluate('(e)=>({inner:innerWidth,scroll:document.documentElement.scrollWidth})')
    page.goto(BASE+'/workspace/upper-airway.html?case=p2')
    page.locator('#message').filter(has_text='本例扩展候选未生成').wait_for()
    result['p2_no_fallback']=page.locator('#candidate').is_hidden()
    page.goto(BASE+'/workspace/upper-airway.html?case=unknown')
    page.locator('#message.error').wait_for()
    result['unknown_message']=page.locator('#message').inner_text()
    result['unknown_no_fallback']=page.locator('#candidate').is_hidden()
    page.goto(BASE+'/workspace/upper-airway.html?uploadContext=u_0123456789abcdef')
    page.locator('#message').filter(has_text='请选择独立工程扫描').wait_for()
    result['upload_context_no_auto_p3']=page.locator('#candidate').is_hidden() and page.locator('#airway-case').input_value()==''
    result['errors']=errors
    browser.close()
(OUT/'browser-first.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
