/* ==========================================================================
   pro.js · 工程工作台 PRO 外壳逻辑（T-052 P1）
   数据全部只读自既有 API；状态图标严格由 API 字段推导，不美化改写。
   ========================================================================== */
'use strict';
(() => {
const API = '';
const $ = id => document.getElementById(id);
const el = (tag, text, cls) => { const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; };

/* ---------- 状态 ---------- */
const S = {
  cases: [], jobs: [], caseId: null,
  view: 'dashboard',      // dashboard | geometry | airway | progress | streamlines | jobs
  sel: null,              // {kind:'flow'|'job', key}
};
const FLOW = [
  {key: 'import',    no: '01', label: 'CT 导入',     sub: '上传与自动处理'},
  {key: 'overview',  no: '02', label: '病例总览',    sub: '状态与下一步'},
  {key: 'geometry',  no: '03', label: '三维检查',    sub: '结构与候选位置'},
  {key: 'review',    no: '04', label: '切片审核',    sub: '逐点检验与记录'},
  {key: 'feedback',  no: '05', label: '意见核对',    sub: '对照意见与原 CT'},
  {key: 'boundary',  no: '06', label: '边界草稿',    sub: '口腔与鼻窦复核'},
  {key: 'airway',    no: '07', label: '咽部扩展',    sub: '口咽候选与覆盖'},
  {key: 'compute',   no: '08', label: '计算与结果',  sub: '准入 · 任务 · 产物'},
];
const VIEWS = [
  {key: 'dashboard',   label: '总览'},
  {key: 'geometry',    label: '三维检查'},
  {key: 'airway',      label: '咽部扩展'},
  {key: 'progress',    label: '进度总览'},
  {key: 'streamlines', label: '流线'},
  {key: 'jobs',        label: '任务控制台'},
];

/* ---------- 数据 ---------- */
async function jget(path) {
  const r = await fetch(API + path, {cache: 'no-store'});
  if (!r.ok) throw new Error(path + ' → ' + r.status);
  return r.json();
}
async function loadCases() {
  const d = await jget('/api/cases');
  S.cases = d.cases || [];
  $('chip-cases').textContent = '病例：' + S.cases.length;
  $('chip-cases').classList.add('ok');
  const sel = $('case-select');
  sel.replaceChildren();
  for (const c of S.cases) {
    const o = el('option', (c.label || c.id || c.case_id), '');
    o.value = c.id || c.case_id; sel.append(o);
  }
  if (S.cases.length) { S.caseId = sel.value = S.cases[0].id || S.cases[0].case_id; }
}
async function loadJobs() {
  const d = await jget('/api/simulation/jobs');
  S.jobs = (d.jobs || []).slice().sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''));
  const run = S.jobs.filter(j => ['running', 'queued'].includes(j.status)).length;
  $('chip-jobs').textContent = '任务：' + S.jobs.length + (run ? '（' + run + ' 进行）' : '');
  $('chip-jobs').classList.toggle('ok', run === 0);
}

/* ---------- 左树：工作流 ---------- */
function flowState(key) {
  // 诚实推导：有病例 → 01 ✓；有三维清单 → 03 ✓；其余未知一律 ◌（不编造完成态）
  if (!S.caseId) return 'todo';
  if (key === 'import') return 'done';
  if (key === 'compute') return S.jobs.some(j => j.case_id === S.caseId) ? 'done' : 'todo';
  return 'todo';
}
function renderFlowTree() {
  const t = $('flow-tree'); t.replaceChildren();
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
      else if (f.key === 'overview') S.view = 'dashboard';
      renderAll(); };
    t.append(li);
  }
}

/* ---------- 左树：CFD 任务 ---------- */
const STATUS_ICON = {completed: ['✓', 'done'], failed: ['✗', 'fail'],
  running: ['▷', 'run'], queued: ['▷', 'run'], interrupted: ['◌', 'fail']};
