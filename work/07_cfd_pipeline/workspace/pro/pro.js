/* ==========================================================================
   pro.js · 工程工作台 PRO 外壳逻辑
   T-052 P1 外壳 → T-053 患者即项目 → T-055 需求×链路重构：
   - 左树 = 参数化处理树（数据源→分割→定位→几何→网格→配置维→后处理→报告），
     状态由 API 真实字段 + 已核验指标文件推导，stale 传播可见（P2/P4 原理）；
   - 对比 = V1 个体 vs 文献参考带（ISCOANA/choana/S15，带出处）+
            V2 配对功能指标对照（域口径并列），采集参数降级附录，不评分不裁判；
   - 数据全部只读；缺项如实「—」；UI 黑白灰单色纪律。
   ========================================================================== */
'use strict';
(() => {
const $ = id => document.getElementById(id);
const el = (tag, text, cls) => { const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; };

/* ---------- 状态 ---------- */
const S = {
  cases: [], jobs: [], metrics: null,                // metrics = patient_metrics.json（已核验搬运）
  caseId: null,                                      // null = 项目总览（全局）
  view: 'projects',
  sel: null,                                         // {kind:'flow'|'job', key}
  cmp: {a: null, b: null, mode: 'ref'},              // mode: 'ref' V1 | 'pair' V2
};

/* ---------- 处理树（PRO重构设计_v2：8 节点，含依赖） ---------- */
const FLOW = [
  {key: 'source',   no: '01', label: '数据源',   sub: 'CT 序列导入',        dep: [],
   desc: 'DICOM 序列读取与脱敏校验。产出：序列清单 / 层距像元 / HU 范围。'},
  {key: 'segment',  no: '02', label: '分割',     sub: '气道掩膜',           dep: ['source'],
   desc: '阈值分割生成气道掩膜。产出：掩膜体 / 腔外空气排除。'},
  {key: 'locate',   no: '03', label: '定位',     sub: '解剖标志 / 候选点',   dep: ['segment'],
   desc: '鼻孔 / 鼻咽 / 嗅区等解剖标志定位。产出：候选点（landmarks）。'},
  {key: 'geometry', no: '04', label: '几何',     sub: '表面 + 开口',        dep: ['locate'],
   desc: '等值面提取与开口定位。产出：STL（单位 m）/ 鼻孔·出口面积 / 四门禁。'},
  {key: 'mesh',     no: '05', label: '网格',     sub: '四面体 + 修复',      dep: ['geometry'],
   desc: 'netgen 网格化与 det<0 修复。产出：.msh / 单元数 / checkMesh 计数。'},
  {key: 'config',   no: '06', label: '配置维',   sub: '层流 / k-ω / 网格档', dep: ['mesh'],
   desc: '同患者多求解配置并列分支（变体非复制）：层流 S-A / kOmegaSST / maxh 档。'},
  {key: 'post',     no: '07', label: '后处理',   sub: 'R / WSS / 流线',    dep: ['config'],
   desc: '功能指标提取与流线追踪。产出：Δp / R / WSS 分布 / streamlines.html。'},
  {key: 'report',   no: '08', label: '报告',     sub: '结论卡 / 验证矩阵',   dep: ['post'],
   desc: '结论卡与验证矩阵归档。产物恒带 clinical_status 口径声明。'},
];
const VIEWS = [
  {key: 'projects',    label: '项目总览'},
  {key: 'pipeline',    label: '处理链路'},
  {key: 'geometry',    label: '三维检查'},
  {key: 'airway',      label: '咽部扩展'},
  {key: 'streamlines', label: '流线'},
  {key: 'compare',     label: '对比'},
  {key: 'jobs',        label: '任务控制台'},
];
const ACTION_LABEL = {preflight: '准入预检', run_reference: '参考求解',
  run_pressure_feedback: '共同压力反馈', run_patient_engineering: '患者工程试算'};
const STAGE_LABEL = {import: '导入', segmentation: '分割', localization: '定位',
  review: '审核', geometry: '几何', validation: '验证', completed: '完成'};
const STATUS_ICON = {completed: ['✓', 'done'], failed: ['✗', 'fail'],
  running: ['▷', 'run'], queued: ['▷', 'run'], interrupted: ['◌', 'fail']};

/* ---------- 数据 ---------- */
async function jget(path) {
  const r = await fetch(path, {cache: 'no-store'});
  if (!r.ok) throw new Error(path + ' → ' + r.status);
  return r.json();
}
const caseIdOf = c => c.id || c.case_id;
const jobsOfCase = id => S.jobs.filter(j => j.case_id === id);
const scopedJobs = () => S.caseId ? jobsOfCase(S.caseId) : S.jobs;

/* metrics 文件的病例键与 API case_id 的匹配：b15_engineering → b15 */
function metricKeyOf(caseId) {
  const m = S.metrics && S.metrics.patients;
  if (!m || !caseId) return null;
  if (m[caseId]) return caseId;
  const base = caseId.replace(/_(engineering|trial|case)$/, '');
  if (m[base]) return base;
  const hit = Object.keys(m).find(k => caseId.startsWith(k + '_') || caseId.startsWith(k));
  return hit || null;
}

function buildCaseOptions() {
  const sel = $('case-select');
  const keep = sel.value;
  sel.replaceChildren();
  const all = el('option', '（全部项目 · 总览）', '');
  all.value = ''; sel.append(all);
  for (const c of S.cases) {
    const id = caseIdOf(c);
    const o = el('option', id.slice(0, 14) + '… · ' + (c.synthetic ? '仿真项目'
      : (STAGE_LABEL[c.active_stage] || c.active_stage || '?')), '');
    o.value = id; sel.append(o);
  }
  sel.value = keep || '';
}
async function loadCases() {
  const d = await jget('/api/cases');
  S.cases = d.cases || [];
  $('chip-cases').textContent = '项目：' + S.cases.length;
  $('chip-cases').classList.add('ok');
  buildCaseOptions();
}
/* 合并 jobs 派生的仿真项目（T-055）：b15 等旗舰病例的求解记录在 jobs API / WSL case，
   不在 /api/cases 导入列表——不合并则「患者即项目」看不到它们。合成条目诚实标注来源。 */
function mergeSyntheticCases() {
  const seen = new Set(S.cases.map(caseIdOf));
  let added = 0;
  for (const j of S.jobs) {
    const cid = j.case_id;
    if (!cid || seen.has(cid)) continue;
    seen.add(cid);
    const isRef = String(cid).startsWith('reference');
    S.cases.push({
      id: cid, kind: isRef ? '参考解算（jobs API）' : '仿真项目（jobs API）',
      synthetic: true, error: null, active_stage: null,
      _note: '工作台外求解：几何/网格记录在 WSL case，工作台内仅呈已核验指标搬运值',
    });
    added++;
  }
  if (added) {
    buildCaseOptions();
    $('chip-cases').textContent = '项目：' + S.cases.length + '（含 ' + added + ' 仿真）';
  }
}
async function loadJobs() {
  const d = await jget('/api/simulation/jobs');
  S.jobs = (d.jobs || []).slice().sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''));
  const run = S.jobs.filter(j => ['running', 'queued'].includes(j.status)).length;
  $('chip-jobs').textContent = '任务：' + S.jobs.length + (run ? '（' + run + ' 进行）' : '');
  $('chip-jobs').classList.toggle('ok', run === 0);
}
async function loadMetrics() {
  try {
    S.metrics = await jget('/workspace/pro/patient_metrics.json');
  } catch (e) { S.metrics = null; }
}

