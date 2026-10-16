/* T-058 双侧三维对比 · 解剖斜切
 * 单画布双视口（左 A / 右 B），共用一条相机轨道：拖动、缩放、平移两侧完全同步，
 * 因此是「两个三维模型直接并排对比」，而不是各自打开一份完整检视界面。
 *
 * 关键口径（与 t058_cut.html 对齐，勿擅改）：
 * - 渲染栈 = 项目既有 viewer/vendor（three 0.180 + OrbitControls，离线锁定）；
 * - 每例各自按 wall+ghost 包围盒中心归零（显示坐标 (x, z, -y)，与 viewer.js 的 lpsToView 同款），
 *   故同一组相机参数对两例都成立；
 * - 取景距离按两例中较大者统一计算 → 不做归一化放大，保留两例真实尺寸差异；
 * - 资产与 t058_cut.html 同源：t058_cut_data.json（索引）+ t058_<case>.json（每例 mesh）。
 *
 * 嵌入契约：?a=<case>&b=<case> 指定左右两例；?embedded=1 收窄页面（工作台中栏 iframe）。
 * T-063：?sa=<lines.json url>&sb=<lines.json url> 可选，每侧叠加流线层（模型+流线综合视图）。
 * 流线数据由 pro.js 按 manifest lines_url 传入；无该参数或读取失败的一侧只有模型（诚实降级）。
 * 流线与模型同坐标系（LPS mm），过与模型相同的 toView(center) 变换对齐；
 * 顶点色按速度映射流线页（T-057）同款色带——颜色只留给数据，符合 tokens.css 纪律。
 */
import * as THREE from 'three';
import { OrbitControls } from '/viewer/vendor/OrbitControls.js';

const $ = id => document.getElementById(id);
const Q = new URLSearchParams(location.search);
const EMBEDDED = Q.get('embedded') === '1' && window.parent !== window;
if (EMBEDDED) document.documentElement.classList.add('embedded');
const WANT = [(Q.get('a') || '').trim(), (Q.get('b') || '').trim()];
const SL_URLS = [(Q.get('sa') || '').trim(), (Q.get('sb') || '').trim()];

const COLORS = {
  wall: 0xc3cdda, nostril_L: 0x1f77b4, nostril_R: 0x2ca02c,
  outlet: 0xe8823a, ghost: 0xd62728, planeNew: 0xc96a1e,
};
const VIEW_DIRS = {
  persp: new THREE.Vector3(0.43, 0.5, 0.75), front: new THREE.Vector3(0, 0, 1),
  frontlow: new THREE.Vector3(0, -0.25, 0.97), side: new THREE.Vector3(1, 0, 0),
  top: new THREE.Vector3(0, 1, 0), bottom: new THREE.Vector3(0, -1, 0),
};
const VIEW_BUTTONS = [
  ['frontlow', '前下（看出口）'], ['front', '前面'], ['side', '左面'],
  ['top', '顶视'], ['persp', '透视'],
];

let renderer = null, controls = null, W = 2, H = 2;
let indexData = { cases: [] };
let currentView = 'frontlow';
const cams = [];
const slots = [
  { name: 'A', scene: null, group: null, ok: false, R: 0, center: null, lines: null },
  { name: 'B', scene: null, group: null, ok: false, R: 0, center: null, lines: null },
];

/* ---------- 流线层（T-063） ---------- */
/* 色带 = 流线页（T-057）同款 stops；返回 [r,g,b] 0..1 */
const STOPS = [[0.19,0.07,0.23],[0.28,0.35,0.85],[0.15,0.72,0.90],[0.25,0.93,0.55],
  [0.72,0.95,0.20],[0.99,0.75,0.10],[0.98,0.42,0.10],[0.80,0.12,0.10],[0.48,0.05,0.09]];
