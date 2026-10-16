/* T-058 切割结果三维检视 · 解剖斜切
 * 建立在项目既定的离线渲染栈上：viewer/vendor 的 three 0.180.0 + OrbitControls
 * （sha 锁定，见 vendor/source.json），import map 经 8769 工作台服务加载。
 * 几何资产：t058_cut_data.json（索引）+ t058_<case>.json（每例 mesh）。
 * LPS → 显示坐标 (x, z, -y)：与 viewer.js 的 lpsToView 一致。
 */
import * as THREE from 'three';
import { OrbitControls } from '/viewer/vendor/OrbitControls.js';

const $ = id => document.getElementById(id);
const COLORS = {
  wall: 0xc3cdda, nostril_L: 0x1f77b4, nostril_R: 0x2ca02c,
  outlet: 0xe8823a, ghost: 0xd62728, planeNew: 0xc96a1e,
  planeAxial: 0x8a9390,   axis: 0x1a1a1a,
};
const FOCUS_MM = 34;          // 出口特写：域底往上 34 mm（显示坐标 y = superior）
const VIEW_DIRS = {
  persp: new THREE.Vector3(0.43, 0.5, 0.75),
  front: new THREE.Vector3(0, 0, 1),
  frontlow: new THREE.Vector3(0, -0.25, 0.97),
  side: new THREE.Vector3(1, 0, 0),
  top: new THREE.Vector3(0, 1, 0),
  bottom: new THREE.Vector3(0, -1, 0),
};

// 嵌入契约（供工作台 pro/index.html 中栏 iframe 使用）：
//   ?case=<b01|b02|b15>  默认选中该例（患者树点选后三维页随之定位）
//   ?embedded=1          收窄页面 chrome（见 t058_cut.html 的 html.embedded 规则）
const Q = new URLSearchParams(location.search);
const EMBEDDED = Q.get('embedded') === '1' && window.parent !== window;
const WANT_CASE = Q.get('case');
/* T-063：?sl=<lines.json url> 可选，把该例已核验流线叠加进同一个 3D 视口
   （模型与流线出自同一例同一套几何，LPS mm 同坐标系，无需第二张图）。
   页内切到别的病例时按 lines.json 的 case 字段诚实降级：不匹配就只有模型。 */
const SL_URL = (Q.get('sl') || '').trim();
if (EMBEDDED) document.documentElement.classList.add('embedded');

let scene, camera, renderer, controls;
let cases = [], cur = null, group = null;
let focusExit = true;
let slData = null, linesGroup = null;

function initScene() {
  scene = new THREE.Scene();
  scene.background = new THREE.Color('#eef0f0');   /* 中性灰视口底（工作台令牌 --canvas） */
  camera = new THREE.PerspectiveCamera(38, 1, 0.01, 10000);
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(Math.max(devicePixelRatio, 1.5), 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.15;
  $('scene').appendChild(renderer.domElement);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  // 影棚布光：半球环境 + 双主光 + 底部补光（仰视出口时的背光问题）
  // 强度经 _light_probe.html 标定：three r180 物理光单位下此档位使壁面达到
  // sRGB≈215–225 的明亮灰且保留明暗层次（ACES 压缩高光）
  scene.add(new THREE.HemisphereLight(0xffffff, 0xc8c8c8, 4.0));
  const key1 = new THREE.DirectionalLight(0xffffff, 1.6);
  key1.position.set(120, 150, 130); scene.add(key1);
  const key2 = new THREE.DirectionalLight(0xffffff, 1.0);
  key2.position.set(-100, 60, -140); scene.add(key2);
  const under = new THREE.DirectionalLight(0xffffff, 1.3);
  under.position.set(90, -150, 70); scene.add(under);
  const fill = new THREE.DirectionalLight(0xffffff, 0.5);
  fill.position.set(-120, -20, -100); scene.add(fill);
  const resize = () => {
    const w = $('scene').clientWidth, h = $('scene').clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };
  window.addEventListener('resize', resize);
  resize();
}

function toView(points, center) {
  // LPS mm -> 显示 mm，与 viewer.js 同款映射
  const out = [];
  for (let i = 0; i < points.length; i += 3) {
    out.push(points[i] - center[0], points[i + 2] - center[2], -(points[i + 1] - center[1]));
  }
  return out;
}

function meshFrom(payload, color, opacity, depthWrite) {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(payload.vertices, 3));
  g.setIndex(payload.indices);
  g.computeVertexNormals();
  const m = new THREE.MeshPhongMaterial({
    color, transparent: opacity < 1, opacity,
    side: THREE.DoubleSide, depthWrite: depthWrite !== false, shininess: 12,
  });
  return new THREE.Mesh(g, m);
}