/* ---------- 处理树状态推导（P4：state = f(自身产物, 上游 state)） ---------- */
function pipelineStates(caseId) {
  const c = S.cases.find(x => caseIdOf(x) === caseId);
  const jobs = caseId ? jobsOfCase(caseId) : [];
  const mk = caseId ? metricKeyOf(caseId) : null;
  const mp = mk && S.metrics ? S.metrics.patients[mk] : null;
  const hasStreamline = jobs.some(j => (j.artifacts || []).some(a => a.name === 'streamlines.html'));
  const st = {};
  const syn = !!(c && c.synthetic);
  st.source   = syn ? 'norec' : (c && !c.error ? 'done' : (c ? 'fail' : 'todo'));
  st.segment  = syn ? 'norec' : ((c && c.active_stage && c.active_stage !== 'import') ? 'done' : 'todo');
  st.locate   = syn ? 'norec' : ((c && (c.landmark_count || 0) > 0) ? 'done' : 'todo');
  st.geometry = syn ? 'norec' : ((c && c.geometry) ? 'done' : 'todo');
  st.mesh     = syn ? 'norec' : ((c && c.geometry) ? 'done' : 'todo');
  st.config   = mp ? 'done' : (jobs.some(j => j.action === 'run_patient_engineering') ? 'fail' : 'todo');
  st.post     = (mp && mp.metrics && mp.metrics.R_Pa_s_ml && mp.metrics.R_Pa_s_ml.value != null) ? 'done'
                : (hasStreamline ? 'done' : 'todo');
  st.report   = mp ? 'done' : 'todo';
  /* stale 传播：上游非 done 的下游标 stale（不可用，非未做） */
  for (const f of FLOW) {
    if (st[f.key] !== 'todo') continue;
    if (f.dep.some(d => st[d] === 'fail' || st[d] === 'stale')) st[f.key] = 'stale';
    else if (f.dep.some(d => st[d] === 'todo')) st[f.key] = 'wait';
  }
  return st;
}
function renderFlowTree() {
  const t = $('flow-tree'); t.replaceChildren();
  if (!S.caseId) {
    t.append(el('li', '先在顶部选择患者项目（或点项目卡片进入）。', 'tnode grp'));
    return;
  }
  const st = pipelineStates(S.caseId);
  for (const f of FLOW) {
    const s = st[f.key];
    const icon = s === 'done' ? '✓' : s === 'fail' ? '✗' : s === 'stale' ? '⊘' : s === 'wait' ? '…' : s === 'norec' ? '◇' : '◌';
    const li = el('li', undefined, 'tnode' + (S.sel && S.sel.kind === 'flow' && S.sel.key === f.key ? ' sel' : ''));
    li.append(el('span', icon, 'st ' + s));
    const lbl = el('span', undefined, 'lbl');
    lbl.textContent = f.no + ' ' + f.label;
    lbl.append(el('span', f.sub, 'sub'));
    li.append(lbl);
    li.title = f.desc;
    li.onclick = () => { S.sel = {kind: 'flow', key: f.key};
      if (f.key === 'geometry') S.view = 'geometry';
      else if (f.key === 'config' || f.key === 'post') S.view = 'pipeline';
      else if (f.key === 'report') S.view = 'pipeline';
      else S.view = 'pipeline';
      renderAll(); };
    t.append(li);
  }
}

