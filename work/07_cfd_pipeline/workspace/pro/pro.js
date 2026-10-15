/* ==========================================================================
   pro.js · 工程工作台 PRO 外壳逻辑（T-052 P1 → T-053 P2：患者即项目 + 对比）
   数据全部只读自既有 API；状态与指标严格由 API 字段推导，缺数据如实「—」。
   ========================================================================== */
'use strict';
(() => {
const $ = id => document.getElementById(id);
const el = (tag, text, cls) => { const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; };

/* ---------- 状态 ---------- */
const S = {
  cases: [], jobs: [], caseId: null,           // null = 项目总览（全局）
  view: 'projects',
  sel: null,                                    // {kind:'flow'|'job', key}
  cmp: {a: null, b: null},
};
const FLOW = [
  {key: 'import',    no: '01', label: 'CT 导入',    sub: '上传与自动处理'},
  {key: 'geometry',  no: '03', label: '三维检查',   sub: '结构与候选位置'},
  {key: 'review',    no: '04', label: '切片审核',   sub: '逐点检验与记录'},
  {key: 'airway',    no: '07', label: '咽部扩展',   sub: '口咽候选与覆盖'},
  {key: 'compute',   no: '08', label: '计算与结果', sub: '准入 · 任务 · 产物'},
];
const VIEWS = [
  {key: 'projects',    label: '项目总览'},
  {key: 'geometry',    label: '三维检查'},
  {key: 'airway',      label: '咽部扩展'},
  {key: 'progress',    label: '进度总览'},
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

async function loadCases() {
  const d = await jget('/api/cases');
  S.cases = d.cases || [];
  $('chip-cases').textContent = '项目：' + S.cases.length;
  $('chip-cases').classList.add('ok');
  const sel = $('case-select');
  sel.replaceChildren();
  const all = el('option', '（全部项目 · 总览）', '');
  all.value = ''; sel.append(all);
  for (const c of S.cases) {
    const id = caseIdOf(c);
    const o = el('option', id.slice(0, 14) + '… · ' + (STAGE_LABEL[c.active_stage] || c.active_stage || '?'), '');
    o.value = id; sel.append(o);
  }
  sel.value = '';
}
async function loadJobs() {
  const d = await jget('/api/simulation/jobs');
  S.jobs = (d.jobs || []).slice().sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''));
  const run = S.jobs.filter(j => ['running', 'queued'].includes(j.status)).length;
  $('chip-jobs').textContent = '任务：' + S.jobs.length + (run ? '（' + run + ' 进行）' : '');
  $('chip-jobs').classList.toggle('ok', run === 0);
}

/* ---------- 左树：项目工作流（按当前项目子集化） ---------- */
function flowState(key) {
  if (!S.caseId) return 'todo';
  const c = S.cases.find(x => caseIdOf(x) === S.caseId);
  if (!c) return 'todo';
  if (key === 'import') return 'done';
  if (key === 'geometry') return c.geometry ? 'done' : 'todo';
  if (key === 'review') return (c.landmark_count || 0) > 0 ? 'done' : 'todo';
  if (key === 'compute') return jobsOfCase(S.caseId).length ? 'done' : 'todo';
  return 'todo';
}
function renderFlowTree() {
  const t = $('flow-tree'); t.replaceChildren();
  if (!S.caseId) {
    t.append(el('li', '先在顶部选择患者项目（或点项目卡片进入）。', 'tnode grp'));
    return;
  }
  for (const f of FLOW) {
    const st = flowState(f.key);
    const li = el('li', undefined, 'tnode' + (S.sel && S.sel.kind === 'flow' && S.sel.key === f.key ? ' sel' : ''));
    li.append(el('span', st === 'done' ? '✓' : '◌', 'st ' + st));
    const lbl = el('span', undefined, 'lbl');
    lbl.textContent = f.no + ' ' + f.label;
    lbl.append(el('span', f.sub, 'sub'));
    li.append(lbl);
    li.onclick = () => { S.sel = {kind: 'flow', key: f.key};
      if (f.key === 'geometry') S.view = 'geometry';
      else if (f.key === 'airway') S.view = 'airway';
      else if (f.key === 'compute') S.view = 'jobs';
      else if (f.key === 'review') openCaseArtifact('review');
      renderAll(); };
    t.append(li);
  }
}
function openCaseArtifact(kind) {
  const c = S.cases.find(x => caseIdOf(x) === S.caseId);
  const url = c && c.artifacts && c.artifacts[kind];
  if (url) window.open(url, '_blank');
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
  if (S.view === 'compare') { body.append(renderCompare()); return; }
  if (S.view === 'jobs') { body.append(renderJobsNative(scopedJobs())); return; }
  if (S.view === 'progress') { body.append(fr('/progress/index.html?embedded=1')); return; }
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

/* ---------- 中：项目总览（患者即项目） ---------- */
function renderProjects() {
  const wrap = el('div', undefined, 'view-native');
  const grid = el('div', undefined, 'proj-grid');
  for (const c of S.cases) {
    const id = caseIdOf(c);
    const jobs = jobsOfCase(id);
    const card = el('div', undefined, 'proj-card' + (id === S.caseId ? ' sel' : '') + (c.error ? ' is-error' : ''));
    const head = el('div', undefined, 'proj-head');
    head.append(el('span', id.slice(0, 14) + '…', 'proj-id'));
    head.append(el('span', STAGE_LABEL[c.active_stage] || c.active_stage || '—',
      'stat ' + (c.error ? 'failed' : (c.active_stage === 'completed' ? 'completed' : 'running'))));
    card.append(head);
    const dl = el('dl', undefined, 'proj-facts');
    const f = (k, v) => { const r = el('div'); r.append(el('dt', k)); r.append(el('dd', v)); dl.append(r); };
    f('来源', c.kind || '—');
    f('文件数', c.file_count ?? '—');
    f('候选点', c.landmark_count ?? '—');
    f('几何', c.geometry ? '已生成' : '—');
    f('任务', jobs.length ? jobs.length + ' 项' : '—');
    f('创建', String(c.created_at || '').slice(0, 10));
    if (c.geometry && c.geometry.spacing_xyz_mm)
      f('层距/像元', c.geometry.spacing_xyz_mm.map(v => +(+v).toFixed(3)).join(' / ') + ' mm');
    card.append(dl);
    if (c.error) card.append(el('div', '导入失败：' + String(c.error).slice(0, 50), 'notice bad'));
    const open = el('button', '进入项目 →', 'proj-open');
    open.onclick = () => { S.caseId = id; $('case-select').value = id; S.view = 'geometry'; renderAll(); };
    card.append(open);
    grid.append(card);
  }
  wrap.append(grid);
  const note = el('p', '项目 = 一位患者的完整工程容器（数据 → 几何 → 任务 → 产物）。'
    + '失败导入的项目保留在列并如实标注，不做隐藏或删除。', 'proj-note');
  wrap.append(note);
  return wrap;
}

/* ---------- 中：对比视图 ---------- */
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
function metricRows(id) {
  if (!id) return null;
  const c = S.cases.find(x => caseIdOf(x) === id);
  if (!c) return null;
  const jobs = jobsOfCase(id);
  const g = c.geometry || {};
  const sl = jobs.map(j => (j.artifacts || []).find(a => a.name === 'streamlines.html')).find(Boolean);
  return {
    '来源类型': c.kind || '—',
    '当前阶段': STAGE_LABEL[c.active_stage] || c.active_stage || '—',
    '导入状态': c.error ? '失败：' + String(c.error).slice(0, 24) : '正常',
    '文件数': c.file_count ?? '—',
    '候选点': c.landmark_count ?? '—',
    'CT 尺寸': g.size_xyz ? g.size_xyz.join(' × ') : '—',
    '像元/层距 mm': g.spacing_xyz_mm ? g.spacing_xyz_mm.map(v => +(+v).toFixed(3)).join(' / ') : '—',
    'HU 范围': g.hu_range ? g.hu_range.join(' ~ ') : '—',
    'CFD 任务数': jobs.length || '—',
    'CFD 结果': c.patient_cfd_results ? '有' : '—',
    '流线产物': sl ? '有' : '—',
  };
}
function renderCompare() {
  const wrap = el('div', undefined, 'view-native compare-wrap');
  const bar = el('div', undefined, 'cmp-bar');
  bar.append(el('span', 'A', 'cmp-tag'));
  const selA = el('select'); caseOptionList(selA, S.cmp.a); bar.append(selA);
  bar.append(el('span', 'B', 'cmp-tag'));
  const selB = el('select'); caseOptionList(selB, S.cmp.b); bar.append(selB);
  selA.onchange = () => { S.cmp.a = selA.value || null; renderAll(); };
  selB.onchange = () => { S.cmp.b = selB.value || null; renderAll(); };
  wrap.append(bar);

  const panes = el('div', undefined, 'cmp-panes');
  for (const [tag, id] of [['A', S.cmp.a], ['B', S.cmp.b]]) {
    const pane = el('div', undefined, 'cmp-pane');
    pane.append(el('div', tag + ' · ' + (id ? id.slice(0, 14) + '…' : '未选择'), 'cmp-title'));
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

  const ma = metricRows(S.cmp.a), mb = metricRows(S.cmp.b);
  const keys = [...new Set([...(ma ? Object.keys(ma) : []), ...(mb ? Object.keys(mb) : [])])];
  if (keys.length) {
    const tb = el('table', undefined, 'jobs-table cmp-table');
    const head = el('tr');
    head.append(el('th', '指标'));
    head.append(el('th', 'A' + (S.cmp.a ? ' · ' + S.cmp.a.slice(0, 10) + '…' : '')));
    head.append(el('th', 'B' + (S.cmp.b ? ' · ' + S.cmp.b.slice(0, 10) + '…' : '')));
    tb.append(head);
    for (const k of keys) {
      const tr = el('tr');
      tr.append(el('td', k));
      tr.append(el('td', ma ? String(ma[k]) : '—', 'jid'));
      tr.append(el('td', mb ? String(mb[k]) : '—', 'jid'));
      tb.append(tr);
    }
    wrap.append(tb);
  } else {
    wrap.append(el('p', '选择 A / B 两个患者项目后，这里出现真实指标对照。', 'muted'));
  }
  wrap.append(el('p', '对照表只列 API 真实字段；跨病例不做归一化评分或优劣裁判（避免暗示诊断）。', 'proj-note'));
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
    sec.append(el('h4', '流程节点'));
    const dl = el('dl');
    kv(dl, '编号', f.no); kv(dl, '名称', f.label, false); kv(dl, '说明', f.sub, false);
    kv(dl, '当前项目', S.caseId || '—');
    kv(dl, '节点状态', flowState(f.key) === 'done' ? '完成' : '待办', false);
    sec.append(dl);
    sec.append(el('div', '状态由 API 真实字段推导；未知一律「待办」，不编造完成态。', 'notice'));
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
  renderAll();
}
$('case-select').addEventListener('change', e => {
  S.caseId = e.target.value || null;
  if (S.caseId) { if (S.view === 'projects') S.view = 'geometry'; }
  else S.view = 'projects';
  renderAll();
});
$('jobs-refresh').addEventListener('click', async () => { await loadJobs(); renderAll(); });
boot();
})();
