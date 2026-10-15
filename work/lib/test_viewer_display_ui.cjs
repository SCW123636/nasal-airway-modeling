// Isolated real-browser verification; reads existing previews, never generates geometry.
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
const http=require('node:http');
const crypto=require('node:crypto');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const sharp=require('sharp');
const project=path.resolve(__dirname,'../..');
const root=path.join(project,'work/07_cfd_pipeline');
const out=path.resolve(process.argv[2]||path.join(project,'outputs/T-017/browser'));
const liveViewer=process.argv[3]||null;
const jobId='s_0123456789abcdef01234567';
const mime={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.json':'application/json','.svg':'image/svg+xml','.png':'image/png'};
async function main(){
  await fs.mkdir(out,{recursive:true});
  const workspace=JSON.parse(await fs.readFile(path.join(root,'viewer/workspace_data.json'),'utf8'));
  const frozenFiles=['p0','p1','p2','p3','p3t1'].flatMap(id=>[path.join(project,'work/06_auto_landmarks',id,'landmarks.json'),path.join(root,'preview',id,'viewer_mesh.json')]);
  const hashes=()=>Promise.all(frozenFiles.map(async file=>({path:path.relative(project,file),sha256:crypto.createHash('sha256').update(await fs.readFile(file)).digest('hex')})));
  const before=await hashes();
  const numerical=workspace.cases.find(item=>item.id==='numerical_channel');
  const server=http.createServer(async(req,res)=>{
    try{
      const uri=new URL(req.url,'http://localhost').pathname;
      if(uri==='/favicon.ico'){res.writeHead(204);res.end();return;}
      if(uri==='/__viewer_live__'&&liveViewer){
        const url=new URL(liveViewer);assert.equal(url.hostname,'127.0.0.1');url.searchParams.set('embedded','1');
        res.setHeader('Content-Type','text/html');res.end('<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="margin:0"><iframe title="Live reference verification" style="display:block;width:100vw;height:100vh;border:0" src="'+url.href.replaceAll('&','&amp;')+'"></iframe></body></html>');return;
      }
      if(uri==='/__viewer_test__'){
        res.setHeader('Content-Type','text/html');
        const query=new URL(req.url,'http://localhost').search;
        const manifest=new URLSearchParams(query).get('manifest');
        const src='/viewer/index.html?embedded=1'+(manifest?'&manifest='+encodeURIComponent(manifest):'');
        res.end('<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="margin:0"><iframe id="viewer" title="Viewer verification" style="display:block;width:100vw;height:100vh;border:0" src="'+src+'"></iframe></body></html>');return;
      }
      if(uri===`/simulation-assets/${jobId}/viewer.json`){
        res.setHeader('Content-Type','application/json');
        res.end(JSON.stringify({schema:'nasal_workspace/v1',patient_scan_count:0,patient_cfd_results:0,cases:[{...numerical,id:jobId,label:'测试索引 · 既有数值参考',mesh_url:'/reference/channel_numerical/viewer_mesh.json'}]}));return;
      }
      const target=path.resolve(root,'.'+decodeURIComponent(uri));
      if(!target.startsWith(root+path.sep)){res.writeHead(403);res.end();return;}
      const buffer=await fs.readFile(target);
      res.setHeader('Content-Type',mime[path.extname(target)]||'application/octet-stream');res.end(buffer);
    }catch(error){res.writeHead(404);res.end('not found');}
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const base=`http://127.0.0.1:${server.address().port}`;
  const browser=await chromium.launch({headless:true,...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{channel:'chrome'})});
  const errors=[],failed=[],modes=[],planes=[],widths=[];
  try{
    const page=await browser.newPage({viewport:{width:1440,height:1100},deviceScaleFactor:1});
    page.setDefaultTimeout(15000);
    page.on('pageerror',error=>errors.push(error.message));
    page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
    page.on('response',response=>{if(response.status()>=400&&!response.url().endsWith('/favicon.ico'))failed.push(response.url());});
    await page.goto(base+'/__viewer_test__');
    const frame=page.frames().find(candidate=>candidate.url().includes('/viewer/index.html'));
    await frame.locator('#scene-state').waitFor({state:'hidden'});
    const digestSnapshot=()=>frame.evaluate(async()=>{
      const snap=(await import('/viewer/viewer.js')).getDisplaySnapshot();
      const digest=async values=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',new Float64Array(values)))].map(v=>v.toString(16).padStart(2,'0')).join('');
      return {...snap,positions:undefined,indices:undefined,positionSha256:await digest(snap.positions),indexSha256:await digest(snap.indices),vertices:snap.positions.length/3,faces:snap.indices.length/3};
    });
    const initial=await digestSnapshot();
    const modeButton=await frame.locator('[data-display="smooth"]').evaluate(el=>({text:el.textContent,color:getComputedStyle(el).color,background:getComputedStyle(el).backgroundColor,fill:getComputedStyle(el).webkitTextFillColor,font:getComputedStyle(el).font,fontSize:getComputedStyle(el).fontSize}));
    const rendered=()=>frame.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    assert.equal(initial.caseId,'p0');assert.equal(initial.mode,'smooth');assert(initial.pixelRatio>=1.5&&initial.pixelRatio<=2);
    assert.match(await frame.locator('#voxel-spacing').textContent(),/0\.350 × 0\.350 × 0\.350 mm/);
    assert.match(await frame.locator('#geometry-detail').textContent(),/396,524.*vtkDecimatePro/);
    for(const mode of ['smooth','facets','wireframe']){
      await frame.locator(`[data-display="${mode}"]`).click();
      const snap=await digestSnapshot();
      assert.equal(snap.mode,mode);assert.equal(snap.flatShading,mode==='facets');assert.equal(snap.wireframe,mode==='wireframe');
      assert.equal(snap.positionSha256,initial.positionSha256);assert.equal(snap.indexSha256,initial.indexSha256);
      assert.deepEqual(snap.camera,initial.camera);assert.deepEqual(snap.target,initial.target);
      assert((await frame.locator(`[data-display="${mode}"]`).textContent()).trim().length>0);
      const color=await frame.locator(`[data-display="${mode}"]`).evaluate(el=>({foreground:getComputedStyle(el).color,background:getComputedStyle(el).backgroundColor}));assert.notEqual(color.foreground,color.background,'Hovered selected mode has invisible text');
      await rendered();await frame.locator('#scene').screenshot({path:path.join(out,'mode-'+mode+'.png')});modes.push({mode,positionSha256:snap.positionSha256,indexSha256:snap.indexSha256,flatShading:snap.flatShading,wireframe:snap.wireframe});
    }
    await frame.locator('[data-display="smooth"]').click();
    const patient=workspace.cases.find(item=>item.id==='p0');
    for(const id of ['nostril_L','nostril_R','nasopharynx_outlet']){
      await frame.locator('#plane-select').selectOption(id);
      const snap=await digestSnapshot(),landmark=patient.landmarks.find(item=>item.id===id);
      assert.equal(snap.plane.caseId,'p0');assert.equal(snap.plane.landmarkId,id);
      assert.deepEqual(snap.plane.point_lps_mm,landmark.point_lps_mm);assert.deepEqual(snap.plane.normal_lps,landmark.normal_lps);
      const expected=[landmark.normal_lps[0],landmark.normal_lps[2],-landmark.normal_lps[1]],norm=Math.hypot(...expected);
      expected.forEach((v,i)=>assert(Math.abs(snap.plane.viewNormal[i]-v/norm)<1e-10,'Cut-plane normal transform differs'));
      const p=landmark.point_lps_mm,c=snap.center,expectedPoint=[p[0]-c[0],p[2]-c[2],-(p[1]-c[1])];
      expectedPoint.forEach((v,i)=>assert(Math.abs(snap.plane.viewPoint[i]-v)<1e-10,'Cut-plane position differs'));
      assert.equal(snap.positionSha256,initial.positionSha256);assert.equal(snap.indexSha256,initial.indexSha256);
      assert.deepEqual(snap.camera,initial.camera);await rendered();await page.screenshot({path:path.join(out,'plane-'+id+'.png')});
      planes.push({id,point_lps_mm:snap.plane.point_lps_mm,normal_lps:snap.plane.normal_lps,viewNormal:snap.plane.viewNormal,visible:snap.plane.visible});
    }
    await frame.locator('#show-plane').uncheck();assert.equal((await digestSnapshot()).plane.visible,false);
    await frame.locator('#show-plane').check();assert.equal((await digestSnapshot()).plane.visible,true);
    await frame.locator('#case-select').selectOption('p1');await frame.waitForFunction(()=>document.querySelector('#model-title').textContent==='病例 1'&&document.querySelector('#scene-state').hidden);
    const second=await digestSnapshot();assert.equal(second.plane.caseId,'p1');assert.equal(second.plane.landmarkId,'nostril_L');assert.notEqual(second.positionSha256,initial.positionSha256);
    await frame.locator('#plane-select').selectOption('nasopharynx_outlet');assert.match(await frame.locator('#plane-proposal').textContent(),/needs_review/);
    for(const field of ['velocity','pressure','turbulence_intensity'])assert(await frame.locator('#layer-'+field).isDisabled());
    await frame.locator('#case-select').selectOption('numerical_channel');await frame.waitForFunction(()=>document.querySelector('#model-title').textContent.includes('平行板')&&document.querySelector('#scene-state').hidden);
    assert.equal((await digestSnapshot()).plane,null);assert(await frame.locator('#plane-select').isDisabled());
    assert(!(await frame.locator('#layer-velocity').isDisabled()));assert(!(await frame.locator('#layer-pressure').isDisabled()));
    await frame.locator('#layer-pressure').click();assert.match(await frame.locator('#legend-title').textContent(),/压力 · Pa/);assert.equal((await digestSnapshot()).layer,'pressure');
    await page.screenshot({path:path.join(out,'numerical-pressure.png')});
    await frame.locator('[data-display="facets"]').click();assert.equal((await digestSnapshot()).layer,'pressure');
    await frame.locator('#case-select').selectOption('analytic_pipe');await frame.waitForFunction(()=>document.querySelector('#model-title').textContent.includes('圆管')&&document.querySelector('#scene-state').hidden);
    assert(!(await frame.locator('#layer-velocity').isDisabled()));assert(!(await frame.locator('#layer-pressure').isDisabled()));assert(await frame.locator('#layer-turbulence_intensity').isDisabled());
    await frame.locator('#case-select').selectOption('p0');await frame.waitForFunction(()=>document.querySelector('#model-title').textContent==='病例 0'&&document.querySelector('#scene-state').hidden);
    await frame.locator('[data-display="smooth"]').click();
    for(const width of [390,320]){
      await page.setViewportSize({width,height:844});
      const bounds=await frame.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert(bounds.scroll<=bounds.width+1,JSON.stringify(bounds));
      await frame.locator('#plane-select').selectOption('nasopharynx_outlet');await frame.locator('.plane-card').scrollIntoViewIfNeeded();
      await page.screenshot({path:path.join(out,'mobile-'+width+'.png')});widths.push(bounds);
    }
    const canvas=await frame.locator('canvas').screenshot();const {data,info}=await sharp(canvas).removeAlpha().raw().toBuffer({resolveWithObject:true});let changed=0;
    for(let i=0;i<data.length;i+=info.channels)if(Math.abs(data[i]-data[0])+Math.abs(data[i+1]-data[1])+Math.abs(data[i+2]-data[2])>35)changed++;
    assert(changed/(info.width*info.height)>.02,'Canvas is blank');
    await page.goto(base+'/__viewer_test__?manifest='+encodeURIComponent(`/simulation-assets/${jobId}/viewer.json`));
    const simulationFrame=page.frames().find(candidate=>candidate.url().includes('/viewer/index.html'));
    await simulationFrame.locator('#scene-state').waitFor({state:'hidden'});assert.match(await simulationFrame.locator('#model-title').textContent(),/既有数值参考/);assert(!(await simulationFrame.locator('#layer-pressure').isDisabled()));
    assert.deepEqual(errors,[]);assert.deepEqual(failed,[]);
    const errorsBefore=errors.length;
    await page.goto(base+'/__viewer_test__?manifest='+encodeURIComponent('https://example.invalid/arbitrary.json'));
    const rejected=page.frames().find(candidate=>candidate.url().includes('/viewer/index.html'));
    await rejected.waitForFunction(()=>document.querySelector('#scene-state').textContent.includes('病例索引地址无效'));
    assert.equal(errors.length,errorsBefore+1,'Expected one explicit invalid-manifest rejection');
    let liveJobVerification=null;
    if(liveViewer){
      const livePage=await browser.newPage({viewport:{width:1440,height:1000}}),liveErrors=[];
      livePage.on('pageerror',error=>liveErrors.push(error.message));livePage.on('console',message=>{if(message.type()==='error')liveErrors.push(message.text());});
      await livePage.goto(base+'/__viewer_live__');const liveFrame=livePage.frames().find(candidate=>candidate.url().includes('/viewer/index.html'));
      await liveFrame.locator('#scene-state').waitFor({state:'hidden'});
      const manifestUrl=new URL(new URL(liveViewer).searchParams.get('manifest'),liveViewer).href;
      const manifest=await (await fetch(manifestUrl)).json();const record=manifest.cases[0];const mesh=await(await fetch(new URL(record.mesh_url,liveViewer))).json();
      assert.equal(record.type,'numerical_reference');assert.equal(mesh.result.provenance.method,'cfd_solver');
      assert.equal(await liveFrame.locator('#model-title').textContent(),record.label);
      const referenceDimensions=await liveFrame.locator('#geometry-detail').textContent();assert.match(referenceDimensions,/40\.0 mm.*2\.0 mm.*1\.0 mm/);
      const beforeLive=await liveFrame.evaluate(async()=>{const s=(await import('/viewer/viewer.js')).getDisplaySnapshot();return {caseId:s.caseId,positions:s.positions,indices:s.indices};});
      assert.equal(beforeLive.caseId,record.id);assert.equal(beforeLive.positions.length/3,mesh.geometry.vertices.length/3);
      const layers=[];
      for(const layer of ['velocity','pressure']){
        assert(!(await liveFrame.locator('#layer-'+layer).isDisabled()));await liveFrame.locator('#layer-'+layer).click();
        const values=mesh.result.fields[layer].values.map(v=>Array.isArray(v)?Math.hypot(...v):v),min=Math.min(...values),max=Math.max(...values);
        assert.equal(await liveFrame.locator('#legend-min').textContent(),min.toPrecision(3));assert.equal(await liveFrame.locator('#legend-max').textContent(),max.toPrecision(3));
        const legendBounds=await liveFrame.locator('#legend').boundingBox();assert(legendBounds.y>=0&&legendBounds.y+legendBounds.height<=1000,'Reference color legend extends below viewport');
        await liveFrame.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
        await livePage.screenshot({path:path.join(out,'live-reference-'+layer+'.png')});layers.push({layer,min,max,unit:mesh.result.fields[layer].unit});
      }
      assert(await liveFrame.locator('#layer-turbulence_intensity').isDisabled());assert(await liveFrame.locator('#plane-select').isDisabled());
      const afterLive=await liveFrame.evaluate(async()=>{const s=(await import('/viewer/viewer.js')).getDisplaySnapshot();return {caseId:s.caseId,positions:s.positions,indices:s.indices};});assert.deepEqual(afterLive,beforeLive);
      assert.deepEqual(liveErrors,[]);
      liveJobVerification={viewerUrl:liveViewer,caseId:record.id,label:record.label,vertices:beforeLive.positions.length/3,faces:beforeLive.indices.length/3,layers,geometryUnchanged:true,errors:liveErrors,sourceMethod:mesh.result.provenance.method,clinicalValidation:mesh.result.clinical_validation};
      await livePage.close();
    }
    assert.deepEqual(await hashes(),before,'Patient inputs changed during display verification');
    const report={status:'execution_checks_pass',generatedAt:new Date().toISOString(),scope:'Static embedded viewer with existing patient previews and genuine existing solver reference; no patient CFD generation',initial:{caseId:initial.caseId,vertices:initial.vertices,faces:initial.faces,pixelRatio:initial.pixelRatio,positionSha256:initial.positionSha256,indexSha256:initial.indexSha256},modeButton,modes,planes,caseSwitchClearsPreviousPlane:true,referenceVelocityPressureAvailable:true,patientFieldsDisabled:true,widths,canvasChangedFraction:changed/(info.width*info.height),allowedSimulationManifest:jobId,rejectedArbitraryManifest:true,errorsBeforeIntentionalRejection:[],httpFailures:failed,liveJobVerification,frozenInputs:before};
    await fs.writeFile(path.join(out,'verification.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));
  }finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
}
main().catch(error=>{console.error(error.stack);process.exitCode=1;});
