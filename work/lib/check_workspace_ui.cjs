// Run with the local workspace service; uses an isolated browser profile.
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const {chromium} = require('playwright');
const sharp = require('sharp');
const base = process.argv[2] || 'http://127.0.0.1:8769';
const root = path.resolve(__dirname,'..');
const out = path.join(root,'07_cfd_pipeline','workspace','qa');
const files = ['p0','p1','p2','p3','p3t1'].map(id => path.join(root,'06_auto_landmarks',id,'landmarks.json'));
files.push(path.join(root,'06_auto_landmarks','feedback_review','audit.json'));
const digest = async file => crypto.createHash('sha256').update(await fs.readFile(file)).digest('hex');
async function nonblank(locator) {
  const buffer = await locator.screenshot();
  const {data,info} = await sharp(buffer).removeAlpha().raw().toBuffer({resolveWithObject:true});
  let different = 0;
  for (let i=0;i<data.length;i+=info.channels) {
    if (Math.abs(data[i]-data[0])+Math.abs(data[i+1]-data[1])+Math.abs(data[i+2]-data[2])>30) different++;
  }
  assert(different/(info.width*info.height)>0.02,'Model canvas is blank or too small');
  return buffer;
}
async function noOverflow(frame) {
  const bounds = await frame.evaluate(() => ({width:innerWidth,scroll:document.documentElement.scrollWidth}));
  assert(bounds.scroll<=bounds.width+1,JSON.stringify(bounds));
}
(async () => {
  await fs.mkdir(out,{recursive:true});
  const before = await Promise.all(files.map(digest));
  const browser = await chromium.launch({headless:true,channel:'chrome'});
  try {
    const context = await browser.newContext({viewport:{width:1440,height:1000}});
    const page = await context.newPage();
    page.setDefaultTimeout(10000);
    const errors=[],failed=[];
    page.on('pageerror',error=>errors.push(error.message));
    page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
    page.on('response',response=>{if(response.status()>=400)failed.push(response.url());});
    const visit = async id => {
      await page.locator('[data-step='+id+']').click();
      await page.locator('#panel-'+id).waitFor({state:'visible'});
      if(id==='overview')return page;
      const handle = await page.locator('#panel-'+id+' iframe').elementHandle();
      const frame = await handle.contentFrame();
      await frame.waitForLoadState('domcontentloaded');
      return frame;
    };
    const shot = name => page.screenshot({path:path.join(out,name+'.png')});
    await page.goto(base+'/workspace/index.html');
    await page.waitForFunction(()=>Number(document.getElementById('total-points').textContent)>=25);
    assert.equal(await page.locator('#total-feedback').textContent(),'2/6');
    assert.equal(await page.locator('#total-results').textContent(),'0');
    const overview = await visit('overview');
    await noOverflow(overview); await shot('desktop-overview');
    const geometry = await visit('geometry');
    await geometry.locator('#scene-state').waitFor({state:'hidden'});
    assert.equal(await geometry.locator('#layer-velocity').isDisabled(),true);
    const canvas = geometry.locator('canvas');
    const firstImage = await nonblank(canvas);
    const bounds = await canvas.boundingBox();
    await page.mouse.move(bounds.x+bounds.width*.45,bounds.y+bounds.height*.55);
    await page.mouse.down();
    await page.mouse.move(bounds.x+bounds.width*.67,bounds.y+bounds.height*.64,{steps:18});
    await page.mouse.up();
    const secondImage = await nonblank(canvas);
    assert.notDeepEqual(firstImage,secondImage,'Rotation did not change the canvas');
    await geometry.locator('#case-select').selectOption('p2');
    await geometry.locator('#model-title').filter({hasText:'病例 2'}).waitFor();
    await shot('desktop-geometry');
    const review = await visit('review');
    await review.locator('#cards .card').first().waitFor();
    await review.locator('#reviewer').fill('UI verification');
    await review.locator('#cards .card').first().locator('textarea').fill('Draft persistence verification');
    await review.locator('#filter').focus();
    const draftDocument = await review.locator('body').elementHandle();
    const feedback = await visit('feedback');
    await feedback.locator('#case').selectOption('p2');
    await feedback.locator('#landmark').selectOption('nostril_L');
    await feedback.waitForFunction(()=>document.getElementById('mpr').complete&&document.getElementById('mpr').naturalWidth>0);
    await shot('desktop-feedback');
    await visit('review');
    assert(await draftDocument.evaluate(element=>element===document.body),'Review was reloaded');
    assert.equal(await review.locator('#reviewer').inputValue(),'UI verification');
    assert.equal(await review.locator('#cards .card').first().locator('textarea').inputValue(),'Draft persistence verification');
    await review.locator('#image-wrap img').click();
    await review.locator('#lightbox').waitFor({state:'visible'});
    await review.locator('#close-lightbox').click();
    const downloadEvent = page.waitForEvent('download');
    await review.locator('#export').click();
    const download = await downloadEvent;
    const stream = await download.createReadStream();
    const chunks=[]; for await (const chunk of stream) chunks.push(chunk);
    const exportBuffer=Buffer.concat(chunks),record=JSON.parse(exportBuffer.toString('utf8'));
    assert.equal(record.artifact_type,'landmark_review_decisions');
    assert.equal(record.coordinate_system,'LPS');
    assert.equal(record.cases.reduce((n,item)=>n+item.decisions.length,0),25);
    assert(record.cases.some(item=>item.decisions.some(decision=>decision.note==='Draft persistence verification')));
    await review.locator('#import-file').setInputFiles({name:'ui-verification.json',mimeType:'application/json',buffer:exportBuffer});
    await review.locator('#import-preview').waitFor({state:'visible'});
    assert.equal(await review.locator('#apply-import').isDisabled(),false);
    await review.locator('#apply-import').click();
    await shot('desktop-review');
    await visit('geometry');
    assert.equal(await geometry.locator('#case-select').inputValue(),'p2');
    await nonblank(canvas);
    await geometry.locator('.feedback-card').evaluate(el=>el.closest('details').open=true);
    await geometry.locator('.feedback-card a').click();
    await page.locator('#panel-feedback').waitFor({state:'visible'});
    assert.equal(await feedback.locator('#case').inputValue(),'p2');
    assert.equal(context.pages().length,1);
    await page.locator('[data-step=validation]').click();
    await page.locator('#panel-validation').waitFor({state:'visible'});
    assert.match(await page.locator('#phantom-state').textContent(),/未通过/);
    assert.equal(await page.locator('#phantom-levels tr').count(),2);
    assert.equal(await page.locator('#diagnostic-rows tr').count(),2);
    assert.match(await page.locator('#diagnostic-state').textContent(),/独立对照/);
    await shot('desktop-validation');
    await page.setViewportSize({width:390,height:844});
    for (const id of ['overview','geometry','review','feedback']) {
      const frame=await visit(id);
      await noOverflow(page); await noOverflow(frame);
      if(id==='geometry')await nonblank(canvas);
      await shot('mobile-'+id);
    }
    await visit('feedback');
    await feedback.locator('#mpr-button').click();
    await feedback.locator('#lightbox').waitFor({state:'visible'});
    const dialog=await feedback.locator('#lightbox').boundingBox();
    assert(dialog.x>=0&&dialog.x+dialog.width<=391,'Image dialog overflows the viewport');
    await shot('mobile-lightbox');
    await feedback.locator('#close').click();
    await page.locator('[data-step=validation]').click();
    await page.locator('#panel-validation').waitFor({state:'visible'});
    await noOverflow(page); await shot('mobile-validation');
    for(const [url,id] of [['/progress/index.html','overview'],['/viewer/index.html','geometry'],['/landmark-review/index.html','review'],['/landmark-review/feedback_review/index.html','feedback']]) {
      await page.goto(base+url);
      await page.waitForURL('**/workspace/index.html#'+id);
      await page.locator('#panel-'+id).waitFor({state:'visible'});
    }
    assert.equal(context.pages().length,1);
    assert.deepEqual(errors,[]); assert.deepEqual(failed,[]);
    assert.deepEqual(await Promise.all(files.map(digest)),before,'Original proposals or audit changed');
    const report={status:'pass',desktop:'1440x1000',mobile:'390x844',flows:5,manual_inspection_chain:true,patient_cfd_results:0,original_inputs_unchanged:true,errors,failed};
    await fs.writeFile(path.join(out,'verification.json'),JSON.stringify(report,null,2)+'\n');
    console.log(JSON.stringify(report));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
