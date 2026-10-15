
(function(){
const {LINE_DATA, WALL_POS, WALL_IDX, PATCH, META} = DATA;
const host = document.getElementById('view');
const scene = new THREE.Scene();
scene.background = new THREE.Color(0xeef3f1);
const camera = new THREE.PerspectiveCamera(45, 1, 1, 4000);
const renderer = new THREE.WebGLRenderer({antialias:true});
renderer.setPixelRatio(Math.min(2, window.devicePixelRatio||1));
host.appendChild(renderer.domElement);
scene.add(new THREE.AmbientLight(0xffffff, 0.78));
const d1 = new THREE.DirectionalLight(0xffffff, 0.5); d1.position.set(1,1,1.2); scene.add(d1);
const d2 = new THREE.DirectionalLight(0xffffff, 0.22); d2.position.set(-1,-0.7,-0.9); scene.add(d2);

/* ---------- 壁面 / patch ---------- */
function triMesh(pos, idx, color, op, dw){
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos,3));
  g.setIndex(new THREE.BufferAttribute(idx,1)); g.computeVertexNormals();
  const m = new THREE.MeshPhongMaterial({color:color, transparent:true, opacity:op,
    side:THREE.DoubleSide, depthWrite:dw===false?false:true, shininess:12});
  const mesh = new THREE.Mesh(g,m); scene.add(mesh); return mesh;
}
const wall = triMesh(WALL_POS, WALL_IDX, 0xc3cdda, 0.18, false);
triMesh(PATCH.nl_pos, PATCH.nl_idx, 0xd62728, 0.92, true);
triMesh(PATCH.nr_pos, PATCH.nr_idx, 0x1f77b4, 0.92, true);
triMesh(PATCH.out_pos, PATCH.out_idx, 0x2ca02c, 0.60, true);

/* ---------- 色带 ---------- */
function turbo(t){
  t = Math.max(0, Math.min(1, t));
  const stops = [[0.19,0.07,0.23],[0.28,0.35,0.85],[0.15,0.72,0.90],[0.25,0.93,0.55],
                 [0.72,0.95,0.20],[0.99,0.75,0.10],[0.98,0.42,0.10],[0.80,0.12,0.10],[0.48,0.05,0.09]];
  const x = t*(stops.length-1), i = Math.floor(x), f = x-i;
  const a = stops[i], b = stops[Math.min(stops.length-1,i+1)];
  return [a[0]+(b[0]-a[0])*f, a[1]+(b[1]-a[1])*f, a[2]+(b[2]-a[2])*f];
}
function cssTurbo(){
  return 'linear-gradient(90deg,' + Array.from({length:32},(_,i)=>{
    const c = turbo(i/31).map(v=>Math.round(v*255)); return 'rgb('+c.join(',')+')';
  }).join(',') + ')';
}
document.getElementById('bar').style.background = cssTurbo();

/* ---------- 流线（管状） ---------- */
let mode = 'speed';
function rangeMM(){
  return mode==='speed' ? [META.spd_p2, META.spd_max] : [META.p_p2, META.p_max];
}
function f32(a){ return new Float32Array(a); }
const tubes = [];
LINE_DATA.forEach(function(L){
  const n = L.pos.length/3;
  const v = [];
  for (let i=0;i<n;i++) v.push(new THREE.Vector3(L.pos[i*3], L.pos[i*3+1], L.pos[i*3+2]));
  const curve = new THREE.CatmullRomCurve3(v, false, 'catmullrom', 0.0);
  const tubular = Math.max(8, n-1);
  const thick = (L.reason === 'reached_outlet');
  const geo = new THREE.TubeGeometry(curve, tubular, thick?0.30:0.16, 6, false);
  const col = new Float32Array(geo.attributes.position.count*3);
  geo.setAttribute('color', new THREE.BufferAttribute(col,3));
  const mat = new THREE.MeshBasicMaterial({vertexColors:true, transparent:true, opacity:0.98});
  const mesh = new THREE.Mesh(geo, mat);
  scene.add(mesh);
  tubes.push({mesh:mesh, meta:L, col:col, n:n, thick:thick});
});
function recolor(){
  const r = rangeMM(), a = r[0], b = r[1];
  tubes.forEach(function(t){
    const arr = (mode==='speed') ? t.meta.spd : t.meta.p;
    for (let i=0;i<t.n;i++){
      let v = (arr[Math.min(i,arr.length-1)] - a)/Math.max(1e-9,(b-a));
      v = Math.max(0, Math.min(1, v));
      const c = turbo(v);
      for (let j=0;j<7;j++){ const k = i*7+j; t.col[k*3]=c[0]; t.col[k*3+1]=c[1]; t.col[k*3+2]=c[2]; }
    }
    t.mesh.geometry.attributes.color.needsUpdate = true;
  });
}
function visibility(){
  const keep = parseInt(document.getElementById('rLines').value,10)/100;
  const showL = document.getElementById('cL').checked, showR = document.getElementById('cR').checked;
  const per = Math.max(1, Math.round(1/keep));
  tubes.forEach(function(t,i){
    t.mesh.visible = (t.meta.side==='L'?showL:showR) && (i % per === 0);
  });
}
recolor(); visibility();