const ACTION_LABEL = {preflight: '准入预检', run_reference: '参考求解',
  run_pressure_feedback: '共同压力反馈', run_patient_engineering: '患者工程试算'};
function renderJobTree() {
  const t = $('job-tree'); t.replaceChildren();
  if (!S.jobs.length) { t.append(el('li', '暂无任务记录', 'tnode grp')); return; }
  for (const j of S.jobs.slice(0, 12)) {
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
function caseManifestUrl() {
  // 三维清单：仅上传病例（u_ 前缀）按惯例路径；内置病例暂无 → 如实占位
  if (S.caseId && S.caseId.startsWith('u_'))
    return '/case-assets/' + S.caseId + '/viewer.json';
  return null;
}
function latestStreamlines() {
  for (const j of S.jobs) {
    const a = (j.artifacts || []).find(a => a.name === 'streamlines.html');
    if (a) return {url: a.url, job: j};
  }
  return null;
}
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
  const fr = (src) => { const f = document.createElement('iframe'); f.src = src; return f; };
  if (S.view === 'dashboard' || S.view === 'progress') {
    body.append(fr('/progress/index.html?embedded=1'));
  } else if (S.view === 'geometry') {
    const m = caseManifestUrl();
    if (m) body.append(fr('/viewer/index.html?manifest=' + encodeURIComponent(m) + '&embedded=1'));
    else body.append(el('div', '该病例暂无三维清单（内置病例的三维检查仍在旧版工作台 03 号流程）。',
      'placeholder'));
  } else if (S.view === 'airway') {
    body.append(fr('/workspace/upper-airway.html'));
  } else if (S.view === 'streamlines') {
    const s = latestStreamlines();
    if (s) body.append(fr(s.url));
    else body.append(el('div', '暂无可用的流线产物：患者任务完成后将自动生成（streamlines.html）。',
      'placeholder'));
  } else if (S.view === 'jobs') {
    body.append(renderJobsNative());
  }
}

/* ---------- 中：原生任务控制台（P1 只读） ---------- */
function renderJobsNative() {
  const wrap = el('div', undefined, 'view-native');
  const tb = el('table', undefined, 'jobs-table');
  const head = el('tr');
  for (const h of ['任务', '类型', '病例', '状态', '阶段', '更新时间', '产物'])
    head.append(el('th', h));
  tb.append(head);
  for (const j of S.jobs) {
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
  if (!S.sel) { body.append(el('p', '在左侧树中选择对象，这里显示其真实参数。', 'muted')); return; }
  if (S.sel.kind === 'flow') {
    const f = FLOW.find(x => x.key === S.sel.key);
    const sec = el('div', undefined, 'prop-sec');
    sec.append(el('h4', '流程节点'));
    const dl = el('dl');
    kv(dl, '编号', f.no); kv(dl, '名称', f.label, false); kv(dl, '说明', f.sub, false);
    kv(dl, '当前病例', S.caseId || '—');
    kv(dl, '节点状态', flowState(f.key) === 'done' ? '完成' : '待办', false);
    sec.append(dl);
    sec.append(el('div', '状态由 API 真实字段推导；未知一律「待办」，不编造完成态。', 'notice'));
    body.append(sec);
    return;
  }
  const j = S.jobs.find(x => x.id === S.sel.key);
  if (!j) { body.append(el('p', '任务记录未找到（可能已刷新）。', 'muted')); return; }
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
    sec.append(el('h4', '产物 ' + j.artifacts.length + ' 项（点击新窗口打开）'));
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
  try { await loadCases(); } catch (e) { $('chip-cases').textContent = '病例：读取失败'; $('chip-cases').classList.add('bad'); }
  try { await loadJobs(); } catch (e) { $('chip-jobs').textContent = '任务：读取失败'; $('chip-jobs').classList.add('bad'); }
  renderAll();
}
$('case-select').addEventListener('change', e => { S.caseId = e.target.value; renderAll(); });
$('jobs-refresh').addEventListener('click', async () => { await loadJobs(); renderAll(); });
boot();
})();
