// Real workspace/iframe route with intercepted, explicitly synthetic VTU assets.
// This checks the display component; it is not native patient-flow validation.
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
const {chromium}=require('playwright');
const out=process.argv[3]?path.resolve(process.argv[3]):__dirname,base=process.argv[2]||'http://127.0.0.1:8769';
const job='s_'+'a'.repeat(24),prefix='/simulation-assets/'+job+'/',manifest=prefix+'viewer.json';
let mode='valid';const evidence=[];

(async()=>{
 const originalMesh=JSON.parse(await fs.readFile(path.join(out,'synthetic_job/viewer_mesh.json'),'utf8'));
 const originalManifest=JSON.parse(await fs.readFile(path.join(out,'synthetic_job/viewer.json'),'utf8'));
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  await context.addInitScript(()=>localStorage.setItem('nasal_active_uploaded_case','u_b39e51153cda46d7'));
  await context.route('**'+prefix+'**',async route=>{
   const url=new URL(route.request().url());let payload;
   if(url.pathname===manifest){
    payload=structuredClone(originalManifest);
    if(mode==='formalCounter')payload.patient_cfd_results=1;
    if(mode==='previewInjection'){
     payload.cases[0]={...payload.cases[0],id:'p0',type:'patient_preview',result:{type:'patient_preview',
      geometry:{kind:'patient',case_id:'p0'},fields:{velocity:null,pressure:null,turbulence_intensity:null}}};
    }
   }else if(url.pathname===prefix+'viewer_mesh.json'){
    payload=structuredClone(originalMesh);
    if(mode==='wrongUnit')payload.result.fields.pressure.unit='mmHg';
    if(mode==='formalForgery'){payload.result.schema='nasal_cfd_result/v1';payload.result.type='cfd_result';payload.result.geometry.kind='idealized';}
    if(mode==='foreignJob')payload.result.provenance.job_id='s_'+'b'.repeat(24);
    if(mode==='missingSlices')delete payload.interior_slices;
    if(mode==='wrongSliceUnit')payload.interior_slices[0].fields.pressure.unit='mmHg';
    if(mode==='foreignSlice')payload.interior_slices[0].source_vtu_sha256='d'.repeat(64);
    if(mode==='slicePlane')payload.interior_slices[0].position_lps_mm+=1;
    if(mode==='sliceLength')payload.interior_slices[0].fields.velocity.values.pop();
    if(mode==='sliceNonfinite')payload.interior_slices[0].fields.velocity.values[0][0]=null;
    if(mode==='duplicateSlice')payload.interior_slices[1]=structuredClone(payload.interior_slices[0]);
    if(mode==='sliceVertex')payload.interior_slices[0].geometry.vertices[0]+=1;
    if(mode==='previewInjection')Object.assign(payload,{schema:'candidate_surface_preview/v1',case:'p0',status:'unreviewed_candidate_preview'});
   }else return route.fulfill({status:404,body:'Synthetic fixture has no real native asset'});
   await route.fulfill({contentType:'application/json',body:JSON.stringify(payload)});
  });
  const page=await context.newPage();page.setDefaultTimeout(15000);
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  async function visit(value=manifest){
   await page.goto(base+'/viewer/index.html?manifest='+encodeURIComponent(value));
   await page.waitForURL('**/workspace/index.html?**');
   if(value!==manifest)return null;
   const element=await page.locator('#panel-geometry iframe').elementHandle();
   const frame=await element.contentFrame();await frame.waitForLoadState('domcontentloaded');
   return frame;
  }
  let frame=await visit();
  await frame.locator('#scene-state').waitFor({state:'hidden'});
  assert.match(await frame.locator('#model-title').textContent(),/合成VTU组件测试/);
  assert.match(await frame.locator('#engineering-warning').textContent(),/非临床.*failed/);
  assert.equal(await frame.locator('#engineering-warning').isVisible(),true);
  assert.equal(await frame.locator('#patient-result-count').textContent(),'0');
  assert.equal(await frame.locator('#layer-velocity').isDisabled(),false);
  assert.equal(await frame.locator('#layer-pressure').isDisabled(),false);
  assert.equal(await frame.locator('#layer-turbulence_intensity').isDisabled(),true);
  assert.match(await frame.locator('#coordinates').textContent(),/LPS/);
  assert.match(frame.url(),new RegExp(encodeURIComponent(manifest).replace(/[.*+?^${}()|[\]\\]/g,'\\$&')));
  await frame.locator('#layer-pressure').click();
  assert.equal(await frame.locator('#legend-title').textContent(),'压力 · Pa');
  assert.equal(await frame.locator('#field-sampling').inputValue(),'y');
  assert.match(await frame.locator('#field-sampling-note').textContent(),/Y = 4.000 mm.*字段时间 17/);
  assert.equal(await frame.locator('#legend-min').textContent(),'2.50');
  assert.equal(await frame.locator('#legend-max').textContent(),'4.38');
  await page.screenshot({path:path.join(out,'desktop-synthetic-engineering-pressure.png'),fullPage:true});
  await frame.locator('#scene').evaluate(element=>element.scrollIntoView({block:'start'}));
  await frame.locator('#scene').screenshot({path:path.join(out,'scene-synthetic-internal-pressure.png')});
  await frame.evaluate(()=>scrollTo(0,0));
  const snapshot=await frame.evaluate(async()=>{const mod=await import('/viewer/viewer.js');return mod.getDisplaySnapshot();});
  assert.equal(snapshot.caseId,job);assert.equal(snapshot.layer,'pressure');assert.equal(snapshot.sampling,'y');assert.equal(snapshot.positions.length,9);
  evidence.push({check:'official_top_entry_preserves_diagnostic_manifest',passed:true,url:page.url(),frame_url:frame.url(),snapshot});
  for(const sampling of ['x','y','z','surface']){
   await frame.locator('#field-sampling').selectOption(sampling);
   const selected=sampling==='surface'?{geometry:originalMesh.geometry,fields:originalMesh.result.fields}:originalMesh.interior_slices.find(slice=>slice.id===sampling);
   const snap=await frame.evaluate(async()=>{const mod=await import('/viewer/viewer.js');return mod.getDisplaySnapshot();});
   assert.equal(snap.sampling,sampling);assert.deepEqual(snap.center,[2,4,6]);assert.deepEqual(snap.indices,selected.geometry.indices);
   const expected=[];for(let i=0;i<selected.geometry.vertices.length;i+=3){const v=selected.geometry.vertices;expected.push(v[i]-2,v[i+2]-6,-(v[i+1]-4));}
   assert.equal(snap.positions.length,expected.length);snap.positions.forEach((value,i)=>assert(Math.abs(value-expected[i])<1e-5));
   const pressures=selected.fields.pressure.values;
   assert.equal(await frame.locator('#legend-min').textContent(),Math.min(...pressures).toPrecision(3));
   assert.equal(await frame.locator('#legend-max').textContent(),Math.max(...pressures).toPrecision(3));
   if(sampling==='surface')assert.match(await frame.locator('#field-sampling-note').textContent(),/不能代表腔内速度/);
   evidence.push({check:'same_vtu_'+sampling+'_geometry_fields_and_units',passed:true,snapshot:snap});
  }
  await page.reload();frame=await(await page.locator('#panel-geometry iframe').elementHandle()).contentFrame();
  await frame.locator('#scene-state').waitFor({state:'hidden'});
  assert.match(await frame.locator('#engineering-warning').textContent(),/failed/);
  evidence.push({check:'refresh_keeps_exact_job_despite_uploaded_case_storage',passed:true});
  for(const width of [390,320]){
   await page.setViewportSize({width,height:900});
   const bounds=await frame.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
   assert(bounds.scroll<=bounds.width+1,JSON.stringify(bounds));
   assert.equal(await frame.locator('#engineering-warning').isVisible(),true);
   await page.screenshot({path:path.join(out,'mobile-'+width+'-synthetic-engineering.png'),fullPage:true});
   evidence.push({check:'mobile_'+width+'_warning_and_no_overflow',passed:true,bounds});
  }
  await page.setViewportSize({width:1440,height:1000});
  for(mode of ['wrongUnit','formalForgery','foreignJob','previewInjection','missingSlices','wrongSliceUnit','foreignSlice','slicePlane','sliceLength','sliceNonfinite','duplicateSlice','sliceVertex']){
   frame=await visit();await frame.waitForFunction(()=>document.getElementById('model-status').textContent==='加载失败');
   assert.match(await frame.locator('#scene-state').textContent(),/无法显示/);
   assert.equal(await frame.locator('canvas').count(),1);
   assert.equal(await frame.locator('#layer-velocity').isDisabled(),true);
   const snapshot=await frame.evaluate(async()=>{const mod=await import('/viewer/viewer.js');return mod.getDisplaySnapshot();});
   assert.equal(snapshot,null);
   evidence.push({check:mode+'_rejected_without_preview_fallback',passed:true,error:await frame.locator('#scene-state').textContent()});
  }
  for(const value of ['', 'https://example.invalid/viewer.json','/simulation-assets/not-a-job/viewer.json']){
   await visit(value);
   await page.waitForFunction(()=>document.getElementById('panel-geometry').textContent.includes('索引')||document.getElementById('panel-geometry').textContent.includes('地址'));
   assert.equal(await page.locator('#panel-geometry iframe').count(),0);
   evidence.push({check:'invalid_manifest_rejected',manifest:value,passed:true,message:await page.locator('#panel-geometry').textContent()});
  }
  mode='formalCounter';frame=await visit();
  await frame.waitForFunction(()=>document.getElementById('scene-state').textContent.includes('不能增加正式患者结果'));
  assert.equal(await frame.evaluate(async()=>{const mod=await import('/viewer/viewer.js');return mod.getDisplaySnapshot();}),null);
  evidence.push({check:'diagnostic_formal_result_counter_forgery_rejected',passed:true});
  mode='valid';await page.goto(base+'/workspace/index.html?case=existing#geometry');
  frame=await(await page.locator('#panel-geometry iframe').elementHandle()).contentFrame();
  await frame.locator('#scene-state').waitFor({state:'hidden'});
  for(const id of ['p0','analytic_pipe','numerical_channel']){
   await frame.locator('#case-select').selectOption(id);
   await frame.locator('#scene-state').waitFor({state:'hidden'});
   const snap=await frame.evaluate(async()=>{const mod=await import('/viewer/viewer.js');return mod.getDisplaySnapshot();});
   assert.equal(snap.caseId,id);assert.equal(snap.sampling,'surface');
   assert.equal(await frame.locator('#engineering-warning').isVisible(),false);
   assert.equal(await frame.locator('#field-sampling-controls').isVisible(),false);
   assert.equal(await frame.locator('#layer-velocity').isDisabled(),id==='p0');
   evidence.push({check:'original_'+id+'_display_contract_preserved',passed:true});
  }
  evidence.push({check:'unexpected_page_errors',passed:errors.length===0,errors});assert.deepEqual(errors,[]);
 }finally{await browser.close();await fs.writeFile(path.join(out,'browser_fixture_results.json'),JSON.stringify({scope:'synthetic_component_fixture_only_not_patient_solver',evidence},null,2));}
 console.log(JSON.stringify({passed:evidence.length,scope:'synthetic component only'}));
})().catch(async error=>{await fs.writeFile(path.join(out,'browser_fixture_failure.txt'),error.stack);console.error(error);process.exitCode=1;});