function lineLoop(flat, color, opacity) {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(flat, 3));
  return new THREE.LineLoop(g, new THREE.LineBasicMaterial({
    color, transparent: opacity < 1, opacity, depthTest: false,
  }));
}

function lineSeg(flat, color) {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(flat, 3));
  return new THREE.Line(g, new THREE.LineBasicMaterial({
    color, transparent: true, opacity: 0.9, depthTest: false,
  }));
}

function row(k, v) {
  return '<div class="row"><span>' + k + '</span><b>' + v + '</b></div>';
}

/* ---------- 流线叠加层（T-063：模型 + 流线同一 3D 视口） ---------- */
/* 色带 = 流线页（T-057）同款 stops；颜色只留给数据，符合 tokens.css 纪律。返回 [r,g,b] 0..1 */
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
function removeLines() {
  if (linesGroup) { scene.remove(linesGroup); linesGroup = null; }
}
function buildLines(data) {
  if (!group || !group.userData.center) return;
  const center = group.userData.center;
  const spd2 = data.meta && data.meta.spd_p2 != null ? data.meta.spd_p2 : 0;
  const spdMax = data.meta && data.meta.spd_max != null ? data.meta.spd_max : 1;
  linesGroup = new THREE.Group();
  for (const L of (data.lines || [])) {
    const raw = atobToF32(L.pos);
    const spd = L.spd ? atobToF32(L.spd) : null;
    const n = raw.length / 3;
    const pos = new Float32Array(raw.length);
    for (let k = 0; k < raw.length; k += 3) {
      const v = toView([raw[k], raw[k + 1], raw[k + 2]], center);
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
    linesGroup.add(new THREE.Line(geo, mat));
  }
  linesGroup.renderOrder = 5;
  linesGroup.visible = $('cLines').checked;
  scene.add(linesGroup);
  /* 图例：叠加成功才显示速度范围 */
  $('legSpd').textContent = '流线 ≈ ' + spd2.toFixed(2) + '–' + spdMax.toFixed(2) + ' m/s（'
    + data.n_lines + ' 条）';
}
function applyStreamlines() {
  removeLines();
  const ok = !!(slData && cur && slData.case === cur.id && group);
  if (ok) buildLines(slData);
  $('wrapLines').style.display = ok ? '' : 'none';
  $('legLines').style.display = ok ? 'inline-block' : 'none';
}

function loadCase(item) {
  cur = item;
  if (group) { scene.remove(group); }
  removeLines();   /* T-063：换例先撤旧流线层（applyStreamlines 按 case 匹配决定是否重建） */
  group = new THREE.Group();
  scene.add(group);
  $('nums').innerHTML = '<div class="row"><span>加载中…</span><b></b></div>';
  fetch(item.mesh_url).then(r => {
    if (!r.ok) throw new Error('模型文件读取失败');
    return r.json();
  }).then(data => {
    const all = [].concat(data.patches.wall.vertices, data.ghost.vertices);
    let lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9];
    for (let i = 0; i < all.length; i += 3) {
      for (let k = 0; k < 3; k++) {
        if (all[i + k] < lo[k]) lo[k] = all[i + k];
        if (all[i + k] > hi[k]) hi[k] = all[i + k];
      }
    }
    const center = [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2];
    // 出口特写盒：域底 FOCUS_MM 内几何的局部包围盒（LPS；z = 竖直方向）
    const zTop = lo[2] + FOCUS_MM;
    let elo = [1e9, 1e9, 1e9], ehi = [-1e9, -1e9, -1e9], nExit = 0;
    for (let i = 0; i < all.length; i += 3) {
      if (all[i + 2] > zTop) continue;
      nExit++;
      for (let k = 0; k < 3; k++) {
        if (all[i + k] < elo[k]) elo[k] = all[i + k];
        if (all[i + k] > ehi[k]) ehi[k] = all[i + k];
      }
    }
    if (!nExit) { elo = lo.slice(); ehi = hi.slice(); }
    // 气道轴：LPS 线段 → 显示方向（x, z, -y），规整为指向上（Superior）
    const a = data.axis;
    const axisDir = new THREE.Vector3(a[3] - a[0], a[5] - a[2], -(a[4] - a[1]));
    if (axisDir.lengthSq() > 0) axisDir.normalize();
    if (axisDir.y < 0) axisDir.negate();
    const cv = p => toView(p, center);
    const at = payload => ({ vertices: cv(payload.vertices), indices: payload.indices });
    const parts = {
      wall: meshFrom(at(data.patches.wall), COLORS.wall,
                     parseInt($('rOpacity').value, 10) / 100, true),
      nostril_L: meshFrom(at(data.patches.nostril_L), COLORS.nostril_L, 0.95, true),
      nostril_R: meshFrom(at(data.patches.nostril_R), COLORS.nostril_R, 0.95, true),
      outlet: meshFrom(at(data.patches.oropharynx_truncation_outlet), COLORS.outlet, 0.9, true),
      ghost: meshFrom(at(data.ghost), COLORS.ghost, 0.32, false),
      planeNew: lineLoop(cv(data.plane_new), COLORS.planeNew, 0.95),
      planeAxial: lineLoop(cv(data.plane_axial), COLORS.planeAxial, 0.8),
      axis: lineSeg(cv(data.axis), COLORS.axis),
    };
    Object.values(parts).forEach(m => group.add(m));
    group.userData = { parts, lo, hi, elo, ehi, center, axisDir };
    applyVis();
    fitCurrent();
    applyStreamlines();   /* T-063：模型就位后按 case 匹配叠加流线层（不匹配则诚实只有模型） */
    const m = data.meta;
    $('nums').innerHTML =
      row('判定', m.decision === 'auto_pass' ? 'auto_pass ✓' : 'escalated') +
      row('鼻孔 L / R（mm²）', m.nostril_L + ' / ' + m.nostril_R) +
      row('出口帽 · 解剖切（mm²）', '<b>' + m.outlet + '</b>') +
      row('出口帽 · 退役轴位切（mm²）', m.outlet_axial) +
      row('气道轴倾角', m.tilt_deg + '°') +
      row('拟合窗内质心漂移（mm）', m.drift_xy_mm[0] + ' / ' + m.drift_xy_mm[1] +
          '（窗 ' + m.fit_height_mm + ' mm）') +
      row('切口锚点 z（mm）', m.z_anchor_mm.toFixed(2) + '（底面 ' + m.z_bottom_mm.toFixed(2) + '）') +
      row('域体积（mm³）', m.volume_mm3) +
      row('切除体积（mm³）', m.removed_mm3) +
      row('显示三角面', data.patches.wall.triangles.toLocaleString() + '（壁面抽稀）');
  }).catch(e => {
    $('nums').innerHTML = '<div class="row"><span>读取失败</span><b>' + e.message + '</b></div>';
  });
}