/* ---------- mm 坐标尺 ---------- */
const B = META.bbox;   // {x:[min,max], y:[...], z:[...]}
const g = new THREE.Group(); scene.add(g);
const edgeMat = new THREE.LineBasicMaterial({color:0x8d9bab, transparent:true, opacity:0.75});
(function(){
  const p = [[B.x[0],B.y[0],B.z[0]],[B.x[1],B.y[0],B.z[0]],[B.x[1],B.y[1],B.z[0]],[B.x[0],B.y[1],B.z[0]],
             [B.x[0],B.y[0],B.z[1]],[B.x[1],B.y[0],B.z[1]],[B.x[1],B.y[1],B.z[1]],[B.x[0],B.y[1],B.z[1]]];
  const e = [[0,1],[1,2],[2,3],[3,0],[4,5],[5,6],[6,7],[7,4],[0,4],[1,5],[2,6],[3,7]];
  const pts = [];
  e.forEach(function(pair){ pts.push(...p[pair[0]], ...p[pair[1]]); });
  g.add(new THREE.LineSegments(new THREE.BufferGeometry().setAttribute('position',
    new THREE.Float32BufferAttribute(pts,3)), edgeMat));
  // 刻度短线
  const tickPts = [];
  const TX = 10, TY = 20, TZ = 10; // mm，y 轴跨度大故步长加倍，避免角部标签叠字
  function push(a,b){ tickPts.push(...a,...b); }
  for (let x=Math.ceil(B.x[0]/TX)*TX; x<=B.x[1]; x+=TX){ push([x,B.y[0],B.z[0]],[x,B.y[0]-2.2,B.z[0]]); }
  for (let y=Math.ceil(B.y[0]/TY)*TY; y<=B.y[1]; y+=TY){ push([B.x[0],y,B.z[0]],[B.x[0]-2.2,y,B.z[0]]); }
  for (let z=Math.ceil(B.z[0]/TZ)*TZ; z<=B.z[1]; z+=TZ){ push([B.x[0],B.y[0],z],[B.x[0]-2.2,B.y[0],z]); }
  g.add(new THREE.LineSegments(new THREE.BufferGeometry().setAttribute('position',
    new THREE.Float32BufferAttribute(tickPts,3)), edgeMat));
})();
function label(text, scale){
  const c = document.createElement('canvas'); c.width = 200; c.height = 56;
  const ctx = c.getContext('2d');
  ctx.font = '600 30px system-ui,"Microsoft YaHei",sans-serif';
  ctx.fillStyle = '#33414f'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText(text, 100, 30);
  const tex = new THREE.CanvasTexture(c);
  tex.minFilter = THREE.LinearFilter;
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({map:tex, transparent:true, depthTest:false}));
  sp.scale.set(scale, scale*0.28, 1);
  g.add(sp); return sp;
}
(function(){
  const TX = 10, TY = 20, TZ = 10, s = 5.6;
  for (let x=Math.ceil(B.x[0]/TX)*TX; x<=B.x[1]; x+=TX)
    label(String(x), s).position.set(x, B.y[0]-5.4, B.z[0]-1.2);
  for (let y=Math.ceil(B.y[0]/TY)*TY; y<=B.y[1]; y+=TY)
    label(String(y), s).position.set(B.x[0]-5.4, y, B.z[0]-1.2);
  for (let z=Math.ceil(B.z[0]/TZ)*TZ; z<=B.z[1]; z+=TZ)
    label(String(z), s).position.set(B.x[0]-5.4, B.y[0]-2.0, z);
  const ax = label('x (mm)', 7.4); ax.position.set((B.x[0]+B.x[1])/2, B.y[0]-11, B.z[0]-1.2);
  const ay = label('y (mm)', 7.4); ay.position.set(B.x[0]-11, (B.y[0]+B.y[1])/2, B.z[0]-1.2);
  const az = label('z (mm)', 7.4); az.position.set(B.x[0]-11, B.y[0]-2.0, (B.z[0]+B.z[1])/2);
})();