/* ---------- 左树：任务（按项目过滤） ---------- */
function renderJobTree() {
  const t = $('job-tree'); t.replaceChildren();
  const jobs = scopedJobs();
  if (!jobs.length) {
    t.append(el('li', S.caseId ? '本项目暂无任务记录' : '暂无任务记录', 'tnode grp'));
    return;
  }
  for (const j of jobs.slice(0, 12)) {
    const [icon, cls] = STATUS_ICON[j.status] || ['◌', 'todo'];
    const li = el('li', undefined, 'tnode' + (S.sel && S.sel.kind === 'job' && S.sel.key === j.id ? ' sel' : ''));
    li.append(el('span', icon, 'st ' + cls));
    const lbl = el('span', undefined, 'lbl');
    lbl.textContent = ACTION_LABEL[j.action] || j.action;
    lbl.append(el('span', (j.id || '').slice(0, 12) + '… · ' + (j.updated_at || '').slice(5, 16), 'sub'));
    li.append(lbl);
    li.onclick = () => { S.sel = {kind: 'job', key: j.id}; S.view = 'jobs'; renderAll(); };
    t.append(li);
  }
}

/* ---------- 中：视图 ---------- */
function renderTabs() {
  const tabs = $('view-tabs'); tabs.replaceChildren();
  for (const v of VIEWS) {
    const b = el('button', v.label, 'vtab' + (S.view === v.key ? ' on' : ''));
    b.onclick = () => { S.view = v.key; renderAll(); };
    tabs.append(b);
  }
}
function renderView() {
  const body = $('view-body'); body.replaceChildren();
  const fr = src => { const f = document.createElement('iframe'); f.src = src; return f; };
  if (S.view === 'projects') { body.append(renderProjects()); return; }
  if (S.view === 'pipeline') { body.append(renderPipeline()); return; }
  if (S.view === 'compare') { body.append(renderCompare()); return; }
  if (S.view === 'jobs') { body.append(renderJobsNative(scopedJobs())); return; }
  if (S.view === 'airway') { body.append(fr('/workspace/upper-airway.html')); return; }
  if (S.view === 'geometry') {
    if (!S.caseId) { body.append(el('div', '先在顶部选择患者项目，或从项目总览进入。', 'placeholder')); return; }
    const c = S.cases.find(x => caseIdOf(x) === S.caseId);
    const url = c && c.artifacts && c.artifacts.viewer;
    if (url) body.append(fr(url + (url.includes('?') ? '&' : '?') + 'embedded=1'));
    else body.append(el('div', '该病例暂无三维清单（可能仍在处理早期阶段）。', 'placeholder'));
    return;
  }
  if (S.view === 'streamlines') {
    const s = latestStreamlines();
    if (s) body.append(fr(s.url));
    else body.append(el('div', '暂无可用的流线产物：患者任务完成后将自动生成（streamlines.html）。', 'placeholder'));
  }
}
function latestStreamlines() {
  for (const j of scopedJobs()) {
    const a = (j.artifacts || []).find(a => a.name === 'streamlines.html');
    if (a) return {url: a.url, job: j};
  }
  for (const j of S.jobs) {
    const a = (j.artifacts || []).find(a => a.name === 'streamlines.html');
    if (a) return {url: a.url, job: j};
  }
  return null;
}