function focusPoints() {
  if (!group || !group.userData.lo) return [];
  const { center } = group.userData;
  const b = focusExit ? [group.userData.elo, group.userData.ehi]
                      : [group.userData.lo, group.userData.hi];
  const pad = 4, pts = [];
  for (const x of [b[0][0] - pad, b[1][0] + pad])
    for (const y of [b[0][1] - pad, b[1][1] + pad])
      for (const z of [b[0][2] - pad, b[1][2] + pad])
        pts.push(new THREE.Vector3(x - center[0], y - center[1], z - center[2]));
  return pts;
}

function viewDir(name) {
  // 底视 = 沿气道轴从出口下方仰视（出口帽正对面）；无轴时退化为正下方
  if (name === 'bottom' && group && group.userData.axisDir &&
      group.userData.axisDir.lengthSq() > 0) {
    return group.userData.axisDir.clone().negate();
  }
  return (VIEW_DIRS[name] || VIEW_DIRS.persp).clone().normalize();
}

function fitCurrent(dirName) {
  const pts = focusPoints();
  if (!pts.length) return;
  const dir = viewDir(dirName || currentView);
  const half = Math.tan(camera.fov * Math.PI / 360);
  const asp = Math.max(0.2, camera.aspect);
  // 视线与 (0,1,0) 近共线时（顶/底视、沿轴出口视）必须换 up，否则叉积退化、
  // 相机落在包围盒面上钻进几何体（底视曾因此整屏深灰）
  const up = new THREE.Vector3(0, 1, 0);
  if (Math.abs(dir.dot(up)) > 0.8) up.set(0, 0, dir.y >= 0 ? -1 : 1);
  const xc = new THREE.Vector3().crossVectors(up, dir).normalize();
  const yc = new THREE.Vector3().crossVectors(dir, xc).normalize();
  const c = new THREE.Vector3();
  pts.forEach(p => c.add(p));
  c.multiplyScalar(1 / pts.length);
  let need = 0;
  pts.forEach(p => {
    const d = p.clone().sub(c);
    need = Math.max(need,
      Math.abs(d.dot(xc)) / (half * asp) + d.dot(dir),
      Math.abs(d.dot(yc)) / half + d.dot(dir));
  });
  controls.target.copy(c);
  camera.position.copy(c).add(dir.multiplyScalar(need * 1.06));
  camera.up.copy(up);
  controls.update();
}

