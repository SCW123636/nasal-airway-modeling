/* ==========================================================================
   pro.js · 工程工作台 PRO 外壳逻辑
   T-052 P1 外壳 → T-053 患者即项目 → T-055 需求×链路重构 →
   T-056 栏位精简与归位（一数据一入口 + CAE 三栏标准站位）：
   - 左栏 = 患者项目树（master-detail：项目 → 处理链路节点，单选展开），
     状态由 API 真实字段 + 已核验指标文件推导，stale 传播可见（P2/P4 原理）；
   - 中栏 = 图形/数据视图（三维 / 流线 / 对比 / 任务控制台）；
   - 右栏 = 属性面板（P3 PropertyManager：项目 / 节点 / 任务三级详情）；
   - 任务数据只保留「任务控制台」一个入口；顶栏只留品牌 + 临床口径 chip；
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
  streamlines: null,                                 // streamlines_manifest.json（已核验流线产物清单）
  projects: null,                                    // patient_projects.json（已核验患者项目搬运清单）
  caseId: null,                                      // null = 未选项目
  view: 'geometry',
  sel: null,                                         // {kind:'flow'|'job', key}
  cmp: {a: null, b: null, mode: 'ref', pa: null, pb: null},   // ref: V1 患者；pair: pa/pb 两侧模型
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
  {key: 'geometry',    label: '三维检查'},
  {key: 'compare',     label: '对比'},
  {key: 'jobs',        label: '任务控制台'},
];
const ACTION_LABEL = {preflight: '准入预检', run_reference: '参考求解',
  run_pressure_feedback: '共同压力反馈', run_patient_engineering: '患者工程试算'};
const STAGE_LABEL = {import: '导入', segmentation: '分割', localization: '定位',
  review: '审核', geometry: '几何', validation: '验证', completed: '完成'};
const FLOW_ICON = {done: '✓', fail: '✗', stale: '⊘', wait: '…', norec: '◇', todo: '◌'};
const FLOW_STATE_TXT = {done: '有产物', fail: '失败', stale: '上游失效', wait: '待上游',
  norec: '工作台无记录', todo: '未开始'};

/* ---------- 数据 ---------- */
async function jget(path) {
  const r = await fetch(path, {cache: 'no-store'});
  if (!r.ok) throw new Error(path + ' → ' + r.status);
  return r.json();
}
const caseIdOf = c => c.id || c.case_id;
const jobsOfCase = id => S.jobs.filter(j => j.case_id === id);
const scopedJobs = () => S.caseId ? jobsOfCase(S.caseId) : S.jobs;

/* metrics 文件的病例键与 API case_id 的匹配：b15_engineering → b15。
   T-056b：删除前缀 startsWith 回退——b15_engineering_t029a 等变体是不同边界条件的
   独立试算（T-054 纪律：两套管路边界不可混用），不得继承 b15 的已核验指标。 */
function metricKeyOf(caseId) {
  const m = S.metrics && S.metrics.patients;
  if (!m || !caseId) return null;
  if (m[caseId]) return caseId;
  const base = caseId.replace(/_(engineering|trial|case)$/, '');
  if (m[base]) return base;
  return null;
}
async function loadCases() {
  const d = await jget('/api/cases');
  S.cases = d.cases || [];
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
  /* 已核验患者项目搬运清单（T-058）：本项目的患者求解在工作台外（WSL 直跑 simpleFoam）
     完成，job 体系里没有对应记录——清单把它们的身份与已核验产物入口登记进树。
     已在树中的（如 jobs 派生的 b15_engineering）就地富化，不新建重复项目。 */
  for (const p of (S.projects || [])) {
    const cid = p.case_id;
    if (!cid) continue;
    const hit = S.cases.find(c => caseIdOf(c) === cid);
    if (hit) {
      hit._manifest = p;
      if (p.artifacts) hit.artifacts = Object.assign({}, hit.artifacts, p.artifacts);
      continue;
    }
    seen.add(cid);
    S.cases.push({
      id: cid, kind: '已核验患者项目（搬运清单）', synthetic: true, error: null,
      active_stage: null, artifacts: p.artifacts || null, _manifest: p,
      _note: p.note || '工作台外求解：已核验产物搬运，数值以 patient_metrics.json 为准',
    });
    added++;
  }
  return added;
}
async function loadJobs() {
  const d = await jget('/api/simulation/jobs');
  S.jobs = (d.jobs || []).slice().sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''));
}
async function loadMetrics() {
  try {
    S.metrics = await jget('/workspace/pro/patient_metrics.json');
  } catch (e) { S.metrics = null; }
}
/* 已核验流线产物清单（T-057）：今天的患者求解走 WSL 直跑，job 体系里没有 streamlines.html，
   若无此回退则「流线」页永远空白。清单 = 搬运模式（同 patient_metrics.json），不伪造 job 记录。 */
