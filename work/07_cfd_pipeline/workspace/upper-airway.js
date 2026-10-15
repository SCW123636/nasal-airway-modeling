import * as THREE from 'three';
import {OrbitControls} from '/viewer/vendor/OrbitControls.js';

const $ = id => document.getElementById(id);
const params = new URLSearchParams(location.search);
let requested = params.get('case');
let generation = 0, aborter = null;
const meshes = new Map();
let scene, camera, renderer, controls, outline, center, extent;
const allowed = ['p0','p1','p2','p3','p3t1'];
const upload = params.get('uploadContext');
if (upload) {
  $('upload-context').hidden = false;
  $('upload-context').textContent = '当前工作台上传病例尚无咽部扩展候选。下方是独立的已有工程扫描，不代表当前上传病例。请明确选择工程扫描查看。';
}
function message(value, error=false) {
  $('message').textContent = value;
  $('message').classList.toggle('error', error);
  $('message').setAttribute('role', error ? 'alert' : 'status');
}
async function json(url, signal) {
  const r = await fetch(url, {signal, cache:'no-store'});
  let value;
  try { value = await r.json(); } catch { throw Error(`读取失败（HTTP ${r.status}）`); }
  if (!r.ok) throw Error(value.error || `读取失败（HTTP ${r.status}）`);
  return value;
}
function removeGeometry() {
  for (const mesh of meshes.values()) {scene?.remove(mesh);mesh.geometry.dispose();mesh.material.dispose();}
  meshes.clear();
  if (outline) {scene.remove(outline);outline.geometry.dispose();outline.material.dispose();outline=null;}
  $('candidate').hidden = true;
  $('unavailable').hidden = true;
  $('ct-preview').removeAttribute('src');
  $('ct-full').removeAttribute('href');
  $('candidate-facts').replaceChildren();
  $('fingerprints').textContent = '';
  delete document.body.dataset.case;
}
function initializeScene() {
  if (renderer) return;
  renderer = new THREE.WebGLRenderer({antialias:true});
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setClearColor(0x172b40);
  $('scene').append(renderer.domElement);
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(38, 1, .05, 5000);
  camera.up.set(0,0,1);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = false;
  scene.add(new THREE.HemisphereLight(0xeaf7ff,0x475164,2.4));
  const lamp = new THREE.DirectionalLight(0xffffff,2.5);
  lamp.position.set(-100,-200,250);scene.add(lamp);
  const lamp2 = new THREE.DirectionalLight(0xc9e5ff,1.5);
  lamp2.position.set(180,50,350);scene.add(lamp2);
  const resize=()=>{
    const width=$('scene').clientWidth,height=$('scene').clientHeight;
    if (!width || !height) return;
    renderer.setSize(width,height,false);camera.aspect=width/height;camera.updateProjectionMatrix();renderer.render(scene,camera);
  };
  new ResizeObserver(resize).observe($('scene'));
  // Render on interaction only; a hidden retained workbench frame uses no loop.
  controls.addEventListener('change',()=>renderer.render(scene,camera));
  resize();
}
function setView(kind='side') {
  if (!center) return;
  const d=extent*2.15;
  camera.position.copy(center).add(kind==='front'?new THREE.Vector3(0,-d,d*.1):new THREE.Vector3(d,-d*.12,d*.1));
  controls.target.copy(center);controls.update();
  renderer.render(scene,camera);
  $('scene').dataset.view=kind;
}
function fact(label, value) {
  const row=document.createElement('div'),dt=document.createElement('dt'),dd=document.createElement('dd');
  dt.textContent=label;dd.textContent=value;row.append(dt,dd);$('candidate-facts').append(row);
}
function showCoverage(data) {
  $('coverage').replaceChildren();
  for (const [label,value,note] of [
    ['口咽下方覆盖',`${data.inferior_face_air_voxels.toLocaleString()} 体素`,'触及 CT 最下层，存在截断风险'],
    ['下咽标签',data.hypopharynx_empty?'空标签':'非空','空标签不能证明该解剖结构不存在'],
    ['喉腔标签',data.larynx_air_exists?'已有文件':'缺失','完整喉部 / 声门覆盖尚未建立'],
    ['医学与出口','待复核','未审核 · 出口未定 · 非正式 CFD'],
  ]) {
    const card=document.createElement('article'),title=document.createElement('span'),v=document.createElement('strong'),small=document.createElement('small');
    title.textContent=label;v.textContent=value;small.textContent=note;card.append(title,v,small);$('coverage').append(card);
  }
}
async function binary(caseId,name,meta,signal) {
  const r=await fetch(`/upper-airway-assets/${caseId}/${name}`,{signal,cache:'no-store'});
  if (!r.ok) {let e;try {e=await r.json();}catch{}throw Error(e?.error||`显示资产读取失败（HTTP ${r.status}）`);}
  const value=await r.arrayBuffer();
  if(value.byteLength!==meta.bytes)throw Error('显示资产大小不符合冻结记录');
  const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',value)),b=>b.toString(16).padStart(2,'0')).join('');
  if(digest!==meta.sha256)throw Error('显示资产指纹不一致，已停止显示');
  return value;
}
async function choose(caseId, persist=true) {
  const version=++generation;
  aborter?.abort();aborter=new AbortController();
  removeGeometry();$('coverage').replaceChildren();
  if(persist) {
    const u=new URL(location.href);u.searchParams.set('case',caseId);history.replaceState(null,'',u);
    if(parent!==window)parent.postMessage({type:'nasal-upper-airway-selected',case:caseId},location.origin);
  }
  if(!caseId) {message('请选择独立工程扫描。当前上传病例未生成口咽候选。');return;}
  message(`正在读取 ${caseId} 的冻结覆盖记录…`);
  try {
    const data=await json('/api/upper-airway/cases/'+encodeURIComponent(caseId),aborter.signal);
    if(version!==generation)return;
    if(data.case!==caseId || data.patient_symptom_mapping!=='unknown' || data.CFD_admitted || data.outlet_selected)throw Error('候选身份或只读状态校验失败');
    document.body.dataset.case=caseId;
    showCoverage(data);
    if(data.candidate_status!=='available'){
      $('unavailable').hidden=false;
      message(`${caseId} · 本例扩展候选未生成；只显示本例审计，不回退其他病例。`);
      $('fingerprints').textContent=`${caseId} audit SHA-256: ${data.audit_sha256}`;
      return;
    }
    const manifest=data.candidate;
    if(manifest.case!==caseId || manifest.coordinate_system!=='LPS' || manifest.unit!=='mm')throw Error('显示面坐标或身份不匹配');
    const buffers=await Promise.all(['baseline','added'].map(async name=>({name,
      vertices:await binary(caseId,`${name}.vertices.bin`,manifest.assets[`${name}.vertices.bin`],aborter.signal),
      faces:await binary(caseId,`${name}.triangles.bin`,manifest.assets[`${name}.triangles.bin`],aborter.signal)})));
    if(version!==generation)return;
    $('candidate').hidden=false;initializeScene();
    const bounds=new THREE.Box3();
    for(const {name,vertices,faces} of buffers){
      const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.BufferAttribute(new Float32Array(vertices),3));g.setIndex(new THREE.BufferAttribute(new Uint32Array(faces),1));g.computeVertexNormals();g.computeBoundingBox();bounds.union(g.boundingBox);
      const material=new THREE.MeshStandardMaterial({color:name==='baseline'?0x20bed1:0xf08a38,roughness:.65,metalness:0,side:THREE.DoubleSide});
      const mesh=new THREE.Mesh(g,material);mesh.name=name;scene.add(mesh);meshes.set(name,mesh);
    }
    center=bounds.getCenter(new THREE.Vector3());extent=Math.max(...bounds.getSize(new THREE.Vector3()).toArray());
    // A local frame on the true CT z-index-0 center plane: annotation only.
    const z=manifest.CT.origin_LPS_mm[2],x0=bounds.min.x-7,x1=bounds.max.x+7,y0=bounds.min.y-7,y1=bounds.max.y+7;
    const line=new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(x0,y0,z),new THREE.Vector3(x1,y0,z),new THREE.Vector3(x1,y1,z),new THREE.Vector3(x0,y1,z)]);
    outline=new THREE.LineLoop(line,new THREE.LineBasicMaterial({color:0xff6ad9}));scene.add(outline);
    $('show-base').checked=true;$('show-added').checked=true;setView();
    const ctUrl=`/upper-airway-assets/${caseId}/ct-comparison.png`;$('ct-preview').src=ctUrl;$('ct-full').href=ctUrl;
    fact('工程扫描',caseId+' · 非当前上传病例');fact('鼻腔＋鼻咽',manifest.surfaces.baseline.source_voxels.toLocaleString()+' 体素');fact('新增口咽',manifest.surfaces.added.source_voxels.toLocaleString()+' 体素');fact('原域保留','全部保留');fact('下方显示面','保持开放');fact('医学状态','未审核');fact('CFD 准入','未准入');
    $('geometry-facts').textContent=`真实掩膜直接提取；${(manifest.surfaces.baseline.triangles+manifest.surfaces.added.triangles).toLocaleString()} 个显示三角形。未封口，不适合作为正式 CFD 输入。`;
    $('fingerprints').textContent=JSON.stringify({case:caseId,source_run:manifest.source_run,source_sha256:manifest.source_sha256,display_surfaces:manifest.surfaces},null,2);
    message(`${caseId} · 已载入真实鼻腔—口咽工程候选。症状患者对应关系未知。`);
  } catch(e) {
    if(e.name==='AbortError'||version!==generation)return;
    removeGeometry();message(e.message,true);
  }
}
async function start() {
  const version=++generation;
  aborter?.abort();aborter=new AbortController();
  removeGeometry();$('coverage').replaceChildren();$('airway-case').disabled=true;
  message('正在读取五例覆盖记录…');
  try {
    const data=await json('/api/upper-airway/catalog',aborter.signal);
    if(version!==generation)return;
    if(data.cases.map(c=>c.case).join(',')!==allowed.join(','))throw Error('工程扫描目录身份不符合冻结清单');
    const select=$('airway-case');select.replaceChildren();
    if(upload){const o=new Option('请选择独立工程扫描','');select.add(o);}
    for(const item of data.cases) select.add(new Option(`${item.case} · ${item.candidate_status==='available'?'有口咽候选':'仅覆盖审计 / 候选未生成'}`,item.case));
    if(requested!==null && !allowed.includes(requested))select.add(new Option('请求的病例无扩展候选',requested));
    select.disabled=false;select.value=requested!==null?requested:upload?'':'p3';
    await choose(select.value,false);
  }catch(e){if(e.name==='AbortError'||version!==generation)return;removeGeometry();message(e.message,true);}
}
$('airway-case').addEventListener('change',()=>{requested=$('airway-case').value;choose(requested);});
$('retry').addEventListener('click',start);
$('show-base').addEventListener('change',()=>{if(meshes.has('baseline')){meshes.get('baseline').visible=$('show-base').checked;renderer.render(scene,camera);}});
$('show-added').addEventListener('change',()=>{if(meshes.has('added')){meshes.get('added').visible=$('show-added').checked;renderer.render(scene,camera);}});
$('reset-view').addEventListener('click',()=>setView());
$('side-view').addEventListener('click',()=>setView('side'));
$('front-view').addEventListener('click',()=>setView('front'));
$('ct-preview').addEventListener('error',()=>{if(!$('candidate').hidden)message('同源 CT 对照读取失败；请重新读取，未使用其他病例替代。',true);});
window.addEventListener('message',e=>{if(e.origin===location.origin&&e.data?.type==='nasal-workspace-visible')controls?.update();});
start();