/* ---------- 相机：默认 = matplotlib azim=-60 / elev=30 / up=+z ---------- */
const c = META.center, R = META.radius;
let theta = -Math.PI/3, phi = Math.PI/3, dist = R*1.55;
let target = new THREE.Vector3(c[0], c[1], c[2]);
/* 拟合点集：壁面顶点（降采样）+ 全部流线点，相对中心；
   用实际几何投影而非包围盒角点——盒角是极值组合，会把长条状气道挤成斜带 */
const fitPts = [];
(function(){
  for (let i=0;i<WALL_POS.length;i+=3*7)
    fitPts.push(new THREE.Vector3(WALL_POS[i]-c[0], WALL_POS[i+1]-c[1], WALL_POS[i+2]-c[2]));
  LINE_DATA.forEach(function(L){
    const n = L.pos.length/3;
    for (let i=0;i<n;i+=2)
      fitPts.push(new THREE.Vector3(L.pos[i*3]-c[0], L.pos[i*3+1]-c[1], L.pos[i*3+2]-c[2]));
  });
})();
/* 按当前朝向把几何精确拟合进视口（考虑宽高比），避免模型出画或过小 */
function fitDistance(margin){
  const half = Math.tan(camera.fov*Math.PI/360);
  const asp = Math.max(0.2, camera.aspect);
  const pos = new THREE.Vector3(Math.sin(phi)*Math.cos(theta), Math.cos(phi), Math.sin(phi)*Math.sin(theta));
  const up = new THREE.Vector3(0,0,1);
  const xc = new THREE.Vector3().crossVectors(up, pos).normalize();
  const yc = new THREE.Vector3().crossVectors(pos, xc).normalize();
  let need = 0;
  fitPts.forEach(function(v){
    const x = Math.abs(v.dot(xc)), y = Math.abs(v.dot(yc)), z = v.dot(pos);
    need = Math.max(need, x/(half*asp) + z, y/half + z);
  });
  return need*margin;
}
function updateCam(){
  camera.position.set(target.x + dist*Math.sin(phi)*Math.cos(theta),
                      target.y + dist*Math.cos(phi),
                      target.z + dist*Math.sin(phi)*Math.sin(theta));
  camera.up.set(0,0,1);
  camera.lookAt(target);
}
let userZoomed = false;
function applyFit(){ dist = fitDistance(1.06); updateCam(); }
function resize(){
  const w = host.clientWidth, h = host.clientHeight;
  renderer.setSize(w,h,false); camera.aspect = w/Math.max(1,h); camera.updateProjectionMatrix();
  if(!userZoomed) applyFit();
}
window.addEventListener('resize', resize); resize(); updateCam(); applyFit();

let drag = null, px = 0, py = 0, spinning = false;
const el = renderer.domElement;
el.addEventListener('pointerdown', function(e){ drag = (e.button===2)?'pan':'rot'; px=e.clientX; py=e.clientY; el.setPointerCapture(e.pointerId); });
el.addEventListener('pointerup', function(){ drag = null; });
el.addEventListener('pointermove', function(e){
  if(!drag) return;
  const dx = e.clientX-px, dy = e.clientY-py; px=e.clientX; py=e.clientY;
  if(drag==='rot'){ theta -= dx*0.006; phi = Math.max(0.05, Math.min(Math.PI-0.05, phi - dy*0.006)); }
  else { const s = dist*0.0016; target.x += dx*s; target.z += dy*s; }
  updateCam();
});
el.addEventListener('contextmenu', function(e){ e.preventDefault(); });
el.addEventListener('wheel', function(e){ e.preventDefault();
  userZoomed = true;
  dist = Math.max(R*0.35, Math.min(R*9, dist*Math.exp(e.deltaY*0.0012))); updateCam(); }, {passive:false});

