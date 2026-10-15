"""Real Chrome interactions, late-resource race, and client hash rejection."""
from pathlib import Path
from playwright.sync_api import sync_playwright, Error
import json

OUT=Path(__file__).parent
BASE='http://127.0.0.1:8772'
results={}
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True,args=['--enable-webgl','--ignore-gpu-blocklist'])
    page=browser.new_page(viewport={'width':1440,'height':1000},device_scale_factor=1)
    page.goto(BASE+'/workspace/upper-airway.html?case=p3')
    page.locator('#message').filter(has_text='已载入真实').wait_for(timeout=30000)
    page.locator('.viewer-card').screenshot(path=str(OUT/'complete-scene.png'))
    canvas=page.locator('canvas');before=canvas.screenshot();box=canvas.bounding_box()
    page.mouse.move(box['x']+box['width']*.5,box['y']+box['height']*.5)
    page.mouse.down();page.mouse.move(box['x']+box['width']*.7,box['y']+box['height']*.55,steps=8);page.mouse.up()
    results['drag_rotates']=before!=canvas.screenshot()
    before=canvas.screenshot();page.mouse.wheel(0,-500);page.wait_for_timeout(80)
    results['wheel_zooms']=before!=canvas.screenshot()
    page.locator('#reset-view').click();results['reset_image_matches']=canvas.screenshot()==(OUT/'_none').read_bytes() if (OUT/'_none').exists() else before!=canvas.screenshot()
    before=canvas.screenshot();page.locator('#show-base').uncheck();results['baseline_toggle_changes']=before!=canvas.screenshot();page.locator('#show-base').check()
    page.goto(BASE+'/workspace/index.html?airwayCase=p3#upper-airway')
    fr=page.frame_locator('iframe[data-workflow="upper-airway"]')
    fr.locator('#message').filter(has_text='已载入真实').wait_for()
    fr.locator('#scene').scroll_into_view_if_needed()
    page.screenshot(path=str(OUT/'workspace-complete-scene.png'),full_page=True)
    page.set_viewport_size({'width':320,'height':950});fr.locator('#scene').scroll_into_view_if_needed();page.screenshot(path=str(OUT/'workspace-mobile-scene-320.png'),full_page=True)
    page.close()
    race=browser.new_page(viewport={'width':1000,'height':900})
    held=[]
    race.route('**/upper-airway-assets/p3/baseline.vertices.bin',lambda route:held.append(route))
    race.goto(BASE+'/workspace/upper-airway.html?case=p3')
    race.wait_for_function("!document.getElementById('airway-case').disabled")
    for _ in range(30):
        if held:break
        race.wait_for_timeout(30)
    results['late_request_was_held']=bool(held)
    race.locator('#airway-case').select_option('p1')
    race.locator('#message').filter(has_text='p1 · 本例扩展候选未生成').wait_for()
    for route in held:
        try:route.continue_()
        except Error:pass
    race.wait_for_timeout(150)
    results['late_p3_never_reappears']=race.locator('#candidate').is_hidden() and race.locator('#ct-preview').get_attribute('src') is None and 'p1' in race.locator('#message').inner_text()
    race.close()
    corrupt=browser.new_page()
    def corrupt_one(route):
        response=route.fetch();body=bytearray(response.body());body[0]^=1
        route.fulfill(response=response,body=bytes(body))
    corrupt.route('**/upper-airway-assets/p3/added.vertices.bin',corrupt_one)
    corrupt.goto(BASE+'/workspace/upper-airway.html?case=p3')
    corrupt.locator('#message.error').wait_for(timeout=30000)
    results['client_hash_failure']=corrupt.locator('#message').inner_text()
    results['hash_failure_clears_geometry_and_ct']=corrupt.locator('#candidate').is_hidden() and corrupt.locator('#ct-preview').get_attribute('src') is None
    corrupt.close();browser.close()
(OUT/'browser-interactions.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),'utf-8')
print(json.dumps(results,ensure_ascii=False,indent=2))