/* ---------- 中：处理链路视图（P1–P4：依赖链 + 状态语义 + stale 传播） ---------- */
function renderPipeline() {
  const wrap = el('div', undefined, 'view-native pipe-wrap');
  if (!S.caseId) {
    wrap.append(el('p', '处理链路是患者项目内部的参数化流水树。先在顶部选择患者项目。', 'placeholder'));
    return wrap;
  }
  const c = S.cases.find(x => caseIdOf(x) === S.caseId);
  const st = pipelineStates(S.caseId);
  const mk = metricKeyOf(S.caseId);
  const mp = mk && S.metrics ? S.metrics.patients[mk] : null;
  const head = el('div', undefined, 'pipe-head');
  head.append(el('span', '患者项目 ' + S.caseId.slice(0, 14) + '… · 处理链路', 'pipe-title'));
  head.append(el('span', '状态语义：✓ 有产物 · ✗ 失败 · ⊘ 上游失效（stale） · … 待上游 · ◌ 未开始 · ◇ 工作台无记录', 'pipe-legend'));
  wrap.append(head);

  const chain = el('div', undefined, 'pipe-chain');
  for (const f of FLOW) {
    const s = st[f.key];
    const node = el('div', undefined, 'pipe-node ' + s
      + (S.sel && S.sel.kind === 'flow' && S.sel.key === f.key ? ' sel' : ''));
    node.append(el('span', f.no, 'pno'));
    node.append(el('span', s === 'done' ? '✓' : s === 'fail' ? '✗' : s === 'stale' ? '⊘'
      : s === 'wait' ? '…' : s === 'norec' ? '◇' : '◌', 'pst'));
    const meta = el('div', undefined, 'pmeta');
    meta.append(el('span', f.label, 'plbl'));
    meta.append(el('span', f.sub, 'psub'));
    node.append(meta);
    if (f.dep.length) node.append(el('span', '← ' + f.dep.map(d =>
      (FLOW.find(x => x.key === d) || {}).label || d).join(' + '), 'pdep'));
    node.onclick = () => { S.sel = {kind: 'flow', key: f.key}; renderAll(); };
    chain.append(node);
    if (f.key !== FLOW[FLOW.length - 1].key) chain.append(el('span', '↓', 'parrow'));
  }
  wrap.append(chain);

  /* 选中节点详情 */
  if (S.sel && S.sel.kind === 'flow') {
    const f = FLOW.find(x => x.key === S.sel.key);
    if (f) {
      const sec = el('div', undefined, 'pipe-detail');
      sec.append(el('h4', f.no + ' ' + f.label + ' · ' + f.sub));
      sec.append(el('p', f.desc, 'pipe-desc'));
      const dl = el('dl', undefined, 'kv-grid');
      const kv2 = (k, v) => { const r = el('div'); r.append(el('dt', k));
        r.append(el('dd', v == null || v === '' ? '—' : String(v))); dl.append(r); };
      kv2('节点状态', {done: '有产物', fail: '失败', stale: '上游失效', wait: '待上游',
        norec: '工作台无记录', todo: '未开始'}[st[f.key]]);
      kv2('上游依赖', f.dep.length ? f.dep.map(d => (FLOW.find(x => x.key === d) || {}).label).join(' + ') : '无（入口节点）');
      kv2('下游', (FLOW.filter(x => x.dep.includes(f.key)).map(x => x.label).join(' + ')) || '无（末端节点）');
      if (f.key === 'source' && c) {
        kv2('导入状态', c.error ? '失败：' + String(c.error).slice(0, 60) : '正常');
        kv2('文件数', c.file_count);
        kv2('创建', String(c.created_at || '').slice(0, 19));
      }
      if (f.key === 'locate' && c) kv2('候选点数', c.landmark_count);
      if (f.key === 'geometry' && c && c.geometry) {
        const g = c.geometry;
        kv2('CT 尺寸', g.size_xyz ? g.size_xyz.join(' × ') : null);
        kv2('像元 mm', g.spacing_xyz_mm ? g.spacing_xyz_mm.map(v => +(+v).toFixed(3)).join(' / ') : null);
        kv2('HU 范围', g.hu_range ? g.hu_range.join(' ~ ') : null);
      }
      if (f.key === 'config' && mp) {
        kv2('求解配置', mp.domain);
        kv2('数值验证', mp.validation);
        kv2('口径注记', mp.domain_note);
      }
      if (f.key === 'post' && mp) {
        for (const k of ['R_Pa_s_ml', 'delta_p_Pa', 'wss_median_Pa', 'wss_integral_N']) {
          const m = mp.metrics[k];
          if (m) kv2(m.label + (m.unit ? '（' + m.unit + '）' : ''),
            m.value == null ? '—（' + (m.note || '未产') + '）' : m.value);
        }
      }
      if (f.key === 'report' && mp) {
        kv2('结论卡出处', mp.metrics.R_Pa_s_ml.source || '—');
        kv2('临床状态', mp.clinical_status);
      }
      sec.append(dl);
      sec.append(el('p', '节点详情只显示 API 真实字段与已核验搬运值（patient_metrics.json）；'
        + '无出处数据一律「—」，不推断不补造。', 'notice'));
      wrap.append(sec);
    }
  }
  return wrap;
}

/* ---------- 中：项目总览（患者即项目） ---------- */
function renderProjects() {
  const wrap = el('div', undefined, 'view-native');
  const grid = el('div', undefined, 'proj-grid');
  for (const c of S.cases) {
    const id = caseIdOf(c);
    const jobs = jobsOfCase(id);
    const mk = metricKeyOf(id);
    const card = el('div', undefined, 'proj-card' + (id === S.caseId ? ' sel' : '') + (c.error ? ' is-error' : ''));
    const head = el('div', undefined, 'proj-head');
    head.append(el('span', id.slice(0, 14) + '…', 'proj-id'));
    head.append(el('span', c.synthetic ? '仿真项目' : (STAGE_LABEL[c.active_stage] || c.active_stage || '—'),
      'stat ' + (c.error ? 'failed' : (c.synthetic ? 'running' : (c.active_stage === 'completed' ? 'completed' : 'running')))));
    card.append(head);
    const dl = el('dl', undefined, 'proj-facts');
    const f = (k, v) => { const r = el('div'); r.append(el('dt', k)); r.append(el('dd', v)); dl.append(r); };
    f('来源', c.kind || '—');
    f('文件数', c.file_count ?? '—');
    f('候选点', c.landmark_count ?? '—');
    f('几何', c.geometry ? '已生成' : '—');
    f('任务', jobs.length ? jobs.length + ' 项' : '—');
    f('功能指标', mk ? '已核验（' + (S.metrics.patients[mk].metrics.R_Pa_s_ml.source || '?') + '）' : '—');
    f('创建', String(c.created_at || '').slice(0, 10) || '—');
    if (c.geometry && c.geometry.spacing_xyz_mm)
      f('层距/像元', c.geometry.spacing_xyz_mm.map(v => +(+v).toFixed(3)).join(' / ') + ' mm');
    card.append(dl);
    if (c.error) card.append(el('div', '导入失败：' + String(c.error).slice(0, 50), 'notice bad'));
    if (c.synthetic) card.append(el('div', c._note || '仿真项目（jobs API 派生）', 'notice'));
    const open = el('button', '进入项目 →', 'proj-open');
    open.onclick = () => { S.caseId = id; $('case-select').value = id; S.view = 'pipeline'; renderAll(); };
    card.append(open);
    grid.append(card);
  }
  wrap.append(grid);
  const note = el('p', '项目 = 一位患者的完整工程容器（数据 → 几何 → 任务 → 产物）。'
    + '失败导入的项目保留在列并如实标注，不做隐藏或删除。', 'proj-note');
  wrap.append(note);
  return wrap;
}

