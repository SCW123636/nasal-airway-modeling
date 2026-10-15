'use strict';
// Only GETs and browser interaction with the unique persisted candidate.
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {chromium}=require('playwright');
const base='http://127.0.0.1:8769',job='s_aa79a63027b94bfb9a273898',caseId='b15_engineering_t029a',reference='s_1811f735241e4d75b5fdf10e';
const out=path.join(__dirname,'actual-candidate-ui');
const result={at:new Date().toISOString(),job_id:job,case_id:caseId,checks:[],posts:[],page_errors:[]};
const digest=buffer=>crypto.createHash('sha256').update(buffer).digest('hex');
async function main(){
 await fs.mkdir(out,{recursive:false});
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  context.on('request',r=>{if(r.method()==='POST')result.posts.push(r.url());});
  context.on('page',p=>p.on('pageerror',e=>result.page_errors.push(e.message)));
  const page=await context.newPage();page.setDefaultTimeout(30000);
  await page.goto(base+'/workspace/index.html#validation');await page.waitForFunction(()=>!document.getElementById('simulation-case').disabled);
  const facts=()=>page.locator('#simulation-result dl div').evaluateAll(ns=>Object.fromEntries(ns.map(n=>[n.querySelector('dt').textContent,n.querySelector('dd').textContent])));
  await page.locator('#simulation-case').selectOption('reference_split_feedback');await page.locator(`[data-job-id="${reference}"]`).click();
  await page.waitForFunction(id=>document.getElementById('simulation-job-meta').textContent.includes(id)&&document.getElementById('simulation-result').textContent.includes('2.44425'),reference);
  result.prior_reference=await facts();
  await page.locator('#simulation-case').selectOption(caseId);await page.locator(`[data-job-id="${job}"]`).click();
  await page.waitForFunction(id=>document.getElementById('simulation-job-meta').textContent.includes(id)&&document.getElementById('simulation-job-status').textContent==='失败',job);
  result.actual_job=await (await context.request.get(base+'/api/simulation/jobs/'+job)).json();
  assert.equal(result.actual_job.status,'failed');assert.equal(result.actual_job.result.clinical_validation,'not_validated');assert.equal(result.actual_job.result.numerical_validation,'failed');
  result.facts=await facts();assert.equal(Object.keys(result.facts).length,9);for(const v of Object.values(result.facts))assert.equal(v,'未获得');
  result.result_text=await page.locator('#simulation-result').innerText();result.error_text=await page.locator('#simulation-job-error').innerText();
  assert.match(result.result_text,/患者工程试算 · 非临床/);assert.match(result.result_text,/数值验证：未通过/);assert.match(result.result_text,/临床验证：未验证/);assert.match(result.result_text,/不代表共同压力反馈达标/);
  assert.doesNotMatch(result.result_text,/2\.44425|50%/);
  result.diagnostic_table=await page.locator('#simulation-result table').innerText();
  result.checks.push('Known successful reference values are cleared; failed candidate keeps all nine accepted-feedback facts unavailable and displays actual diagnostic table separately');
  await page.locator('#simulation-result').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'desktop-quality-failure.png'),fullPage:true});
  const artifact=page.locator('#simulation-job-assets a[href^="/viewer/index.html?manifest="]').first();await artifact.waitFor();const href=await artifact.getAttribute('href');
  const manifest='/simulation-assets/'+job+'/viewer.json';assert.equal(new URL(href,base).searchParams.get('manifest'),manifest);
  const popupEvent=page.waitForEvent('popup');await artifact.click();const popup=await popupEvent;
  const frameOf=async()=>{await popup.waitForURL(u=>u.pathname==='/workspace/index.html'&&u.searchParams.get('manifest')===manifest);const h=await popup.locator('#panel-geometry iframe:visible').elementHandle();const f=await h.contentFrame();await f.locator('#scene-state').waitFor({state:'hidden'});return f;};
  let frame=await frameOf();assert.equal(await frame.locator('#case-select').inputValue(),job);assert.equal(await frame.locator('#field-sampling').inputValue(),'y');
  assert.match(await frame.locator('#kind-badge').innerText(),/患者工程试算 · 非临床/);assert.match(await frame.locator('#engineering-warning').innerText(),/数值状态 failed/);assert.match(await frame.locator('#engineering-warning').innerText(),/质量失败保留显示，不构成正式患者 CFD 结果/);
  result.viewer=[];
  for(const sample of ['x','y','z','surface']){
   await frame.locator('#field-sampling').selectOption(sample);
   for(const field of ['velocity','pressure']){assert.equal(await frame.locator('#layer-'+field).isDisabled(),false);await frame.locator('#layer-'+field).click();}
   const detail=JSON.parse(await frame.locator('#source-detail').innerText());assert.equal(detail.job_id,job);assert.equal(detail.case_id,caseId);assert.equal(detail.provenance.field_time,'120');assert.equal(detail.display_sampling.id,sample);assert.equal(detail.numerical_validation,'failed');
   result.viewer.push({sample,detail,note:await frame.locator('#field-sampling-note').innerText()});
   if(sample==='surface')assert.match(await frame.locator('#field-sampling-note').innerText(),/不能代表腔内速度/);
  }
  await frame.locator('#field-sampling').selectOption('y');await frame.locator('#layer-velocity').click();await popup.screenshot({path:path.join(out,'actual-120-y-diagnostic.png'),fullPage:true});
  await popup.reload();frame=await frameOf();assert.equal(await frame.locator('#case-select').inputValue(),job);await popup.goto(base+href);frame=await frameOf();assert.equal(await frame.locator('#case-select').inputValue(),job);
  result.checks.push('Formal artifact click/direct open/refresh bind this job/time120; default Y, all three internal cuts and outer surface keep failed/nonclinical warning');
  for(const width of [390,320]){await popup.setViewportSize({width,height:844});assert.ok(await popup.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await popup.screenshot({path:path.join(out,'diagnostic-'+width+'.png'),fullPage:true});}
  const response=await context.request.get(base+'/workspace/workspace.js');result.workspace_js_sha256=digest(await response.body());
  result.positive_display_snapshot=await frame.evaluate(async()=>{const m=await import('/viewer/viewer.js');return m.getDisplaySnapshot();});
  // Isolated browser response mutation only, after observing a real field.
  const servedMesh=await (await context.request.get(base+'/simulation-assets/'+job+'/viewer_mesh.json')).json();servedMesh.job_id='s_942fdbebfffd433c8fcec956';
  await context.route('**/simulation-assets/'+job+'/viewer_mesh.json',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(servedMesh)}));
  await popup.reload();await popup.waitForURL(u=>u.pathname==='/workspace/index.html');const h=await popup.locator('#panel-geometry iframe:visible').elementHandle();frame=await h.contentFrame();await frame.waitForFunction(()=>document.getElementById('scene-state').textContent.includes('无法显示'));
  result.stale_identity_rejection={state:await frame.locator('#scene-state').innerText(),snapshot:await frame.evaluate(async()=>{const m=await import('/viewer/viewer.js');return m.getDisplaySnapshot();}),velocity_disabled:await frame.locator('#layer-velocity').isDisabled(),pressure_disabled:await frame.locator('#layer-pressure').isDisabled()};
  assert.match(result.stale_identity_rejection.state,/身份或受控资产路径不符/);assert.equal(result.stale_identity_rejection.snapshot,null);assert.equal(result.stale_identity_rejection.velocity_disabled,true);assert.equal(result.stale_identity_rejection.pressure_disabled,true);
  await popup.screenshot({path:path.join(out,'stale-identity-rejected.png'),fullPage:true});
  result.checks.push('Isolated stale-job response after real viewing is rejected with null display snapshot and both fields disabled; production files unchanged');
  assert.deepEqual(result.posts,[]);assert.deepEqual(result.page_errors,[]);result.passed=true;
 }catch(e){result.passed=false;result.failure=e.stack;throw e;}
 finally{result.finished_at=new Date().toISOString();await browser.close();await fs.writeFile(path.join(out,'verification.json'),JSON.stringify(result,null,2)+'\n',{flag:'wx'});}
 console.log(JSON.stringify({passed:result.passed,job_id:job,checks:result.checks,posts:result.posts.length}));
}
main().catch(e=>{console.error(e);process.exitCode=1;});
