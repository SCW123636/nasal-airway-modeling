'use strict';
// Read actual rejected A job; no POST, export, retry, or service action.
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {chromium}=require('playwright');
const base='http://127.0.0.1:8769',job='s_aa79a63027b94bfb9a273898',caseId='b15_engineering_t029a',reference='s_1811f735241e4d75b5fdf10e';
const out=path.join(__dirname,'actual-rejected-ui-v2');
const report={at:new Date().toISOString(),job_id:job,case_id:caseId,checks:[],posts:[],page_errors:[]};
async function main(){
 await fs.mkdir(out,{recursive:false});
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();page.setDefaultTimeout(30000);
  context.on('request',r=>{if(r.method()==='POST')report.posts.push(r.url());});context.on('page',p=>p.on('pageerror',e=>report.page_errors.push(e.message)));
  await page.goto(base+'/workspace/index.html#validation');await page.waitForFunction(()=>!document.getElementById('simulation-case').disabled);
  const facts=()=>page.locator('#simulation-result dl div').evaluateAll(ns=>Object.fromEntries(ns.map(n=>[n.querySelector('dt').textContent,n.querySelector('dd').textContent])));
  await page.locator('#simulation-case').selectOption('reference_split_feedback');await page.locator(`[data-job-id="${reference}"]`).click();
  await page.waitForFunction(id=>document.getElementById('simulation-job-meta').textContent.includes(id)&&document.getElementById('simulation-result').textContent.includes('2.44425'),reference);report.prior_reference_facts=await facts();
  await page.locator('#simulation-case').selectOption(caseId);await page.locator(`[data-job-id="${job}"]`).click();
  const api=await (await context.request.get(base+'/api/simulation/jobs/'+job)).json();report.api_job=api;
  assert.equal(api.status,'failed');assert.equal(api.result.scenario.result.status,'quality_rejected_not_converged');assert.equal(api.result.numerical_validation,'unchecked');
  const verify=async()=>{
   await page.waitForFunction(id=>document.getElementById('simulation-job-meta').textContent.includes(id)&&document.getElementById('simulation-job-status').textContent==='失败',job);
   const values=await facts(),text=await page.locator('#simulation-result').innerText(),error=await page.locator('#simulation-job-error').innerText();
   assert.equal(Object.keys(values).length,9);assert.equal(values['共同入口静压 Pa'],'10');assert.equal(values['目标总流量 L/min'],'15');
   assert.ok(Math.abs(Number(values['实测总流量 L/min'])-api.result.scenario.result.q_total_m3_s*60000)<0.001);
   assert.ok(Math.abs(Number(values['左侧自然分流'].replace('%',''))-api.result.scenario.result.left_fraction*100)<0.001);
   assert.match(text,/患者工程试算 · 非临床/);assert.match(text,/临床验证：未验证/);assert.match(text,/本次执行未完成/);assert.match(text,/不代表共同压力反馈达标/);assert.match(text,/网格质量[\s\S]*未通过/);assert.doesNotMatch(text,/2\.44425/);
   assert.match(error,/退出码：1/);assert.equal(await page.locator('#simulation-live-iteration').innerText(),'120');
   assert.equal(await page.locator('#simulation-job-assets a[href*="viewer"]').count(),0);
   assert.equal(await page.locator('#simulation-job-assets a[href$="-internal.vtu"]').count(),1);
   return {facts:values,result_text:text,error_text:error,quality_status_explicitly_visible:text.includes('quality_rejected_not_converged'),viewer_export_error_visible:text.includes('抽取后存在退化三角面'),numerical_label_shown:'未检查',live_step:await page.locator('#simulation-live-step').innerText(),artifact_links:await page.locator('#simulation-job-assets a').evaluateAll(ns=>ns.map(n=>({label:n.textContent,href:n.getAttribute('href')})))};
  };
  report.actual_view=await verify();await page.locator('#simulation-result').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'desktop-quality-rejected.png'),fullPage:true});
  await page.reload();await page.waitForFunction(()=>!document.getElementById('simulation-case').disabled);report.after_reload=await verify();
  for(const width of [390,320]){await page.setViewportSize({width,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.locator('#simulation-result').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'quality-rejected-'+width+'.png'),fullPage:true});}
  report.checks.push('Actual rejected diagnostic values match this run, failed/nonclinical/no-target-success notices persist on reload and 390/320; prior successful reference numbers are absent');
  const missing=await context.newPage(),manifest='/simulation-assets/'+job+'/viewer.json';await missing.goto(base+'/viewer/index.html?manifest='+manifest);
  await missing.waitForURL(u=>u.pathname==='/workspace/index.html'&&u.searchParams.get('manifest')===manifest);
  const h=await missing.locator('#panel-geometry iframe:visible').elementHandle(),frame=await h.contentFrame();await frame.waitForFunction(()=>document.getElementById('scene-state').textContent.includes('未能启动'));
  report.missing_field={state:await frame.locator('#scene-state').innerText(),case_options:await frame.locator('#case-select option').count(),snapshot:await frame.evaluate(async()=>{const m=await import('/viewer/viewer.js');return m.getDisplaySnapshot();})};
  assert.equal(report.missing_field.case_options,0);assert.equal(report.missing_field.snapshot,null);assert.match(report.missing_field.state,/索引未生成/);
  await missing.screenshot({path:path.join(out,'actual-missing-field-rejected.png'),fullPage:true});
  const js=await context.request.get(base+'/workspace/workspace.js');report.actual_workspace_js_sha256=crypto.createHash('sha256').update(await js.body()).digest('hex');
  report.checks.push('Missing actual A field manifest is refused with no cases or fallback field; raw VTU link remains separate from unavailable three-dimensional viewer');
  report.limitations=['Actual A three-dimensional field display fails: viewer_export_error=抽取后存在退化三角面 and no viewer files.','Top-level numerical state remains unchecked although this evaluation is quality rejected.','Explicit quality_rejected_not_converged code and extractor error are observed below, not assumed visible in primary result text.'];
  report.visible_quality_status_requirement_passed=report.actual_view.quality_status_explicitly_visible;
  report.formal_field_display_passed=false;report.honest_failed_and_missing_ui_checks_passed=true;
  assert.deepEqual(report.posts,[]);assert.deepEqual(report.page_errors,[]);
 }catch(e){report.honest_failed_and_missing_ui_checks_passed=false;report.failure=e.stack;throw e;}
 finally{report.finished_at=new Date().toISOString();await browser.close();await fs.writeFile(path.join(out,'verification.json'),JSON.stringify(report,null,2)+'\n',{flag:'wx'});}
 console.log(JSON.stringify({honest_failed_and_missing_ui_checks_passed:report.honest_failed_and_missing_ui_checks_passed,visible_quality_status_requirement_passed:report.visible_quality_status_requirement_passed,formal_field_display_passed:false,checks:report.checks,posts:report.posts.length}));
}
main().catch(e=>{console.error(e);process.exitCode=1;});
