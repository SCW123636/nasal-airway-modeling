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
main().catch(error => {console.error(error);process.exitCode = 1;});
