'use strict';
// Fresh actual-8769 acceptance. No network route mocks except one explicit
// HTTP-read-error branch after the real reference has finished.
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
const cp=require('node:child_process');
const {chromium}=require('playwright');
const base='http://127.0.0.1:8769';
const mode=process.argv[2];assert.ok(['reference','patient-start'].includes(mode));
const out=path.resolve(__dirname,mode==='reference'?'live-reference':'live-patient-start');
const terminal=job=>['completed','failed','interrupted'].includes(job.status);
const report={mode,base,started_at:new Date().toISOString(),checks:[],created_jobs:[],progress:[],page_errors:[],api_posts:[]};
const record=name=>report.checks.push(name);
const json=async(url,request)=>{const response=await request.get(base+url);assert.equal(response.status(),200);return response.json();};
const writeOnce=(name,data)=>fs.writeFile(path.join(out,name),JSON.stringify(data,null,2)+'\n',{flag:'wx'});
const nativeProbe=(native,observed)=>{
  assert.match(native,/^\/home\/lenovo2\/nasal_cfd_workspace_jobs\/s_[0-9a-f]{24}\/(?:[A-Za-z0-9_-]+\/)*evaluations\/eval_\d+$/);
  const code=`import hashlib,json,pathlib,re,subprocess,sys
p=pathlib.Path(sys.argv[1]);s=json.loads((p/'run_status.json').read_text());log=(p/'log.simpleFoam').read_text() if (p/'log.simpleFoam').is_file() else '';times=re.findall(r'(?m)^Time = (\\S+)',log)
try:procs=subprocess.check_output(['pgrep','-a','-x','simpleFoam'],text=True).splitlines()
except subprocess.CalledProcessError:procs=[]
print(json.dumps({'native_case':str(p),'run_status':s,'actual_final_time_now':times[-1] if times else None,'observed_iteration_in_raw_log':sys.argv[2] in times,'log_tail':log[-2500:],'log_sha256':hashlib.sha256(log.encode()).hexdigest(),'simpleFoam_processes':procs,'zero_p':(p/'0/p').read_text(),'zero_U':(p/'0/U').read_text()}))`;
  const result=cp.spawnSync('wsl.exe',['-d','Ubuntu-22.04','--','python3','-c',code,native,observed],{encoding:'utf8',timeout:10000,maxBuffer:4e6});
  assert.equal(result.status,0,result.stderr);return JSON.parse(result.stdout);
};
async function main(){
 await fs.mkdir(out,{recursive:false});
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 let job;
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  const page=await context.newPage();page.setDefaultTimeout(25000);
  page.on('pageerror',e=>report.page_errors.push(e.message));
  page.on('request',request=>{if(request.url()===base+'/api/simulation/jobs'&&request.method()==='POST')report.api_posts.push(request.postDataJSON());});
  const shot=async(name)=>page.screenshot({path:path.join(out,name+'.png'),fullPage:true});
  const noOverflow=async()=>assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  const ready=()=>page.waitForFunction(()=>!document.getElementById('simulation-case').disabled);
  await page.goto(base+'/workspace/index.html#validation');await ready();
  const catalog=await json('/api/simulation/catalog',context.request);report.catalog=catalog;
  const reference=catalog.cases.find(x=>x.id==='reference_split_feedback');
  const patient=catalog.cases.find(x=>x.id==='b15_engineering');
  assert.equal(reference.run_action,'run_pressure_feedback');assert.equal(reference.run_allowed,true);
  assert.equal(patient.run_action,'run_patient_engineering');assert.equal(patient.clinical_validation,'not_validated');
  record('actual catalog includes correct common-pressure and independently bound patient actions');
  const existing=catalog.cases.find(x=>x.id==='p0');assert.equal(existing.run_allowed,false);
  await page.locator('#simulation-case').selectOption('p0');
  await page.waitForFunction(()=>document.getElementById('simulation-kind').textContent==='患者数据');
  assert.equal(await page.locator('#simulation-run').isDisabled(),true);
  assert.match(await page.locator('#simulation-engineering-checks').innerText(),/未验证/);
  record('actual p0 blocked reasons and nonclinical state remain visible');
  if(mode==='reference'){
   const before=(await json('/api/simulation/jobs',context.request)).jobs.map(x=>x.id);
   const invalid=[
    {case_id:'b15_engineering',action:'run_patient_engineering',settings:{},force:true},
    {case_id:'b15_engineering',action:'run_patient_engineering',settings:{path:'C:/outside'}},
    {case_id:'../b15_engineering',action:'run_patient_engineering',settings:{}},
    {case_id:'b9999_engineering',action:'run_patient_engineering',settings:{}},
    {case_id:'p0',action:'run_patient_engineering',settings:{}},
    {case_id:'reference_split_feedback',action:'run_patient_engineering',settings:{}},
    {case_id:'reference_split_feedback',action:'run_pressure_feedback',settings:{scenarios:['symmetric'],pressure:10}}
   ];
   report.negative_api=[];
   for(const data of invalid){const r=await context.request.post(base+'/api/simulation/jobs',{data,headers:{Origin:base,Referer:base+'/workspace/index.html'}});const body=await r.json();assert.ok(r.status()>=400&&r.status()<500,{data,status:r.status(),body});report.negative_api.push({data,status:r.status(),body});}
   assert.deepEqual((await json('/api/simulation/jobs',context.request)).jobs.map(x=>x.id),before);
   record('unknown binding, cross-case action, traversal, arbitrary path/pressure and generic force reject without jobs');
  }
  const caseId=mode==='reference'?'reference_split_feedback':'b15_engineering';
  const action=mode==='reference'?'run_pressure_feedback':'run_patient_engineering';
  await page.locator('#simulation-case').selectOption(caseId);
  if(mode==='reference')await page.locator('#simulation-scenario').selectOption('symmetric');
  else assert.equal(patient.run_allowed,true,patient.blocking_reasons?.join(';'));
  const post=()=>page.waitForResponse(r=>r.url()===base+'/api/simulation/jobs'&&r.request().method()==='POST');
  let responsePromise=post();await page.locator('#simulation-preflight').click();let response=await responsePromise;
  assert.equal(response.status(),202);const preflight=await response.json();report.created_jobs.push({id:preflight.id,case_id:caseId,action:'preflight'});
  await page.waitForFunction(id=>document.getElementById('simulation-job-meta').textContent.includes(id)&&['已执行','失败','已中断'].includes(document.getElementById('simulation-job-status').textContent),preflight.id,{timeout:120000});
  const preflightFinal=await json('/api/simulation/jobs/'+preflight.id,context.request);assert.equal(preflightFinal.preflight.passed,true,preflightFinal);
  assert.equal(await page.locator('#simulation-result table').count(),0);
  report.preflight=preflightFinal;record('real UI preparation POST completes actual checks without numerical result');
  await shot('desktop-ready');
  await page.waitForFunction(()=>!document.getElementById('simulation-run').disabled);
  responsePromise=post();await page.locator('#simulation-run').click();response=await responsePromise;
  assert.equal(response.status(),202);job=await response.json();assert.equal(job.action,action);assert.equal(job.case_id,caseId);
  const payload=response.request().postDataJSON();assert.deepEqual(payload,{case_id:caseId,action,settings:mode==='reference'?{scenarios:['symmetric']}:{}});
  report.created_jobs.push({id:job.id,case_id:caseId,action});report.run_job_id=job.id;
  await writeOnce('created-job.json',{at:new Date().toISOString(),payload,job});
  record('actual run button POST uses catalog action and exact permitted settings');
  await page.reload();await ready();
  await page.waitForFunction(id=>document.getElementById('simulation-job-meta').textContent.includes(id),job.id);
  assert.equal(await page.locator('#simulation-case').inputValue(),caseId);
  record('real persisted selected job and case survive reload');
  let previous='',proofCount=0;const deadline=Date.now()+(mode==='reference'?180000:120000);
  while(Date.now()<deadline){
   job=await json('/api/simulation/jobs/'+job.id,context.request);
   const progress=job.live_progress;
   const state=JSON.stringify({status:job.status,stage:job.stage,progress});
   if(state!==previous){const row={at:new Date().toISOString(),job_id:job.id,worker_pid:job.worker_pid,solver_pid:job.solver_pid,status:job.status,stage:job.stage,progress};report.progress.push(row);await fs.appendFile(path.join(out,'progress.jsonl'),JSON.stringify(row)+'\n');previous=state;}
   if(progress?.iteration&&progress.native_case&&proofCount<3){
    const visible=await page.locator('#simulation-live-progress').isVisible();
    const observed=visible?await page.locator('#simulation-live-iteration').innerText():'';
    const shownEval=visible?await page.locator('#simulation-live-evaluation').innerText():'';
    if(/^\d+(?:\.\d+)?$/.test(observed)&&shownEval===progress.evaluation){
     const proof=nativeProbe(progress.native_case,observed);assert.equal(proof.observed_iteration_in_raw_log,true);
     assert.equal(proof.run_status.case,progress.native_case);
     proof.ui={iteration:observed,evaluation:shownEval,step:await page.locator('#simulation-live-step').innerText(),updated:await page.locator('#simulation-live-updated').innerText()};
     await writeOnce('native-progress-'+proofCount+'.json',proof);proofCount++;
     await page.locator('#simulation-live-log-detail summary').click().catch(()=>{});
     await shot('running-'+proofCount);
    }
   }
   if(terminal(job))break;
   if(mode==='patient-start'&&proofCount>=2)break;
   await page.waitForTimeout(1000);
  }
  report.final_observed_job=job;report.raw_progress_proofs=proofCount;
  assert.ok(proofCount>0,'No actual GUI/native iteration correspondence was observed');
  record('actual SIMPLE iteration shown by UI occurs in this new native raw log; real worker and solver identity retained');
  if(mode==='reference'){
   assert.equal(job.status,'completed',job.error);assert.equal(job.exit_code,0);
   assert.equal(job.result.patient_data,false);assert.deepEqual(Object.keys(job.result.scenarios),['symmetric']);
   const result=job.result.scenarios.symmetric.result;
   assert.ok(Math.abs(result.left_fraction-.5)<.01);assert.ok(result.relative_flow_error<=.01);
   await page.locator('#simulation-refresh').click();
   await page.waitForFunction(()=>document.querySelectorAll('#simulation-result dl div').length>=9);
   const facts=await page.locator('#simulation-result dl div').evaluateAll(nodes=>Object.fromEntries(nodes.map(n=>[n.querySelector('dt').textContent,n.querySelector('dd').textContent])));
   const fmt=(v,d=6)=>v.toLocaleString('zh-CN',{maximumSignificantDigits:d});
   assert.equal(facts['共同入口静压 Pa'],fmt(result.pressure_pa));
   assert.equal(facts['目标总流量 L/min'],fmt(result.target_m3_s*60000));
   assert.equal(facts['实测总流量 L/min'],fmt(result.q_total_m3_s*60000));
   assert.equal(facts['左侧流量 L/min'],fmt(result.q_left_m3_s*60000));
   assert.equal(facts['右侧流量 L/min'],fmt(result.q_right_m3_s*60000));
   assert.match(await page.locator('#simulation-result').innerText(),/非患者参考.*本次数值结果/s);
   assert.match(await page.locator('#simulation-result').innerText(),/临床验证：未验证/);
   report.displayed_facts=facts;record('real result fields and m3/s to L/min display agree exactly; reference and unverified labels visible');
   await page.locator('#simulation-result').scrollIntoViewIfNeeded();await shot('desktop-result');
   const asset=page.locator('#simulation-job-assets a[href^="/viewer/index.html?manifest="]').first();await asset.waitFor();
   const href=await asset.getAttribute('href');const manifestPath=new URL(href,base).searchParams.get('manifest');
   assert.match(manifestPath,new RegExp('^/simulation-assets/'+job.id+'/'));
   const manifest=await json(manifestPath,context.request);assert.equal(manifest.cases.length,1);
   const popupEvent=page.waitForEvent('popup');await asset.click();const popup=await popupEvent;
   await popup.waitForURL(url=>url.pathname==='/workspace/index.html'&&url.searchParams.get('manifest')===manifestPath&&url.hash==='#geometry');
   const geometry=async()=>{const handle=await popup.locator('#panel-geometry iframe:visible').elementHandle();const frame=await handle.contentFrame();await frame.locator('#scene-state').waitFor({state:'hidden',timeout:30000});return frame;};
   let frame=await geometry();assert.equal(await frame.locator('#case-select').inputValue(),manifest.cases[0].id);
   assert.equal(await frame.locator('#layer-velocity').isDisabled(),false);assert.equal(await frame.locator('#layer-pressure').isDisabled(),false);
   await popup.screenshot({path:path.join(out,'actual-reference-artifact.png')});
   await popup.reload();frame=await geometry();assert.equal(await frame.locator('#case-select').inputValue(),manifest.cases[0].id);
   await popup.goto(base+href);await popup.waitForURL(url=>url.pathname==='/workspace/index.html'&&url.searchParams.get('manifest')===manifestPath);
   frame=await geometry();assert.equal(await frame.locator('#case-select').inputValue(),manifest.cases[0].id);
   record('actual artifact click, refresh and direct viewer URL preserve the new reference result identity and p/U fields');
   report.viewer={href,manifestPath,case_id:manifest.cases[0].id};await popup.close();
   await page.route(base+'/api/simulation/jobs/'+job.id,route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'T023 explicit read-error branch'})}));
   await page.locator(`[data-job-id="${job.id}"]`).click();await page.waitForFunction(()=>document.getElementById('simulation-job-empty').textContent.includes('任务详情未读取'));
   assert.equal(await page.locator('#simulation-result table').count(),0);
   await page.unroute(base+'/api/simulation/jobs/'+job.id);await page.locator('#simulation-refresh').click();
   await page.waitForFunction(id=>document.getElementById('simulation-job-meta').textContent.includes(id)&&document.querySelector('#simulation-result table'),job.id);
   record('explicit read-error clears prior numerical result and refresh restores actual persisted task');
  }else{
   assert.equal(job.result?.clinical_validation||'not_validated','not_validated');
   record('new patient engineering worker started; no convergence or patient numerical acceptance claimed');
  }
  for(const width of [390,320]){await page.setViewportSize({width,height:844});await noOverflow();await shot('actual-'+width);}
  await page.setViewportSize({width:1440,height:1000});await noOverflow();
  assert.deepEqual(report.page_errors,[]);report.passed=true;
 }catch(error){report.failure=error.stack;throw error;}
 finally{report.finished_at=new Date().toISOString();await browser.close();await writeOnce('verification.json',report);}
 console.log(JSON.stringify({passed:report.passed,mode,run_job_id:report.run_job_id,created_jobs:report.created_jobs,checks:report.checks,final_status:report.final_observed_job?.status,raw_progress_proofs:report.raw_progress_proofs},null,2));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
