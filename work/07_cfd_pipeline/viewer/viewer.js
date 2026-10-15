import * as THREE from 'three';
import {OrbitControls} from './vendor/OrbitControls.js';

const $=id=>document.getElementById(id);
let scene,camera,renderer,controls,mesh,markers,cutPlane,active,meshData,meshCenter,extent=80,loadToken=0,currentLayer='geometry',displayMode='smooth';
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
  resetPlaneInfo();
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
function fieldValues(name){const field=meshData?.result?.fields?.[name];if(!field||field.association!=='point'||!Array.isArray(field.values))return null;const percent=name==='turbulence_intensity'&&field.unit==='1'&&field.display_unit==='%';return field.values.map(v=>v===null?null:(Array.isArray(v)?Math.hypot(...v):v)*(percent?100:1));}
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
    $('legend').hidden=false;const field=meshData.result.fields[name];const unit=name==='turbulence_intensity'&&field.unit==='1'&&field.display_unit==='%'?'%':field.unit;
    $('legend-title').textContent=titles[name]+' · '+unit;$('legend-min').textContent=min.toPrecision(3);$('legend-max').textContent=max.toPrecision(3);
  }mesh.material.needsUpdate=true;
}
function updateInfo(){
  const reference=active.type!=='patient_preview',numerical=active.type==='numerical_reference',fields=meshData.result?.fields||active.result?.fields||{};
  $('model-title').textContent=active.label;$('model-note').textContent=active.note;
  $('kind-badge').textContent=numerical?'数值求解 · 非患者':reference?'解析参考 · 非患者':'真实 CT · 待审核';$('kind-badge').classList.toggle('reference',reference);
  $('model-status').textContent=numerical?'已完成标准算例求解':reference?'解析值，用于验证展示':'候选几何，尚未审核';
  $('coordinates').textContent=reference?'合成坐标 · mm':'LPS 物理坐标 · mm';
  $('triangles').textContent=(meshData.geometry.indices.length/3).toLocaleString();
  const sourceVertices=meshData.geometry.vertices;
  let modelSpan='未记录';
  if(Array.isArray(sourceVertices)&&sourceVertices.length%3===0&&sourceVertices.length){const lo=[Infinity,Infinity,Infinity],hi=[-Infinity,-Infinity,-Infinity];for(let i=0;i<sourceVertices.length;i+=3)for(let a=0;a<3;a++){lo[a]=Math.min(lo[a],sourceVertices[i+a]);hi[a]=Math.max(hi[a],sourceVertices[i+a]);}modelSpan=hi.map((v,a)=>(v-lo[a]).toFixed(3)).join(' × ')+' mm';}
  const spacing=meshData.source_geometry?.spacing_xyz_mm;
  $('voxel-spacing').textContent=validVector(spacing)?spacing.map(v=>v.toFixed(3)).join(' × ')+' mm':reference?'不适用（参考几何）':'未记录';
  const raw=meshData.qc?.raw_surface?.triangles,decimation=meshData.operations?.viewer_decimation;
  const parameters=meshData.result?.parameters,domain=numerical&&[parameters?.L_m,parameters?.gap_H_m,parameters?.empty_width_W_m].every(Number.isFinite)?`参考计算域：长 ${(parameters.L_m*1000).toFixed(1)} mm，间隙 ${(parameters.gap_H_m*1000).toFixed(1)} mm，宽 ${(parameters.empty_width_W_m*1000).toFixed(1)} mm；当前仅显示中间切片。 `:'';
  $('geometry-detail').textContent=`显示范围（x × y × z）：${modelSpan}。 `+(reference?domain+'当前为参考展示几何；表面显示方式不改变流场数据。':`源表面面数：${Number.isInteger(raw)?raw.toLocaleString():'未记录'}；显示抽稀：${decimation||'未记录'}。当前表面仅供显示，不等于已验收计算几何。`);
  $('landmark-count').textContent=reference?'不适用':String(active.landmarks.length)+' 个，均未确认';
  $('scene-note').textContent=numerical?'通道中间切面 · 真实数值解 · 非患者 · 保留实际比例':reference?'圆管中心截面解析解 · 不代表患者流场':'待审核候选表面 · 暂无患者流场';
  $('field-status').replaceChildren();
  for(const [key,name]of Object.entries(titles)){
    const available=!!fields[key];const row=textNode('div','', 'field-row');row.append(textNode('strong',name));
    const displayUnit=key==='turbulence_intensity'&&fields[key]?.unit==='1'&&fields[key]?.display_unit==='%'?'%':fields[key]?.unit;
    row.append(textNode('span',available?(numerical?'OpenFOAM 求解值 · ':'解析参考值 · ')+displayUnit:reference&&key==='turbulence_intensity'?'层流参考：不适用，不填 0%':'尚未求解，无可用数值'));
    $('field-status').append(row);$('layer-'+key).disabled=!available;
  }
  $('landmarks').replaceChildren();
  if(reference)$('landmarks').append(textNode('p','此参考没有患者解剖标定点。'));
  for(const lm of active.landmarks){const row=textNode('div','', 'landmark'+(lm.status==='needs_review'?' alert':''));row.append(textNode('span',lm.label_zh),textNode('span',lm.status==='needs_review'?'重点复核':'待复核'));$('landmarks').append(row);}
  $('show-landmarks').disabled=reference;
  $('source-detail').textContent=JSON.stringify({status:meshData.status,coordinate_system:meshData.coordinate_system,unit:meshData.unit,source:meshData.source??meshData.sources??null,source_geometry:meshData.source_geometry??null,operations:meshData.operations??null,qc:meshData.qc??{},reference:meshData.result?.parameters??null},null,2);
}
async function loadCase(item){
  const token=++loadToken;$('scene-state').hidden=false;$('scene-state').textContent='正在读取 '+item.label+'…';
  clearObjects();meshData=null;active=null;$('legend').hidden=true;$('model-title').textContent=item.label;
  $('model-note').textContent='正在核对模型身份与字段…';$('model-status').textContent='加载中';
  for(const id of ['coordinates','triangles','landmark-count','voxel-spacing'])$(id).textContent='—';
  $('geometry-detail').textContent='';resetPlaneInfo('正在读取当前病例切面…');
  $('field-status').replaceChildren();$('landmarks').replaceChildren();$('source-detail').textContent='';$('scene-note').textContent='';
  document.querySelectorAll('[data-layer]').forEach(b=>{b.disabled=true;b.classList.remove('selected');});
  try{
    const response=await fetch(item.mesh_url);if(!response.ok)throw Error('模型文件读取失败');const data=await response.json();if(token!==loadToken)return;
    if(data.schema!=='candidate_surface_preview/v1'||data.unit!=='mm')throw Error('模型格式或单位不一致');
    const emptyPatientResult=r=>r?.type==='patient_preview'&&r?.geometry?.kind==='patient'&&r?.geometry?.case_id===item.id&&r.fields&&['velocity','pressure','turbulence_intensity'].every(k=>r.fields[k]===null);
    if(item.type==='patient_preview'){
      if(data.case!==item.id||data.coordinate_system!=='LPS'||data.status!=='unreviewed_candidate_preview'||data.cfd_ready!==false||data.display_geometry_only!==true||!emptyPatientResult(item.result)||(data.result!=null&&!emptyPatientResult(data.result)))throw Error('患者预览身份不符或混入未允许的流场');
      data.result=item.result;
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
    markers.visible=$('show-landmarks').checked;scene.add(markers);resetView(item.type==='numerical_reference'||item.type==='analytic_reference'?'reference':'reset');updateInfo();setupPlanes();setDisplayMode(displayMode);$('layer-geometry').disabled=false;setLayer(item.type!=='patient_preview'?'velocity':'geometry');$('scene-state').hidden=true;
  }catch(error){if(token!==loadToken)return;clearObjects();meshData=null;active=null;$('model-status').textContent='加载失败';$('scene-state').textContent='无法显示：'+error.message;console.error(error);}
}
for(const id of ['front','side','top','reset'])$(id).addEventListener('click',()=>resetView(id));
document.querySelectorAll('[data-layer]').forEach(b=>b.addEventListener('click',()=>setLayer(b.dataset.layer)));
document.querySelectorAll('[data-display]').forEach(b=>b.addEventListener('click',()=>setDisplayMode(b.dataset.display)));
$('plane-select').addEventListener('change',updatePlane);
$('show-plane').addEventListener('change',updatePlane);
$('show-landmarks').addEventListener('change',()=>{if(markers)markers.visible=$('show-landmarks').checked;});
$('opacity').addEventListener('input',()=>{if(mesh){mesh.material.opacity=Number($('opacity').value);mesh.material.transparent=mesh.material.opacity<1;mesh.material.needsUpdate=true;}});
try{
  initScene();
  const manifest = new URLSearchParams(location.search).get('manifest');
  const allowedManifest=value=>/^\/case-assets\/u_[0-9a-f]{16}\/(?:versions\/v_[0-9a-f]{16}\/)?viewer\.json$/.test(value)||/^\/simulation-assets\/s_[0-9a-f]{24}\/viewer\.json$/.test(value);
  if (manifest && !allowedManifest(manifest)) throw Error('病例索引地址无效');
  const response=await fetch(manifest || './workspace_data.json');
  if(!response.ok)throw Error('工作台索引未生成');
  const data=await response.json();
  if(data.schema !== 'nasal_workspace/v1' || !Array.isArray(data.cases) || !data.cases.length)throw Error('病例索引格式无效');
  $('scan-count').textContent=data.patient_scan_count;$('patient-result-count').textContent=data.patient_cfd_results;updateFeedbackAudit(data.feedback_audit);
  for(const item of data.cases){const opt=textNode('option',item.label);opt.value=item.id;$('case-select').append(opt);}
  $('case-select').addEventListener('change',()=>loadCase(data.cases.find(c=>c.id===$('case-select').value)));await loadCase(data.cases[0]);
}catch(error){$('feedback-count').textContent='未生成';$('feedback-status').textContent='工作台未能读取人工意见摘要';$('feedback-detail').textContent=error.message;$('scene-state').textContent='工作台未能启动：'+error.message;console.error(error);}

// Read-only browser verification: no geometry or patient state mutation.
export function getDisplaySnapshot(){return mesh?{caseId:active.id,mode:displayMode,layer:currentLayer,positions:Array.from(mesh.geometry.attributes.position.array),indices:Array.from(mesh.geometry.index.array),center:[...meshCenter],camera:camera.position.toArray(),target:controls.target.toArray(),flatShading:mesh.material.flatShading,wireframe:mesh.material.wireframe,pixelRatio:renderer.getPixelRatio(),plane:cutPlane?{...cutPlane.userData,visible:cutPlane.visible,viewPoint:cutPlane.children[0].position.toArray(),viewNormal:new THREE.Vector3(0,0,1).applyQuaternion(cutPlane.children[0].quaternion).toArray()}:null}:null;}
