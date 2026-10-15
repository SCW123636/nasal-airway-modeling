# -*- coding: utf-8 -*-
"""
T-045 · Web 版流场可视化：对齐静态 3D 透视图风格

输入（只读）：outputs/T-044/{field.npz, streamlines.npz, trace_meta.json, three.min.js}
输出（本卡）：outputs/T-045/鼻腔气流可视化_web_v2.html

与 T-044 版的差异（全部为呈现层，数据零改动）：
  1. 默认取景 = matplotlib 3D 的 azim=-60° / elev=30° / up=+z，模型撑满视口；
  2. 画出 mm 坐标尺（包围盒线框 + 三轴 10 mm 刻度 + 轴标签 + 刻度数值）；
  3. 流线由 1px 线改为管状几何（WebGL linewidth 被忽略），抵达出口组更粗；
  4. 侧栏补流线长度分布直方图 + patch 图例（与静态图信息对齐）。
"""
import base64
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "T-044")

THREE_JS = open(os.path.join(SRC, "three.min.js"), encoding="utf-8").read()


def b64(a):
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode("ascii")


def load():
    f = np.load(os.path.join(SRC, "field.npz"))
    s = np.load(os.path.join(SRC, "streamlines.npz"))
    meta = json.load(open(os.path.join(SRC, "trace_meta.json"), encoding="utf-8"))
    n = sum(1 for k in s.files if k.startswith("line_"))
    lines = []
    for i in range(n):
        lines.append({
            "side": meta["lines"][i]["side"],
            "reason": meta["lines"][i]["reason"],
            "length_mm": meta["lines"][i]["length_mm"],
            "pts": s[f"line_{i:03d}"],
            "spd": s[f"spd_{i:03d}"],
            "p": s[f"pPa_{i:03d}"],
        })
    return f, lines, meta


APP = r"""
(function(){
const {LINE_DATA, WALL_POS, WALL_IDX, PATCH, META} = DATA;
const host = document.getElementById('view');
const scene = new THREE.Scene();
scene.background = new THREE.Color(0xeef2f7);
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
"""