let currentView = 'frontlow';
function setView(name) {
  currentView = name;
  fitCurrent(name);
}

function applyVis() {
  if (!group) return;
  const p = group.userData.parts;
  const v = {
    wall: $('cWall').checked, caps: $('cCaps').checked, ghost: $('cGhost').checked,
    planes: $('cPlanes').checked, axis: $('cAxis').checked,
  };
  p.wall.visible = v.wall;
  p.nostril_L.visible = v.caps; p.nostril_R.visible = v.caps; p.outlet.visible = v.caps;
  p.ghost.visible = v.ghost;
  p.planeNew.visible = v.planes; p.planeAxial.visible = v.planes;
  p.axis.visible = v.axis;
  if (linesGroup) linesGroup.visible = $('cLines').checked;
  p.wall.material.opacity = parseInt($('rOpacity').value, 10) / 100;
}

function tick() {
  requestAnimationFrame(tick);
  controls.update();
  renderer.render(scene, camera);
}

function main() {
  initScene();
  fetch('./t058_cut_data.json').then(r => r.json()).then(index => {
    cases = index.cases;
    const bar = $('caseBar');
    cases.forEach(item => {
      const b = document.createElement('button');
      b.className = 'case'; b.id = 'c' + item.id; b.textContent = item.id;
      b.addEventListener('click', () => {
        cases.forEach(k => $('c' + k.id).classList.remove('on'));
        b.classList.add('on');
        loadCase(item);
      });
      bar.appendChild(b);
    });
    // ?case= 指定则默认选中该例（工作台患者树点选后三维页随之定位）；否则取末例
    const initial = cases.find(k => k.id === WANT_CASE) || cases[cases.length - 1];
    $('c' + initial.id).classList.add('on');
    loadCase(initial);
    setView('frontlow');
  });
  const views = { bPersp: 'persp', bFrontlow: 'frontlow', bFront: 'front',
                  bSide: 'side', bTop: 'top', bBottom: 'bottom' };
  Object.keys(views).forEach(id => {
    $(id).addEventListener('click', () => {
      Object.keys(views).forEach(k => $(k).classList.remove('on'));
      $(id).classList.add('on');
      setView(views[id]);
    });
  });
  ['cWall', 'cCaps', 'cGhost', 'cPlanes', 'cAxis', 'cLines'].forEach(id =>
    $(id).addEventListener('change', applyVis));
  $('rOpacity').addEventListener('input', applyVis);
  $('cFocus').addEventListener('change', e => { focusExit = e.target.checked; fitCurrent(); });
  $('bFrontlow').classList.add('on');
  /* T-063：?sl= 指定该例已核验流线 lines.json → 读到后叠加进当前病例视口。
     读取失败只少一层（诚实降级），绝不阻塞几何检视。 */
  if (SL_URL) {
    fetch(SL_URL, { cache: 'no-store' }).then(r => {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(d => {
      slData = d;
      if (cur) applyStreamlines();
    }).catch(e => console.warn('流线数据读取失败（只显示模型）：', e.message));
  }
  tick();
}

main();