async function loadStreamlines() {
  try {
    const d = await jget('/workspace/pro/streamlines_manifest.json');
    S.streamlines = (d.items || []);
  } catch (e) { S.streamlines = []; }
}
/* 已核验患者项目搬运清单（T-058）：工作台外（WSL）直跑的患者求解没有 job 记录，
   若无此清单则 b01/b02 不出现在患者树、三维检查页也无产物入口。
   清单只挂产物 URL 与出处；数值一律以 patient_metrics.json 为准。 */
async function loadProjects() {
  try {
    const d = await jget('/workspace/pro/patient_projects.json');
    S.projects = (d.items || []);
  } catch (e) { S.projects = []; }
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

/* ---------- 左：患者项目树（master-detail，单选展开；T-056b 为人可读） ---------- */
const GROUPS = [
  {key: 'eng',    label: '患者工程'},
  {key: 'import', label: 'CT 导入'},
  {key: 'ref',    label: '参考解算'},
];
function caseGroup(c) {
  if (!c.synthetic) return 'import';
  return String(caseIdOf(c)).startsWith('reference') ? 'ref' : 'eng';
}
function fmtBytes(b) {
  if (b == null) return null;
  const u = ['B', 'KB', 'MB', 'GB']; let i = 0; let v = +b;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return (i === 0 ? Math.round(v) : (v >= 10 ? Math.round(v) : v.toFixed(1))) + ' ' + u[i];
}
function fmtDT(iso) { const s = String(iso || ''); return s.slice(5, 10) + ' ' + s.slice(11, 16); }
/* 合成项目可读名：已知 id 用语义标签；未知 id 保序替换下划线（不编造名称） */
const SYNTH_LABEL = {
  b15_engineering: 'b15 · 工程试算',
  b15_engineering_t029a: 'b15 · 工程试算 · T-029a',
  reference_split_feedback: '参考解算 · 分流反馈',
  reference_channel: '参考解算 · 通道',
};
function synthLabel(id) { return SYNTH_LABEL[id] || String(id).replace(/_/g, ' · '); }
const IMPORT_STATUS = {awaiting_review: '待审核', failed: '导入失败', interrupted: '已中断'};
function importLabel(c) { return 'CT 导入 · ' + (fmtDT(c.created_at) || '—'); }
function importSub(c) {
  const st = IMPORT_STATUS[c.status] || c.status || '—';
  const sz = fmtBytes(c.total_bytes);
  return st + (sz ? ' · ' + sz : '') + (c.kind ? ' · ' + c.kind : '');
}
function synthSub(c, id) {
  if (c && c._manifest) return '已核验患者项目 · ' + (metricKeyOf(id) ? '已核验指标' : '指标缺记录');
  if (metricKeyOf(id)) return '仿真项目 · 已核验指标';
  /* 只认 run_* 真实求解任务（preflight 不算求解）；取最新一个 run 的状态 */
  const runs = jobsOfCase(id).filter(j => String(j.action || '').startsWith('run_'));
  if (!runs.length) return '仿真项目 · 未求解';
  const latest = runs[0];                                  // jobs 已按 updated_at 降序
  if (latest.status === 'failed') return '仿真项目 · 求解失败';
  if (latest.status === 'completed') return '仿真项目 · 求解完成';
  return '仿真项目 · ' + (latest.status || '状态未知');
}
function projectIcon(c) {
  if (c.synthetic) return ['◇', 'todo'];
  if (c.error || c.status === 'failed') return ['✗', 'fail'];
  if (c.active_stage === 'completed') return ['✓', 'done'];
  return ['◌', 'todo'];
}
function renderProjectTree() {
  const t = $('proj-tree'); t.replaceChildren();
  $('proj-count').textContent = S.cases.length ? S.cases.length + ' 个项目' : '';
  if (!S.cases.length) {
    t.append(el('li', '暂无项目数据（/api/cases 与 jobs API 均无记录）', 'tnode grp'));
    return;
  }
  for (const g of GROUPS) {
    const members = S.cases.filter(c => caseGroup(c) === g.key)
      .sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')));
    if (!members.length) continue;
    const gh = el('li', undefined, 'tgroup');
    gh.append(el('span', g.label));
    gh.append(el('span', String(members.length), 'tcount'));
    t.append(gh);
    for (const c of members) {
      const id = caseIdOf(c);
      const sel = id === S.caseId;
      const [icon, cls] = projectIcon(c);
      const li = el('li', undefined, 'tnode' + (sel ? ' sel' : ''));
      li.append(el('span', sel ? '▾' : '▸', 'caret'));
      li.append(el('span', icon, 'st ' + cls));
      const lbl = el('span', undefined, 'lbl');
      lbl.textContent = c.synthetic
        ? ((c._manifest && c._manifest.label) || synthLabel(id)) : importLabel(c);
      lbl.append(el('span', c.synthetic ? synthSub(c, id) : importSub(c), 'sub'));
      li.append(lbl);
      li.title = (c.synthetic ? (c._note || '仿真项目（jobs API 派生）') : (IMPORT_STATUS[c.status] || c.status || ''))
        + '｜' + id + (c.error ? '｜' + String(c.error).slice(0, 60) : '');
      li.onclick = () => { S.caseId = id; S.sel = null; S.view = 'geometry'; renderAll(); };
      t.append(li);
      /* 选中项目展开其 8 节点处理链（其余折叠，避免树过长） */
      if (!sel) continue;
      const st = pipelineStates(id);
      for (const f of FLOW) {
        const s = st[f.key];
        const ci = el('li', undefined, 'tnode child'
          + (S.sel && S.sel.kind === 'flow' && S.sel.key === f.key ? ' sel' : ''));
        ci.append(el('span', FLOW_ICON[s] || '◌', 'st ' + s));
        const cl = el('span', undefined, 'lbl');
        cl.textContent = f.no + ' ' + f.label;
        ci.append(cl);
        ci.title = f.desc;
        ci.onclick = ev => { ev.stopPropagation();
          S.sel = {kind: 'flow', key: f.key};
          if (f.key === 'geometry' || f.key === 'post') S.view = 'geometry';   /* T-063：三维检查含流线 */
          renderAll(); };
        t.append(ci);
      }
    }
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
  if (S.view === 'geometry') {
    /* T-063/T-064：三维检查 = 单一 3D 视口，模型 + 流线叠加（同一例同一套几何，
       流线经 t058_cut.html?sl= 画进模型场景，不再上下两栏各开一张图） */
    if (!S.caseId) { body.append(el('div', '在左侧选择患者项目，这里显示其三维检查（模型 + 流线）。', 'placeholder')); return; }
    const c = S.cases.find(x => caseIdOf(x) === S.caseId);
    const url = c && c.artifacts && c.artifacts.viewer;
    if (!url) {
      body.append(el('div', '三维模型：该病例暂无三维清单（可能仍在处理早期阶段）。', 'placeholder'));
      return;
    }
    const it = streamlineItemOf(S.caseId);
    const stack = el('div', undefined, 'geo-stack');
    stack.append(el('p', '三维检查：模型 + 流线（同一 3D 视口 · 左键旋转 / 滚轮缩放 / 右键平移）', 'proj-note'));
    const cell = el('div', undefined, 'geo-cell');
    cell.append(fr(url + (url.includes('?') ? '&' : '?') + 'embedded=1'
      + (it ? '&sl=' + encodeURIComponent(it.lines_url) : '')));
    stack.append(cell);
    stack.append(el('p', it
      ? ('流线（产物清单搬运）：' + it.label + ' · ' + it.domain + ' · ' + it.source
        + ' · ' + it.clinical_status)
      : '该病例暂无流线数据，视口内只有模型（患者任务完成后自动补充）。', 'proj-note'));
    body.append(stack);
    return;
  }
  if (S.view === 'compare') { body.append(renderCompare()); return; }
  if (S.view === 'jobs') { body.append(renderJobsNative(scopedJobs())); return; }
}
/* T-063：病例 → 已核验流线条目（含 lines_url）。匹配 = 精确或 item.case_id 为
   病例 id 的工程主项目（'b15' → 'b15_engineering'）；变体（_t029a 等）不回退继承——
   页内没有就只有模型，不画别例/别边界的线冒充。 */
function streamlineItemOf(caseId) {
  if (!caseId) return null;
  return (S.streamlines || []).find(i => i.lines_url &&
    (i.case_id === caseId || i.case_id.startsWith(caseId + '_'))) || null;
}
function linesUrlOf(caseId) {
  const it = streamlineItemOf(caseId);
  return it ? it.lines_url : null;
}

/* ---------- 中：对比视图（T-055 重设计：V1 参考带 + V2 配对） ---------- */
function caseOptionList(selEl, current) {
  selEl.replaceChildren();
  const empty = el('option', '（选择患者项目）', '');
  empty.value = ''; selEl.append(empty);
  for (const c of S.cases) {
    const id = caseIdOf(c);
    const o = el('option', id.length > 16 ? id.slice(0, 16) + '…' : id, '');
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
  ['outlet_area_mm2', 'truncation_outlet_note'],
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
    note: 'T-043 已首跑 PASS，但取值截面裁定为后鼻孔（非域出口）→ 患者级未产'}, refs.S15_temp_C]);
  for (const [m, r] of rows) {
    if (!m) continue;
    const tr = el('tr');
    tr.append(el('td', m.label + (m.unit ? '（' + m.unit + '）' : '')));
    tr.append(el('td', m.value == null ? '—' : m.value, 'jid'));
    const refTxt = r ? (r.band_note ? r.band_note + '（' + (r.source || '').slice(0, 30) + '）'
      : (r.band ? r.band.join('–') : (r.band_min != null ? '≥ ' + r.band_min : r.value)) + ' ' + r.unit
      + '（' + (r.source || '').slice(0, 30) + '）') : '暂无带出处参考带';
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
/* 三维模型可用性：搬运清单的 viewer_case，或产物 URL 的 ?case= 参数。
   只有能解析出模型 id 的病例才进「对比」两侧的选择列表——对比视图放的是模型本身，
   不是各病例的处理界面；选完即把该模型放进对应一侧。 */
function viewerCaseOf(c) {
  if (!c) return null;
  if (c._manifest && c._manifest.viewer_case) return c._manifest.viewer_case;
  const url = c.artifacts && c.artifacts.viewer;
  const m = url ? /[?&]case=([^&]+)/.exec(url) : null;
  return m ? decodeURIComponent(m[1]) : null;
}
function modelCases() {
  const seen = new Set(); const out = [];
  for (const c of S.cases) {
    const vc = viewerCaseOf(c);
    if (!vc || seen.has(vc)) continue;
    seen.add(vc);
    out.push({id: caseIdOf(c), vc, label: (c._manifest && c._manifest.label) || synthLabel(caseIdOf(c))});
  }
  return out;
}
function compareViewerCase(caseId) {
  return caseId ? viewerCaseOf(S.cases.find(x => caseIdOf(x) === caseId)) : null;
}
function modelOptionList(selEl, current) {
  selEl.replaceChildren();
  const empty = el('option', '（选择三维模型）', '');
  empty.value = ''; selEl.append(empty);
  for (const m of modelCases()) {
    const o = el('option', m.label + '（' + m.id + '）', '');
    o.value = m.id; selEl.append(o);
  }
  selEl.value = current || '';
}
function renderComparePair() {
  const wrap = el('div');
  const models = modelCases();
  if (models.length) {
    if (!models.some(m => m.id === S.cmp.pa)) S.cmp.pa = models[0].id;
    if (!models.some(m => m.id === S.cmp.pb)) S.cmp.pb = (models[1] || models[0]).id;
  }
  const bar = el('div', undefined, 'cmp-bar');
  bar.append(el('span', 'A', 'cmp-tag'));
  const selA = el('select'); modelOptionList(selA, S.cmp.pa); bar.append(selA);
  bar.append(el('span', 'B', 'cmp-tag'));
  const selB = el('select'); modelOptionList(selB, S.cmp.pb); bar.append(selB);
  bar.append(el('span', '两侧 = 模型 + 流线综合（有流线的病例叠加；同一相机轨道同步旋转 / 缩放）', 'cmp-hint'));
  selA.onchange = () => { S.cmp.pa = selA.value || null; renderAll(); };
  selB.onchange = () => { S.cmp.pb = selB.value || null; renderAll(); };
  wrap.append(bar);

  /* 三维双视口：单画布两视口 + 共用相机轨道（t058_cmp.html），拖动两侧同步。
     T-063：每侧叠加该病例的流线层（sa/sb，模型+流线综合对比；无流线侧只有模型） */
  const stage = el('div', undefined, 'cmp-stage');
  const vcA = compareViewerCase(S.cmp.pa), vcB = compareViewerCase(S.cmp.pb);
  if (vcA || vcB) {
    const q = new URLSearchParams();
    if (vcA) q.set('a', vcA);
    if (vcB) q.set('b', vcB);
    const sa = linesUrlOf(S.cmp.pa), sb = linesUrlOf(S.cmp.pb);
    if (sa) q.set('sa', sa);
    if (sb) q.set('sb', sb);
    q.set('embedded', '1');
    const f = document.createElement('iframe');
    f.src = '/workspace/t058_cmp.html?' + q.toString();
    f.title = '双侧三维对比（解剖斜切）';
    stage.append(f);
  } else {
    stage.append(el('div', '选择两个患者模型后并排显示三维对比。', 'cmp-empty'));
  }
  wrap.append(stage);

  /* 功能指标对照表（H-PAIR：功能指标为主；采集参数降级附录） */
  const mkA = S.cmp.pa ? metricKeyOf(S.cmp.pa) : null;
  const mkB = S.cmp.pb ? metricKeyOf(S.cmp.pb) : null;
  const ma = mkA && S.metrics ? S.metrics.patients[mkA] : null;
  const mb = mkB && S.metrics ? S.metrics.patients[mkB] : null;
  if (!ma && !mb) {
    wrap.append(el('p', '选择 A / B 两个患者项目后，这里出现功能指标对照。', 'muted'));
    return wrap;
  }
  const keys = [...new Set([...(ma ? Object.keys(ma.metrics) : []),
                            ...(mb ? Object.keys(mb.metrics) : [])])];
  const tb = el('table', undefined, 'jobs-table cmp-table');
  const head = el('tr');
  head.append(el('th', '功能指标'));
  head.append(el('th', 'A' + (S.cmp.pa ? ' · ' + S.cmp.pa.slice(0, 10) + '…' : '')
    + (ma ? '（' + ma.domain.split('（')[0] + '）' : '')));
  head.append(el('th', 'B' + (S.cmp.pb ? ' · ' + S.cmp.pb.slice(0, 10) + '…' : '')
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
  const ga = geo(S.cmp.pa || ''), gb = geo(S.cmp.pb || '');
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

/* ---------- 中：任务控制台（原生只读；刷新随数据入口，T-056） ---------- */
function renderJobsNative(jobs) {
  const wrap = el('div', undefined, 'view-native');
  const head = el('div', undefined, 'jobs-head');
  head.append(el('span', 'CFD 任务 · 只读（数据源 /api/simulation/jobs）', 'jobs-title'));
  const ref = el('button', '⟳ 刷新', 'icon-btn');
  ref.onclick = async () => { await loadJobs(); renderAll(); };
  head.append(ref);
  wrap.append(head);
  if (S.caseId) {
    const crumb = el('p', undefined, 'proj-note');
    crumb.textContent = '当前项目：' + S.caseId.slice(0, 16) + '…（仅显示本项目任务）';
    wrap.append(crumb);
  }
  const tb = el('table', undefined, 'jobs-table');
  const head2 = el('tr');
  for (const h of ['任务', '类型', '病例', '状态', '阶段', '更新时间', '产物']) head2.append(el('th', h));
  tb.append(head2);
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

/* ---------- 右：属性面板（项目 / 节点 / 任务三级） ---------- */
function kv(dl, k, v, mono = true) {
  const row = el('div', undefined, 'kv');
  row.append(el('dt', k));
  const dd = el('dd', v === null || v === undefined || v === '' ? '—' : String(v), mono ? '' : 'txt');
  row.append(dd); dl.append(row);
}
/* 节点级字段（原 T-055 中间链路视图的节点详情，T-056 并入属性面板） */
function flowFields(f, c, mp) {
  const rows = [];
  rows.push(['上游依赖', f.dep.length ? f.dep.map(d => (FLOW.find(x => x.key === d) || {}).label).join(' + ') : '无（入口节点）', false]);
  rows.push(['下游', (FLOW.filter(x => x.dep.includes(f.key)).map(x => x.label).join(' + ')) || '无（末端节点）', false]);
  if (f.key === 'source' && c) {
    rows.push(['导入状态', c.error ? '失败：' + String(c.error).slice(0, 60) : '正常', false]);
    rows.push(['文件数', c.file_count]);
    rows.push(['创建', String(c.created_at || '').slice(0, 19)]);
  }
  if (f.key === 'segment' && c)
    rows.push(['阶段', STAGE_LABEL[c.active_stage] || c.active_stage || '—', false]);
  if (f.key === 'locate' && c) rows.push(['候选点数', c.landmark_count]);
  if (f.key === 'geometry' && c && c.geometry) {
    const g = c.geometry;
    rows.push(['CT 尺寸', g.size_xyz ? g.size_xyz.join(' × ') : null]);
    rows.push(['像元 mm', g.spacing_xyz_mm ? g.spacing_xyz_mm.map(v => +(+v).toFixed(3)).join(' / ') : null]);
    rows.push(['HU 范围', g.hu_range ? g.hu_range.join(' ~ ') : null]);
  }
  if (f.key === 'config' && mp) {
    rows.push(['求解配置', mp.domain, false]);
    rows.push(['数值验证', mp.validation, false]);
    rows.push(['口径注记', mp.domain_note, false]);
  }
  if (f.key === 'post' && mp) {
    for (const k of ['R_Pa_s_ml', 'delta_p_Pa', 'wss_median_Pa', 'wss_integral_N']) {
      const m = mp.metrics[k];
      if (m) rows.push([m.label + (m.unit ? '（' + m.unit + '）' : ''),
        m.value == null ? '—（' + (m.note || '未产') + '）' : m.value]);
    }
  }
  if (f.key === 'report' && mp) {
    rows.push(['结论卡出处', (mp.metrics.R_Pa_s_ml || {}).source || '—', false]);
    rows.push(['临床状态', mp.clinical_status, false]);
  }
  return rows;
}
function renderProps() {
  const body = $('prop-body'); body.replaceChildren();
  if (S.sel && S.sel.kind === 'job') {
    const j = S.jobs.find(x => x.id === S.sel.key);
    if (j) { renderJobProps(body, j); return; }
  }
  if (S.sel && S.sel.kind === 'flow') {
    const f = FLOW.find(x => x.key === S.sel.key);
    if (f) {
      const c = S.caseId ? S.cases.find(x => caseIdOf(x) === S.caseId) : null;
      const mk = S.caseId ? metricKeyOf(S.caseId) : null;
      const mp = mk && S.metrics ? S.metrics.patients[mk] : null;
      const sec = el('div', undefined, 'prop-sec');
      sec.append(el('h4', '处理节点'));
      const dl = el('dl');
      kv(dl, '编号', f.no); kv(dl, '名称', f.label, false); kv(dl, '说明', f.sub, false);
      kv(dl, '当前项目', S.caseId || '—');
      const st = S.caseId ? pipelineStates(S.caseId)[f.key] : 'todo';
      kv(dl, '节点状态', FLOW_STATE_TXT[st], false);
      for (const [k, v, mono] of flowFields(f, c, mp)) kv(dl, k, v, mono !== false);
      sec.append(dl);
      sec.append(el('div', '节点详情只显示 API 真实字段与已核验搬运值（patient_metrics.json）；'
        + '无出处数据一律「—」，不推断不补造。stale = 上游失败/失效传播（P2/P4），不是「没做」；'
        + '◇ = 该项目为仿真项目（jobs API 派生），其前序记录在工作台外的 WSL case。', 'notice'));
      body.append(sec);
      return;
    }
  }
  if (S.caseId) { renderCaseProps(body); return; }
  body.append(el('p', '在左侧选择项目或节点，这里显示其真实参数。', 'muted'));
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
  if (c.synthetic) sec.append(el('div', c._note || '仿真项目（jobs API 派生）', 'notice'));
  /* 已核验搬运清单条目：出处 + 产物入口（三维 = 解剖切检视页） */
  if (c._manifest) {
    const m = c._manifest;
    sec.append(el('h4', '已核验搬运清单'));
    const dlm = el('dl');
    kv(dlm, '出处', m.source, false);
    kv(dlm, '域口径', m.domain, false);
    kv(dlm, '临床状态', m.clinical_status, false);
    sec.append(dlm);
    const box = el('div', undefined, 'acts');
    for (const [k, url] of Object.entries(m.artifacts || {})) {
      const l = el('a', k === 'viewer' ? '解剖切三维检视' : k,
        'act-link' + (k === 'viewer' ? ' hot' : ''));
      l.href = url; l.target = '_blank'; box.append(l);
    }
    if (box.childNodes.length) sec.append(box);
    if (m.note) sec.append(el('p', m.note, 'proj-note'));
  }
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

/* ---------- 总装 ----------
   底：日志面板已于 2026-10-16 按用户指令移除——它与「任务控制台」是同一份 jobs 数据的
   第二个入口（违反「一数据一入口」），且信息量低于控制台表格。任务数据唯一入口 = 任务控制台。 */
function renderAll() { renderProjectTree(); renderTabs(); renderView(); renderProps(); }
async function boot() {
  try { await loadCases(); } catch (e) { S.cases = []; }
  try { await loadJobs(); } catch (e) {}
  await loadProjects();
  mergeSyntheticCases();
  await loadMetrics();
  await loadStreamlines();
  /* 嵌入的三维检视页（t058_cut）内切换病例时回传，保持患者树/属性面板同步 */
  window.addEventListener('message', ev => {
    if (ev.origin !== location.origin) return;
    const d = ev.data;
    if (!d || d.type !== 'nasal-pro-select-case' || !d.case) return;
    const p = (S.projects || []).find(x => x.viewer_case === d.case);
    if (p && p.case_id !== S.caseId) {
      S.caseId = p.case_id; S.sel = null; S.view = 'geometry'; renderAll();
    }
  });
  renderAll();
}
boot();
})();
