/* Run against an isolated case-root; never import synthetic feedback into real cases. */
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

async function main() {
  const url = process.argv[2];
  const out = path.resolve(process.argv[3] || '.tools/medical-review-qa');
  if (!url || !/^http:\/\/127\.0\.0\.1:\d+$/.test(url)) throw Error('Provide an isolated localhost server URL');
  await fs.mkdir(out, {recursive:true});
  const browser = await chromium.launch({headless:true, executablePath:process.env.BROWSER_EXECUTABLE || undefined});
  const report = {url, checks:[], errors:[]};
  const check = label => report.checks.push(label);
  try {
    const context = await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
    const page = await context.newPage();
    page.on('pageerror', error => report.errors.push(error.message));
    await page.goto(url+'/workspace/index.html#review');
    await page.locator('#medical-export').click();
    await page.waitForFunction(()=>document.getElementById('medical-export-message').textContent==='');
    await page.locator('#medical-export-case').selectOption('p0');
    await page.locator('#medical-export-stage').selectOption('landmarks');
    const exported = page.waitForEvent('download');
    await page.locator('#medical-export-download').click();
    const downloaded = await exported;
    const htmlPath = path.join(out, 'p0_landmarks.html');
    await downloaded.saveAs(htmlPath);
    await page.locator('#medical-export-close').click();
    check('real p0 exported from workspace');

    const offline = await browser.newContext({viewport:{width:1440,height:1000},offline:true,acceptDownloads:true});
    const review = await offline.newPage();
    review.on('pageerror', error => report.errors.push(error.message));
    const network = [];
    review.on('request', request => {if (/^https?:/.test(request.url())) network.push(request.url());});
    await review.goto(pathToFileURL(htmlPath).href);
    assert.equal(await review.evaluate(()=>MANIFEST.case),'p0');
    await review.locator('#images img').first().waitFor();
    assert.equal(await review.locator('#item-list button').count(),5);
    const pixels = await review.evaluate(() => [...document.querySelectorAll('#images img')].map(img => {
      const canvas = document.createElement('canvas');canvas.width=32;canvas.height=32;
      canvas.getContext('2d').drawImage(img,0,0,32,32);
      const rgb=canvas.getContext('2d').getImageData(0,0,32,32).data;
      return {width:img.naturalWidth,height:img.naturalHeight,levels:new Set(rgb).size};
    }));
    assert.ok(pixels.every(p=>p.width>100&&p.height>100&&p.levels>10));
    assert.equal(network.length,0);
    report.image_pixels=pixels;
    check('file URL loads real CT images with offline networking and nonblank pixels');

    await review.locator('#decision').selectOption('adjust');
    await review.locator('#point-inputs input').nth(0).fill('1.25');
    await review.reload();
    assert.equal(await review.locator('#decision').inputValue(),'adjust');
    assert.equal(await review.locator('#point-inputs input').nth(0).inputValue(),'1.25');
    assert.equal(await review.locator('#point-inputs input').nth(1).inputValue(),'');
    await review.locator('#download').click();
    assert.ok((await review.locator('#message').innerText()).includes('复核人'));
    await review.locator('#reviewer').fill('Synthetic UI QA');
    await review.locator('#note').fill('位置需复查，仅用于软件流程验证。');
    await review.locator('#download').click();
    assert.ok((await review.locator('#message').innerText()).includes('坐标'));
    const point = await review.evaluate(()=>MANIFEST.items[0].point_lps_mm);
    for(let i=0;i<3;i++)await review.locator('#point-inputs input').nth(i).fill(String(point[i]));
    await review.locator('#next').click();
    await review.locator('#decision').selectOption('reject');
    await review.reload();
    await review.locator('#item-list button').nth(1).click();
    assert.equal(await review.locator('#decision').inputValue(),'reject');
    await review.locator('#note').fill('仅用于软件流程验证的否决意见。');
    await review.locator('#item-list button').nth(2).click();
    await review.locator('#decision').selectOption('accept');
    await review.screenshot({path:path.join(out,'offline-desktop.png'),fullPage:true});
    const replyDownload = review.waitForEvent('download');
    await review.locator('#download').click();
    const replyPath = path.join(out,'p0_feedback.json');
    await (await replyDownload).saveAs(replyPath);
    const reply = JSON.parse(await fs.readFile(replyPath,'utf8'));
    assert.equal(reply.items.length,5);
    assert.deepEqual(reply.items.map(i=>i.decision),['adjust','reject','accept','pending','pending']);
    check('partial adjustment and rejection drafts survive reload; final feedback validation and download pass');
    await review.locator('#resume-file').setInputFiles(replyPath);
    assert.equal(await review.locator('#reviewer').inputValue(),'Synthetic UI QA');
    check('downloaded feedback can be reopened as a draft');

    for(const viewport of [{width:390,height:844},{width:320,height:700}]) {
      await review.setViewportSize(viewport);
      assert.ok(await review.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      const fits = await review.locator('.toolbar button').evaluateAll(nodes=>nodes.every(node=>node.scrollWidth<=node.clientWidth));
      assert.ok(fits);
      assert.ok((await review.locator('#reviewer').boundingBox()).width >= 150);
      await review.screenshot({path:path.join(out,`offline-mobile-${viewport.width}.png`),fullPage:true});
      await review.locator('#images img').first().click();
      assert.ok(await review.locator('#lightbox').isVisible());
      await review.keyboard.press('Escape');
      assert.ok(await review.locator('#lightbox').isHidden());
    }
    check('390px and 320px offline layouts, image enlargement and closing pass');

    await page.locator('#medical-feedback-file').setInputFiles(replyPath);
    await page.locator('#medical-feedback-message').filter({hasText:'朋友反馈已导入'}).waitFor();
    const feedbackRecord=page.locator('.feedback-record').first();
    assert.ok((await feedbackRecord.innerText()).includes('Synthetic UI QA'));
    await page.screenshot({path:path.join(out,'feedback-desktop.png'),fullPage:true});
    await feedbackRecord.locator('.feedback-item input').first().check();
    const selectionDownload = page.waitForEvent('download');
    await feedbackRecord.getByRole('button',{name:'下载所选审核记录'}).click();
    const selectedPath = path.join(out,'selected_review.json');
    await (await selectionDownload).saveAs(selectedPath);
    const selected = JSON.parse(await fs.readFile(selectedPath,'utf8'));
    assert.equal(selected.cases[0].decisions.length,1);
    check('feedback import and selected point conversion pass');

    const sliceFrame = page.frames().find(frame=>frame.url().includes('/landmark-review/index.html'));
    assert.ok(sliceFrame);
    await sliceFrame.evaluate(({reply,selected})=>{
      const c=DATA.cases.find(c=>c.case==='p0');
      const chosen=c.landmarks.find(l=>l.id===selected.cases[0].decisions[0].landmark_id);
      const other=c.landmarks.find(l=>l.id!==chosen.id);
      records[recordKey(c,other)]={decision:'reject',note:'prior local review',updated_at:new Date().toISOString()};
      records[recordKey(c,chosen)]={decision:'reject',note:'existing selected review',updated_at:new Date().toISOString()};save();render();
    },{reply,selected});
    await page.locator('a[data-step="review"]').click();
    await sliceFrame.locator('#import').click();
    await sliceFrame.locator('#import-file').setInputFiles(selectedPath);
    await sliceFrame.locator('#apply-import').click();
    let exportedReview=await sliceFrame.evaluate(()=>exportReview(true));
    assert.equal(exportedReview.cases.find(c=>c.case==='p0').decisions.find(d=>d.landmark_id===selected.cases[0].decisions[0].landmark_id).decision,'reject');
    await sliceFrame.locator('#import').click();
    await sliceFrame.locator('#import-file').setInputFiles(selectedPath);
    await sliceFrame.locator('#import-overwrite').check();
    await sliceFrame.locator('#apply-import').click();
    exportedReview=await sliceFrame.evaluate(()=>exportReview(true));
    const result=exportedReview.cases.find(c=>c.case==='p0').decisions;
    assert.equal(result.find(d=>d.landmark_id===selected.cases[0].decisions[0].landmark_id).decision,'adjust');
    assert.ok(result.some(d=>d.note==='prior local review'&&d.decision==='reject'));
    check('existing slice import preserves unselected decisions and requires overwrite choice for reviewed points');

    const changed={...reply,package_sha256:'0'.repeat(64)};
    await page.locator('#medical-feedback-file').setInputFiles({name:'stale.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(changed))});
    await page.locator('#medical-toast').filter({hasText:'不属于'}).waitFor();
    check('unregistered feedback is rejected in workspace');
    await page.locator('a[data-step="feedback"]').click();
    for(const width of [390,320]) {
      await page.setViewportSize({width,height:844});
      await page.locator('.feedback-record').first().waitFor();
      await page.waitForFunction(()=>!document.getElementById('medical-feedback-list').textContent.includes('正在读取反馈'));
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      await page.screenshot({path:path.join(out,`feedback-mobile-${width}.png`),fullPage:true});
    }
    check('workspace feedback mobile layouts pass');

    await page.locator('#medical-export').click();
    await page.waitForFunction(()=>document.getElementById('medical-export-message').textContent==='');
    await page.locator('#medical-export-case').selectOption('p0');
    await page.locator('#medical-export-stage').selectOption('boundary');
    const boundaryDownload=page.waitForEvent('download');
    await page.locator('#medical-export-download').click();
    const boundaryPath=path.join(out,'p0_boundary.html');
    await (await boundaryDownload).saveAs(boundaryPath);
    await review.goto(pathToFileURL(boundaryPath).href);
    assert.equal(await review.locator('#item-list button').count(),9);
    assert.ok(await review.locator('#decision option[value="accept"]').isDisabled());
    assert.ok(await review.locator('#decision option[value="adjust"]').isDisabled());
    await review.locator('#reviewer').fill('Synthetic UI QA');
    await review.locator('#decision').selectOption('insufficient');
    const boundaryReply=await review.evaluate(()=>exportFeedback(true));
    const response=await context.request.post(url+'/api/cases/p0/medical-feedback',{data:boundaryReply});
    assert.equal(response.status(),201);
    check('later boundary feedback roundtrip works; missing evidence cannot pass');
    assert.deepEqual(report.errors,[]);
    report.passed=true;
  } catch (error) {
    report.failure=error.message;
    throw error;
  } finally {
    await browser.close();
    await fs.writeFile(path.join(out,'verification.json'),JSON.stringify(report,null,2)+'\n');
  }
  console.log(JSON.stringify(report,null,2));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