/* ---------- 中：对比视图（T-055 重设计：V1 参考带 + V2 配对） ---------- */
function caseOptionList(selEl, current) {
  selEl.replaceChildren();
  const empty = el('option', '（选择患者项目）', '');
  empty.value = ''; selEl.append(empty);
  for (const c of S.cases) {
    const id = caseIdOf(c);
    const o = el('option', id.slice(0, 14) + '…', '');
    o.value = id; selEl.append(o);
  }
  selEl.value = current || '';
}
/* 参考带判定：低于 / 入带 / 高于 / 无数据（如实标注，不评分） */
function bandPos(val, ref) {
  if (val == null || !ref) return {txt: '无数据', cls: 'na', why: '本指标未提取或未求解'};
  if (ref.band) {
    if (val < ref.band[0]) return {txt: '低于参考带', cls: 'low', why: '< ' + ref.band[0] + ' ' + ref.unit};
    if (val > ref.band[1]) return {txt: '高于参考带', cls: 'high', why: '> ' + ref.band[1] + ' ' + ref.unit};
    return {txt: '入带', cls: 'in', why: ref.band[0] + '–' + ref.band[1] + ' ' + ref.unit};
  }
  if (ref.band_min != null && val < ref.band_min) return {txt: '低于参考下限', cls: 'low', why: '< ' + ref.band_min + ' ' + ref.unit};
  if (ref.value != null) {
    if (val < ref.value) return {txt: '低于参考值', cls: 'low', why: '< ' + ref.value + ' ' + ref.unit};
    return {txt: '高于参考值', cls: 'high', why: '> ' + ref.value + ' ' + ref.unit};
  }
  return {txt: '—', cls: 'na', why: '参考带未定义'};
}
const REF_MAP = [
  ['R_Pa_s_ml', 'iscoana_R_Pa_s_ml'],
  ['outlet_area_mm2', 'choana_area_mm2'],
];
function renderCompare() {
  const wrap = el('div', undefined, 'view-native compare-wrap');
  /* 模式切换 */
  const bar = el('div', undefined, 'cmp-bar');
  const mRef = el('button', 'V1 · 个体 vs 参考带', 'vtab' + (S.cmp.mode === 'ref' ? ' on' : ''));
  const mPair = el('button', 'V2 · 配对对照', 'vtab' + (S.cmp.mode === 'pair' ? ' on' : ''));
  mRef.onclick = () => { S.cmp.mode = 'ref'; renderAll(); };
  mPair.onclick = () => { S.cmp.mode = 'pair'; renderAll(); };
  bar.append(mRef, mPair);
  bar.append(el('span', '症状 vs 正常人的分组队列（V3）需先建正常参考数据集 → 缓建（患者需求文档 L43）', 'cmp-hint'));
  wrap.append(bar);

  if (S.cmp.mode === 'ref') { wrap.append(renderCompareRef()); return wrap; }
  wrap.append(renderComparePair());
  return wrap;
}
function renderCompareRef() {
  const wrap = el('div');
  const bar = el('div', undefined, 'cmp-bar');
  bar.append(el('span', '患者', 'cmp-tag'));
  const sel = el('select'); caseOptionList(sel, S.cmp.a || S.caseId); bar.append(sel);
  sel.onchange = () => { S.cmp.a = sel.value || null; renderAll(); };
  wrap.append(bar);
  const id = S.cmp.a || S.caseId;
  const mk = id ? metricKeyOf(id) : null;
  const mp = mk && S.metrics ? S.metrics.patients[mk] : null;
  if (!mp) {
    wrap.append(el('p', id ? '该项目暂无已核验功能指标（patient_metrics.json 无记录）。'
      + '指标来源限定为已 VERIFIED 结论卡搬运，不做实时推算。' : '选择患者项目后显示其三指标 vs 参考带。', 'muted'));
    return wrap;
  }
  const refs = S.metrics.references;
  /* 口径条 */
  wrap.append(el('p', '口径：' + mp.domain + ' · 数值验证 ' + mp.validation
    + ' · ' + mp.clinical_status, 'cmp-domain'));
  if (mp.domain_note) wrap.append(el('p', mp.domain_note, 'proj-note'));

  const tb = el('table', undefined, 'jobs-table cmp-table');
  const head = el('tr');
  for (const h of ['指标', '实测值', '参考带（带出处）', '相对位置', '出处 / 注记']) head.append(el('th', h));
  tb.append(head);
  const rows = [];
  for (const [mkey, rkey] of REF_MAP) {
    const m = mp.metrics[mkey], r = refs[rkey];
    if (m) rows.push([m, r]);
  }
  /* S15 温湿行：本项目标未产 → 如实「—」 */
  rows.push([mp.metrics.R_Pa_s_ml && {label: '后鼻孔温度', unit: '℃', value: null, source: null,
    note: '需能量求解（T-043 已立卡未排期）'}, refs.S15_temp_C]);
  for (const [m, r] of rows) {
    if (!m) continue;
    const tr = el('tr');
    tr.append(el('td', m.label + (m.unit ? '（' + m.unit + '）' : '')));
    tr.append(el('td', m.value == null ? '—' : m.value, 'jid'));
    const refTxt = r ? (r.band ? r.band.join('–') : (r.band_min != null ? '≥ ' + r.band_min : r.value)) + ' ' + r.unit
      + '（' + (r.source || '').slice(0, 30) + '）' : '暂无带出处参考带';
    tr.append(el('td', refTxt));
    const pos = bandPos(m.value, r);
    tr.append(el('td', pos.txt, 'pos ' + pos.cls));
    tr.append(el('td', (m.source ? m.source + '；' : '') + (m.note || ''), 'note'));
    tb.append(tr);
  }
  /* WSS 行：无参考锚，仅列实测 */
  for (const k of ['wss_median_Pa', 'wss_max_Pa', 'wss_integral_N']) {
    const m = mp.metrics[k];
    if (!m) continue;
    const tr = el('tr');
    tr.append(el('td', m.label + (m.unit ? '（' + m.unit + '）' : '')));
    tr.append(el('td', m.value == null ? '—' : m.value, 'jid'));
    tr.append(el('td', '暂无带出处参考带'));
    tr.append(el('td', m.value == null ? '无数据' : '仅实测', 'pos na'));
    tr.append(el('td', (m.source ? m.source + '；' : '') + (m.note || ''), 'note'));
    tb.append(tr);
  }
  wrap.append(tb);
  wrap.append(el('p', '参考带只列带出处值（ISCOANA / choana 文献带 / S15 需求文档）。'
    + '相对位置如实标注，不做归一化评分——避免暗示诊断。', 'proj-note'));
  return wrap;
}
function renderComparePair() {
  const wrap = el('div');
  const bar = el('div', undefined, 'cmp-bar');
  bar.append(el('span', 'A', 'cmp-tag'));
  const selA = el('select'); caseOptionList(selA, S.cmp.a); bar.append(selA);
  bar.append(el('span', 'B', 'cmp-tag'));
  const selB = el('select'); caseOptionList(selB, S.cmp.b); bar.append(selB);
  selA.onchange = () => { S.cmp.a = selA.value || null; renderAll(); };
  selB.onchange = () => { S.cmp.b = selB.value || null; renderAll(); };
  wrap.append(bar);

  const mkA = S.cmp.a ? metricKeyOf(S.cmp.a) : null;
  const mkB = S.cmp.b ? metricKeyOf(S.cmp.b) : null;
  const ma = mkA && S.metrics ? S.metrics.patients[mkA] : null;
  const mb = mkB && S.metrics ? S.metrics.patients[mkB] : null;

  /* 双栏三维并排（既有 viewer 嵌入） */
  const panes = el('div', undefined, 'cmp-panes');
  for (const [tag, id, mp] of [['A', S.cmp.a, ma], ['B', S.cmp.b, mb]]) {
    const pane = el('div', undefined, 'cmp-pane');
    pane.append(el('div', tag + ' · ' + (id ? id.slice(0, 14) + '…' : '未选择')
      + (mp ? '（' + mp.domain + '）' : ''), 'cmp-title'));
    if (id) {
      const c = S.cases.find(x => caseIdOf(x) === id);
      const url = c && c.artifacts && c.artifacts.viewer;
      if (url) {
        const f = document.createElement('iframe');
        f.src = url + (url.includes('?') ? '&' : '?') + 'embedded=1';
        pane.append(f);
      } else pane.append(el('div', '该病例暂无三维清单。', 'cmp-empty'));
    } else pane.append(el('div', '选择患者项目后并排显示。', 'cmp-empty'));
    panes.append(pane);
  }
  wrap.append(panes);

  /* 功能指标对照表（H-PAIR：功能指标为主；采集参数降级附录） */
  if (!ma && !mb) {
    wrap.append(el('p', '选择 A / B 两个患者项目后，这里出现功能指标对照。', 'muted'));
    return wrap;
  }
  const keys = [...new Set([...(ma ? Object.keys(ma.metrics) : []),
                            ...(mb ? Object.keys(mb.metrics) : [])])];
  const tb = el('table', undefined, 'jobs-table cmp-table');
  const head = el('tr');
  head.append(el('th', '功能指标'));
  head.append(el('th', 'A' + (S.cmp.a ? ' · ' + S.cmp.a.slice(0, 10) + '…' : '')
    + (ma ? '（' + ma.domain.split('（')[0] + '）' : '')));
  head.append(el('th', 'B' + (S.cmp.b ? ' · ' + S.cmp.b.slice(0, 10) + '…' : '')
    + (mb ? '（' + mb.domain.split('（')[0] + '）' : '')));
  tb.append(head);
  for (const k of keys) {
    const x = ma && ma.metrics[k], y = mb && mb.metrics[k];
    const label = (x || y || {}).label || k;
    const unit = (x || y || {}).unit || '';
    const tr = el('tr');
    tr.append(el('td', label + (unit ? '（' + unit + '）' : '')));
    tr.append(el('td', x && x.value != null ? x.value : '—', 'jid'));
    tr.append(el('td', y && y.value != null ? y.value : '—', 'jid'));
    tb.append(tr);
  }
  wrap.append(tb);
  if (ma && mb && ma.domain !== mb.domain) {
    wrap.append(el('p', '⚠ A/B 域口径不同（' + ma.domain + ' vs ' + mb.domain
      + '）——Δp 不可比为「修正」，只可比为「域口径差异」（T-054 纪律）。', 'notice bad'));
  }
  /* 采集参数降级：折叠附录 */
  const det = el('details', undefined, 'cmp-appendix');
  det.append(el('summary', '采集参数附录（形态参数，非功能指标）'));
  const tb2 = el('table', undefined, 'jobs-table');
  const h2 = el('tr');
  for (const h of ['采集参数', 'A', 'B']) h2.append(el('th', h));
  tb2.append(h2);
  const geo = id => { const c = S.cases.find(x => caseIdOf(x) === id); return (c && c.geometry) || {}; };
  const ga = geo(S.cmp.a || ''), gb = geo(S.cmp.b || '');
  const appRows = [
    ['CT 尺寸', ga.size_xyz ? ga.size_xyz.join('×') : '—', gb.size_xyz ? gb.size_xyz.join('×') : '—'],
    ['像元 mm', ga.spacing_xyz_mm ? ga.spacing_xyz_mm.map(v => +(+v).toFixed(3)).join('/') : '—',
      gb.spacing_xyz_mm ? gb.spacing_xyz_mm.map(v => +(+v).toFixed(3)).join('/') : '—'],
    ['HU 范围', ga.hu_range ? ga.hu_range.join('~') : '—', gb.hu_range ? gb.hu_range.join('~') : '—'],
  ];
  for (const [k, va, vb] of appRows) {
    const tr = el('tr');
    tr.append(el('td', k)); tr.append(el('td', va, 'jid')); tr.append(el('td', vb, 'jid'));
    tb2.append(tr);
  }
  det.append(tb2);
  wrap.append(det);
  wrap.append(el('p', '对照表只列已核验搬运值；跨病例不做归一化评分或优劣裁判（避免暗示诊断）。'
    + '症状轻重的配对假设（H-PAIR）待第二个以上有 CFD 结果的病例后检验。', 'proj-note'));
  return wrap;
}

