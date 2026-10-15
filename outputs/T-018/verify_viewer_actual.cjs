'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
const crypto=require('node:crypto');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const base=process.argv[2]||'http://127.0.0.1:8769';
const job=process.argv[3]||'s_970bd197fb3b41d289170ceb';
const out=path.resolve(process.argv[4]||'outputs/T-018/viewer_browser');
const report={base,job,checks:[],errors:[],failed:[],snapshots:[]};
const check=(name,passed,detail)=>{report.checks.push({name,passed:Boolean(passed),detail});if(!passed)throw new Error(name+(detail?': '+detail:''));};
async function main(){
  await fs.mkdir(out,{recursive:true});
  const browser=await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000},deviceScaleFactor:1});page.setDefaultTimeout(20000);
  page.on('pageerror',e=>report.errors.push(e.message));page.on('console',m=>{if(m.type()==='error')report.errors.push(m.text())});page.on('response',r=>{if(r.status()>=400&&!r.url().includes('favicon'))report.failed.push({url:r.url(),status:r.status()})});
  try{
    await page.goto(`${base}/viewer/index.html?manifest=/simulation-assets/${job}/viewer.json`);
    await page.locator('#scene-state').waitFor({state:'hidden'});
    const frame=page;
    const snap=()=>frame.evaluate(async()=>{const s=(await import('/viewer/viewer.js')).getDisplaySnapshot();const dig=a=>crypto.subtle.digest('SHA-256',new Float64Array(a));const hex=async a=>[...new Uint8Array(await dig(a))].map(x=>x.toString(16).padStart(2,'0')).join('');return {...s,positions:undefined,indices:undefined,positionSha256:await hex(s.positions),indexSha256:await hex(s.indices),vertices:s.positions.length/3,faces:s.indices.length/3};});
    const first=await snap();check('actual job manifest loads',first.caseId===job&&first.vertices>100&&first.faces>100,first);check('actual result defaults smooth',first.mode==='smooth'&&first.pixelRatio>=1.5&&first.pixelRatio<=2,first);
    check('actual fields shown',await frame.locator('#field-status').innerText().then(x=>/速度|压力/.test(x)),await frame.locator('#field-status').innerText());
    for(const mode of ['smooth','facets','wireframe']){await frame.locator(`[data-display="${mode}"]`).click();const s=await snap();check('mode preserves actual geometry '+mode,s.positionSha256===first.positionSha256&&s.indexSha256===first.indexSha256&&JSON.stringify(s.camera)===JSON.stringify(first.camera)&&JSON.stringify(s.target)===JSON.stringify(first.target),s);await frame.locator('#scene').screenshot({path:path.join(out,`mode-${mode}.png`)});report.snapshots.push({mode,vertices:s.vertices,faces:s.faces,positionSha256:s.positionSha256,indexSha256:s.indexSha256});}
    await frame.locator('[data-display="smooth"]').click();
    check('viewer has three opening options',await frame.locator('#plane-select option').count()===3,await frame.locator('#plane-select').innerText());
    for(const id of ['nostril_L','nostril_R','nasopharynx_outlet']){await frame.locator('#plane-select').selectOption(id);const s=await snap();check('plane preserves actual geometry '+id,s.positionSha256===first.positionSha256&&s.indexSha256===first.indexSha256&&s.plane?.landmarkId===id,s.plane);await frame.screenshot({path:path.join(out,`plane-${id}.png`)});}
    check('no console/page/network errors',report.errors.length===0&&report.failed.length===0,{errors:report.errors,failed:report.failed});
    await frame.setViewportSize({width:390,height:844});check('narrow viewer has no horizontal overflow',await frame.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),await frame.evaluate(()=>({scrollWidth:document.documentElement.scrollWidth,innerWidth})));await frame.screenshot({path:path.join(out,'mobile-390.png'),fullPage:true});
  } finally {await browser.close();await fs.writeFile(path.join(out,'actual_viewer_report.json'),JSON.stringify(report,null,2));}
  console.log(JSON.stringify({checks:report.checks.length,errors:report.errors,failed:report.failed,report:path.join(out,'actual_viewer_report.json')}));
}
main().catch(e=>{console.error(e.stack||e);process.exitCode=1});
