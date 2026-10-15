'use strict';
// This verifier only reads the existing task. It never POSTs or starts solvers.
const fs=require('node:fs/promises'),path=require('node:path'),cp=require('node:child_process'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const jobId='s_942fdbebfffd433c8fcec956',base='http://127.0.0.1:8769';
const phase=process.argv[2],out=path.resolve(process.argv[3]||'');assert.ok(['progress','terminal'].includes(phase));
assert.ok(out.startsWith(path.resolve(__dirname)+path.sep));
const result={phase,job_id:jobId,at:new Date().toISOString(),checks:[],page_errors:[],posts:[]};
const save=(name,value)=>fs.writeFile(path.join(out,name),JSON.stringify(value,null,2)+'\n',{flag:'wx'});
async function run(){
 await fs.mkdir(out,{recursive:false});
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();page.setDefaultTimeout(30000);
  page.on('pageerror',e=>result.page_errors.push(e.message));page.on('request',r=>{if(r.method()==='POST')result.posts.push(r.url());});
  await page.goto(base+'/workspace/index.html#validation');await page.waitForFunction(()=>!document.getElementById('simulation-case').disabled);
  await page.locator('#simulation-case').selectOption('b15_engineering');await page.locator(`[data-job-id="${jobId}"]`).click();
  await page.waitForFunction(id=>document.getElementById('simulation-job-meta').textContent.includes(id),jobId);
  const job=await (await context.request.get(base+'/api/simulation/jobs/'+jobId)).json();result.job=job;
  if(phase==='progress'){
   await page.waitForFunction(()=>/^\d+$/.test(document.getElementById('simulation-live-iteration').textContent)&&Number(document.getElementById('simulation-live-iteration').textContent)>1);
   const shown={iteration:await page.locator('#simulation-live-iteration').innerText(),evaluation:await page.locator('#simulation-live-evaluation').innerText(),step:await page.locator('#simulation-live-step').innerText(),updated:await page.locator('#simulation-live-updated').innerText()};
   const code="import pathlib,re,json,sys,subprocess,hashlib;p=pathlib.Path(sys.argv[1]);s=(p/'log.simpleFoam').read_text();t=re.findall(r'(?m)^Time = (\\S+)',s);print(json.dumps({'case':str(p),'iterations':t,'shown_in_raw':sys.argv[2] in t,'raw_sha256':hashlib.sha256(s.encode()).hexdigest(),'last_raw_iteration':t[-1],'run_status':json.loads((p/'run_status.json').read_text()),'processes':subprocess.check_output(['pgrep','-a','-x','simpleFoam'],text=True).splitlines()}))";
   const native=job.live_progress.native_case;assert.equal(native,`/home/lenovo2/nasal_cfd_workspace_jobs/${jobId}/evaluations/${shown.evaluation}`);
   const probe=cp.spawnSync('wsl.exe',['-d','Ubuntu-22.04','--','python3','-c',code,native,shown.iteration],{encoding:'utf8',timeout:15000});assert.equal(probe.status,0,probe.stderr);
   result.ui=shown;result.native=JSON.parse(probe.stdout);assert.equal(result.native.shown_in_raw,true);
   result.checks.push('Existing persisted task restored; actual later GUI iteration >1 occurs in this task native raw log');
   await page.locator('#simulation-live-log-detail summary').click();
  }else{
   assert.ok(['completed','failed','interrupted'].includes(job.status));assert.equal(job.case_id,'b15_engineering');
   assert.equal(job.result.clinical_validation,'not_validated');
   const asset=page.locator('#simulation-job-assets a[href^="/viewer/index.html?manifest="]').first();await asset.waitFor();
   const href=await asset.getAttribute('href'),manifest='/simulation-assets/'+jobId+'/viewer.json';assert.equal(new URL(href,base).searchParams.get('manifest'),manifest);
   const popupEvent=page.waitForEvent('popup');await asset.click();const popup=await popupEvent;
   await popup.waitForURL(u=>u.pathname==='/workspace/index.html'&&u.searchParams.get('manifest')===manifest);
   const frameOf=async()=>{const h=await popup.locator('#panel-geometry iframe:visible').elementHandle();const f=await h.contentFrame();await f.locator('#scene-state').waitFor({state:'hidden'});return f;};
   let frame=await frameOf();assert.equal(await frame.locator('#case-select').inputValue(),jobId);
   assert.match(await frame.locator('#kind-badge').innerText(),/患者工程试算.*非临床/);
   assert.match(await frame.locator('#engineering-warning').innerText(),/数值状态 (unchecked|failed)/);
   assert.equal(await frame.locator('#field-sampling').inputValue(),'y');
   for(const key of ['velocity','pressure']){assert.equal(await frame.locator('#layer-'+key).isDisabled(),false);await frame.locator('#layer-'+key).click();}
   result.viewer_states=[];
   for(const slice of ['x','y','z','surface']){
    await frame.locator('#field-sampling').selectOption(slice);
    const detail=JSON.parse(await frame.locator('#source-detail').innerText());assert.equal(detail.job_id,jobId);assert.equal(detail.case_id,'b15_engineering');assert.equal(detail.display_sampling.id,slice);
    result.viewer_states.push({slice,detail,note:await frame.locator('#field-sampling-note').innerText()});
    if(slice==='surface')assert.match(await frame.locator('#field-sampling-note').innerText(),/不能代表腔内速度/);
   }
   await frame.locator('#field-sampling').selectOption('y');await frame.locator('#layer-velocity').click();
   await popup.screenshot({path:path.join(out,'actual-patient-interior-field.png')});
   await popup.reload();frame=await frameOf();assert.equal(await frame.locator('#case-select').inputValue(),jobId);
   await popup.goto(base+href);await popup.waitForURL(u=>u.pathname==='/workspace/index.html'&&u.searchParams.get('manifest')===manifest);frame=await frameOf();assert.equal(await frame.locator('#case-select').inputValue(),jobId);
   result.checks.push('Actual patient artifact click/direct open/refresh preserve job, nonclinical state, Y default, X/Y/Z and surface fields');
   await popup.close();
  }
  await page.screenshot({path:path.join(out,'desktop.png'),fullPage:true});
  for(const width of [390,320]){await page.setViewportSize({width,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.screenshot({path:path.join(out,'width-'+width+'.png'),fullPage:true});}
  assert.deepEqual(result.page_errors,[]);assert.deepEqual(result.posts,[]);result.passed=true;
 }catch(e){result.passed=false;result.failure=e.stack;throw e;}
 finally{result.finished_at=new Date().toISOString();await browser.close();await save('verification.json',result);}
 console.log(JSON.stringify({passed:true,phase,job_id:jobId,ui_iteration:result.ui?.iteration,checks:result.checks}));
}
run().catch(e=>{console.error(e);process.exitCode=1;});