def build():
    f, lines, meta = load()
    wall_pos = (f["wall_pts"] * 1000.0).astype(np.float32).reshape(-1)
    wall_tri = f["wall_tri"].astype(np.uint32).reshape(-1)
    nl_pos = (f["nl_pts"] * 1000.0).astype(np.float32).reshape(-1); nl_tri = f["nl_tri"].astype(np.uint32).reshape(-1)
    nr_pos = (f["nr_pts"] * 1000.0).astype(np.float32).reshape(-1); nr_tri = f["nr_tri"].astype(np.uint32).reshape(-1)
    out_pos = (f["out_pts"] * 1000.0).astype(np.float32).reshape(-1); out_tri = f["out_tri"].astype(np.uint32).reshape(-1)

    allpts = np.concatenate([l["pts"] for l in lines] + [f["wall_pts"] * 1000.0])
    bmin, bmax = allpts.min(axis=0), allpts.max(axis=0)
    center = ((bmax + bmin) / 2).tolist()
    radius = float(np.linalg.norm(bmax - bmin) / 2)

    allspd = np.concatenate([l["spd"] for l in lines])
    allp = np.concatenate([l["p"] for l in lines])

    def line_js(l):
        return ('{side:%s,reason:%s,length_mm:%s,'
                'pos:new Float32Array(U8("%s").buffer),'
                'spd:new Float32Array(U8("%s").buffer),'
                'p:new Float32Array(U8("%s").buffer)}'
                % (json.dumps(l["side"]), json.dumps(l["reason"]), l["length_mm"],
                   b64(l["pts"].astype(np.float32)), b64(l["spd"].astype(np.float32)),
                   b64(l["p"].astype(np.float32))))

    def u32(a):
        return 'new Uint32Array(U8("%s").buffer)' % base64.b64encode(np.ascontiguousarray(a).tobytes()).decode("ascii")

    def f32s(a):
        return 'new Float32Array(U8("%s").buffer)' % b64(a)

    data = ("(function(){function U8(s){const b=atob(s);const u=new Uint8Array(b.length);"
            "for(let i=0;i<b.length;i++)u[i]=b.charCodeAt(i);return u;}"
            "return {"
            "LINE_DATA:[%s],"
            "WALL_POS:%s, WALL_IDX:%s,"
            "PATCH:{nl_pos:%s,nl_idx:%s,nr_pos:%s,nr_idx:%s,out_pos:%s,out_idx:%s},"
            "META:{spd_p2:%s,spd_max:%s,p_p2:%s,p_max:%s,center:%s,radius:%s,"
            "bbox:{x:[%s,%s],y:[%s,%s],z:[%s,%s]}}};})()"
            % (",".join(line_js(l) for l in lines),
               f32s(wall_pos), u32(wall_tri),
               f32s(nl_pos), u32(nl_tri), f32s(nr_pos), u32(nr_tri), f32s(out_pos), u32(out_tri),
               repr(float(np.percentile(allspd, 2))), repr(float(allspd.max())),
               repr(float(np.percentile(allp, 2))), repr(float(allp.max())),
               json.dumps(center), repr(radius),
               repr(round(float(bmin[0]), 1)), repr(round(float(bmax[0]), 1)),
               repr(round(float(bmin[1]), 1)), repr(round(float(bmax[1]), 1)),
               repr(round(float(bmin[2]), 1)), repr(round(float(bmax[2]), 1))))

    reasons = meta["reasons"]
    n_reach = reasons.get("reached_outlet", 0)
    table = "".join([
        "<tr><th>来源</th><td><code>t004_diag</code> time=400（真实 U/p 场）</td></tr>",
        "<tr><th>网格</th><td>1,161,194 四面体 / 229,033 节点</td></tr>",
        "<tr><th>工况</th><td>双鼻孔各 1.25e-4 m³/s（15 L/min），出口 p=0 gauge</td></tr>",
        "<tr><th>进口面平均静压</th><td>左 8.85 Pa / 右 11.74 Pa（均值 10.29 Pa）</td></tr>",
        "<tr><th>质量不平衡</th><td>≈ 1.1e-6（相对）</td></tr>",
        "<tr><th>流线</th><td>%d 条（每侧 60 种子）</td></tr>" % len(lines),
        "<tr><th>抵达鼻咽出口</th><td>%d 条（占 %d%%）</td></tr>" % (n_reach, round(n_reach / len(lines) * 100)),
        "<tr><th>沿流线速度</th><td>%.3f – %.3f m/s（中位 %.2f）</td></tr>" % (allspd.min(), allspd.max(), float(np.median(allspd))),
        "<tr><th>收敛状态</th><td>未达 residualControl（numerical_validation: unchecked）</td></tr>",
        "<tr><th>临床状态</th><td>generalisation_test_only_no_human_review</td></tr>",
    ])

    html = TEMPLATE.replace("__THREEJS__", THREE_JS).replace("__DATA__", data) \
                   .replace("__APP__", APP).replace("__TABLE__", table) \
                   .replace("__NLINES__", str(len(lines))) \
                   .replace("__NREACH__", str(n_reach)) \
                   .replace("__PCT__", str(round(n_reach / len(lines) * 100)))
    out = os.path.join(HERE, "鼻腔气流可视化_web_v2.html")
    with open(out, "w", encoding="utf-8") as fp:
        fp.write(html)
    print("写出", out, os.path.getsize(out) // 1024, "KB")


TEMPLATE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>鼻腔气流可视化 · 真实 CFD 流场（time=400，未收敛）</title>
<style>
:root{--bg:#f4f6f9;--panel:#fff;--line:#d8dee7;--ink:#1d2733;--muted:#5c6b7a;--accent:#2f6fb0}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
 font-family:system-ui,"Microsoft YaHei",sans-serif;font-size:14px}
header{padding:14px 18px 6px}
h1{font-size:19px;margin:0 0 4px}
.sub{color:var(--muted);font-size:12.5px;line-height:1.6}
.warn{margin:10px 18px 0;border-left:4px solid #e8913c;background:#fff5e9;padding:10px 12px;
 border-radius:6px;font-size:12.5px;line-height:1.7}
#wrap{display:flex;gap:12px;padding:12px 18px 18px;align-items:flex-start;flex-wrap:wrap}
#view{flex:1 1 640px;min-width:360px;height:min(74vh,760px);background:#eef2f7;
 border:1px solid var(--line);border-radius:8px;position:relative}
aside{flex:0 0 320px;min-width:280px;background:var(--panel);border:1px solid var(--line);
 border-radius:8px;padding:12px 14px}
aside h2{font-size:14px;margin:0 0 8px}
.row{display:flex;gap:8px;align-items:center;margin:7px 0;flex-wrap:wrap}
button{background:#fff;border:1px solid var(--line);border-radius:6px;padding:5px 9px;cursor:pointer;
 font-size:12.5px;color:var(--ink)}