/* ---------- 中：任务控制台（原生只读） ---------- */
function renderJobsNative(jobs) {
  const wrap = el('div', undefined, 'view-native');
  if (S.caseId) {
    const crumb = el('p', undefined, 'proj-note');
    crumb.textContent = '当前项目：' + S.caseId.slice(0, 14) + '…（仅显示本项目任务）';
    wrap.append(crumb);
  }
  const tb = el('table', undefined, 'jobs-table');
  const head = el('tr');
  for (const h of ['任务', '类型', '病例', '状态', '阶段', '更新时间', '产物']) head.append(el('th', h));
  tb.append(head);
  for (const j of jobs) {
    const tr = el('tr', undefined, S.sel && S.sel.kind === 'job' && S.sel.key === j.id ? 'sel' : '');
    tr.style.cursor = 'pointer';
    tr.onclick = () => { S.sel = {kind: 'job', key: j.id}; renderAll(); };
    const tdId = el('td', j.id, 'jid');
    tr.append(tdId);
    tr.append(el('td', ACTION_LABEL[j.action] || j.action));
    tr.append(el('td', j.case_id || '—', 'jid'));
    const st = el('td'); st.append(el('span', j.status, 'stat ' + j.status)); tr.append(st);
    tr.append(el('td', j.stage || '—'));
    tr.append(el('td', (j.updated_at || '').slice(0, 19), 'jid'));
    const acts = el('td');
    const box = el('div', undefined, 'acts');
    for (const a of (j.artifacts || [])) {
      const l = el('a', a.label || a.name, 'act-link' + (a.name === 'streamlines.html' ? ' hot' : ''));
      l.href = a.url; l.target = '_blank'; box.append(l);
    }
    acts.append(box); tr.append(acts);
    tb.append(tr);
  }
  wrap.append(tb);
  return wrap;
}

