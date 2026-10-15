const fs=require('fs'),path=require('path'),crypto=require('crypto');
const {chromium}=require('C:/Users/lenovo/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const port=process.argv[2],name=process.argv[3],out=path.join(__dirname,'runs',name);fs.mkdirSync(out,{recursive:false});
const origin=`http://127.0.0.1:${port}`,expected=JSON.parse(fs.readFileSync(path.join(__dirname,'known_answers.json'),'utf8'));
const result={time:new Date().toISOString(),origin,checks:[],errors:[],api:{},screenshots:[]};
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
function check(label,ok,detail){result.checks.push({label,passed:!!ok,detail});if(!ok)throw Error(label);}
function flush(){fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));}
async function phase(label,fn){try{await fn()}catch(e){result.errors.push({phase:label,exception:e.stack})}flush();}
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 const page=await context.newPage();page.on('pageerror',e=>result.errors.push({type:'pageerror',exception:e.message}));
 async function shot(file){await page.screenshot({path:path.join(out,file),fullPage:true});result.screenshots.push(file);}
 await phase('API identity and rejection',async()=>{
  for(const route of ['/api/upper-airway/catalog',...Object.keys(expected.cases).map(c=>'/api/upper-airway/cases/'+c),'/api/simulation/jobs','/api/simulation/catalog','/api/cases','/viewer/workspace_data.json']){
   const r=await page.request.get(origin+route);result.api[route]={status:r.status(),json:await r.json()};check(route+' status',r.status()===200);
  }
  const catalog=result.api['/api/upper-airway/catalog'].json;
  check('catalog exact identity',catalog.cases.map(c=>c.case).join(',')==='p0,p1,p2,p3,p3t1');
  for(const c of catalog.cases){const e=expected.cases[c.case];check(c.case+' known coverage',c.inferior_face_air_voxels===e.inferior_air_voxels&&c.hypopharynx_empty&&!c.larynx_air_exists&&c.patient_symptom_mapping==='unknown'&&!c.CFD_admitted&&!c.outlet_selected);}
  for(const route of ['/api/upper-airway/cases/p4','/api/upper-airway/cases/u_fbca9137690e4837','/api/upper-airway/cases/p3/extra','/upper-airway-assets/p0/baseline.vertices.bin','/upper-airway-assets/p3/manifest.json','/upper-airway-assets/p3/%2e%2e%2fmanifest.json','/upper-airway-assets/p3/ct.nii.gz','/api/upper-airway/unknown']){
   const r=await page.request.get(origin+route);check('reject '+route,r.status()===404);result.api[route]={status:r.status(),text:await r.text()};
  }
  const image=await page.request.get(origin+'/upper-airway-assets/p3/ct-comparison.png');check('same-CT exact PNG',hash(await image.body())==='d254c92256351f7de1c6c4b28c4bedb2f531654d56165512543b1cb7cfef9886');
 });
 await phase('entry and actual 3D interactions',async()=>{
  await page.goto(origin+'/workspace/index.html?case=existing#overview',{waitUntil:'networkidle'});
  await page.locator('[data-step="upper-airway"]').click();
  const f=page.frameLocator('iframe[data-workflow="upper-airway"]');
  await f.locator('#message').filter({hasText:'已载入真实鼻腔'}).waitFor();await page.waitForTimeout(800);
  check('workbench heading and p3 identity',(await page.locator('#step-title').innerText())==='咽部扩展'&&(await f.locator('body').getAttribute('data-case'))==='p3');
  check('candidate not formal CFD',(await f.locator('body').innerText()).includes('尚未进入正式 CFD')&&(await f.locator('#candidate-facts').innerText()).includes('未准入'));
  const c=f.locator('#scene canvas');await c.waitFor();
  const initial=await c.screenshot({path:path.join(out,'3d-initial.png')});
  const box=await c.boundingBox();await page.mouse.move(box.x+box.width*.5,box.y+box.height*.5);await page.mouse.down();await page.mouse.move(box.x+box.width*.7,box.y+box.height*.58,{steps:12});await page.mouse.up();await page.waitForTimeout(900);
  const rotated=await c.screenshot({path:path.join(out,'3d-rotated.png')});check('actual drag changes rendered 3D',hash(initial)!==hash(rotated));
  await page.mouse.move(box.x+box.width*.5,box.y+box.height*.5);await page.mouse.wheel(0,-420);await page.waitForTimeout(900);
  const zoomed=await c.screenshot({path:path.join(out,'3d-zoomed.png')});check('actual wheel changes rendered 3D',hash(rotated)!==hash(zoomed));
  await f.locator('#reset-view').click();await page.waitForTimeout(1300);
  const reset=await c.screenshot({path:path.join(out,'3d-reset.png')});check('reset restores rendered side view',hash(initial)===hash(reset),{initial:hash(initial),reset:hash(reset)});
  await f.locator('#show-added').uncheck();await page.waitForTimeout(400);const base=await c.screenshot({path:path.join(out,'3d-baseline-only.png')});check('added layer toggle affects actual rendering',hash(base)!==hash(reset));
  await f.locator('#show-base').uncheck();await page.waitForTimeout(300);const noDomain=await c.screenshot({path:path.join(out,'3d-domains-hidden.png')});check('base layer toggle affects actual rendering',hash(noDomain)!==hash(base));
  await f.locator('#show-base').check();await f.locator('#show-added').check();
  await f.locator('h1').scrollIntoViewIfNeeded();await shot('desktop-3d-workbench.png');
  await f.locator('#ct-preview').scrollIntoViewIfNeeded();await f.locator('#ct-preview').evaluate(img=>img.decode());check('same CT image rendered',await f.locator('#ct-preview').evaluate(i=>i.naturalWidth>1000&&i.naturalHeight>100));
  await shot('desktop-entry.png');
  for(const id of ['p0','p1','p2','p3t1']){
   await f.locator('#airway-case').selectOption(id);await f.locator('#message').filter({hasText:id+' · 本例扩展候选未生成'}).waitFor();
   check(id+' unavailable no stale p3',await f.locator('#candidate').isHidden()&&await f.locator('#unavailable').isVisible()&&await f.locator('#ct-preview').getAttribute('src')===null&&(await f.locator('body').getAttribute('data-case'))===id);
   const coverage=await f.locator('#coverage').innerText();check(id+' visible known coverage',coverage.includes(expected.cases[id].inferior_air_voxels.toLocaleString()));
  }
  await f.locator('#airway-case').selectOption('p1');await f.locator('#message').filter({hasText:'p1 · 本例扩展候选未生成'}).waitFor();
  check('parent URL preserves explicit engineering selection',new URL(page.url()).searchParams.get('airwayCase')==='p1');
  await page.reload({waitUntil:'networkidle'});const reload=page.frameLocator('iframe[data-workflow="upper-airway"]');await reload.locator('#message').filter({hasText:'p1 · 本例扩展候选未生成'}).waitFor();check('direct refresh preserves p1',await reload.locator('#candidate').isHidden());
 });
 await phase('unknown direct identity error',async()=>{
  await page.goto(origin+'/workspace/upper-airway.html?case=p4',{waitUntil:'networkidle'});
  await page.locator('#message[role="alert"]').waitFor();check('unknown direct case visible refusal',await page.locator('#candidate').isHidden()&&(await page.locator('#message').innerText()).includes('未加载默认病例'));await shot('unknown-case.png');
 });
 await phase('uploaded patient context and old routes',async()=>{
  const cases=result.api['/api/cases']?.json?.cases||[];
  if(!cases.length){result.checks.push({label:'real upload context',passed:null,detail:'isolated service has no existing upload cases; required on formal 8769'});return;}
  const upload=cases.find(c=>c.artifacts?.viewer);check('known existing upload available',!!upload);
  let release;const gate=new Promise(resolve=>release=resolve);const seen=[],pendingRoutes=[];
  const listener=request=>{if(request.url().endsWith('/api/upper-airway/cases/p3'))seen.push(request.url());};page.on('request',listener);
  const routePattern='**/api/cases/'+upload.id;
  await page.route(routePattern,route=>{const run=(async()=>{const r=await route.fetch();await gate;await route.fulfill({response:r});})();pendingRoutes.push(run);return run.catch(e=>{result.errors.push({phase:'delayed route handler',exception:e.stack});});});
  try{
   await page.goto(origin+'/workspace/index.html?case='+upload.id+'#upper-airway',{waitUntil:'domcontentloaded'});
   const initial=page.frameLocator('iframe[data-workflow="upper-airway"]');await initial.locator('#upload-context').waitFor();await initial.locator('#message').filter({hasText:'请选择独立工程扫描'}).waitFor();
   check('delayed upload API has no transient default p3',seen.length===0&&await initial.locator('#candidate').isHidden()&&await initial.locator('#airway-case').inputValue()==='');
   await shot('upload-api-delayed-initial.png');
  }finally{release();await Promise.all(pendingRoutes);await page.unroute(routePattern);page.off('request',listener);}
  await page.goto(origin+'/workspace/index.html?case='+upload.id+'#upper-airway',{waitUntil:'networkidle'});
  const f=page.frameLocator('iframe[data-workflow="upper-airway"]');await f.locator('#airway-case').waitFor();await page.waitForTimeout(400);
  check('upload identity remains selected',await page.locator('#active-case').inputValue()===upload.id);
  check('upload no auto p3',await f.locator('#airway-case').inputValue()===''&&await f.locator('#candidate').isHidden()&&await f.locator('#upload-context').isVisible());
  await f.locator('#airway-case').selectOption('p3');await f.locator('#message').filter({hasText:'已载入真实鼻腔'}).waitFor();check('explicit engineering example still distinct upload',await page.locator('#active-case').inputValue()===upload.id&&(await f.locator('#candidate-facts').innerText()).includes('非当前上传病例'));
  await page.reload({waitUntil:'networkidle'});const f2=page.frameLocator('iframe[data-workflow="upper-airway"]');await f2.locator('#message').filter({hasText:'已载入真实鼻腔'}).waitFor();check('reload preserves upload and explicit engineering identities',await page.locator('#active-case').inputValue()===upload.id&&await f2.locator('#airway-case').inputValue()==='p3'&&await f2.locator('#upload-context').isVisible());await shot('upload-explicit-example.png');
  await page.locator('[data-step="geometry"]').click();const gf=page.locator('iframe[data-workflow="geometry"]:visible');await gf.waitFor();check('upload geometry keeps own manifest',(await gf.getAttribute('src')).includes(encodeURIComponent(upload.id))||(await gf.getAttribute('src')).includes(upload.id));
  await page.locator('[data-step="validation"]').click();await page.waitForTimeout(500);check('old validation still visible',await page.locator('#panel-validation').isVisible()&&(await page.locator('#validation-result-count').innerText())==='患者流场：0');
  check('old engineering report tables populated',await page.locator('#phantom-levels tr').count()>0&&await page.locator('#patient-engineering-rows tr').count()===5&&await page.locator('#diagnostic-rows tr').count()>0);
  check('old engineering report reads remain successful',!(await page.locator('#phantom-state').textContent()).includes('未读取')&&!(await page.locator('#patient-engineering-state').textContent()).includes('未读取')&&!(await page.locator('#diagnostic-state').textContent()).includes('未读取'));
  await page.locator('#active-case').selectOption('existing');await page.locator('[data-step="geometry"]').click();const ef=page.frameLocator('iframe[data-workflow="geometry"]:visible');await ef.locator('#model-status').filter({hasText:'候选几何'}).waitFor();check('old existing geometry plane source present',(await ef.locator('#plane-source').innerText()).length>0);
  check('old p0 geometry still actual LPS display',(await ef.locator('#coordinates').innerText()).includes('LPS')&&(await ef.locator('#triangles').innerText())==='114,906'&&await ef.locator('#scene canvas').isVisible());
 });
 await phase('narrow screens',async()=>{
  for(const width of [390,320]){
   await page.setViewportSize({width,height:900});await page.goto(origin+'/workspace/index.html?case=existing&airwayCase=p3#upper-airway',{waitUntil:'networkidle'});const f=page.frameLocator('iframe[data-workflow="upper-airway"]');await f.locator('#message').filter({hasText:'已载入真实鼻腔'}).waitFor();await page.waitForTimeout(500);
   const outer=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,width:innerWidth}));const inner=await f.locator('html').evaluate(e=>({scroll:e.scrollWidth,width:e.clientWidth}));check(width+' no horizontal page overflow',outer.scroll<=outer.width&&inner.scroll<=inner.width,{outer,inner});
   await f.locator('h1').scrollIntoViewIfNeeded();await shot('mobile-'+width+'-top.png');
   await f.locator('#show-added').uncheck();await f.locator('#reset-view').click();await f.locator('#show-added').check();check(width+' controls operable',await f.locator('#show-added').isChecked());await shot('mobile-'+width+'.png');
  }
 });
 await phase('browser rejects tampered binary',async()=>{
  await page.setViewportSize({width:1440,height:1000});
  await page.route('**/upper-airway-assets/p3/added.vertices.bin',async route=>{const r=await route.fetch();const b=Buffer.from(await r.body());b[4]^=1;await route.fulfill({response:r,body:b});});
  await page.goto(origin+'/workspace/upper-airway.html?case=p3',{waitUntil:'networkidle'});await page.locator('#message[role="alert"]').waitFor();check('binary fingerprint error visible no scene fallback',await page.locator('#candidate').isHidden()&&(await page.locator('#message').innerText()).includes('指纹不一致'));await shot('tampered-binary.png');await page.unroute('**/upper-airway-assets/p3/added.vertices.bin');
 });
 await phase('browser CT image failure visible',async()=>{
  await page.route('**/upper-airway-assets/p3/ct-comparison.png',route=>route.fulfill({status:404,contentType:'application/json',body:'{"error":"independent missing image fixture"}'}));
  await page.goto(origin+'/workspace/upper-airway.html?case=p3',{waitUntil:'networkidle'});await page.locator('#ct-preview').scrollIntoViewIfNeeded();await page.locator('#message[role="alert"]').waitFor();check('missing CT visible error no alternate image',(await page.locator('#message').innerText()).includes('同源 CT 对照读取失败')&&(await page.locator('#ct-preview').getAttribute('src')).includes('/p3/'));await shot('missing-CT.png');await page.unroute('**/upper-airway-assets/p3/ct-comparison.png');
 });
 result.passed=result.checks.every(x=>x.passed!==false)&&result.errors.length===0;flush();await browser.close();console.log(JSON.stringify({passed:result.passed,checks:result.checks.length,failed:result.checks.filter(x=>x.passed===false),errors:result.errors,out},null,2));
})().catch(e=>{result.errors.push({phase:'outer',exception:e.stack});flush();console.error(e);process.exit(1)});
