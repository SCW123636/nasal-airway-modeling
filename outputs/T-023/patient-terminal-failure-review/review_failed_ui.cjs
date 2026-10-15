'use strict';
// Existing task GETs only. No new task, run, export, service or monitor action.
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const base='http://127.0.0.1:8769',jobId='s_942fdbebfffd433c8fcec956',referenceId='s_1811f735241e4d75b5fdf10e';
const out=path.join(__dirname,'actual-failed-ui');
const report={at:new Date().toISOString(),job_id:jobId,checks:[],posts:[],page_errors:[]};
async function main(){
 await fs.mkdir(out,{recursive:false});
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();page.setDefaultTimeout(30000);
  page.on('pageerror',e=>report.page_errors.push(e.message));page.on('request',r=>{if(r.method()==='POST')report.posts.push(r.url());});
  await page.goto(base+'/workspace/index.html#validation');await page.waitForFunction(()=>!document.getElementById('simulation-case').disabled);
  const facts=()=>page.locator('#simulation-result dl div').evaluateAll(nodes=>Object.fromEntries(nodes.map(n=>[n.querySelector('dt').textContent,n.querySelector('dd').textContent])));
  await page.locator('#simulation-case').selectOption('reference_split_feedback');await page.locator(`[data-job-id="${referenceId}"]`).click();
  await page.waitForFunction(id=>document.getElementById('simulation-job-meta').textContent.includes(id)&&document.getElementById('simulation-result').textContent.includes('2.44425'),referenceId);
  report.prior_reference_facts=await facts();assert.equal(report.prior_reference_facts['共同入口静压 Pa'],'2.44425');
  await page.locator('#simulation-result').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'reference-before-switch.png'),fullPage:true});
  await page.locator('#simulation-case').selectOption('b15_engineering');await page.locator(`[data-job-id="${jobId}"]`).click();
  const verifyFailed=async()=>{
   await page.waitForFunction(id=>document.getElementById('simulation-job-meta').textContent.includes(id)&&document.getElementById('simulation-job-status').textContent==='失败',jobId);
   assert.equal(await page.locator('#simulation-case').inputValue(),'b15_engineering');
   assert.equal(await page.locator('#simulation-job-error').isVisible(),true);assert.match(await page.locator('#simulation-job-error').innerText(),/退出码：1/);
   const values=await facts();assert.equal(Object.keys(values).length,9);for(const value of Object.values(values))assert.equal(value,'未获得');
   const text=await page.locator('#simulation-result').innerText();assert.match(text,/本次执行未完成/);assert.match(text,/不代表共同压力反馈达标/);assert.match(text,/临床验证：未验证/);
   assert.doesNotMatch(text,/2\.44425|0\.998313|0\.499157|50%/);
   assert.equal(await page.locator('#simulation-job-assets a[href*="viewer"], #simulation-job-assets a[href$=".vtu"]').count(),0);
   assert.equal(await page.locator('#simulation-live-iteration').innerText(),'223');assert.match(await page.locator('#simulation-live-step').innerText(),/失败/);
   return {facts:values,result_text:text,error:await page.locator('#simulation-job-error').innerText(),live_step:await page.locator('#simulation-live-step').innerText(),last_iteration:await page.locator('#simulation-live-iteration').innerText(),artifact_links:await page.locator('#simulation-job-assets a').evaluateAll(nodes=>nodes.map(n=>({label:n.textContent,href:n.getAttribute('href')})))};
  };
  report.failed_view=await verifyFailed();report.checks.push('Switching from known successful reference clears every numeric fact; failed patient values remain explicitly unavailable');
  await page.locator('#simulation-result').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'desktop-failed-result.png'),fullPage:true});
  await page.reload();await page.waitForFunction(()=>!document.getElementById('simulation-case').disabled);report.after_reload=await verifyFailed();
  report.checks.push('Failed status, exit error, last actual iteration223 and no field/viewer links survive task-history reload');
  for(const width of [390,320]){await page.setViewportSize({width,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.locator('#simulation-result').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'failed-'+width+'.png'),fullPage:true});}
  const missingManifest='/simulation-assets/'+jobId+'/viewer.json';const missing=await context.newPage();missing.on('pageerror',e=>report.page_errors.push(e.message));
  await missing.goto(base+'/viewer/index.html?manifest='+missingManifest);await missing.waitForURL(u=>u.pathname==='/workspace/index.html'&&u.searchParams.get('manifest')===missingManifest);
  const handle=await missing.locator('#panel-geometry iframe:visible').elementHandle();const frame=await handle.contentFrame();await frame.locator('#scene-state').waitFor({state:'visible'});
  await frame.waitForFunction(()=>document.getElementById('scene-state').textContent.includes('失败'));
  report.missing_field_view={url:missing.url(),frame_url:frame.url(),state:await frame.locator('#scene-state').innerText(),case_option_count:await frame.locator('#case-select option').count()};
  assert.equal(report.missing_field_view.case_option_count,0);assert.match(report.missing_field_view.state,/失败/);
  await missing.screenshot({path:path.join(out,'missing-current-field-rejected.png'),fullPage:true});
  report.checks.push('Direct request for absent current manifest shows a loading failure with zero cases; no fallback patient/reference field');
  assert.deepEqual(report.posts,[]);assert.deepEqual(report.page_errors,[]);report.ui_failure_display_checks_passed=true;
 }catch(e){report.ui_failure_display_checks_passed=false;report.error=e.stack;throw e;}
 finally{report.finished_at=new Date().toISOString();await browser.close();await fs.writeFile(path.join(out,'verification.json'),JSON.stringify(report,null,2)+'\n',{flag:'wx'});}
 console.log(JSON.stringify({ui_failure_display_checks_passed:true,job_id:jobId,checks:report.checks,posts:report.posts.length}));
}
main().catch(e=>{console.error(e);process.exitCode=1;});