/* ---------- 右：属性面板 ---------- */
function kv(dl, k, v, mono = true) {
  const row = el('div', undefined, 'kv');
  row.append(el('dt', k));
  const dd = el('dd', v === null || v === undefined || v === '' ? '—' : String(v), mono ? '' : 'txt');
  row.append(dd); dl.append(row);
}
function renderProps() {
  const body = $('prop-body'); body.replaceChildren();
  if (S.sel && S.sel.kind === 'job') {
    const j = S.jobs.find(x => x.id === S.sel.key);
    if (j) { renderJobProps(body, j); return; }
  }
  if (S.sel && S.sel.kind === 'flow') {
    const f = FLOW.find(x => x.key === S.sel.key);
    const sec = el('div', undefined, 'prop-sec');
    sec.append(el('h4', '处理节点'));
    const dl = el('dl');
    kv(dl, '编号', f.no); kv(dl, '名称', f.label, false); kv(dl, '说明', f.sub, false);
    kv(dl, '依赖', f.dep.length ? f.dep.map(d => (FLOW.find(x => x.key === d) || {}).label).join(' + ') : '入口', false);
    kv(dl, '当前项目', S.caseId || '—');
    const st = S.caseId ? pipelineStates(S.caseId)[f.key] : 'todo';
    kv(dl, '节点状态', {done: '有产物', fail: '失败', stale: '上游失效', wait: '待上游',
      norec: '工作台无记录', todo: '未开始'}[st], false);
    sec.append(dl);
    sec.append(el('div', '状态由 API 真实字段推导；stale = 上游失败/失效传播（P2/P4），不是「没做」；'
      + '◇ = 该项目为仿真项目（jobs API 派生），其前序记录在工作台外的 WSL case。', 'notice'));
    body.append(sec);
    return;
  }
  if (S.caseId) { renderCaseProps(body); return; }
  body.append(el('p', '选择项目或任务后，这里显示其真实参数。', 'muted'));
}
function renderCaseProps(body) {
  const c = S.cases.find(x => caseIdOf(x) === S.caseId);
  if (!c) return;
  const sec = el('div', undefined, 'prop-sec');
  sec.append(el('h4', '患者项目'));
  const dl = el('dl');
  kv(dl, '项目 ID', caseIdOf(c));
  kv(dl, '来源', c.kind, false);
  kv(dl, '阶段', STAGE_LABEL[c.active_stage] || c.active_stage, false);
  kv(dl, '文件数', c.file_count);
  kv(dl, '候选点', c.landmark_count);
  const g = c.geometry || {};
  kv(dl, 'CT 尺寸', g.size_xyz ? g.size_xyz.join(' × ') : '—');
  kv(dl, '像元 mm', g.spacing_xyz_mm ? g.spacing_xyz_mm.map(v => +(+v).toFixed(3)).join(' / ') : '—');
  kv(dl, 'HU 范围', g.hu_range ? g.hu_range.join(' ~ ') : '—');
  kv(dl, '创建', String(c.created_at || '').slice(0, 19));
  sec.append(dl);
  if (c.error) sec.append(el('div', '导入失败：' + c.error, 'notice bad'));
  const mk = metricKeyOf(S.caseId);
  if (mk && S.metrics) {
    const mp = S.metrics.patients[mk];
    sec.append(el('h4', '已核验功能指标'));
    const dl2 = el('dl');
    for (const k of ['R_Pa_s_ml', 'delta_p_Pa', 'outlet_area_mm2', 'wss_integral_N']) {
      const m = mp.metrics[k];
      if (m) kv(dl2, m.label + (m.unit ? '（' + m.unit + '）' : ''), m.value == null ? '—' : m.value);
    }
    kv(dl2, '域口径', mp.domain, false);
    kv(dl2, '数值验证', mp.validation, false);
    kv(dl2, '临床状态', mp.clinical_status, false);
    sec.append(dl2);
  }
  const jobs = jobsOfCase(S.caseId);
  sec.append(el('h4', '本项目任务 ' + jobs.length + ' 项'));
  if (!jobs.length) sec.append(el('p', '暂无任务。', 'muted'));
  body.append(sec);
}
function renderJobProps(body, j) {
  const sec = el('div', undefined, 'prop-sec');
  sec.append(el('h4', '任务'));
  const dl = el('dl');
  kv(dl, '任务 ID', j.id);
  kv(dl, '类型', ACTION_LABEL[j.action] || j.action, false);
  kv(dl, '病例', j.case_id);
  kv(dl, '状态', j.status);
  kv(dl, '阶段', j.stage);
  kv(dl, '创建', (j.created_at || '').slice(0, 19));
  kv(dl, '更新', (j.updated_at || '').slice(0, 19));
  kv(dl, '退出码', j.exit_code);
  if (j.error) kv(dl, '错误', j.error, false);
  sec.append(dl);
  const r = j.result || {};
  const rkeys = Object.keys(r).filter(k => r[k] !== null && r[k] !== undefined && r[k] !== '');
  if (rkeys.length) {
    sec.append(el('h4', '结果字段'));
    const dl2 = el('dl');
    for (const k of rkeys.slice(0, 10)) {
      const v = typeof r[k] === 'object' ? JSON.stringify(r[k]).slice(0, 80) : r[k];
      kv(dl2, k, v);
    }
    sec.append(dl2);
  }
  if ((j.artifacts || []).length) {
    sec.append(el('h4', '产物 ' + j.artifacts.length + ' 项'));
    const box = el('div', undefined, 'acts');
    for (const a of j.artifacts) {
      const l = el('a', a.label || a.name, 'act-link' + (a.name === 'streamlines.html' ? ' hot' : ''));
      l.href = a.url; l.target = '_blank'; box.append(l);
    }
    sec.append(box);
  }
  if (j.status === 'failed')
    sec.append(el('div', '该任务失败：数值产物仅作原始证据保留，不构成有效气流结果。', 'notice bad'));
  body.append(sec);
}

