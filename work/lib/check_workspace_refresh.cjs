const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {chromium} = require('playwright');
const sharp = require('sharp');
const base = process.argv[2] || 'http://127.0.0.1:8769';
const caseId = 'u_367bb67006344b78';
const root = path.resolve(__dirname,'..');
const out = path.join(root,'07_cfd_pipeline/workspace/qa/ui-refresh');
const hash = async file => crypto.createHash('sha256').update(await fs.readFile(file)).digest('hex');
async function noOverflow(frame) {
  const box = await frame.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
  assert(box.scroll<=box.width+1,JSON.stringify(box));
}
(async()=>{
 await fs.mkdir(out,{recursive:true});
 const protectedFiles=['p0','p1','p2','p3','p3t1'].map(c=>path.join(root,'06_auto_landmarks',c,'landmarks.json'));
 protectedFiles.push(path.join(root,'06_auto_landmarks/feedback_review/audit.json'));
 const before=await Promise.all(protectedFiles.map(hash));
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const failures=[],errors=[];
 try{
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 const page=await context.newPage();page.setDefaultTimeout(20000);
 page.on('pageerror',e=>errors.push(e.message));
 page.on('response',r=>{if(r.status()>=400)failures.push({status:r.status(),url:r.url()});});
 await page.goto(base+'/workspace/index.html?case='+caseId+'#import');
 await page.waitForFunction(c=>document.getElementById('active-case').value===c,caseId);
 assert.match(await page.locator('#run-message').textContent(),/新版/);
 assert.equal(await page.locator('#pipeline-stages li').count(),8);
 const visit=async id=>{await page.locator('[data-step='+id+']').click();await page.locator('#panel-'+id).waitFor({state:'visible'});
   if(['geometry','review'].includes(id)){const frame=await (await page.locator('#panel-'+id+' iframe:not([hidden])').elementHandle()).contentFrame();await frame.waitForLoadState('domcontentloaded');await frame.waitForFunction(()=>document.documentElement.dataset.workflow);return frame;}
   return null;
 };
 const shot=async(name)=>{await noOverflow(page);await page.screenshot({path:path.join(out,name+'.png')});};
 await shot('desktop-import');
 await visit('overview');assert.match(await page.locator('#overview-case').textContent(),/344b78/);assert.equal(await page.locator('#overview-stages > div').count(),8);await shot('desktop-overview');
 const geometry=await visit('geometry');await geometry.locator('#scene-state').waitFor({state:'hidden'});
 await geometry.locator('#model-title').filter({hasText:'上传 CT'}).waitFor();assert.equal(await geometry.locator('#landmarks .landmark').count(),5);
 assert(await geometry.locator('#layer-velocity').isDisabled());await noOverflow(geometry);
 const canvas=geometry.locator('canvas');const buffer=await canvas.screenshot();const stats=await sharp(buffer).stats();assert(stats.channels.some(c=>c.stdev>5),'Canvas blank');
 await shot('desktop-geometry');
 const review=await visit('review');await review.locator('#cards .card').first().waitFor();
 await review.waitForFunction(()=>document.documentElement.classList.contains('single-case'));
 assert.equal(await review.locator('#cards .card').count(),5);assert.equal(await review.locator('#cards .card.focused').count(),1);
 await review.locator('#reviewer').fill('UI draft check');
 await review.locator('#cards .card.focused textarea').fill('Isolated draft; no medical decision.');await review.locator('#filter').focus();
 const beforeRecords=await review.evaluate(()=>exportReview(true));assert(beforeRecords.cases[0].decisions.every(d=>d.decision==='pending'));
 await review.locator('#cards .card').nth(2).locator('.card-head button').click();
 await review.waitForFunction(()=>document.querySelector('#image-wrap img')?.complete && document.querySelector('#image-wrap img')?.naturalWidth>0);
 await noOverflow(review);await shot('desktop-review');
 await review.locator('#image-wrap img').click();await review.locator('#lightbox').waitFor({state:'visible'});await review.locator('#close-lightbox').click();
 await visit('geometry');await visit('review');assert.equal(await review.locator('#reviewer').inputValue(),'UI draft check');
 assert((await review.evaluate(()=>exportReview(true))).cases[0].decisions.some(d=>d.note.includes('Isolated draft')));
 await visit('feedback');assert.match(await page.locator('#panel-feedback .case-notice').textContent(),/暂无外部意见/);await shot('desktop-upload-feedback');
 await visit('validation');assert.equal(await page.locator('#phantom-levels tr').count(),2);await shot('desktop-validation');
 await page.setViewportSize({width:390,height:844});
 for(const id of ['import','overview','geometry','review','feedback','validation']){const f=await visit(id);if(f)await noOverflow(f);await shot('mobile-'+id);}
 // Existing project tools retain their camera, candidate selection and documents.
 await page.setViewportSize({width:1440,height:1000});await page.locator('#active-case').selectOption('existing');
 assert(!new URL(page.url()).searchParams.has('case'),'Stale case query retained');
 await visit('feedback');const feedback=await(await page.locator('#panel-feedback iframe:not([hidden])').elementHandle()).contentFrame();
 await feedback.locator('#case').selectOption('p2');await feedback.locator('#landmark').selectOption('nostril_L');
 await feedback.waitForFunction(()=>document.getElementById('mpr').complete&&document.getElementById('mpr').naturalWidth>0);
 await noOverflow(feedback);await shot('desktop-feedback');
 await page.setViewportSize({width:390,height:844});await noOverflow(feedback);await shot('mobile-existing-feedback');
 await feedback.locator('#mpr-button').click();await feedback.locator('#lightbox').waitFor({state:'visible'});await feedback.locator('#close').click();
 const oldReview=await visit('review');await oldReview.locator('#cards .card').first().waitFor();await noOverflow(oldReview);await shot('mobile-existing-review');
 const oldGeometry=await visit('geometry');await oldGeometry.locator('#scene-state').waitFor({state:'hidden'});await noOverflow(oldGeometry);await shot('mobile-existing-geometry');
 await page.setViewportSize({width:1440,height:1000});await visit('review');await noOverflow(oldReview);await shot('desktop-existing-review');
 await visit('geometry');await noOverflow(oldGeometry);await shot('desktop-existing-geometry');
 await visit('overview');await page.locator('#project-report summary').click();const report=await(await page.locator('#overview-report iframe').elementHandle()).contentFrame();await report.waitForLoadState('domcontentloaded');await noOverflow(report);
 assert.deepEqual(errors,[]);assert.deepEqual(failures,[]);assert.deepEqual(await Promise.all(protectedFiles.map(hash)),before);
 const result={status:'pass',desktop:'1440x1000',mobile:'390x844',flows:6,caseId,new_candidate_version:true,review_draft_preserved:true,original_proposals_unchanged:true,errors,failures};
 await fs.writeFile(path.join(out,'verification.json'),JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
