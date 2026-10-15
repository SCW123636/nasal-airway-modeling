/* Live browser verification. Creates only preflight jobs, never CFD / mesh jobs. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.argv[2] || 'http://127.0.0.1:8769';
const out = path.resolve(process.argv[3] || 'outputs/T-016/browser');
const onlyRead = process.argv.includes('--readonly');
const root = path.resolve(__dirname, '..', '..');
const inputs = ['p0','p1','p2','p3','p3t1'].map(id => path.join(root,'work','06_auto_landmarks',id,'landmarks.json'));
const digest = async file => crypto.createHash('sha256').update(await fs.readFile(file)).digest('hex');
async function main() {
  assert.match(base, /^http:\/\/127\.0\.0\.1:\d+$/);
  await fs.mkdir(out, {recursive:true});
  const before = await Promise.all(inputs.map(digest));
  const report = {base,started_at:new Date().toISOString(),preflight_only:true,readonly:onlyRead,checks:[],created_jobs:[],api_records:[],console_errors:[],page_errors:[],failed_requests:[]};
  const record = label => report.checks.push(label);
  const browser = await chromium.launch({headless:true, executablePath:process.env.BROWSER_EXECUTABLE || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  let expectedFault = false;
  try {
    const context = await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
    const page = await context.newPage(); page.setDefaultTimeout(20000);
    page.on('pageerror', error => report.page_errors.push(error.message));
    page.on('console', msg => {if(msg.type() === 'error') report.console_errors.push({text:msg.text(),expected_fault:expectedFault});});
    page.on('requestfailed', req => report.failed_requests.push({url:req.url(),error:req.failure()?.errorText,expected_fault:expectedFault}));
    page.on('response', async response => {if(response.url().includes('/api/simulation/')) {let body;try {body = await response.json();} catch {body = null;} report.api_records.push({method:response.request().method(),url:response.url(),status:response.status(),expected_fault:expectedFault,body});}});
    const shot = async name => {await page.locator('#panel-validation').evaluate(node=>node.scrollTop=0); return page.screenshot({path:path.join(out,name+'.png'),fullPage:true});};
    const ready = () => page.waitForFunction(() => !document.getElementById('simulation-case').disabled);
    const noOverflow = async () => assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Workspace overflows viewport');
    const navigate = async step => {await page.locator(`[data-step="${step}"]`).click(); await page.locator('#panel-'+step).waitFor({state:'visible'});};
    await page.goto(base+'/workspace/index.html#validation'); await ready();
    assert.ok(await page.locator('#simulation-case option').count() >= 6);
    assert.doesNotMatch(await page.locator('#panel-validation').innerText(), /adapter 实现中|适配器实现中/);
    record('live catalog, six or more objects, obsolete adapter text removed');
    await page.locator('#simulation-case').selectOption('p0');
    await page.waitForFunction(() => document.getElementById('simulation-kind').textContent === '患者数据');
    assert.equal(await page.locator('#simulation-run').isDisabled(), true);
    assert.ok((await page.locator('#simulation-blockers').innerText()).length > 10);
    await noOverflow(); await shot('desktop-patient-blocked');
    record('patient launch disabled with API blocking reasons');
    await page.locator('#simulation-case').selectOption('reference_channel');
    await page.waitForFunction(() => document.getElementById('simulation-kind').textContent === '非患者参考');
    assert.match(await page.locator('#simulation-parameters').innerText(), /0\.012/);
    await page.locator('#simulation-level').selectOption('coarse');
    record('fixed actual reference physics displayed; editable mesh level only');
    if (!onlyRead) {
      const posted = page.waitForResponse(response => response.url() === base+'/api/simulation/jobs' && response.request().method() === 'POST');
      await page.locator('#simulation-preflight').click();
      const response = await posted; assert.equal(response.status(),202);
      const job = await response.json(); assert.equal(job.action,'preflight'); assert.equal(job.case_id,'reference_channel');
      report.created_jobs.push({id:job.id,case_id:job.case_id,action:job.action});
      await page.waitForFunction(id => document.getElementById('simulation-job-meta').textContent.includes(id) && ['已执行','失败','已中断'].includes(document.getElementById('simulation-job-status').textContent), job.id, {timeout:120000});
      assert.ok(await page.locator('#simulation-checks .simulation-check').count() > 0);
      assert.equal(await page.locator('#simulation-result table').count(),0,'Preflight must not fabricate numerical flow results');
      record('real reference preflight created through UI and actual checks read');
      await shot('desktop-reference-preflight');
      await page.reload(); await ready();
      await page.waitForFunction(id => document.getElementById('simulation-job-meta').textContent.includes(id), job.id);
      assert.equal(await page.locator('#simulation-case').inputValue(),'reference_channel','Refresh changed dropdown identity');
      record('refresh restores persisted selected reference task');
      // Inject an explicit read failure; no simulated success or numerical result is used.
      const failingUrl = base+'/api/simulation/jobs/'+job.id;
      await page.route(failingUrl, route => route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'故障注入：任务读取暂不可用'})}));
      expectedFault = true;
      await page.locator(`[data-job-id="${job.id}"]`).click();
      await page.waitForFunction(() => document.getElementById('simulation-job-empty').textContent.includes('任务详情未读取'));
      assert.equal(await page.locator('#simulation-result table').count(),0);
      await shot('desktop-task-read-failure');
      await page.unroute(failingUrl); expectedFault = false;
      await page.locator('#simulation-refresh').click();
      await page.waitForFunction(id => document.getElementById('simulation-job-meta').textContent.includes(id) && !document.getElementById('simulation-job-detail').hidden, job.id);
      record('controlled HTTP 503 clears result and refresh recovers live task');
      await page.locator('#simulation-case').selectOption('p0');
      const patientPosted = page.waitForResponse(res => res.url() === base+'/api/simulation/jobs' && res.request().method() === 'POST');
      await page.locator('#simulation-preflight').click();
      const patientResponse = await patientPosted; assert.equal(patientResponse.status(),202);
      const patientJob = await patientResponse.json(); assert.equal(patientJob.case_id,'p0'); assert.equal(patientJob.action,'preflight');
      report.created_jobs.push({id:patientJob.id,case_id:patientJob.case_id,action:patientJob.action});
      await page.waitForFunction(id => document.getElementById('simulation-job-meta').textContent.includes(id) && ['已执行','失败','已中断'].includes(document.getElementById('simulation-job-status').textContent), patientJob.id, {timeout:120000});
      assert.match(await page.locator('#simulation-checks').innerText(), /未通过/);
      assert.equal(await page.locator('#simulation-run').isDisabled(),true);
      assert.equal(await page.locator('#simulation-result table').count(),0);
      record('real patient preflight fails admission honestly, no reference result leaks');
    }
    await page.locator('#simulation-show-all').check();
    assert.ok(await page.locator('.simulation-job-row').count() >= (onlyRead ? 0 : 2));
    await page.locator('#simulation-show-all').uncheck();
    record('task history supports all objects and selected object');
    for (const width of [390,320]) {
      await page.setViewportSize({width,height:844}); await noOverflow();
      await shot(`mobile-patient-${width}`);
      await page.locator('#simulation-case').selectOption('reference_channel'); await noOverflow();
      await shot(`mobile-reference-${width}`);
      await page.locator('#simulation-case').selectOption('p0');
    }
    record('390px and 320px narrow layouts show controls without overflow');
    await page.setViewportSize({width:1440,height:1000});
    await navigate('import'); assert.equal(await page.locator('#upload-start').isVisible(),true);
    await navigate('review'); await page.locator('#panel-review iframe').waitFor();
    const reviewHandle = await page.locator('#panel-review iframe').elementHandle(); const review = await reviewHandle.contentFrame(); await review.locator('#cards .card').first().waitFor();
    await navigate('feedback'); await page.locator('#medical-feedback-case').waitFor();
    await page.locator('#medical-export').click(); await page.locator('#medical-export-dialog').waitFor({state:'visible'}); await page.locator('#medical-export-close').click();
    record('import, slice review, feedback and export dialog still open');
    await navigate('overview'); const priorRequests = report.api_records.length;
    await page.waitForTimeout(2500); assert.equal(report.api_records.length,priorRequests,'Hidden simulation page keeps polling');
    record('simulation polling stops outside visible page');
    await navigate('validation'); await ready(); await shot('desktop-final');
    const liveJobs = (await (await context.request.get(base+'/api/simulation/jobs')).json()).jobs;
    const referenceRun = liveJobs.find(job=>job.action==='run_reference' && job.case_id==='reference_channel' && job.status==='completed' && job.result?.cases?.length);
    if (referenceRun) {
      await page.locator('#simulation-case').selectOption('reference_channel');
      await page.locator(`[data-job-id="${referenceRun.id}"]`).click();
      await page.waitForFunction(id => !document.getElementById('simulation-job-detail').hidden && document.getElementById('simulation-job-meta').textContent.includes(id) && document.querySelector('#simulation-result table'),referenceRun.id);
      assert.match(await page.locator('#simulation-result').innerText(),/非患者参考/);
      assert.ok(await page.locator('#simulation-job-assets a[href^="/viewer/index.html?manifest="]').count()>0);
      assert.equal(await page.locator('#simulation-job-assets a[download]').count(),0);
      assert.equal(await page.locator('#simulation-case').inputValue(),'reference_channel');
      await shot('desktop-real-reference-result');
      await page.setViewportSize({width:390,height:844}); await noOverflow(); await shot('mobile-real-reference-result');
      report.read_reference_job=referenceRun.id;
      record('Lead-created real reference numerical result and live three-dimensional link visible');
      const manifestPath = `/simulation-assets/${referenceRun.id}/viewer.json`;
      const manifest = await (await context.request.get(base+manifestPath)).json();
      const expectedCase = manifest.cases[0].id;
      const catalogData = await (await context.request.get(base+'/api/simulation/catalog')).json();
      const uploadId = catalogData.cases.find(item=>/^u_[0-9a-f]{16}$/.test(item.id))?.id;
      if (uploadId) await page.evaluate(id=>localStorage.setItem('nasal_active_uploaded_case',id),uploadId);
      const readGeometry = async target => {
        await target.locator('#panel-geometry').waitFor({state:'visible'});
        const handle = await target.locator('#panel-geometry iframe:visible').elementHandle();
        const frame = await handle.contentFrame();
        await frame.locator('#scene-state').waitFor({state:'hidden',timeout:30000});
        return frame;
      };
      const popupEvent = page.waitForEvent('popup');
      await page.locator('#simulation-job-assets a[href^="/viewer/index.html?manifest="]').click();
      const popup = await popupEvent;
      popup.on('pageerror',error=>report.page_errors.push(error.message));
      await popup.waitForURL(url=>url.pathname==='/workspace/index.html' && url.searchParams.get('manifest')===manifestPath && url.hash==='#geometry');
      let geometry = await readGeometry(popup);
      assert.equal(new URL(geometry.url()).searchParams.get('manifest'),manifestPath);
      assert.equal(await geometry.locator('#case-select').inputValue(),expectedCase);
      assert.equal(await geometry.locator('#layer-velocity').isDisabled(),false);
      assert.equal(await geometry.locator('#layer-pressure').isDisabled(),false);
      await popup.setViewportSize({width:1440,height:1000});
      await popup.screenshot({path:path.join(out,'desktop-artifact-live-viewer.png')});
      await popup.reload(); geometry = await readGeometry(popup);
      assert.equal(new URL(popup.url()).searchParams.get('manifest'),manifestPath);
      assert.equal(await geometry.locator('#case-select').inputValue(),expectedCase);
      record('actual artifact click reaches correct reference geometry and survives refresh, including stale uploaded-case storage');
      await popup.goto(base+'/viewer/index.html?manifest='+manifestPath);
      await popup.waitForURL(url=>url.pathname==='/workspace/index.html' && url.searchParams.get('manifest')===manifestPath);
      geometry = await readGeometry(popup); assert.equal(await geometry.locator('#case-select').inputValue(),expectedCase);
      record('top-level viewer URL preserves manifest through workspace redirect');
      await popup.locator('#active-case').selectOption('existing');
      await popup.waitForFunction(()=>!new URL(location.href).searchParams.has('manifest'));
      geometry = await readGeometry(popup); assert.equal(await geometry.locator('#case-select').inputValue(),'p0');
      await popup.goto(base+'/viewer/index.html');
      await popup.waitForURL(url=>url.pathname==='/workspace/index.html' && url.hash==='#geometry');
      geometry = await readGeometry(popup); assert.equal(await geometry.locator('#case-select').inputValue(),'p0');
      record('explicit patient switch and original top-level patient viewer still open p0');
      await popup.goto(base+'/viewer/index.html?manifest=/simulation-assets/invalid/viewer.json');
      await popup.waitForURL(url=>url.pathname==='/workspace/index.html');
      await popup.locator('#panel-geometry .case-notice h3').filter({hasText:'三维结果地址无效'}).waitFor();
      assert.equal(await popup.locator('#panel-geometry iframe:visible').count(),0);
      record('invalid manifest gives explicit error and never silently falls back to patient');
      await popup.close();
    }
    assert.equal(await page.locator('#simulation-job-assets a[download]').count(),0,'Viewer link must not be forced to download');
    assert.equal(context.pages().length,1);
    assert.deepEqual(report.page_errors,[]);
    assert.deepEqual(report.console_errors.filter(item => !item.expected_fault),[]);
    assert.deepEqual(report.failed_requests.filter(item => !item.expected_fault),[]);
    assert.deepEqual(await Promise.all(inputs.map(digest)),before,'Original landmark inputs changed');
    report.input_sha256 = Object.fromEntries(inputs.map((file,i)=>[file,before[i]]));
    record('input fingerprints unchanged; no unexpected browser errors');
    report.passed = true;
  } catch (error) { report.failure = error.stack; throw error; }
  finally {report.finished_at = new Date().toISOString(); await browser.close(); await fs.writeFile(path.join(out,'verification.json'),JSON.stringify(report,null,2)+'\n');}
  console.log(JSON.stringify({passed:report.passed,checks:report.checks,created_jobs:report.created_jobs},null,2));
}
/* Isolated UI contracts. All simulation API calls are intercepted; no job or
 * solver is created. Fixture numbers test rendering only, never physics. */