button.on{background:var(--accent);color:#fff;border-color:var(--accent)}
label.sw{display:flex;gap:6px;align-items:center;font-size:12.5px;cursor:pointer}
input[type=range]{width:100%}
table{border-collapse:collapse;width:100%;font-size:12px}
td,th{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600}
.bar{height:12px;border-radius:6px;margin:6px 0 2px}
.legend{display:flex;justify-content:space-between;font-size:11.5px;color:var(--muted)}
.note{font-size:11.5px;color:var(--muted);line-height:1.65;margin-top:8px}
.swatches{display:flex;gap:12px;flex-wrap:wrap;font-size:12px;margin:4px 0 2px}
.sw{display:flex;gap:5px;align-items:center}
.sw i{width:11px;height:11px;border-radius:2px;display:inline-block}
#hist{display:block;width:100%;height:auto;background:#fbfcfe;border:1px solid var(--line);border-radius:6px}
.hcap{font-size:11.5px;color:var(--muted);margin:2px 0 4px}
</style></head><body>
<header>
<h1>鼻腔气流可视化 · 真实 CFD 流场（并非示意图）</h1>
<div class="sub">数据来源：WSL <code>/home/lenovo2/patient_cfd/t004_diag</code>，time index <b>400</b> ——
simpleFoam 真实迭代写出的 U / p 场，经 <code>foamToVTK</code> 导出后追踪流线。
几何 = 患者体网格 <code>b15_patient_maxh1_repaired.msh</code>（1,161,194 四面体单元）。</div>
</header>
<div class="warn"><b>诚实声明（务必先读）</b><br>
① 该次跑<b>未达 residualControl 收敛</b>（<code>numerical_validation: unchecked</code>），
Δp 稳态等业务判据尚不成立，此图<b>只能用于看流动形态，不能用于临床结论</b>；<br>
② 绘图的插值方式是「定位点所在四面体后按重心坐标线性插值」，<b>可视化级</b>，
不等于 OpenFOAM 的定量后处理；定量数字以 postProcessing 的 <code>surfaceFieldValue</code> 为准；<br>
③ 未见人体复核：<code>clinical_status: generalisation_test_only_no_human_review</code>；
几何未过 N6 解剖门，鼻腔内结构归属未经医生复核；<br>
④ 坐标尺为<b>求解器坐标</b>（mm），未做 LPS/解剖方位归位核验 —— 图中 x/y/z 的刻度不等于「左右/前后/上下」，
仅用于读数与量纲参照。</div>
<div id="wrap">
  <div id="view"></div>
  <aside>
    <h2>显示控制</h2>
    <div class="row">
      <button id="bPersp" class="on">透视</button>
      <button id="bFront">正视</button>
      <button id="bSide">侧视</button>
      <button id="bTop">俯视</button>
      <button id="bSpin">自动旋转</button>
    </div>
    <div class="row">
      <button id="bSpeed" class="on">按速度着色</button>
      <button id="bPress">按静压着色</button>
    </div>
    <div class="row">
      <label class="sw"><input type="checkbox" id="cWall" checked>壁面</label>
      <label class="sw"><input type="checkbox" id="cAxis" checked>坐标尺</label>
      <label class="sw"><input type="checkbox" id="cL" checked>左</label>
      <label class="sw"><input type="checkbox" id="cR" checked>右</label>
      <label class="sw"><input type="checkbox" id="cOut" checked>出口加粗</label>
    </div>
    <div class="row">壁面不透明度 <input type="range" id="rOpacity" min="2" max="60" value="20"></div>
    <div class="row">显示流线比例 <input type="range" id="rLines" min="10" max="100" value="100"></div>
    <div class="bar" id="bar"></div>
    <div class="legend"><span id="lgMin"></span><span id="cbarTitle">速度 |U| (m/s)</span><span id="lgMax"></span></div>
    <div class="swatches">
      <span class="sw"><i style="background:#d62728"></i>左鼻孔</span>
      <span class="sw"><i style="background:#1f77b4"></i>右鼻孔</span>
      <span class="sw"><i style="background:#2ca02c"></i>鼻咽出口</span>
      <span class="sw"><i style="background:#8d9bab"></i>坐标尺(mm)</span>
    </div>
    <h2 style="margin-top:12px">流线在腔内的长度分布</h2>
    <div class="hcap">与静态图同口径：共 __NLINES__ 条，抵达鼻咽出口 __NREACH__ 条（占 __PCT__%）；纵轴=条数。</div>
    <canvas id="hist"></canvas>
    <h2 style="margin-top:12px">本次读数（真实数值）</h2>
    <table>__TABLE__</table>
    <div class="note">操作：左键拖动旋转，滚轮缩放，右键/双指拖动平移。<br>
    流线追踪：RK4 单位速度场积分，步长 0.30 mm；种子取两侧鼻孔面各 60 个（最远点采样）。<br>
    本页为 T-045（呈现层对齐静态透视图）；数据与 T-044 完全一致，未重算。</div>
  </aside>
</div>
<script>__THREEJS__</script>
<script>const DATA = __DATA__;</script>
<script>__APP__</script>
</body></html>
"""

if __name__ == "__main__":
    build()
