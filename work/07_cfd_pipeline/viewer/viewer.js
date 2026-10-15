import * as THREE from 'three';
import {OrbitControls} from './vendor/OrbitControls.js';

const $=id=>document.getElementById(id);
let scene,camera,renderer,controls,mesh,markers,cutPlane,active,meshData,meshCenter,requestedManifest=null,currentSampling='surface',extent=80,loadToken=0,currentLayer='geometry',displayMode='smooth';
const titles={velocity:'流速',pressure:'压力',turbulence_intensity:'湍流强度'};
const openingIds=['nostril_L','nostril_R','nasopharynx_outlet'];
const modeNotes={smooth:'平滑着色仅改变光照，不移动顶点，也不提高 CT 分辨率。',facets:'面片着色显示原有三角面的方向；与平滑着色使用同一份顶点和面索引。',wireframe:'线框显示原有三角网格；显示抽稀模型不等于 CFD 计算几何或体网格。'};
const sceneEl=$('scene');
function textNode(tag,text,cls){const node=document.createElement(tag);node.textContent=text;if(cls)node.className=cls;return node;}
function updateFeedbackAudit(audit){
  const complete=audit?.status==='diagnostic_review_complete';
  const observed=Number.isFinite(audit?.observations)?audit.observations:0;
  const matched=Number.isFinite(audit?.matched_current_proposals)?audit.matched_current_proposals:0;
  $('feedback-count').textContent=complete?`${matched}/${observed}`:'未生成';
  $('feedback-status').textContent=complete?`诊断核对完成：${matched}/${observed} 条可绑定当前候选`:'诊断核对尚未生成';
  $('feedback-detail').textContent=complete?`${audit.unresolved_or_mismatched} 条仍需解释或人工复核；原始候选未改写。`:'工作台没有可用的人工意见审计摘要。';
}
function lpsToView(point,center){return new THREE.Vector3(point[0]-center[0],point[2]-center[2],-(point[1]-center[1]));}
function initScene(){
  scene=new THREE.Scene();scene.background=new THREE.Color('#e8eff1');
  camera=new THREE.PerspectiveCamera(38,1,.01,10000);renderer=new THREE.WebGLRenderer({antialias:true,alpha:false});
  renderer.setPixelRatio(Math.min(Math.max(devicePixelRatio,1.5),2));sceneEl.appendChild(renderer.domElement);
  renderer.outputColorSpace=THREE.SRGBColorSpace;
  renderer.domElement.setAttribute('aria-label','可拖动旋转的三维候选模型');
  controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;
  scene.add(new THREE.HemisphereLight(0xffffff,0x637981,2.3));
  const light=new THREE.DirectionalLight(0xffffff,2.6);light.position.set(120,150,130);scene.add(light);
  const fill=new THREE.DirectionalLight(0xbedee8,1.4);fill.position.set(-120,-20,-100);scene.add(fill);
  const resize=()=>{const width=sceneEl.clientWidth,height=sceneEl.clientHeight;if(!width||!height)return;renderer.setSize(width,height);camera.aspect=width/height;camera.updateProjectionMatrix();};
  new ResizeObserver(resize).observe(sceneEl);resize();
  function draw(){requestAnimationFrame(draw);if(!sceneEl.clientWidth||!sceneEl.clientHeight)return;controls.update();renderer.render(scene,camera);}draw();
}
function disposeObject(obj){if(!obj)return;scene.remove(obj);obj.traverse(child=>{child.geometry?.dispose();if(Array.isArray(child.material))child.material.forEach(m=>m.dispose());else child.material?.dispose();});}
function clearObjects(){
  for(const obj of [mesh,markers,cutPlane])disposeObject(obj);
  mesh=null;markers=null;cutPlane=null;meshCenter=null;
}
function setDisplayMode(mode){
  if(!(mode in modeNotes))return;
  displayMode=mode;
  document.querySelectorAll('[data-display]').forEach(button=>{const selected=button.dataset.display===mode;button.classList.toggle('selected',selected);button.setAttribute('aria-pressed',String(selected));});
  $('display-note').textContent=modeNotes[mode];
  if(mesh){mesh.material.flatShading=mode==='facets';mesh.material.wireframe=mode==='wireframe';mesh.material.needsUpdate=true;}
}
function validVector(value){return Array.isArray(value)&&value.length===3&&value.every(Number.isFinite);}
function resetPlaneInfo(message='此参考无患者解剖切面。'){
  $('plane-select').replaceChildren();$('plane-select').disabled=true;$('show-plane').disabled=true;
  $('plane-status').textContent=message;for(const id of ['plane-point','plane-normal','plane-proposal','plane-source'])$(id).textContent='—';
}
function updatePlane(){
  disposeObject(cutPlane);cutPlane=null;
  const lm=active?.landmarks?.find(candidate=>candidate.id===$('plane-select').value);
  if(!lm||!meshCenter)return;
  $('plane-point').textContent=validVector(lm.point_lps_mm)?lm.point_lps_mm.map(n=>n.toFixed(3)).join(' / '):'未记录';
  $('plane-normal').textContent=validVector(lm.normal_lps)?lm.normal_lps.map(n=>n.toFixed(6)).join(' / '):'未记录';
  $('plane-proposal').textContent=lm.status==='needs_review'?'重点复核 · needs_review':lm.status==='proposed'?'自动候选 · proposed':lm.status||'未记录';
  $('plane-source').textContent=`当前病例 ${active.id} · landmarks[${lm.id}]；源文件：${lm.source?.path??(typeof lm.source==='string'?lm.source:'未记录')}`;
  const available=validVector(lm.point_lps_mm)&&validVector(lm.normal_lps)&&Math.hypot(...lm.normal_lps)>0;
  $('show-plane').disabled=!available;
  if(!available){$('plane-status').textContent='候选位置或法向未记录，无法绘制切面。';return;}
  const normal=new THREE.Vector3(lm.normal_lps[0],lm.normal_lps[2],-lm.normal_lps[1]).normalize();
  const point=lpsToView(lm.point_lps_mm,meshCenter),width=Math.max(10,Math.min(24,extent*.22));
  const color=lm.status==='needs_review'?0xb87513:0x285da0;
  cutPlane=new THREE.Group();cutPlane.userData={caseId:active.id,landmarkId:lm.id,point_lps_mm:[...lm.point_lps_mm],normal_lps:[...lm.normal_lps]};
  const planeGeometry=new THREE.PlaneGeometry(width,width);
  const plane=new THREE.Mesh(planeGeometry,new THREE.MeshBasicMaterial({color,transparent:true,opacity:.23,side:THREE.DoubleSide,depthTest:false,depthWrite:false}));
  plane.position.copy(point);plane.quaternion.setFromUnitVectors(new THREE.Vector3(0,0,1),normal);plane.renderOrder=14;cutPlane.add(plane);
  const border=new THREE.LineSegments(new THREE.EdgesGeometry(planeGeometry),new THREE.LineBasicMaterial({color,transparent:true,opacity:.95,depthTest:false,depthWrite:false}));border.position.copy(point);border.quaternion.copy(plane.quaternion);border.renderOrder=15;cutPlane.add(border);
  const arrow=new THREE.ArrowHelper(normal,point,extent*.12,color,extent*.025,extent*.014);arrow.traverse(child=>{if(child.material){child.material.depthTest=false;child.material.depthWrite=false;child.renderOrder=16;}});cutPlane.add(arrow);
  const center=new THREE.Mesh(new THREE.SphereGeometry(extent*.011,12,8),new THREE.MeshBasicMaterial({color,depthTest:false,depthWrite:false}));center.position.copy(point);center.renderOrder=17;cutPlane.add(center);
  cutPlane.visible=$('show-plane').checked;scene.add(cutPlane);
  $('plane-status').textContent=lm.label_zh+' · '+($('show-plane').checked?'显示原始候选平面':'切面已隐藏');
}
function setupPlanes(){
  resetPlaneInfo(active.type==='patient_engineering_diagnostic'?'本次工程试算未绑定解剖切面；内部流场剖面不改变进出口切面。':'此参考无患者解剖切面。');
  if(active.type!=='patient_preview')return;
  for(const id of openingIds){const lm=active.landmarks.find(candidate=>candidate.id===id);if(lm){const opt=textNode('option',lm.label_zh);opt.value=id;$('plane-select').append(opt);}}
  $('plane-select').disabled=!$('plane-select').options.length;
  if(!$('plane-select').options.length){$('plane-status').textContent='当前病例未记录进出口切面。';return;}
  updatePlane();
}
function resetView(which='reset'){
  camera.up.set(0,1,0);const d=extent*1.7;
  if(which==='front')camera.position.set(0,0,d);
  else if(which==='side')camera.position.set(d,0,0);
  else if(which==='top'){camera.up.set(0,0,-1);camera.position.set(0,d,0);}
  else if(which==='reference'||which==='reset'&&['numerical_reference','analytic_reference'].includes(active?.type)){camera.up.set(1,0,0);const fit=extent/(2*Math.tan(THREE.MathUtils.degToRad(camera.fov/2))*Math.max(camera.aspect,.1))*1.12;camera.position.set(0,0,fit);}
  else camera.position.set(.75,.48,1).normalize().multiplyScalar(d);
  camera.near=Math.max(extent/10000,.001);camera.far=extent*50;camera.updateProjectionMatrix();
  controls.target.set(0,0,0);controls.update();
}
function colorAt(t){const stops=[[.267,.005,.329],[.231,.322,.545],[.129,.569,.549],[.369,.788,.384],[.992,.906,.145]];t=Math.max(0,Math.min(1,t))*4;const i=Math.min(3,Math.floor(t)),f=t-i;return stops[i].map((v,j)=>v+(stops[i+1][j]-v)*f);}
function sampledDataset(){return meshData?.interior_slices?.find(slice=>slice.id===currentSampling)||{geometry:meshData?.geometry,fields:meshData?.result?.fields};}
function setSampling(id){
  if(!mesh||active?.type!=='patient_engineering_diagnostic')return;
  const slice=meshData.interior_slices.find(value=>value.id===id);if(id!=='surface'&&!slice)return;
  currentSampling=id;$('field-sampling').value=id;const data=sampledDataset(),verts=data.geometry.vertices;
  const positions=new Float32Array(verts.length);for(let i=0;i<verts.length;i+=3)lpsToView(verts.slice(i,i+3),meshCenter).toArray(positions,i);
  const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.BufferAttribute(positions,3));geometry.setIndex(data.geometry.indices);geometry.computeVertexNormals();mesh.geometry.dispose();mesh.geometry=geometry;
  $('field-sampling-note').textContent=slice?`${slice.axis.toUpperCase()} = ${slice.position_lps_mm.toFixed(3)} mm（LPS包围盒中部）；本次VTU点字段线性采样，字段时间 ${meshData.result.provenance.field_time}。该显示剖面不改变进出口切面。`:'体网格外表面：noSlip壁面速度通常接近0，不能代表腔内速度；请切换内部剖面。';
  setLayer(currentLayer);updateInfo();
}
function setupSampling(){
  currentSampling='surface';$('field-sampling-controls').hidden=active.type!=='patient_engineering_diagnostic';
  $('field-sampling').replaceChildren();if(active.type!=='patient_engineering_diagnostic')return;
  const surface=textNode('option','体网格外表面（壁面速度通常≈0）');surface.value='surface';$('field-sampling').append(surface);
  for(const slice of meshData.interior_slices){const option=textNode('option',`${slice.axis.toUpperCase()} = ${slice.position_lps_mm.toFixed(3)} mm · 内部中部剖面`);option.value=slice.id;$('field-sampling').append(option);}
  const selected=meshData.interior_slices.find(slice=>slice.id==='y')||meshData.interior_slices[0];
  $('field-sampling').value=selected.id;setSampling(selected.id);
}
function fieldValues(name){const field=sampledDataset()?.fields?.[name];if(!field||field.association!=='point'||!Array.isArray(field.values))return null;const percent=name==='turbulence_intensity'&&field.unit==='1'&&field.display_unit==='%';return field.values.map(v=>v===null?null:(Array.isArray(v)?Math.hypot(...v):v)*(percent?100:1));}
function setLayer(name){
  if(!mesh)return;
  const values=name==='geometry'?null:fieldValues(name);
  if(name!=='geometry'&&!values)return;
  currentLayer=name;
  document.querySelectorAll('[data-layer]').forEach(b=>b.classList.toggle('selected',b.dataset.layer===name));
  if(!values){mesh.material.vertexColors=false;mesh.material.color.set('#70a9b6');$('legend').hidden=true;}
  else{
    const finite=values.filter(Number.isFinite);if(!finite.length)return;
    if(values.length!==mesh.geometry.attributes.position.count)throw Error('字段数量与网格顶点不一致');
    const min=finite.reduce((a,b)=>Math.min(a,b),Infinity),max=finite.reduce((a,b)=>Math.max(a,b),-Infinity);
    const rgb=new Float32Array(values.length*3);values.forEach((v,i)=>rgb.set(Number.isFinite(v)?colorAt((v-min)/(max-min||1)):[.7,.7,.7],3*i));
    mesh.geometry.setAttribute('color',new THREE.BufferAttribute(rgb,3));mesh.material.vertexColors=true;mesh.material.color.set('#ffffff');
    $('legend').hidden=false;const field=sampledDataset().fields[name];const unit=name==='turbulence_intensity'&&field.unit==='1'&&field.display_unit==='%'?'%':field.unit;
    $('legend-title').textContent=titles[name]+' · '+unit;$('legend-min').textContent=min.toPrecision(3);$('legend-max').textContent=max.toPrecision(3);
  }mesh.material.needsUpdate=true;
}
function updateInfo(){
  const engineering=active.type==='patient_engineering_diagnostic',reference=['analytic_reference','numerical_reference'].includes(active.type),numerical=active.type==='numerical_reference',fields=meshData.result?.fields||active.result?.fields||{};
  $('model-title').textContent=active.label;$('model-note').textContent=active.note;
  $('kind-badge').textContent=engineering?'患者工程试算 · 非临床':numerical?'数值求解 · 非患者':reference?'解析参考 · 非患者':'真实 CT · 待审核';$('kind-badge').classList.toggle('reference',reference);
  $('kind-badge').classList.toggle('engineering',engineering);
  $('model-status').textContent=engineering?'数值状态 '+meshData.result.numerical_validation+' · 解剖/临床未验证':numerical?'已完成标准算例求解':reference?'解析值，用于验证展示':'候选几何，尚未审核';
  $('engineering-warning').hidden=!engineering;
  $('engineering-warning').textContent=engineering?'患者工程试算，非临床；数值状态 '+meshData.result.numerical_validation+'。剖面来自本次真实体场；外壁速度不代表腔内速度。质量失败保留显示，不构成正式患者 CFD 结果。':'';
  $('coordinates').textContent=reference?'合成坐标 · mm':'LPS 物理坐标 · mm';
  $('triangles').textContent=(sampledDataset().geometry.indices.length/3).toLocaleString();
  const sourceVertices=meshData.geometry.vertices;
  let modelSpan='未记录';
  if(Array.isArray(sourceVertices)&&sourceVertices.length%3===0&&sourceVertices.length){const lo=[Infinity,Infinity,Infinity],hi=[-Infinity,-Infinity,-Infinity];for(let i=0;i<sourceVertices.length;i+=3)for(let a=0;a<3;a++){lo[a]=Math.min(lo[a],sourceVertices[i+a]);hi[a]=Math.max(hi[a],sourceVertices[i+a]);}modelSpan=hi.map((v,a)=>(v-lo[a]).toFixed(3)).join(' × ')+' mm';}
  const spacing=meshData.source_geometry?.spacing_xyz_mm;
  $('voxel-spacing').textContent=validVector(spacing)?spacing.map(v=>v.toFixed(3)).join(' × ')+' mm':reference?'不适用（参考几何）':engineering?'本次体网格外表面，不代表 CT 体素':'未记录';
  const raw=meshData.qc?.raw_surface?.triangles,decimation=meshData.operations?.viewer_decimation;
  const parameters=meshData.result?.parameters,domain=numerical&&[parameters?.L_m,parameters?.gap_H_m,parameters?.empty_width_W_m].every(Number.isFinite)?`参考计算域：长 ${(parameters.L_m*1000).toFixed(1)} mm，间隙 ${(parameters.gap_H_m*1000).toFixed(1)} mm，宽 ${(parameters.empty_width_W_m*1000).toFixed(1)} mm；当前仅显示中间切片。 `:'';
  $('geometry-detail').textContent=`计算域范围（x × y × z）：${modelSpan}。 `+(engineering?'本次VTU外边界/内部剖面；LPS原轴，m→mm一次，速度分量不旋转。内部切片仅为体场显示，不改变原进出口面；几何审核及网格无关性尚未完成。':reference?domain+'当前为参考展示几何；表面显示方式不改变流场数据。':`源表面面数：${Number.isInteger(raw)?raw.toLocaleString():'未记录'}；显示抽稀：${decimation||'未记录'}。当前表面仅供显示，不等于已验收计算几何。`);
  $('landmark-count').textContent=reference?'不适用':engineering?'本次流场不替代解剖候选审核':String(active.landmarks.length)+' 个，均未确认';
  $('scene-note').textContent=engineering?'患者工程试算 · 非临床 · '+meshData.result.numerical_validation+' · '+(currentSampling==='surface'?'外表面（非腔内速度）':currentSampling.toUpperCase()+' 内部中部剖面'):numerical?'通道中间切面 · 真实数值解 · 非患者 · 保留实际比例':reference?'圆管中心截面解析解 · 不代表患者流场':'待审核候选表面 · 暂无患者流场';
  $('field-status').replaceChildren();
  for(const [key,name]of Object.entries(titles)){
    const available=!!fields[key];const row=textNode('div','', 'field-row');row.append(textNode('strong',name));
    const displayUnit=key==='turbulence_intensity'&&fields[key]?.unit==='1'&&fields[key]?.display_unit==='%'?'%':fields[key]?.unit;
    row.append(textNode('span',available?(engineering?'本次工程诊断值 · ':numerical?'OpenFOAM 求解值 · ':'解析参考值 · ')+displayUnit:(reference||engineering)&&key==='turbulence_intensity'?'未导出/层流不适用，不填 0%':'尚未求解，无可用数值'));
    $('field-status').append(row);$('layer-'+key).disabled=!available;
  }
  $('landmarks').replaceChildren();
  if(reference||engineering)$('landmarks').append(textNode('p',engineering?'本次工程流场不创建或确认解剖标定点。':'此参考没有患者解剖标定点。'));
  for(const lm of active.landmarks){const row=textNode('div','', 'landmark'+(lm.status==='needs_review'?' alert':''));row.append(textNode('span',lm.label_zh),textNode('span',lm.status==='needs_review'?'重点复核':'待复核'));$('landmarks').append(row);}
  $('show-landmarks').disabled=reference||engineering;
  const sampling=engineering&&currentSampling!=='surface'?meshData.interior_slices.find(slice=>slice.id===currentSampling):null;
  $('source-detail').textContent=JSON.stringify({status:meshData.status,coordinate_system:meshData.coordinate_system,unit:meshData.unit,source:meshData.source??meshData.sources??null,source_geometry:meshData.source_geometry??null,operations:meshData.operations??null,qc:meshData.qc??{},reference:meshData.result?.parameters??null,...(engineering?{job_id:meshData.job_id,case_id:meshData.case,clinical_validation:meshData.result.clinical_validation,numerical_validation:meshData.result.numerical_validation,provenance:meshData.result.provenance,input_fingerprint:meshData.result.input_fingerprint,diagnostics:meshData.result.diagnostics,display_sampling:sampling?{id:sampling.id,axis:sampling.axis,plane_lps_mm:sampling.plane_lps_mm,normal_lps:sampling.normal_lps,source_vtu_sha256:sampling.source_vtu_sha256,method:sampling.sampling}:{id:'surface',note:'outer boundary; wall speed does not represent internal flow'}}:{})},null,2);
}
function validateDiagnosticFields(fields,rho){
  if(!fields||fields.velocity?.unit!=='m/s'||fields.pressure?.unit!=='Pa'||fields.pressure.source_unit!=='m2/s2'||fields.pressure.source_field!=='p'||fields.pressure.reference!=='gauge'||fields.pressure.quantity!=='static'||fields.pressure.rho_kg_m3!==rho||fields.turbulence_intensity!==null||Object.keys(fields).some(key=>!['velocity','pressure','turbulence_intensity'].includes(key)))throw Error('工程字段单位、压力转换或字段集合不符');
}
function validateSamplingDataset(geometry,fields){
  const verts=geometry?.vertices,faces=geometry?.indices;
  if(!Array.isArray(verts)||!Array.isArray(faces)||!verts.length||!faces.length||verts.length%3||faces.length%3||verts.some(v=>!Number.isFinite(v))||faces.some(i=>!Number.isInteger(i)||i<0||i>=verts.length/3))throw Error('工程采样几何或索引无效');
  for(const [name,field]of Object.entries(fields)){
    if(field===null)continue;
    if(field.association!=='point'||!Array.isArray(field.values)||field.values.length!==verts.length/3||!field.values.every(v=>name==='velocity'?validVector(v):Number.isFinite(v)))throw Error('工程剖面字段长度、维度或数值无效：'+name);
  }
}
function validateEngineeringDiagnostic(item,data){
  const r=data.result,p=r?.provenance,job=item.id,source='/simulation-assets/'+job+'/';
  const sha=value=>typeof value==='string'&&/^[0-9a-f]{64}$/.test(value);
  if(!/^s_[0-9a-f]{24}$/.test(job)||requestedManifest!==source+'viewer.json'||item.job_id!==job||typeof item.case_id!=='string'||!item.case_id||item.mesh_url!==source+'viewer_mesh.json'||!Array.isArray(item.landmarks)||item.landmarks.length||data.schema!=='patient_engineering_surface/v1'||data.case!==item.case_id||data.job_id!==job||data.status!=='unvalidated_patient_engineering_diagnostic'||data.coordinate_system!=='LPS'||data.display_geometry_only!==true||data.cfd_ready!==false)throw Error('患者工程表面身份或受控资产路径不符');
  if(r?.schema!=='nasal_patient_engineering_diagnostic/v1'||r.type!=='patient_engineering_diagnostic'||r.job_id!==job||r.case_id!==item.case_id||r.patient_data!==true||r.engineering_trial!==true||r.clinical_validation!=='not_validated'||!['unchecked','failed'].includes(r.numerical_validation)||!['completed','failed'].includes(r.execution_status)||r.execution_status==='failed'&&r.numerical_validation!=='failed'||r.geometry?.kind!=='patient'||r.geometry.case_id!==item.case_id||r.geometry.coordinate_system!=='LPS'||r.geometry.units!=='mm'||r.geometry.solver_units!=='m'||r.geometry.scale_to_m!==.001||!sha(r.geometry.sha256))throw Error('工程诊断不能替代已审核患者结果');
  if(p?.method!=='cfd_solver'||p.job_id!==job||p.case_id!==item.case_id||p.source_vtu_url!==source+'patient-final-internal.vtu'||!sha(p.source_vtu_sha256)||!sha(p.config_sha256)||!sha(p.p_file_sha256)||!sha(p.U_file_sha256)||!Number.isFinite(Number(p.field_time))||!sha(r.input_fingerprint?.admission_sha256)||r.input_fingerprint.config_sha256!==p.config_sha256)throw Error('本次工程字段来源或内容指纹缺失');
  if(!Number.isFinite(r.physics?.rho_kg_m3)||r.physics.rho_kg_m3<=0)throw Error('工程流体密度无效');
  validateDiagnosticFields(r.fields,r.physics.rho_kg_m3);validateSamplingDataset(data.geometry,r.fields);
  const vertices=data.geometry.vertices,lo=[Infinity,Infinity,Infinity],hi=[-Infinity,-Infinity,-Infinity];
  for(let i=0;i<vertices.length;i+=3)for(let a=0;a<3;a++){lo[a]=Math.min(lo[a],vertices[i+a]);hi[a]=Math.max(hi[a],vertices[i+a]);}
  const center=lo.map((value,a)=>(value+hi[a])/2),tolerance=Math.max(1e-5,...hi.map((value,a)=>(value-lo[a])*1e-7));
  if(!Array.isArray(data.interior_slices)||!data.interior_slices.length||data.interior_slices.length>3)throw Error('本次体场缺少内部剖面，不能以外壁代替腔内速度');
  const ids=new Set();
  for(const slice of data.interior_slices){
    const axis=['x','y','z'].indexOf(slice?.axis);
    if(axis<0||slice.id!==slice.axis||ids.has(slice.id)||slice.source_vtu_sha256!==p.source_vtu_sha256||slice.sampling!=='vtkCutter linear interpolation of this volume VTU point field; no synthetic field'||!validVector(slice.plane_lps_mm)||!validVector(slice.normal_lps)||!Number.isFinite(slice.position_lps_mm)||slice.normal_lps.some((v,a)=>v!==(a===axis?1:0))||slice.plane_lps_mm.some((v,a)=>Math.abs(v-center[a])>tolerance)||Math.abs(slice.position_lps_mm-center[axis])>tolerance)throw Error('内部剖面的LPS位置、方向或本次VTU身份不符');
    ids.add(slice.id);validateDiagnosticFields(slice.fields,r.physics.rho_kg_m3);validateSamplingDataset(slice.geometry,slice.fields);
    for(let i=axis;i<slice.geometry.vertices.length;i+=3)if(Math.abs(slice.geometry.vertices[i]-slice.position_lps_mm)>tolerance)throw Error('内部剖面顶点不在声明的LPS平面');
  }
}
async function loadCase(item){
  const token=++loadToken;$('scene-state').hidden=false;$('scene-state').textContent='正在读取 '+item.label+'…';
  clearObjects();meshData=null;active=null;$('legend').hidden=true;$('model-title').textContent=item.label;
  $('engineering-warning').hidden=true;currentSampling='surface';currentLayer='geometry';$('field-sampling-controls').hidden=true;$('field-sampling').replaceChildren();$('field-sampling-note').textContent='';
  document.querySelector('.view-panel').classList.toggle('engineering',item.type==='patient_engineering_diagnostic');
  $('model-note').textContent='正在核对模型身份与字段…';$('model-status').textContent='加载中';
  for(const id of ['coordinates','triangles','landmark-count','voxel-spacing'])$(id).textContent='—';
  $('geometry-detail').textContent='';resetPlaneInfo('正在读取当前病例切面…');
  $('field-status').replaceChildren();$('landmarks').replaceChildren();$('source-detail').textContent='';$('scene-note').textContent='';
  document.querySelectorAll('[data-layer]').forEach(b=>{b.disabled=true;b.classList.remove('selected');});
  try{
    if(item.type==='patient_engineering_diagnostic'&&(!/^s_[0-9a-f]{24}$/.test(item.id)||requestedManifest!=='/simulation-assets/'+item.id+'/viewer.json'||item.mesh_url!=='/simulation-assets/'+item.id+'/viewer_mesh.json'))throw Error('工程流场只允许本次受控同源资产');
    const response=await fetch(item.mesh_url);if(!response.ok)throw Error('模型文件读取失败');const data=await response.json();if(token!==loadToken)return;
    if((item.type==='patient_engineering_diagnostic'?data.schema!=='patient_engineering_surface/v1':data.schema!=='candidate_surface_preview/v1')||data.unit!=='mm')throw Error('模型格式或单位不一致');
    const emptyPatientResult=r=>r?.type==='patient_preview'&&r?.geometry?.kind==='patient'&&r?.geometry?.case_id===item.id&&r.fields&&['velocity','pressure','turbulence_intensity'].every(k=>r.fields[k]===null);
    if(item.type==='patient_preview'){
      if(data.case!==item.id||data.coordinate_system!=='LPS'||data.status!=='unreviewed_candidate_preview'||data.cfd_ready!==false||data.display_geometry_only!==true||!emptyPatientResult(item.result)||(data.result!=null&&!emptyPatientResult(data.result)))throw Error('患者预览身份不符或混入未允许的流场');
      data.result=item.result;
    }else if(item.type==='patient_engineering_diagnostic'){
      validateEngineeringDiagnostic(item,data);
    }else if(item.type==='analytic_reference'){
      if(data.status!=='analytic_reference'||data.coordinate_system!=='synthetic_Cartesian'||data.case!==null||data.result?.type!=='analytic_reference'||data.result.geometry?.kind!=='idealized'||data.result.geometry?.case_id!==null)throw Error('解析参考身份不符');
    }else if(item.type==='numerical_reference'){
      if(data.status!=='numerical_reference'||data.coordinate_system!=='synthetic_Cartesian'||data.case!==null||data.result?.type!=='cfd_result'||data.result.geometry?.kind!=='idealized'||data.result.geometry?.case_id!==null||data.result.provenance?.method!=='cfd_solver')throw Error('数值参考身份不符');
    }else throw Error('未知数据类型');
    const verts=data.geometry?.vertices,faces=data.geometry?.indices;if(!Array.isArray(verts)||!Array.isArray(faces)||verts.length%3||faces.length%3||!verts.length||verts.some(v=>!Number.isFinite(v))||faces.some(i=>!Number.isInteger(i)||i<0||i>=verts.length/3))throw Error('几何数据无效');
    for(const [name,field]of Object.entries(data.result?.fields||{})){
      if(field===null)continue;
      if(field.association!=='point'||!Array.isArray(field.values)||field.values.length!==verts.length/3)throw Error('字段与网格顶点数量不一致：'+name);
      const valid=field.values.every(v=>name==='velocity'?Array.isArray(v)&&v.length===3&&v.every(Number.isFinite):name==='turbulence_intensity'?v===null||Number.isFinite(v)&&v>=0:Number.isFinite(v));
      if(!valid)throw Error('字段数值或维度无效：'+name);
    }
    active=item;meshData=data;
    const bounds=new THREE.Box3();for(let i=0;i<verts.length;i+=3)bounds.expandByPoint(new THREE.Vector3(verts[i],verts[i+1],verts[i+2]));
    const ctr=bounds.getCenter(new THREE.Vector3()).toArray(),size=bounds.getSize(new THREE.Vector3());meshCenter=ctr;extent=Math.max(size.x,size.y,size.z,1);
    const positions=new Float32Array(verts.length);for(let i=0;i<verts.length;i+=3)lpsToView(verts.slice(i,i+3),ctr).toArray(positions,i);
    const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.BufferAttribute(positions,3));geometry.setIndex(faces);geometry.computeVertexNormals();
    const opacity=Number($('opacity').value);const material=new THREE.MeshStandardMaterial({color:'#70a9b6',metalness:0,roughness:.65,side:THREE.DoubleSide,transparent:opacity<1,opacity});
    mesh=new THREE.Mesh(geometry,material);scene.add(mesh);markers=new THREE.Group();
    for(const lm of item.landmarks){const marker=new THREE.Mesh(new THREE.SphereGeometry(extent*.009,12,8),new THREE.MeshBasicMaterial({color:lm.status==='needs_review'?0xffa12f:0x395eb9,depthTest:false,depthWrite:false,transparent:true,opacity:1}));marker.position.copy(lpsToView(lm.point_lps_mm,ctr));marker.renderOrder=10;markers.add(marker);}
    markers.visible=$('show-landmarks').checked;scene.add(markers);resetView(item.type==='numerical_reference'||item.type==='analytic_reference'?'reference':'reset');setupSampling();updateInfo();setupPlanes();setDisplayMode(displayMode);$('layer-geometry').disabled=false;setLayer(item.type!=='patient_preview'?'velocity':'geometry');$('scene-state').hidden=true;
  }catch(error){if(token!==loadToken)return;clearObjects();meshData=null;active=null;$('model-status').textContent='加载失败';$('scene-state').textContent='无法显示：'+error.message;console.error(error);}
}
for(const id of ['front','side','top','reset'])$(id).addEventListener('click',()=>resetView(id));
document.querySelectorAll('[data-layer]').forEach(b=>b.addEventListener('click',()=>setLayer(b.dataset.layer)));
document.querySelectorAll('[data-display]').forEach(b=>b.addEventListener('click',()=>setDisplayMode(b.dataset.display)));
$('plane-select').addEventListener('change',updatePlane);
$('show-plane').addEventListener('change',updatePlane);
$('field-sampling').addEventListener('change',()=>setSampling($('field-sampling').value));
$('show-landmarks').addEventListener('change',()=>{if(markers)markers.visible=$('show-landmarks').checked;});
$('opacity').addEventListener('input',()=>{if(mesh){mesh.material.opacity=Number($('opacity').value);mesh.material.transparent=mesh.material.opacity<1;mesh.material.needsUpdate=true;}});
try{
  initScene();
  const manifest = new URLSearchParams(location.search).get('manifest');
  const allowedManifest=value=>/^\/case-assets\/u_[0-9a-f]{16}\/(?:versions\/v_[0-9a-f]{16}\/)?viewer\.json$/.test(value)||/^\/simulation-assets\/s_[0-9a-f]{24}\/viewer\.json$/.test(value);
  if (manifest !== null && !allowedManifest(manifest)) throw Error('病例索引地址无效');
  requestedManifest=manifest;
  const response=await fetch(manifest || './workspace_data.json');
  if(!response.ok)throw Error('工作台索引未生成');
  const data=await response.json();
  if(data.schema !== 'nasal_workspace/v1' || !Array.isArray(data.cases) || !data.cases.length)throw Error('病例索引格式无效');
  if(data.cases.some(item=>item.type==='patient_engineering_diagnostic')&&(data.cases.length!==1||data.patient_scan_count!==0||data.patient_cfd_results!==0))throw Error('工程诊断索引不能增加正式患者结果或混入其他病例');
  $('scan-count').textContent=data.patient_scan_count;$('patient-result-count').textContent=data.patient_cfd_results;updateFeedbackAudit(data.feedback_audit);
  for(const item of data.cases){const opt=textNode('option',item.label);opt.value=item.id;$('case-select').append(opt);}
  $('case-select').addEventListener('change',()=>loadCase(data.cases.find(c=>c.id===$('case-select').value)));await loadCase(data.cases[0]);
}catch(error){$('feedback-count').textContent='未生成';$('feedback-status').textContent='工作台未能读取人工意见摘要';$('feedback-detail').textContent=error.message;$('scene-state').textContent='工作台未能启动：'+error.message;console.error(error);}

// Read-only browser verification: no geometry or patient state mutation.
export function getDisplaySnapshot(){return mesh?{caseId:active.id,mode:displayMode,layer:currentLayer,sampling:currentSampling,positions:Array.from(mesh.geometry.attributes.position.array),indices:Array.from(mesh.geometry.index.array),center:[...meshCenter],camera:camera.position.toArray(),target:controls.target.toArray(),flatShading:mesh.material.flatShading,wireframe:mesh.material.wireframe,pixelRatio:renderer.getPixelRatio(),plane:cutPlane?{...cutPlane.userData,visible:cutPlane.visible,viewPoint:cutPlane.children[0].position.toArray(),viewNormal:new THREE.Vector3(0,0,1).applyQuaternion(cutPlane.children[0].quaternion).toArray()}:null}:null;}