async function mockMain() {
  const mockOut = out;
  await fs.mkdir(mockOut,{recursive:true});
  const report = {mode:'mock_UI_contract_only',base,started_at:new Date().toISOString(),checks:[],requests:[],real_solver_started:false,page_errors:[],screenshots:[]};
  const record = text => report.checks.push(text);
  const shared = {source_detail:'UI rendering fixture; no real CFD source',geometry_status:'ready',mesh_status:'ready',solver_status:'available',clinical_validation:'not_validated',engineering_checks:[{name:'fixture_identity',passed:true,source:'test fixture',detail:'UI contract fixture; no clinical or numerical validation'}]};
  const cases = [
    {...shared,id:'p0',kind:'patient',label:'患者 · 受阻 fixture',run_action:'run_patient_engineering',run_allowed:false,blocking_reasons:['fixture：最终几何尚未准入']},
    {...shared,id:'patient_ready_fixture',kind:'patient',label:'患者工程可运行 fixture',run_action:'run_patient_engineering',run_allowed:true,blocking_reasons:[]},
    {...shared,id:'reference_channel',kind:'reference',label:'平行板参考 fixture',run_action:'run_reference',run_allowed:true,blocking_reasons:[],fixed_parameters:{Q_L_min:0.012,outlet_gauge_p_Pa:0}},
    {...shared,id:'reference_split_feedback',kind:'reference',label:'共同压力分流参考 fixture',run_action:'run_pressure_feedback',run_allowed:true,blocking_reasons:[],fixed_parameters:{target_flow_L_min:1,outlet_gauge_p_Pa:0,boundary_strategy:'common_inlet_pressure_feedback'}},
    {...shared,id:'unknown_fixture',kind:'reference',label:'未知动作 fixture',run_action:'unsupported_action',run_allowed:true,blocking_reasons:[]}
  ];
  const feedback = {
    patient_data:false,reference_type:'split_pressure_feedback',backend:'mock_fixture_not_a_solver',numerical_validation:'unchecked',clinical_validation:'not_validated',
    checks:{fixture_record_only:{passed:true,detail:'rendering fixture only'}},
    scenarios:{unequal:{result:{pressure_pa:2.5,target_m3_s:1/60000,q_total_m3_s:1/60000,q_left_m3_s:.4/60000,q_right_m3_s:.6/60000,q_out_m3_s:1/60000,left_fraction:.4,relative_flow_error:.0005,evaluation_count:2,iterations:[{pressure_pa:1,q_total_m3_s:.4/60000,q_left_m3_s:.16/60000,q_right_m3_s:.24/60000,relative_flow_error:.6},{pressure_pa:2.5,q_total_m3_s:1/60000,q_left_m3_s:.4/60000,q_right_m3_s:.6/60000,relative_flow_error:.0005,residuals_passed:true}]},evaluations:[{pressure_pa:2.5,status:'completed',exit_code:0,diagnostics:{flux:{mass_imbalance_frac:.0001},residual_max:.00002,monitor_relative_change:.00003,mesh_quality_passed:true}}]}}
  };
  let mockJobs = [], failPost = false, serial = 0;
  const browser = await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    const context = await browser.newContext({viewport:{width:1440,height:1000}});
    const page = await context.newPage(); page.setDefaultTimeout(20000);
    page.on('pageerror',error=>report.page_errors.push(error.message));
    await page.route('**/api/simulation/**',async route=>{
      const request = route.request(), url = new URL(request.url());
      const send = (data,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
      if (url.pathname.endsWith('/catalog')) return send({cases});
      if (request.method()==='POST') {
        const payload=request.postDataJSON(); report.requests.push(payload);
        if (failPost) return send({error:'fixture：后端拒绝工程准入'},403);
        const id='s_'+(++serial).toString(16).padStart(24,'0');
        const job={id,case_id:payload.case_id,action:payload.action,status:'completed',stage:'completed',created_at:new Date().toISOString(),updated_at:new Date().toISOString(),exit_code:0,artifacts:[],log_excerpt:'Mock rendering fixture; no solver process.'};
        if (payload.action==='preflight') job.preflight={passed:true,clinical_validation:'not_validated',checks:[{name:'wsl_environment',passed:true,detail:'mock only'}]};
        else if (payload.action==='run_reference') job.result={patient_data:false,clinical_validation:'not_validated',numerical_validation:'unchecked',cases:[{level:'coarse',cells:800,delta_p_boundary_Pa:.2,mass_imbalance_fraction:.0001,converged:true}]};
        else if (payload.action==='run_patient_engineering') {job.status='failed';job.stage='failed';job.error='fixture quality gate failure';job.result={patient_data:true,clinical_validation:'not_validated',numerical_validation:'unchecked',backend:'mock_fixture_not_a_solver',engineering_trial:true,execution_status:'failed',scenario:{result:{},evaluations:[{pressure_pa:1,status:'failed',diagnostics:{flux:{mass_imbalance_frac:.04},residual_max:.1,mesh_quality_passed:false}}]}};}
        else job.result=structuredClone(feedback);
        mockJobs.unshift(job); return send(job,202);
      }
      if (url.pathname.endsWith('/jobs')) return send({jobs:mockJobs});
      const job=mockJobs.find(item=>url.pathname.endsWith('/'+item.id));
      return job ? send(job) : send({error:'fixture task not found'},404);
    });
    const ready = () => page.waitForFunction(()=>!document.getElementById('simulation-case').disabled);
    const choose = async id => {await page.locator('#simulation-case').selectOption(id); await page.waitForFunction(value=>document.getElementById('simulation-case').value===value,id);};
    const post = async selector => {const prior=report.requests.length; await page.locator(selector).click(); await page.waitForFunction(()=>!document.getElementById('simulation-preflight').disabled); assert.equal(report.requests.length,prior+1); return report.requests.at(-1);};
    const noOverflow = async () => assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'viewport overflow');
    const screenshot = async name => {await page.locator('#panel-validation').evaluate(node=>node.scrollTop=0); await page.screenshot({path:path.join(mockOut,name+'.png'),fullPage:true}); report.screenshots.push(name+'.png');};
    await page.goto(base+'/workspace/index.html#validation'); await ready();
    await choose('p0'); assert.equal(await page.locator('#simulation-run').isDisabled(),true);
    assert.match(await page.locator('#simulation-blockers').innerText(),/最终几何/);
    assert.match(await page.locator('#simulation-engineering-checks').innerText(),/临床验证：未验证/);
    record('blocked patient retains reasons and explicit clinical status');
    await choose('reference_split_feedback');
    assert.equal(await page.locator('#simulation-run').isDisabled(),false);
    assert.equal(await page.locator('#simulation-feedback-settings').isVisible(),true);
    assert.equal(await page.locator('#simulation-reference-settings').isVisible(),false);
    assert.match(await page.locator('#simulation-feedback-parameters').innerText(),/目标总流量 1 L\/min/);
    const prepared=await post('#simulation-preflight');
    assert.equal(prepared.action,'preflight');
    assert.deepEqual(prepared.settings,{scenarios:['unequal','symmetric','swapped_labels']});
    assert.equal(await page.locator('#simulation-result table').count(),0);
    record('feedback preflight posts scenarios and never synthesizes flow results');
    const launched=await post('#simulation-run');
    assert.equal(launched.action,'run_pressure_feedback');
    assert.deepEqual(launched.settings,{scenarios:['unequal','symmetric','swapped_labels']});
    const rendered = await page.locator('#simulation-result').innerText();
    assert.match(rendered,/非患者参考/); assert.match(rendered,/数值验证：未检查 · 临床验证：未验证/);
    assert.match(rendered,/共同入口静压 Pa/); assert.match(rendered,/左侧自然分流/); assert.match(rendered,/40%/);
    assert.match(rendered,/守恒不平衡/); assert.match(rendered,/最大残差/);
    assert.match(rendered,/mock_fixture_not_a_solver/);
    await page.locator('#simulation-result details summary').click();
    assert.equal(await page.locator('#simulation-result details tbody tr').count(),2);
    record('feedback shows common pressure, target/measured flow, natural split, diagnostics and raw iterations');
    await noOverflow(); await screenshot('desktop-feedback-mock');
    const feedbackJob=mockJobs[0].id;
    await page.reload(); await ready();
    await page.waitForFunction(id=>document.getElementById('simulation-job-meta').textContent.includes(id),feedbackJob);
    assert.equal(await page.locator('#simulation-case').inputValue(),'reference_split_feedback');
    record('persistent selected feedback task restores after reload');
    for (const width of [390,320]) {
      await page.setViewportSize({width,height:844}); await noOverflow(); await screenshot('feedback-mock-'+width);
      await page.locator('#simulation-result').screenshot({path:path.join(mockOut,'feedback-result-mock-'+width+'.png')}); report.screenshots.push('feedback-result-mock-'+width+'.png');
      await choose('patient_ready_fixture'); await noOverflow(); await screenshot('patient-mock-'+width);
      await choose('reference_split_feedback');
    }
    record('desktop, 390 and 320 pixel layouts remain within viewport');
    await page.setViewportSize({width:1440,height:1000});
    await page.locator('#simulation-scenario').selectOption('symmetric');
    const symmetric=await post('#simulation-run'); assert.deepEqual(symmetric.settings,{scenarios:['symmetric']});
    record('individual feedback scenario posts only the selected scenario');
    await choose('patient_ready_fixture');
    assert.equal(await page.locator('#simulation-run').isDisabled(),false);
    assert.match(await page.locator('#simulation-run').innerText(),/患者工程试算/);
    assert.equal(await page.locator('#simulation-feedback-settings').isVisible(),false);
    const patient=await post('#simulation-run'); assert.equal(patient.action,'run_patient_engineering'); assert.deepEqual(patient.settings,{});
    assert.match(await page.locator('#simulation-result').innerText(),/患者工程试算 · 非临床结果/);
    assert.equal(await page.locator('#simulation-job-status').innerText(),'失败');
    assert.match(await page.locator('#simulation-result').innerText(),/未获得/);
    assert.match(await page.locator('#simulation-result').innerText(),/不代表共同压力反馈达标/);
    assert.match(await page.locator('#simulation-result table').innerText(),/4%/);
    assert.match(await page.locator('#simulation-result table').innerText(),/未通过/);
    record('run_allowed patient posts engineering action with empty settings; failed single scenario retains diagnostics without claiming target success');
    failPost=true;
    await post('#simulation-run');
    assert.match(await page.locator('#simulation-message').innerText(),/后端拒绝工程准入/);
    assert.equal(mockJobs.length,4);
    failPost=false;
    record('backend admission rejection displayed with no successful new task');
    await choose('unknown_fixture'); assert.equal(await page.locator('#simulation-run').isDisabled(),true);
    record('unknown run_action remains disabled');
    await choose('reference_channel'); await page.locator('#simulation-level').selectOption('all');
    const oldReference=await post('#simulation-run'); assert.equal(oldReference.action,'run_reference'); assert.deepEqual(oldReference.settings,{levels:['coarse','medium','fine']});
    assert.equal(await page.locator('#simulation-result table tbody tr').count(),1);
    record('existing parallel plate reference levels and results remain usable');
    await choose('reference_split_feedback');
    const partial=mockJobs.find(job=>job.action==='run_pressure_feedback');
    delete partial.result.scenarios.unequal.result.q_right_m3_s;
    delete partial.result.scenarios.unequal.evaluations[0].diagnostics.residual_max;
    await page.locator('[data-job-id="'+partial.id+'"]').click();
    await page.waitForFunction(()=>document.getElementById('simulation-result').textContent.includes('未获得'));
    const rightFact=page.locator('.simulation-feedback-facts>div').filter({has:page.locator('dt',{hasText:'右侧流量 L/min'})});
    assert.equal(await rightFact.locator('dd').innerText(),'未获得');
    assert.match(await page.locator('#simulation-result table').first().innerText(),/未获得/);
    record('missing flow and residual values show unavailable, never fallback zero');
    await page.locator('#simulation-show-all').check(); assert.equal(await page.locator('.simulation-job-row').count(),mockJobs.length);
    await page.locator('#simulation-show-all').uncheck();
    assert.equal(await page.locator('.simulation-job-row').count(),mockJobs.filter(job=>job.case_id==='reference_split_feedback').length);
    record('mixed persistent history retains action labels and case filtering');
    await noOverflow(); await screenshot('desktop-partial-feedback-mock');
    const progressJob={id:'s_ffffffffffffffffffffffff',case_id:'reference_split_feedback',action:'run_pressure_feedback',status:'running',stage:'mesh',created_at:new Date().toISOString(),updated_at:new Date().toISOString(),live_progress:{stage:'mesh',evaluation:'eval_001',actual_step:'checkMesh',iteration:null,runner_status:'running',log_tail:'checkMesh fixture; no SIMPLE iteration yet',updated_at:'2026-10-15T10:00:00+08:00'}};
    mockJobs.unshift(progressJob);
    await page.locator('#simulation-refresh').click();
    await page.locator('[data-job-id="'+progressJob.id+'"]').click();
    await page.waitForFunction(()=>document.getElementById('simulation-live-step').textContent.includes('checkMesh'));
    assert.equal(await page.locator('#simulation-live-iteration').innerText(),'未获得');
    assert.equal(await page.locator('#simulation-run').isDisabled(),true);
    await page.locator('#simulation-live-log-detail summary').click();
    const changedAt=Date.now();
    progressJob.stage='solver';
    progressJob.live_progress={stage:'solver',evaluation:'eval_002',actual_step:'simpleFoam',iteration:'533',runner_status:'running',log_tail:'Time = 533\nfixture <tag> raw log; no real CFD',updated_at:'2026-10-15T10:00:03+08:00'};
    await page.waitForFunction(()=>document.getElementById('simulation-live-iteration').textContent==='533',{},{timeout:8000});
    const elapsed=Date.now()-changedAt; assert.ok(elapsed>=2400 && elapsed<8000,'progress did not follow the 3 second read polling interval: '+elapsed);
    assert.match(await page.locator('#simulation-live-step').innerText(),/simpleFoam/);
    assert.equal(await page.locator('#simulation-live-evaluation').innerText(),'eval_002');
    assert.match(await page.locator('#simulation-live-updated').innerText(),/10:00:03/);
    assert.equal(await page.locator('#simulation-live-log').innerText(),progressJob.live_progress.log_tail);
    assert.equal(await page.locator('#simulation-live-log tag').count(),0,'raw log was interpreted as HTML');
    assert.equal(await page.locator('#simulation-live-log-detail').evaluate(node=>node.open),true,'polling closed the opened log');
    report.progress_poll={elapsed_ms:elapsed,iteration_before:null,iteration_after:'533',real_solver_started:false};
    record('3 second running-task polling updates actual step, evaluation, SIMPLE iteration, timestamp and raw log without inventing missing iterations');
    await noOverflow(); await screenshot('desktop-running-progress-mock');
    for (const width of [390,320]) {await page.setViewportSize({width,height:844}); await noOverflow(); await screenshot('running-progress-mock-'+width);}
    progressJob.status='completed';progressJob.stage='completed';
    await page.locator('#simulation-refresh').click();
    assert.deepEqual(report.page_errors,[]);
    report.passed=true;
  } catch(error) {report.failure=error.stack; throw error;}
  finally {report.finished_at=new Date().toISOString(); await browser.close(); await fs.writeFile(path.join(mockOut,'mock-verification.json'),JSON.stringify(report,null,2)+'\n');}
  console.log(JSON.stringify({passed:report.passed,mode:report.mode,checks:report.checks,post_requests:report.requests.length,real_solver_started:false},null,2));
}
(process.argv.includes('--mock') ? mockMain() : main()).catch(error => {console.error(error);process.exitCode = 1;});