function ramp(t) {
  const x = Math.max(0, Math.min(1, t)) * (STOPS.length - 1);
  const i = Math.floor(x), f = x - i;
  const a = STOPS[i], b = STOPS[Math.min(STOPS.length - 1, i + 1)];
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
}
function atobToF32(s64) {
  const b = atob(s64);
  const u = new Uint8Array(b.length);
  for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i);
  return new Float32Array(u.buffer);
}
async function addStreamlines(slot, i, url) {
  slot.lines = null;
  if (!url) return;
  let data;
  try {
    const r = await fetch(url, { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    data = await r.json();
  } catch (e) {
    console.warn('streamlines load failed:', e.message);   /* 诚实降级：只少一层，不阻塞模型 */
    return;
  }
  if (!slot.center || !slot.scene) return;
  const cv = p => toView(p, slot.center);
  const spd2 = data.meta && data.meta.spd_p2 != null ? data.meta.spd_p2 : 0;
  const spdMax = data.meta && data.meta.spd_max != null ? data.meta.spd_max : 1;
  const g = new THREE.Group();
  for (const L of (data.lines || [])) {
    const raw = atobToF32(L.pos);
    const spd = L.spd ? atobToF32(L.spd) : null;
    const n = raw.length / 3;
    const pos = new Float32Array(raw.length);
    for (let k = 0; k < raw.length; k += 3) {
      const v = cv([raw[k], raw[k + 1], raw[k + 2]]);
      pos[k] = v[0]; pos[k + 1] = v[1]; pos[k + 2] = v[2];
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    let mat;
    if (spd && spd.length >= n) {
      const col = new Float32Array(n * 3);
      for (let k = 0; k < n; k++) {
        const c = ramp((spd[k] - spd2) / (spdMax - spd2 || 1));
        col[k * 3] = c[0]; col[k * 3 + 1] = c[1]; col[k * 3 + 2] = c[2];
      }
      geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
      mat = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.95, depthTest: false });
    } else {
      mat = new THREE.LineBasicMaterial({ color: 0x26828e, transparent: true, opacity: 0.95, depthTest: false });
    }
    g.add(new THREE.Line(geo, mat));
  }
  g.renderOrder = 5;
  g.visible = $('cLines').checked;
  slot.lines = g;
  slot.scene.add(g);
  /* 图例：任一侧成功加载即显示速度范围 */
  const wrap = $('wrapLines'), leg = $('legLines');
  wrap.style.display = ''; leg.style.display = 'flex';
  $('legSpd').textContent = '≈ ' + spd2.toFixed(2) + '–' + spdMax.toFixed(2) + ' m/s（'
    + data.n_lines + ' 条 · ' + (data.case || '?') + ' 扩展域 t600）';
}

/* ---------- 几何工具（与 t058_cut.js 同款） ---------- */
function toView(points, center) {
  const out = new Float32Array(points.length);
  for (let i = 0; i < points.length; i += 3) {
    out[i] = points[i] - center[0];
    out[i + 1] = points[i + 2] - center[2];
    out[i + 2] = -(points[i + 1] - center[1]);
  }
  return out;
}
function meshFor(payload, color, opacity, depthWrite) {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(payload.vertices, 3));
  g.setIndex(payload.indices);
  g.computeVertexNormals();
  return new THREE.Mesh(g, new THREE.MeshPhongMaterial({
    color, transparent: opacity < 1, opacity,
    side: THREE.DoubleSide, depthWrite: depthWrite !== false, shininess: 12,
  }));
}
function lineFor(flat, loop, color, opacity) {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(flat, 3));
  const Klass = loop ? THREE.LineLoop : THREE.Line;
  return new Klass(g, new THREE.LineBasicMaterial({
    color, transparent: true, opacity, depthTest: false,
  }));
}
/* 影棚布光：与 t058_cut.js 同档（light_probe 标定），保持两页观感一致 */
function addLights(scene) {
  scene.add(new THREE.HemisphereLight(0xffffff, 0xc8c8c8, 4.0));
  const add = (x, y, z, i) => { const l = new THREE.DirectionalLight(0xffffff, i);
    l.position.set(x, y, z); scene.add(l); };
  add(120, 150, 130, 1.6); add(-100, 60, -140, 1.0);
  add(90, -150, 70, 1.3); add(-120, -20, -100, 0.5);
}