/* ---------- 底：日志 ---------- */
function renderLog() {
  const body = $('log-body'); body.replaceChildren();
  const evs = [];
  for (const j of S.jobs.slice(0, 8)) {
    const kind = j.status === 'failed' ? 'err' : (j.status === 'completed' ? 'ok' : 'info');
    evs.push({t: (j.updated_at || '').slice(5, 19),
      m: (ACTION_LABEL[j.action] || j.action) + ' ' + j.id.slice(0, 12) + '… → ' + j.status +
         (j.error ? '：' + String(j.error).slice(0, 60) : ''), k: kind});
  }
  $('log-count').textContent = evs.length + ' 条（数据源：/api/simulation/jobs）';
  for (const e of evs) {
    const line = el('div', undefined, 'log-line ' + e.k);
    line.append(el('span', e.t, 'lt')); line.append(el('span', e.m, 'lm'));
    body.append(line);
  }
}

/* ---------- 总装 ---------- */
function renderAll() { renderFlowTree(); renderJobTree(); renderTabs(); renderView(); renderProps(); renderLog(); }
async function boot() {
  try { await loadCases(); } catch (e) { $('chip-cases').textContent = '项目：读取失败'; $('chip-cases').classList.add('bad'); }
  try { await loadJobs(); } catch (e) { $('chip-jobs').textContent = '任务：读取失败'; $('chip-jobs').classList.add('bad'); }
  mergeSyntheticCases();
  await loadMetrics();
  renderAll();
}
$('case-select').addEventListener('change', e => {
  S.caseId = e.target.value || null;
  S.sel = null;                                   // 切换项目清空选中对象（属性面板回到项目级）
  if (S.caseId) { if (S.view === 'projects') S.view = 'pipeline'; }
  else S.view = 'projects';
  renderAll();
});
$('jobs-refresh').addEventListener('click', async () => { await loadJobs(); renderAll(); });
boot();
})();
