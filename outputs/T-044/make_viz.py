# -*- coding: utf-8 -*-
"""
T-042 · 由真实流线数据生成：① 静态 PNG 图  ② 单文件交互式 HTML（内嵌 three.js 与全部数据）

输入：field.npz（网格/壁面/patch）、streamlines.npz（真实追踪结果）、trace_meta.json
输出：outputs/T-042/静态图_流线三视图.png、静态图_速度分布.png、鼻腔气流可视化.html
"""
import base64
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

CN = {"L": "左鼻孔", "R": "右鼻孔"}


def b64(arr):
    return base64.b64encode(np.ascontiguousarray(arr).tobytes()).decode("ascii")


def load():
    f = np.load(os.path.join(HERE, "field.npz"))
    s = np.load(os.path.join(HERE, "streamlines.npz"))
    with open(os.path.join(HERE, "trace_meta.json"), encoding="utf-8") as fp:
        meta = json.load(fp)
    n = sum(1 for k in s.files if k.startswith("line_"))
    lines = []
    for i in range(n):
        lm = meta["lines"][i]
        lines.append({
            "side": lm["side"], "reason": lm["reason"], "length_mm": lm["length_mm"],
            "seed_mm": lm["seed_mm"],
            "pts": s[f"line_{i:03d}"], "spd": s[f"spd_{i:03d}"], "pPa": s[f"pPa_{i:03d}"],
        })
    return f, lines, meta


def make_static(f, lines, meta):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    from matplotlib.cm import ScalarMappable
    from matplotlib.colors import Normalize

    matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DengXian", "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False

    allspd = np.concatenate([l["spd"] for l in lines])
    vmin, vmax = float(allspd.min()), float(np.percentile(allspd, 98))
    cmap = plt.get_cmap("turbo")
    norm = Normalize(vmin=vmin, vmax=vmax)

    wall = f["wall_pts"] * 1000.0

    fig = plt.figure(figsize=(15.5, 6.6))
    fig.suptitle("鼻腔气流流线（真实 simpleFoam 解，time index = 400，未达残差收敛）", fontsize=14)
    views = [("x-y", 0, 1, "俯视：x-y"), ("y-z", 1, 2, "正向：y-z"), ("x-z", 0, 2, "侧向：x-z")]
    for ax_i, (nm, a, b, title) in enumerate(views, start=1):
        ax = fig.add_subplot(1, 3, ax_i)
        ax.scatter(wall[:, a], wall[:, b], s=0.25, c="#cdd6df", alpha=0.55, linewidths=0)
        for l in lines:
            P = l["pts"]
            segs = np.stack([P[:-1, [a, b]], P[1:, [a, b]]], axis=1)
            lc = LineCollection(segs, cmap=cmap, norm=norm, linewidths=0.9, alpha=0.95)
            lc.set_array(0.5 * (l["spd"][:-1] + l["spd"][1:]))
            ax.add_collection(lc)
        # 边界 patch 投影
        for key, col, lab in (("nl_pts", "#d62728", "左鼻孔"), ("nr_pts", "#1f77b4", "右鼻孔"),
                              ("out_pts", "#2ca02c", "鼻咽出口")):
            Q = f[key] * 1000.0
            ax.scatter(Q[:, a], Q[:, b], s=1.2, c=col, label=lab, alpha=0.8)
        ax.autoscale_view()
        ax.set_aspect("equal")
        ax.set_title(title, fontsize=11)
        ax.set_xlabel(f"{'xyz'[a]} (mm)")
        ax.set_ylabel(f"{'xyz'[b]} (mm)")
        if ax_i == 1:
            ax.legend(fontsize=8, loc="upper right", markerscale=3)
    cb = fig.colorbar(ScalarMappable(norm=norm, cmap=cmap), ax=fig.axes, shrink=0.82, pad=0.02)
    cb.set_label("速度 |U| (m/s)")
    out = os.path.join(HERE, "静态图_流线三视图.png")
    fig.savefig(out, dpi=155, bbox_inches="tight")
    plt.close(fig)
    print("写出", out, flush=True)

    # 第二张：透视 + 到达出口的流线高亮 + 长度分布
    fig2 = plt.figure(figsize=(13.0, 5.4))
    ax = fig2.add_subplot(1, 2, 1, projection="3d")
    reached = [l for l in lines if l["reason"] == "reached_outlet"]
    others = [l for l in lines if l["reason"] != "reached_outlet"]
    for l, alpha in ((others, 0.55), (reached, 1.0)):
        for ln in l:
            P = ln["pts"]
            for k in range(len(P) - 1):
                c = cmap(norm(0.5 * (ln["spd"][k] + ln["spd"][k + 1])))
                ax.plot([P[k, 0], P[k + 1, 0]], [P[k, 1], P[k + 1, 1]], [P[k, 2], P[k + 1, 2]],
                        color=c, linewidth=1.0 if ln["reason"] == "reached_outlet" else 0.7,
                        alpha=alpha)
    try:
        for key, col, lab in (("nl_pts", "#d62728", "左鼻孔"), ("nr_pts", "#1f77b4", "右鼻孔"),
                              ("out_pts", "#2ca02c", "鼻咽出口")):
            Q = f[key] * 1000.0
            ax.scatter(Q[:, 0], Q[:, 1], Q[:, 2], s=2.0, c=col, label=lab)
    except Exception as e:
        print("patch 绘制异常:", e, flush=True)
    ax.set_title("三维透视图（加粗=抵达鼻咽出口）", fontsize=11)
    ax.set_xlabel("x (mm)"); ax.set_ylabel("y (mm)"); ax.set_zlabel("z (mm)")
    ax.legend(fontsize=8)

    ax2 = fig2.add_subplot(1, 2, 2)
    lv = [l["length_mm"] for l in lines]
    ax2.hist(lv, bins=18, color="#3b6ea5", alpha=0.85)
    ax2.set_xlabel("流线在腔内的长度 (mm)")
    ax2.set_ylabel("条数")
    ax2.set_title(f"共 {len(lines)} 条种子流线；抵达出口 {len(reached)} 条，占 {len(reached)/max(1,len(lines))*100:.0f}%", fontsize=11)
    out2 = os.path.join(HERE, "静态图_透视与长度分布.png")
    fig2.savefig(out2, dpi=150, bbox_inches="tight")
    plt.close(fig2)
    print("写出", out2, flush=True)


HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>鼻腔气流可视化 · 真实 simpleFoam 流场（time=400）</title>
<style>
:root{--bg:#f4f6f9;--panel:#ffffff;--line:#d8dee7;--ink:#1d2733;--muted:#5c6b7a;--accent:#2f6fb0}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
 font-family:system-ui,"Microsoft YaHei",sans-serif;font-size:14px}
header{padding:14px 18px 6px}
h1{font-size:19px;margin:0 0 4px}
.sub{color:var(--muted);font-size:12.5px;line-height:1.6}
.warn{margin:10px 18px 0;border-left:4px solid #e8913c;background:#fff5e9;padding:10px 12px;border-radius:6px;font-size:12.5px;line-height:1.7}
#wrap{display:flex;gap:12px;padding:12px 18px 18px;align-items:flex-start;flex-wrap:wrap}
#view{flex:1 1 620px;min-width:340px;height:min(72vh,720px);background:#e9eef4;border:1px solid var(--line);border-radius:8px;position:relative}
aside{flex:0 0 310px;min-width:270px;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px 14px}
aside h2{font-size:14px;margin:0 0 8px}
.row{display:flex;gap:8px;align-items:center;margin:7px 0;flex-wrap:wrap}
button{background:#fff;border:1px solid var(--line);border-radius:6px;padding:5px 9px;cursor:pointer;font-size:12.5px;color:var(--ink)}
button.on{background:var(--accent);color:#fff;border-color:var(--accent)}
label.sw{display:flex;gap:6px;align-items:center;font-size:12.5px;cursor:pointer}
input[type=range]{width:100%}
table{border-collapse:collapse;width:100%;font-size:12px}
td,th{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600}
.bar{height:12px;border-radius:6px;margin:6px 0 2px;background:linear-gradient(90deg,__GRAD__)}
.legend{display:flex;justify-content:space-between;font-size:11.5px;color:var(--muted)}
.note{font-size:11.5px;color:var(--muted);line-height:1.65;margin-top:8px}
kbd{background:#eef2f7;border:1px solid var(--line);border-radius:4px;padding:0 4px;font-size:11px}
</style></head><body>
<header>
<h1>鼻腔气流可视化 · 真实 CFD 解（并非示意图）</h1>
<div class="sub">数据来源：WSL <code>/home/lenovo2/patient_cfd/t004_diag</code>，time index <b>400</b>（simpleFoam 真实迭代写出的 U / p 场，
由 <code>foamToVTK</code> 导出后追踪流线）。几何 = 患者体网格 <code>b15_patient_maxh1_repaired.msh</code>（1,161,194 四面体单元）。</div>
</header>
<div class="warn"><b>诚实声明（务必先读）</b><br>
① 该次跑<b>未达 residualControl 收敛</b>（<code>numerical_validation: unchecked</code>），Δp 稳态等业务判据尚不成立，此图<b>只能用于看流动形态，不能用于临床结论</b>；<br>
② 绘图的插值方式是「定位点所在四面体后按重心坐标线性插值」，<b>可视化级</b>，不等于 OpenFOAM 的定量后处理；定量数字请以 postProcessing 的 <code>surfaceFieldValue</code> 为准；<br>
③ 未见utting gest human review：<code>clinical_status: generalisation_test_only_no_human_review</code>；几何未过 N6 解剖门放行，<b>鼻腔内结构归属未由医生复核</b>；<br>
④ 坐标系沿用求解器坐标（mm），<b>未做 LPS/解剖方位归位核验</b>，图中 x/y/z 不等于「左右/前后/上下」。</div>
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
      <label class="sw"><input type="checkbox" id="cL" checked>左侧流线</label>
      <label class="sw"><input type="checkbox" id="cR" checked>右侧流线</label>
      <label class="sw"><input type="checkbox" id="cOut" checked>抵达出口加粗</label>
    </div>
    <div class="row">壁面不透明度 <input type="range" id="rOpacity" min="2" max="60" value="16"></div>
    <div class="row">显示流线比例 <input type="range" id="rLines" min="10" max="100" value="100"></div>
    <div class="bar" id="bar"></div>
    <div class="legend"><span id="lgMin"></span><span id="cbarTitle">速度 |U| (m/s)</span><span id="lgMax"></span></div>
    <h2 style="margin-top:14px">本次读数（真实数值）</h2>
    <table>__TABLE__</table>
    <div class="note">操作：左键拖动旋转，滚轮缩放，右键/双指拖动平移。<br>
    流线追踪：RK4 单位速度场积分，步长 0.30 mm；种子取两侧鼻孔面 __NSEED__ 个/侧。</div>
  </aside>
</div>
<script>__THREEJS__</script>
<script>
const DATA = __DATA__;
</script>
<script>__APP__</script>
</body></html>
"""


APP_JS = """
(function(){
const {LINE_DATA, WALL_POS, WALL_IDX, PATCH} = DATA;
const host = document.getElementById('view');
const scene = new THREE.Scene();
scene.background = new THREE.Color(0xe9eef4);
const camera = new THREE.PerspectiveCamera(45, 1, 0.5, 5000);
const renderer = new THREE.WebGLRenderer({antialias:true});
renderer.setPixelRatio(Math.min(2, window.devicePixelRatio||1));
host.appendChild(renderer.domElement);

scene.add(new THREE.AmbientLight(0xffffff, 0.75));
const dl = new THREE.DirectionalLight(0xffffff, 0.55); dl.position.set(1,1,1); scene.add(dl);
const dl2 = new THREE.DirectionalLight(0xffffff, 0.25); dl2.position.set(-1,-0.6,-1); scene.add(dl2);

// 壁面
const wg = new THREE.BufferGeometry();
wg.setAttribute('position', new THREE.BufferAttribute(WALL_POS, 3));
wg.setIndex(new THREE.BufferAttribute(WALL_IDX, 1));
wg.computeVertexNormals();
const wmat = new THREE.MeshPhongMaterial({color:0xb9c7d8, transparent:true, opacity:0.16,
  side:THREE.DoubleSide, depthWrite:false, shininess:18});
const wall = new THREE.Mesh(wg, wmat); scene.add(wall);

// patch
function patchMesh(pos, idx, color, op){
  const g=new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos,3));
  g.setIndex(new THREE.BufferAttribute(idx,1)); g.computeVertexNormals();
  const m=new THREE.MeshPhongMaterial({color:color, transparent:true, opacity:op, side:THREE.DoubleSide});
  const mesh=new THREE.Mesh(g,m); scene.add(mesh); return mesh;
}
patchMesh(PATCH.nl_pos, PATCH.nl_idx, 0xd62728, 0.9);
patchMesh(PATCH.nr_pos, PATCH.nr_idx, 0x1f77b4, 0.9);
patchMesh(PATCH.out_pos, PATCH.out_idx, 0x2ca02c, 0.55);

// 色标
function turbo(t){ // 近似 turbo 色带
  t = Math.max(0, Math.min(1, t));
  const stops = [[0.19,0.07,0.23],[0.28,0.35,0.85],[0.15,0.72,0.90],[0.25,0.93,0.55],
                 [0.72,0.95,0.20],[0.99,0.75,0.10],[0.98,0.42,0.10],[0.80,0.12,0.10],[0.48,0.05,0.09]];
  const x = t*(stops.length-1); const i = Math.floor(x); const f = x-i;
  const a = stops[i]; const b = stops[Math.min(stops.length-1,i+1)];
  return [a[0]+(b[0]-a[0])*f, a[1]+(b[1]-a[1])*f, a[2]+(b[2]-a[2])*f];
}
document.getElementById('bar').style.background = 'linear-gradient(90deg,' +
  Array.from({length:24},(_,i)=>'rgb('+turbo(i/23).map(v=>Math.round(v*255)).join(',')+')').join(',') + ')';

const V = DATA.META;
let mode = 'speed';
function rangeMinMax(){
  if(mode==='speed'){ return [V.spd_p2, V.spd_max]; }
  return [V.p_p2, V.p_max];
}
function applyRange(){
  const [a,b] = rangeMinMax();
  document.getElementById('lgMin').textContent = (Math.round(a*100)/100)+'';
  document.getElementById('lgMax').textContent = (Math.round(b*100)/100)+'';
  document.getElementById('cbarTitle').textContent = (mode==='speed'?'速度 |U| (m/s)':'静压 p (Pa, ×1.2 kg/m³ 换算)');
}
// 流线
const lines = [];
LINE_DATA.forEach(function(L, li){
  const n = L.pos.length/3;
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(L.pos, 3));
  const cols = new Float32Array(n*3); g.setAttribute('color', new THREE.BufferAttribute(cols,3));
  const mat = new THREE.LineBasicMaterial({vertexColors:true, transparent:true, opacity:0.95});
  const obj = new THREE.Line(g, mat);
  scene.add(obj);
  lines.push({obj:obj, meta:L, colors:cols, n:n});
});
function recolor(){
  const [a,b] = rangeMinMax();
  lines.forEach(function(rec){
    const arr = (mode==='speed') ? rec.meta.spd : rec.meta.p;
    const c = rec.colors;
    for(let i=0;i<rec.n;i++){
      let t = (arr[i]-a)/Math.max(1e-9,(b-a)); t=Math.max(0,Math.min(1,t));
      const rgb = turbo(t); c[i*3]=rgb[0]; c[i*3+1]=rgb[1]; c[i*3+2]=rgb[2];
    }
    rec.obj.geometry.attributes.color.needsUpdate = true;
  });
}
function visibility(){
  let keep = parseInt(document.getElementById('rLines').value,10)/100;
  const showL = document.getElementById('cL').checked, showR = document.getElementById('cR').checked;
  const per = Math.max(1, Math.round(1/keep));
  lines.forEach(function(rec, i){
    let vis = (rec.meta.side==='L'?showL:showR) && (i % per === 0);
    rec.obj.visible = vis;
  });
}
recolor(); applyRange(); visibility();

// 相机
const c = DATA.META.center, r = DATA.META.radius;
let theta = 0.9, phi = 1.15, dist = r*2.6, target = new THREE.Vector3(c[0],c[1],c[2]);
function updateCam(){
  camera.position.set(target.x + dist*Math.sin(phi)*Math.cos(theta),
                      target.y + dist*Math.cos(phi),
                      target.z + dist*Math.sin(phi)*Math.sin(theta));
  camera.up.set(0,0,1); camera.lookAt(target);
}
function resize(){
  const w = host.clientWidth, h = host.clientHeight;
  renderer.setSize(w,h,false); camera.aspect = w/Math.max(1,h); camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize); resize(); updateCam();

// 交互
let drag=null, px=0, py=0, spinning=false;
const el = renderer.domElement;
el.addEventListener('pointerdown', e=>{drag = e.button===2?'pan':'rot'; px=e.clientX; py=e.clientY; el.setPointerCapture(e.pointerId);});
el.addEventListener('pointerup', e=>{drag=null;});
el.addEventListener('pointermove', e=>{
  if(!drag) return;
  const dx = e.clientX-px, dy = e.clientY-py; px=e.clientX; py=e.clientY;
  if(drag==='rot'){ theta -= dx*0.006; phi = Math.max(0.05, Math.min(Math.PI-0.05, phi - dy*0.006)); }
  else { const s = dist*0.0015; target.x += dx*s; target.z += dy*s; }
  updateCam();
});
el.addEventListener('contextmenu', e=>e.preventDefault());
el.addEventListener('wheel', e=>{ e.preventDefault(); dist = Math.max(r*0.4, Math.min(r*8, dist*Math.exp(e.deltaY*0.0012))); updateCam(); }, {passive:false});

function setView(name){
  if(name==='persp'){ theta=0.9; phi=1.15; }
  if(name==='front'){ theta=Math.PI/2; phi=Math.PI/2; }
  if(name==='side'){ theta=0; phi=Math.PI/2; }
  if(name==='top'){ theta=Math.PI/2; phi=0.02; }
  updateCam();
}
const btns = {bPersp:'persp', bFront:'front', bSide:'side', bTop:'top'};
Object.keys(btns).forEach(id=>{
  document.getElementById(id).addEventListener('click', ()=>{
    Object.keys(btns).forEach(k=>document.getElementById(k).classList.remove('on'));
    document.getElementById(id).classList.add('on'); setView(btns[id]);
  });
});
document.getElementById('bSpin').addEventListener('click', e=>{ spinning=!spinning; e.target.classList.toggle('on', spinning); });
document.getElementById('bSpeed').addEventListener('click', ()=>{ mode='speed';
  document.getElementById('bSpeed').classList.add('on'); document.getElementById('bPress').classList.remove('on'); recolor(); applyRange(); });
document.getElementById('bPress').addEventListener('click', ()=>{ mode='press';
  document.getElementById('bPress').classList.add('on'); document.getElementById('bSpeed').classList.remove('on'); recolor(); applyRange(); });
document.getElementById('cWall').addEventListener('change', e=>{ wall.visible = e.target.checked; });
document.getElementById('cOut').addEventListener('change', e=>{
  lines.forEach(rec=>{ rec.obj.material.opacity = (e.target.checked && rec.meta.reason==='reached_outlet')?1.0:0.75; });
});
document.getElementById('rOpacity').addEventListener('input', e=>{ wmat.opacity = parseInt(e.target.value,10)/100; });
document.getElementById('rLines').addEventListener('input', visibility);
document.getElementById('cL').addEventListener('change', visibility);
document.getElementById('cR').addEventListener('change', visibility);

function animate(){
  requestAnimationFrame(animate);
  if(spinning){ theta += 0.004; updateCam(); }
  renderer.render(scene, camera);
}
animate();
})();
"""


def build_html(f, lines, meta):
    three_js = open(os.path.join(HERE, "three.min.js"), encoding="utf-8").read()

    wall_pos = (f["wall_pts"] * 1000.0).astype(np.float32)
    wall_tri = f["wall_tri"].astype(np.int64).reshape(-1)
    nl_pos = (f["nl_pts"] * 1000.0).astype(np.float32); nl_tri = f["nl_tri"].astype(np.int64).reshape(-1)
    nr_pos = (f["nr_pts"] * 1000.0).astype(np.float32); nr_tri = f["nr_tri"].astype(np.int64).reshape(-1)
    out_pos = (f["out_pts"] * 1000.0).astype(np.float32); out_tri = f["out_tri"].astype(np.int64).reshape(-1)

    line_data = []
    for l in lines:
        line_data.append({
            "side": l["side"], "reason": l["reason"], "length_mm": l["length_mm"],
            "pos": l["pts"].astype(np.float32).reshape(-1),
            "spd": l["spd"].astype(np.float32), "p": l["pPa"].astype(np.float32),
        })

    allspd = np.concatenate([l["spd"] for l in lines])
    allp = np.concatenate([l["pPa"] for l in lines])
    allpts = np.concatenate([l["pts"] for l in lines])
    center = ((allpts.max(axis=0) + allpts.min(axis=0)) / 2).tolist()
    radius = float(np.linalg.norm(allpts.max(axis=0) - allpts.min(axis=0)) / 2)

    data_js_lines = []
    for ld in line_data:
        data_js_lines.append(
            '{side:%s,reason:%s,length_mm:%s,pos:new Float32Array(U8("%s").buffer),'
            'spd:new Float32Array(U8("%s").buffer),p:new Float32Array(U8("%s").buffer)}'
            % (json.dumps(ld["side"]), json.dumps(ld["reason"]), ld["length_mm"],
               b64(ld["pos"]), b64(ld["spd"]), b64(ld["p"])))

    def u32(idx):
        return b64(idx.astype(np.uint32))

    data_obj = {
        "LINE_DATA": "@@LINES@@",
        "WALL_POS": 'new Float32Array(U8("%s").buffer)' % b64(wall_pos.reshape(-1)),
        "WALL_IDX": 'new Uint32Array(U8("%s").buffer)' % u32(wall_tri),
        "PATCH": 'PL',
        "META": "ME",
    }
    lines_src = "[" + ",".join(data_js_lines) + "]"
    meta_src = json.dumps({
        "spd_p2": float(np.percentile(allspd, 2)), "spd_max": float(allspd.max()),
        "p_p2": float(np.percentile(allp, 2)), "p_max": float(allp.max()),
        "center": center, "radius": radius,
    })
    patch_src = ('{nl_pos:new Float32Array(U8("%s").buffer),nl_idx:new Uint32Array(U8("%s").buffer),'
                 'nr_pos:new Float32Array(U8("%s").buffer),nr_idx:new Uint32Array(U8("%s").buffer),'
                 'out_pos:new Float32Array(U8("%s").buffer),out_idx:new Uint32Array(U8("%s").buffer)}'
                 % (b64(nl_pos.reshape(-1)), u32(nl_tri), b64(nr_pos.reshape(-1)), u32(nr_tri),
                    b64(out_pos.reshape(-1)), u32(out_tri)))

    data_src = ("(function(){function U8(s){const b=atob(s);const u=new Uint8Array(b.length);"
                "for(let i=0;i<b.length;i++)u[i]=b.charCodeAt(i);return u;}"
                "return {LINE_DATA:%s, WALL_POS:%s, WALL_IDX:%s, PATCH:%s, META:%s};})()"
                % (lines_src, data_obj["WALL_POS"], data_obj["WALL_IDX"], patch_src, meta_src))

    reasons = meta["reasons"]
    n_reach = reasons.get("reached_outlet", 0)
    table_rows = [
        ("来源 case", "<code>t004_diag</code> time=400"),
        ("网格", "1,161,194 四面体 / 229,033 节点"),
        ("工况", "双鼻孔各 1.25e-4 m³/s（合计 15 L/min），出口 p=0 gauge"),
        ("进口面平均静压（time=400）", "左 8.85 Pa / 右 11.74 Pa（出口 0）"),
        ("质量不平衡（time=400）", "≈ 1.1e-6（相对）"),
        ("流线条数", f"{len(lines)} 条（每侧 {meta.get('per_side','60')} 个种子）"),
        ("抵达鼻咽出口", f"{n_reach} 条（占 {n_reach/max(1,len(lines))*100:.0f}%）"),
        ("其余终止原因", "、".join(f"{k}×{v}" for k, v in reasons.items() if k != "reached_outlet")),
        ("速度范围（沿流线）", f"{allspd.min():.3f} – {allspd.max():.3f} m/s"),
        ("迭代状态", "未达 residualControl 收敛（numerical_validation: unchecked）"),
        ("临床状态", "generalisation_test_only_no_human_review"),
    ]
    table = "".join(f"<tr><th>{a}</th><td>{b}</td></tr>" for a, b in table_rows)

    grad = ",".join(["hsl(%d,70%%,50%%)" % int(240 * (1 - i / 9)) for i in range(10)])
    html = (HTML_TEMPLATE
            .replace("__THREEJS__", three_js)
            .replace("__DATA__", data_src)
            .replace("__APP__", APP_JS)
            .replace("__TABLE__", table)
            .replace("__GRAD__", grad)
            .replace("__NSEED__", str(meta.get("per_side", 60))))
    out = os.path.join(HERE, "鼻腔气流可视化.html")
    with open(out, "w", encoding="utf-8") as fp:
        fp.write(html)
    print("写出", out, os.path.getsize(out) // 1024, "KB", flush=True)


def main():
    f, lines, meta = load()
    per_side = {}
    for l in lines:
        per_side[l["side"]] = per_side.get(l["side"], 0) + 1
    meta["per_side"] = max(per_side.values()) if per_side else 0
    # patch 质心（事实记录）
    for k in ("nl_pts", "nr_pts", "out_pts"):
        meta.setdefault("centroid_mm", {})[k] = [round(float(v), 2) for v in (f[k] * 1000).mean(axis=0)]
    build_html(f, lines, meta)
    make_static(f, lines, meta)
    with open(os.path.join(HERE, "trace_meta.json"), "w", encoding="utf-8") as fp:
        json.dump(meta, fp, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