/* ---------- 槽位（A/B 两侧） ---------- */
function setTag(i, title, sub) {
  const el = document.getElementById(i === 0 ? 'tagA' : 'tagB');
  if (!el) return;
  el.replaceChildren();
  el.append(document.createTextNode((i === 0 ? 'A · ' : 'B · ') + title));
  if (sub) { const s = document.createElement('span'); s.className = 'sub'; s.textContent = sub; el.append(s); }
}
function emptySlot(slot, title, sub) {
  slot.ok = false; slot.group = null; slot.scene = null; slot.R = 0;
  setTag(slots.indexOf(slot), title, sub || null);
}
function buildModel(slot, data) {
  const all = [].concat(data.patches.wall.vertices, data.ghost.vertices);
  const lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9];
  for (let i = 0; i < all.length; i += 3) {
    for (let k = 0; k < 3; k++) {
      const v = all[i + k]; if (v < lo[k]) lo[k] = v; if (v > hi[k]) hi[k] = v;
    }
  }
  const center = [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2];
  slot.center = center;   /* 流线层（T-063）复用同一 center 归零 */
  /* 显示变换保距，故半径可在 LPS 下直接算 */
  let R2 = 0;
  const scan = pts => {
    for (let i = 0; i < pts.length; i += 3) {
      const dx = pts[i] - center[0], dy = pts[i + 1] - center[1], dz = pts[i + 2] - center[2];
      const d2 = dx * dx + dy * dy + dz * dz;
      if (d2 > R2) R2 = d2;
    }
  };
  scan(data.patches.wall.vertices); scan(data.ghost.vertices);
  scan(data.patches.nostril_L.vertices); scan(data.patches.nostril_R.vertices);
  scan(data.patches.oropharynx_truncation_outlet.vertices);
  slot.R = Math.sqrt(R2);

  const cv = p => toView(p, center);
  const at = pl => ({ vertices: cv(pl.vertices), indices: pl.indices });
  const g = new THREE.Group();
  const parts = {
    wall: meshFor(at(data.patches.wall), COLORS.wall, 1, true),
    nostril_L: meshFor(at(data.patches.nostril_L), COLORS.nostril_L, 0.95, true),
    nostril_R: meshFor(at(data.patches.nostril_R), COLORS.nostril_R, 0.95, true),
    outlet: meshFor(at(data.patches.oropharynx_truncation_outlet), COLORS.outlet, 0.9, true),
    ghost: meshFor(at(data.ghost), COLORS.ghost, 0.32, false),
    planeNew: lineFor(cv(data.plane_new), true, COLORS.planeNew, 0.95),
  };
  Object.values(parts).forEach(m => g.add(m));
  g.userData = { parts };
  slot.group = g;
  slot.scene.add(g);
}
async function setSide(i, caseId) {
  const slot = slots[i];
  const entry = indexData.cases.find(c => c.id === caseId);
  if (!entry) { emptySlot(slot, '未选择模型', '在上方选择患者模型'); return; }
  if (!slot.scene) {
    slot.scene = new THREE.Scene();
    slot.scene.background = new THREE.Color('#eef0f0');
    addLights(slot.scene);
  }
  if (slot.group) { slot.scene.remove(slot.group); slot.group = null; }
  if (slot.lines) { slot.scene.remove(slot.lines); slot.lines = null; }
  slot.ok = false;
  setTag(i, entry.label || caseId, '正在读取几何…');
  let data;
  try {
    const r = await fetch(entry.mesh_url, { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    data = await r.json();
  } catch (e) {
    emptySlot(slot, entry.label || caseId, '模型文件读取失败：' + e.message);
    return;
  }
  buildModel(slot, data);
  slot.ok = true;
  const m = data.meta || {};
  setTag(i, entry.label || caseId,
    (m.outlet != null ? '出口帽 · 解剖切 ' + m.outlet + ' mm²' : '') +
    (m.tilt_deg != null ? ' · 轴倾角 ' + m.tilt_deg + '°' : ''));
  applyVis();
  fit(currentView);
  /* T-063：模型就位后叠加流线（若有该侧的数据 URL） */
  if (SL_URLS[i]) await addStreamlines(slot, i, SL_URLS[i]);
}

/* ---------- 可见性 / 取景 ---------- */
function applyVis() {
  const v = {
    caps: $('cCaps').checked, ghost: $('cGhost').checked, plane: $('cPlane').checked,
    lines: $('cLines') ? $('cLines').checked : true,
    opacity: parseInt($('rOpacity').value, 10) / 100,
  };
  for (const s of slots) {
    if (!s.group) continue;
    const p = s.group.userData.parts;
    p.wall.material.opacity = v.opacity;
    p.wall.material.transparent = v.opacity < 1;
    p.nostril_L.visible = p.nostril_R.visible = p.outlet.visible = v.caps;
    p.ghost.visible = v.ghost;
    p.planeNew.visible = v.plane;
    if (s.lines) s.lines.visible = v.lines;
  }
}
function dirFor(name) {
  return (VIEW_DIRS[name] || VIEW_DIRS.frontlow).clone().normalize();
}
function fit(dirName) {
  const dir = dirFor(dirName);
  const up = new THREE.Vector3(0, 1, 0);
  /* 视线与 (0,1,0) 近共线时必须换 up，否则相机钻进几何体（同 t058_cut 的坑） */
  if (Math.abs(dir.dot(up)) > 0.85) up.set(0, 0, dir.y >= 0 ? -1 : 1);
  const Rs = slots.filter(s => s.ok && s.R > 0).map(s => s.R);
  let dist = 100;
  if (Rs.length) {
    const R = Math.max.apply(null, Rs);
    const hw = Math.max(1, Math.floor(W / 2)), hh = Math.max(1, H);
    const vHalf = Math.tan(cams[0].fov * Math.PI / 360);
    dist = R / Math.min(vHalf, vHalf * (hw / hh)) * 1.12;
  }
  for (const c of cams) {
    c.up.copy(up);
    c.position.copy(dir).multiplyScalar(dist);
    c.lookAt(0, 0, 0);
    c.updateMatrixWorld();
  }
  controls.target.set(0, 0, 0);
  controls.update();
  sync();
}
function sync() {
  /* 同一相机轨道：位置与朝向逐帧复制到 B。两例各自以包围盒中心归零，
     故同一组位置/朝向对两例都成立。 */
  const a = cams[0], b = cams[1];
  b.position.copy(a.position);
  b.quaternion.copy(a.quaternion);
  b.up.copy(a.up);
  b.updateMatrixWorld();
}

/* ---------- 渲染 ---------- */
function resize() {
  const stage = $('stage');
  if (!stage || !renderer) return;
  const r = stage.getBoundingClientRect();
  W = Math.max(2, Math.round(r.width));
  H = Math.max(2, Math.round(r.height));
  renderer.setSize(W, H, false);
  const hw = Math.max(1, Math.floor(W / 2));
  cams[0].aspect = hw / H;
  cams[1].aspect = (W - hw) / H;
  cams.forEach(c => c.updateProjectionMatrix());
}
function tick() {
  requestAnimationFrame(tick);
  controls.update();
  sync();
  const hw = Math.max(1, Math.floor(W / 2));
  for (let i = 0; i < 2; i++) {
    const x = i === 0 ? 0 : hw;
    const w = i === 0 ? hw : W - hw;
    renderer.setViewport(x, 0, w, H);
    renderer.setScissor(x, 0, w, H);
    const s = slots[i];
    if (s.ok && s.scene) renderer.render(s.scene, cams[i]);
    else renderer.clear();
  }
}

/* ---------- 启动 ---------- */
function initGL() {
  const stage = $('stage');
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(Math.max(devicePixelRatio, 1.5), 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.15;
  renderer.setClearColor(0xeef0f0, 1);   /* 中性灰视口底（工作台令牌 --canvas） */
  renderer.setScissorTest(true);
  stage.appendChild(renderer.domElement);
  cams.push(new THREE.PerspectiveCamera(38, 1, 0.01, 10000));
  cams.push(new THREE.PerspectiveCamera(38, 1, 0.01, 10000));
  controls = new OrbitControls(cams[0], renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.target.set(0, 0, 0);
  window.addEventListener('resize', resize);
  if (window.ResizeObserver) new ResizeObserver(resize).observe(stage);
  resize();
}
function buildBar() {
  const box = $('viewBtns');
  for (const [key, label] of VIEW_BUTTONS) {
    const b = document.createElement('button');
    b.textContent = label; b.dataset.view = key;
    b.addEventListener('click', () => {
      currentView = key;
      box.querySelectorAll('button').forEach(x => x.classList.toggle('on', x.dataset.view === key));
      fit(key);
    });
    box.append(b);
  }
  ['cCaps', 'cGhost', 'cPlane', 'cLines'].forEach(id => { const e = $(id); if (e) e.addEventListener('change', applyVis); });
  $('rOpacity').addEventListener('input', applyVis);
}
async function boot() {
  initGL();
  buildBar();
  try {
    indexData = await (await fetch('./t058_cut_data.json', { cache: 'no-store' })).json();
  } catch (e) {
    setTag(0, '资产索引读取失败', String(e.message));
    setTag(1, '资产索引读取失败', String(e.message));
    tick();
    return;
  }
  const ids = (indexData.cases || []).map(c => c.id);
  if (!ids.length) { setTag(0, '无可用模型', null); setTag(1, '无可用模型', null); tick(); return; }
  const pick = want => (ids.includes(want) ? want : null);
  const a = pick(WANT[0]) || ids[ids.length - 1];
  const b = pick(WANT[1]) || ids.find(x => x !== a) || a;
  await Promise.all([setSide(0, a), setSide(1, b)]);
  fit(currentView);
  const on = $('viewBtns').querySelector('button[data-view="' + currentView + '"]');
  if (on) on.classList.add('on');
  resize();
  setTimeout(resize, 80);
  tick();
}
boot();
