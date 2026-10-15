// Read-only live 8769 UI checks: real rejected A, real old FPE, real success.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),crypto=require('node:crypto');
const {chromium}=require('playwright');
const base='http://127.0.0.1:8769',out=path.join(__dirname,'diagnostic_ui');
const a='s_aa79a63027b94bfb9a273898',fpe='s_942fdbebfffd433c8fcec956';
const root='C:/ts_work/project_cases/simulation_jobs';
const sha=async file=>crypto.createHash('sha256').update(await fs.readFile(file)).digest('hex');
(async()=>{
 await fs.mkdir(out,{recursive:false});
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 const evidence={scope:'read_only_actual_8769_jobs_no_solver_or_POST',checks:[],posts:[],page_errors:[]};
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  const get=async url=>{const r=await context.request.get(base+url);assert.equal(r.status(),200);return r.json();};
  const history=await get('/api/simulation/jobs');
  const reference=history.jobs.find(job=>job.status==='completed'&&job.action==='run_pressure_feedback'&&job.case_id==='reference_split_feedback');assert(reference);
  const originals=await Promise.all([a,fpe,reference.id].map(id=>get('/api/simulation/jobs/'+id)));
  const before=Object.fromEntries(await Promise.all(originals.map(async job=>[job.id,await sha(path.join(root,job.id,'job.json'))])));
  evidence.original_jobs=originals.map(job=>({id:job.id,case_id:job.case_id,status:job.status,
   execution_status:job.result?.execution_status,numerical_validation:job.result?.numerical_validation,
   viewer_export_error:job.result?.viewer_export_error,source_result_status:job.result?.scenario?.result?.status}));
  const page=await context.newPage();page.setDefaultTimeout(20000);
  page.on('request',r=>{if(r.method()==='POST')evidence.posts.push({url:r.url(),data:r.postData()});});
  page.on('pageerror',e=>evidence.page_errors.push(e.message));
  await page.goto(base+'/workspace/index.html?case=existing#validation');
  await page.waitForFunction(()=>!document.getElementById('simulation-case').disabled);
  async function select(job){
   await page.locator('#simulation-case').selectOption(job.case_id);
   await page.locator('[data-job-id="'+job.id+'"]').click();
   await page.waitForFunction(id=>document.getElementById('simulation-job-meta').textContent.includes(id)&&document.getElementById('simulation-result').children.length>0,job.id);
  }
  async function rejectedA(label){
   const text=await page.locator('#simulation-result').innerText();
   assert.match(text,/质量未通过 \/ 未收敛，仅原始诊断/);assert.match(text,/未形成有效气流结果/);
   assert.match(text,/本次三维流场导出失败：抽取后存在退化三角面/);assert.match(text,/数值验证：未检查/);
   const quality=await page.locator('#simulation-result table').first().locator('tbody tr td').allTextContents();
   assert.deepEqual(quality.slice(-2),['未通过','未通过']);
   const style=await page.locator('#simulation-result .simulation-feedback-facts>div').first().evaluate(node=>getComputedStyle(node).backgroundColor);
   assert.equal(style,'rgb(255, 241, 238)');
   assert.equal(await page.locator('#simulation-result').evaluate(node=>node.classList.contains('is-diagnostic-failure')),true);
   const fmt=value=>value.toLocaleString('zh-CN',{maximumSignificantDigits:6}),solved=originals[0].result.scenario.result;
   const facts=await page.locator('#simulation-result dl div').evaluateAll(nodes=>Object.fromEntries(nodes.map(n=>[n.querySelector('dt').textContent,n.querySelector('dd').textContent])));
   assert.equal(facts['共同入口静压 Pa'],fmt(solved.pressure_pa));assert.equal(facts['实测总流量 L/min'],fmt(solved.q_total_m3_s*60000));
   evidence.checks.push({check:label,passed:true,quality,facts,card_background:style,text});
  }
  await select(originals[0]);await rejectedA('actual_A_quality_residual_false_and_export_error');
  await page.locator('#simulation-result').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'actual-A-desktop.png'),fullPage:true});
  await page.reload();await page.waitForFunction(id=>document.getElementById('simulation-job-meta').textContent.includes(id)&&document.getElementById('simulation-result').children.length>0,a);
  await rejectedA('actual_A_refresh_keeps_failed_diagnostic');
  for(const width of [390,320]){
   await page.setViewportSize({width,height:900});await rejectedA('actual_A_'+width+'_failed_diagnostic');
   const bounds=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert(bounds.scroll<=bounds.width+1);
   await page.locator('#simulation-result').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'actual-A-'+width+'.png'),fullPage:true});
   evidence.checks.push({check:'actual_A_'+width+'_no_horizontal_overflow',passed:true,bounds});
  }
  await page.setViewportSize({width:1440,height:1000});await select(originals[1]);
  let text=await page.locator('#simulation-result').innerText();assert.match(text,/本次执行失败/);assert.match(text,/本次最终评估VTU缺失或不唯一/);assert.doesNotMatch(text,/质量未通过 \/ 未收敛/);
  assert.equal(await page.locator('#simulation-result').evaluate(node=>node.classList.contains('is-diagnostic-failure')),true);
  assert.equal(await page.locator('#simulation-result table').first().locator('tbody tr td').last().textContent(),'未获得');
  evidence.checks.push({check:'actual_FPE_missing_field_is_not_quality_status_or_known_false',passed:true,text});
  await page.locator('#simulation-result').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'actual-FPE-desktop.png'),fullPage:true});
  await select(originals[2]);text=await page.locator('#simulation-result').innerText();assert.match(text,/非患者参考/);assert.doesNotMatch(text,/本次三维流场导出失败/);
  assert.equal(await page.locator('#simulation-result').evaluate(node=>node.classList.contains('is-diagnostic-failure')),false);
  assert.equal(await page.locator('#simulation-result .simulation-feedback-facts>div').first().evaluate(node=>getComputedStyle(node).backgroundColor==='rgb(255, 241, 238)'),false);
  evidence.checks.push({check:'actual_successful_reference_keeps_normal_result_style',passed:true,id:reference.id,text});
  await page.locator('#simulation-result').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'actual-reference-desktop.png'),fullPage:true});
  assert.deepEqual(evidence.posts,[]);assert.deepEqual(evidence.page_errors,[]);
  const after=Object.fromEntries(await Promise.all(originals.map(async job=>[job.id,await sha(path.join(root,job.id,'job.json'))])));
  assert.deepEqual(after,before);evidence.job_sha_before=before;evidence.job_sha_after=after;
  evidence.checks.push({check:'POST_zero_original_three_jobs_unchanged_and_no_pageerror',passed:true});
  evidence.production_sha256={simulation_js:await sha(path.resolve(__dirname,'../../../work/07_cfd_pipeline/workspace/simulation.js')),
   workspace_css:await sha(path.resolve(__dirname,'../../../work/07_cfd_pipeline/workspace/workspace.css'))};
  evidence.passed=true;
 }catch(error){evidence.failure=error.stack;throw error;}
 finally{await browser.close();await fs.writeFile(path.join(out,'verification.json'),JSON.stringify(evidence,null,2));}
 console.log(JSON.stringify({passed:evidence.passed,checks:evidence.checks.length,posts:evidence.posts.length}));
})().catch(error=>{console.error(error);process.exitCode=1;});