function setView(n){
  if(n==='persp'){ theta=-Math.PI/3; phi=Math.PI/3; }
  if(n==='front'){ theta=-Math.PI/2; phi=Math.PI/2; }
  if(n==='side'){ theta=0; phi=Math.PI/2; }
  if(n==='top'){ theta=-Math.PI/2; phi=0.03; }
  userZoomed = false;   // 视角切换即回到自动拟合，保证新朝向下模型完整入画
  applyFit();
}
const btns = {bPersp:'persp', bFront:'front', bSide:'side', bTop:'top'};
Object.keys(btns).forEach(function(id){
  document.getElementById(id).addEventListener('click', function(){
    Object.keys(btns).forEach(function(k){ document.getElementById(k).classList.remove('on'); });
    document.getElementById(id).classList.add('on'); setView(btns[id]);
  });
});
document.getElementById('bSpin').addEventListener('click', function(e){ spinning=!spinning; e.target.classList.toggle('on', spinning); });
document.getElementById('bSpeed').addEventListener('click', function(){ mode='speed';
  this.classList.add('on'); document.getElementById('bPress').classList.remove('on'); recolor(); applyRange(); });
document.getElementById('bPress').addEventListener('click', function(){ mode='press';
  this.classList.add('on'); document.getElementById('bSpeed').classList.remove('on'); recolor(); applyRange(); });
document.getElementById('cWall').addEventListener('change', function(e){ wall.visible = e.target.checked; });
document.getElementById('cAxis').addEventListener('change', function(e){ g.visible = e.target.checked; });
document.getElementById('cOut').addEventListener('change', function(){
  const on = this.checked;
  tubes.forEach(function(t){ t.mesh.material.opacity = (on && t.thick) ? 1.0 : 0.96; });
});
document.getElementById('rOpacity').addEventListener('input', function(e){ wall.material.opacity = parseInt(e.target.value,10)/100; });
document.getElementById('rLines').addEventListener('input', visibility);
document.getElementById('cL').addEventListener('change', visibility);
document.getElementById('cR').addEventListener('change', visibility);
function applyRange(){
  const r = rangeMM();
  document.getElementById('lgMin').textContent = (Math.round(r[0]*100)/100)+'';
  document.getElementById('lgMax').textContent = (Math.round(r[1]*100)/100)+'';
  document.getElementById('cbarTitle').textContent = (mode==='speed') ? '速度 |U| (m/s)' : '静压 p (Pa, ×1.2 kg/m³)';
}
applyRange();

/* ---------- 长度分布直方图（与静态图同口径） ---------- */
(function(){
  const cv = document.getElementById('hist');
  const ctx = cv.getContext('2d');
  const W = cv.width = 268, H = cv.height = 132;
  const lens = LINE_DATA.map(function(L){ return L.length_mm; });
  const vmin = 0, vmax = Math.ceil(Math.max.apply(null, lens)/20)*20;
  const bins = 18, w = (vmax-vmin)/bins;
  const cnt = new Array(bins).fill(0);
  lens.forEach(function(v){ cnt[Math.min(bins-1, Math.floor((v-vmin)/w))]++; });
  const cmax = Math.max.apply(null, cnt);
  ctx.clearRect(0,0,W,H);
  ctx.fillStyle = '#3b6ea5';
  const bw = W/bins;
  for (let i=0;i<bins;i++){
    const h = (H-18)*cnt[i]/cmax;
    ctx.fillRect(i*bw+1, H-14-h, bw-2, h);
  }
  ctx.strokeStyle = '#9aa7b4'; ctx.beginPath(); ctx.moveTo(0,H-13.5); ctx.lineTo(W,H-13.5); ctx.stroke();
  ctx.fillStyle = '#5c6b7a'; ctx.font = '10px system-ui,"Microsoft YaHei",sans-serif';
  ctx.fillText('0', 2, H-3); ctx.textAlign='right'; ctx.fillText(String(vmax)+' mm', W-2, H-3); ctx.textAlign='left';
  ctx.fillText(String(cmax), 2, 10);
})();

(function animate(){
  requestAnimationFrame(animate);
  if(spinning){ theta += 0.004; updateCam(); }
  renderer.render(scene, camera);
})();
})();
