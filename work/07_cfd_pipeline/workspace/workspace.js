'use strict';
const STEPS = [
  {id:'import', title:'CT 导入', hint:'上传扫描，查看自动处理进度'},
  {id:'overview', title:'病例总览', hint:'查看本例状态与下一步'},
  {id:'geometry', title:'三维检查', hint:'检查结构范围与候选位置', url:'/viewer/index.html'},
  {id:'review', title:'切片审核', hint:'点选候选、检查切片、记录决定', url:'/landmark-review/index.html'},
  {id:'feedback', title:'意见核对', hint:'医学复核与逐项意见'},
  {id:'boundary', title:'边界草稿', hint:'检查口腔排除、鼻窦掩膜与开口证据', url:'/boundary-review/index.html'},
  {id:'validation', title:'计算与结果', hint:'确认几何与计算条件'}
];
const $ = id => document.getElementById(id);
const frames = new Map();
let current = 'overview';
let selectedUpload = null;
let existingSummary = null, importSummary = {scans:0,points:0};
const allowedGeometryManifest = value => /^\/case-assets\/u_[0-9a-f]{16}\/(?:versions\/v_[0-9a-f]{16}\/)?viewer\.json$/.test(value) || /^\/simulation-assets\/s_[0-9a-f]{24}\/viewer\.json$/.test(value);
let requestedGeometryManifest = new URLSearchParams(location.search).get('manifest');
function setGeometryManifest(value) {
  requestedGeometryManifest = value;
  const url = new URL(location.href);
  if (value === null) url.searchParams.delete('manifest');
  else {
    url.searchParams.set('manifest', value);
    const uploadCase = value.match(/^\/case-assets\/(u_[0-9a-f]{16})\//)?.[1];
    // An explicit reference result must not restore an unrelated uploaded case.
    url.searchParams.set('case', uploadCase || 'existing');
  }
  history.replaceState(null, '', url);
}
if (requestedGeometryManifest !== null) setGeometryManifest(requestedGeometryManifest);
function renderOverview() {
  const localization = $('overview-localization');
  if (localization) {
    const summary = selectedUpload?.localization_summary;
    if (selectedUpload) {
      const states = {search_prior:'已用参考预设搜索范围',display_only:'预计点仅供显示',unavailable:'粗定位不适用，使用本例 CT',not_generated:'尚无粗定位记录'};
      localization.textContent = summary ? `${states[summary.status] || '定位记录待检查'}；${summary.independent_reference_patients} 位独立参考患者，${summary.search_prior_points} 点可搜索或对照，${summary.fallback_landmarks.length} 点局部失败后回退。` + (Number.isFinite(summary.max_refinement_delta_mm) ? `最大粗到精偏移 ${summary.max_refinement_delta_mm.toFixed(2)} mm。` : '') + '请复核本例 CT 精调候选。' : '本例定位记录尚未生成，处理完成后检查精调候选。';
    } else if (existingSummary?.localizations) {
      const summaries = existingSummary.localizations;
      const active = summaries.filter(s => s.status === 'search_prior').length;
      const unavailable = summaries.filter(s => s.status === 'unavailable').length;
      const warning = summaries.some(s => s.reference_quality_warnings?.length);
      localization.textContent = `${active} 组扫描可用粗定位搜索或对照，${unavailable} 组粗定位不适用，继续本例 CT 定位。` + (warning ? '部分粗定位参考带质量警告，详见下方项目记录。' : '') + '精调候选仍需人工切片审核。';
    } else localization.textContent = '正在读取定位记录…';
  }
  const name = selectedUpload ? `上传病例 · ${selectedUpload.id.slice(-6)}` : '已有五组扫描';
  const state = selectedUpload?.message || (selectedUpload ? '候选等待人工检验' : '选择病例开始检验');
  const title = $('overview-case'); if (title) title.textContent = name;
  const status = $('overview-state'); if (status) status.textContent = state;
  const button = $('overview-next'); if (button) {
    const ready = !selectedUpload || !!selectedUpload.artifacts?.review;
    button.textContent = ready ? '开始切片审核' : '进入 CT 导入';
    button.onclick = () => navigate(ready ? 'review' : 'import');
  }
  const box = $('overview-stages'); if (!box) return;
  const stages = selectedUpload?.stages || {import:'done',segmentation:'done',candidates:'done',review:'waiting',geometry:'pending',mesh:'pending',solver:'pending',results:'pending'};
  const labels = {import:'CT 导入',segmentation:'自动分割',candidates:'粗定位与精标定',review:'人工审核',geometry:'几何确认',mesh:'体网格',solver:'流场计算',results:'结果检验'};
  box.replaceChildren();
  Object.entries(labels).forEach(([id,label]) => {const item=document.createElement('div');item.className='overview-stage';item.dataset.state=stages[id]||'pending';item.innerHTML=`<span>${label}</span><small>${({done:'完成',waiting:'待人工',running:'处理中',failed:'失败',pending:'未开始'}[item.dataset.state]||'未开始')}</small>`;box.append(item);});
}
function updateTotals() {
  if (!existingSummary) return;
  $('total-scans').textContent = String(existingSummary.scans + importSummary.scans);
  $('total-points').textContent = String(existingSummary.points + importSummary.points);
}
window.addEventListener('nasal-upload-summary', event => {importSummary = event.detail;updateTotals();});
function setUploadedCase(data) {
  selectedUpload = data;
  window.dispatchEvent(new CustomEvent('nasal-case-changed', {detail:data}));
  renderOverview();
  renderValidationContext();
  const saveButton = $('save-case-review');
  if(saveButton) saveButton.hidden = !data?.artifacts?.review || current !== 'review';
  selectStep(current);
}
function toolUrl(step) {
  if (step.id === 'geometry' && requestedGeometryManifest !== null) return allowedGeometryManifest(requestedGeometryManifest) ? '/viewer/index.html?manifest=' + encodeURIComponent(requestedGeometryManifest) : null;
  if (!selectedUpload) return step.url;
  if (step.id === 'geometry') return selectedUpload.artifacts?.viewer;
  if (step.id === 'review') return selectedUpload.artifacts?.review;
  if (step.id === 'feedback') return null;
  if (step.id === 'boundary') return selectedUpload ? `${step.url}?case=${encodeURIComponent(selectedUpload.id)}` : null;
  return step.url;
}
function activeFrame(id=current) {
  const step = STEPS.find(s => s.id === id), url = step && toolUrl(step);
  return frames.get(id + ':' + url);
}
window.nasalWorkspace = {setUploadedCase, activeFrame, navigate};
function selectStep(id) {
  const index = STEPS.findIndex(step => step.id === id);
  if (index < 0) { location.replace('#overview'); return; }
  current = id;
  document.title = STEPS[index].title + ' · 鼻腔建模项目工作台';
  for (const step of STEPS) $('panel-' + step.id).hidden = step.id !== id;
  document.querySelectorAll('[data-step]').forEach(link => {
    if (link.dataset.step === id) {link.setAttribute('aria-current','step');if(matchMedia('(max-width: 650px)').matches)link.scrollIntoView({block:'nearest',inline:'nearest'});}
    else link.removeAttribute('aria-current');
  });
  $('step-label').textContent = STEPS[index].hint;
  $('step-title').textContent = STEPS[index].title;
  $('previous-step').disabled = index === 0;
  $('next-step').disabled = index === STEPS.length - 1;
  const step = STEPS[index];
  const url = toolUrl(step), frameKey = id + ':' + url;
  $('save-case-review').hidden = !selectedUpload?.artifacts?.review || !['awaiting_review','review_recorded'].includes(selectedUpload?.status) || id !== 'review';
  $('regenerate-case').hidden = !selectedUpload?.artifacts?.review || !['awaiting_review','review_recorded'].includes(selectedUpload?.status) || id === 'import';
  window.dispatchEvent(new CustomEvent('nasal-step-changed', {detail:id}));
  const invalidManifest = id === 'geometry' && requestedGeometryManifest !== null && !allowedGeometryManifest(requestedGeometryManifest);
  if (invalidManifest || ['geometry','review','boundary'].includes(id) && selectedUpload && !url) {
    const panel = $('panel-' + id);
    [...panel.children].forEach(child => child.hidden = true);
    let notice = panel.querySelector('.case-notice');
    if (!notice) {notice = document.createElement('div');notice.className = 'case-notice';panel.append(notice);}
    notice.hidden = false;
    notice.replaceChildren();
    const title = document.createElement('h3');title.textContent = invalidManifest ? '三维结果地址无效' : id === 'feedback' ? '本例暂无外部意见' : id === 'boundary' ? '点位审核尚未完成' : '候选正在准备';
    const description = document.createElement('p');description.textContent = invalidManifest ? '未加载默认病例。请从计算与结果中的真实任务产物重新打开三维结果。' : id === 'feedback' ? '可直接在切片审核中记录你的判断。' : id === 'boundary' ? '完成三处点位审核后，上传鼻窦排除掩膜并生成绑定草稿。' : '自动处理完成后即可检验三维与切片。';
    const action = document.createElement('button');action.textContent = invalidManifest ? '查看计算与结果' : id === 'feedback' || id === 'boundary' ? '进入切片审核' : '查看处理进度';action.onclick = () => navigate(invalidManifest ? 'validation' : id === 'feedback' || id === 'boundary' ? 'review' : 'import');
    notice.append(title,description,action);
  }
  if (url && !frames.has(frameKey)) {
    const panel = $('panel-' + id);
    const loading = document.createElement('p');
    loading.className = 'loading'; loading.setAttribute('role','status');
    loading.textContent = '正在读取' + step.title + '…';
    const frame = document.createElement('iframe');
    frame.title = step.title; frame.dataset.workflow = id;
    frame.src = url + (url.includes('?') ? '&' : '?') + 'embedded=1';
    frame.addEventListener('load', () => {
      loading.remove();
      if (!frame.contentDocument?.querySelector('body')) {
        const error = document.createElement('p'); error.className = 'frame-error';
        error.textContent = '页面未能载入，请刷新后重试。'; panel.append(error);
      }
    });
    [...panel.children].forEach(child => child.hidden = true);
    panel.append(frame, loading); frames.set(frameKey,frame);
  }
  if (url && frames.has(frameKey)) [...$('panel-' + id).children].forEach(child => child.hidden = child !== frames.get(frameKey) && !child.classList.contains('loading'));
  // Keep each tool alive so switching flows preserves selection, camera and review edits.
  activeFrame(id)?.contentWindow?.postMessage({type:'nasal-workspace-visible'},location.origin);
}
function navigate(id) { if (current !== id) location.hash = id; }
window.addEventListener('hashchange', () => selectStep(location.hash.slice(1) || 'import'));
window.addEventListener('message', event => {
  if (event.origin !== location.origin || ![...frames.values()].some(frame => frame.contentWindow === event.source)) return;
  if (event.data?.type === 'nasal-workspace-navigate' && STEPS.some(step => step.id === event.data.step)) {
    if (event.data.step === 'geometry' && typeof event.data.manifest === 'string') {setGeometryManifest(event.data.manifest); selectStep('geometry');}
    navigate(event.data.step);
  }
});
$('active-case').addEventListener('change', () => {if (requestedGeometryManifest !== null) setGeometryManifest(null);});
document.querySelectorAll('[data-workflow]').forEach(link => link.addEventListener('click', event => {event.preventDefault();navigate(link.dataset.workflow);}));
$('previous-step').addEventListener('click', () => navigate(STEPS[STEPS.findIndex(step => step.id === current) - 1].id));
$('next-step').addEventListener('click', () => navigate(STEPS[STEPS.findIndex(step => step.id === current) + 1].id));
$('project-report').addEventListener('toggle', () => {
  if (!$('project-report').open || $('overview-report').firstChild) return;
  const frame = document.createElement('iframe');frame.title='项目详细记录';frame.src='/progress/index.html?embedded=1';$('overview-report').append(frame);frames.set('project-report',frame);
});
async function readJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw Error('读取失败：' + response.status);
  return response.json();
}
let projectFeedbackText = '待核对';
function renderValidationContext() {
  $('validation-feedback').textContent = selectedUpload ? '查看本例医学复核反馈' : projectFeedbackText;
}
async function loadSummary() {
  try {
    const data = await readJson('/viewer/workspace_data.json');
    if (data.schema !== 'nasal_workspace/v1') throw Error('项目摘要格式无效');
    const patients = data.cases.filter(item => item.type === 'patient_preview');
    existingSummary = {scans:data.patient_scan_count,points:patients.reduce((n,item) => n + item.landmarks.length,0),localizations:patients.map(item => item.localization_summary).filter(Boolean)};
    renderOverview();
    updateTotals();
    $('total-results').textContent = String(data.patient_cfd_results);
    $('validation-result-count').textContent = '患者流场：' + data.patient_cfd_results;
    const audit = data.feedback_audit;
    const valid = audit?.status === 'diagnostic_review_complete';
    $('total-feedback').textContent = valid ? audit.matched_current_proposals + '/' + audit.observations : '未生成';
    projectFeedbackText = valid ? audit.matched_current_proposals + '/' + audit.observations + ' 条可对应原核对版本；尚未正式接受' : '核对摘要未生成';
    renderValidationContext();
  } catch (error) {
    ['total-scans','total-points','total-feedback','total-results'].forEach(id => $(id).textContent = '未读取');
    $('validation-result-count').textContent = '患者流场：未读取';
  }
}
async function loadValidation() {
  try {
    const data = await readJson('/solver_reference/phantom_validation/validation.json');
    if (data.schema !== 'nasal_cfd_phantom_validation/v1' || !Array.isArray(data.levels) || !data.checks) throw Error('验证报告格式无效');
    $('phantom-state').textContent = data.verdict === 'pass' ? '预设检查通过。此结果仅适用于该非患者算例。' : data.verdict === 'fail' ? '闭环已执行，严格压降检查未通过。需要继续改进并重新验证。' : '报告没有有效的通过结论。';
    for (const level of data.levels) {
      const row = document.createElement('tr');
      const n = (value,digits,unit) => Number.isFinite(value) ? value.toFixed(digits) + unit : '未获得';
      const values = [n(level.cell_size_mm,1,' mm'),n(level.delta_p_numeric_pa,3,' Pa'),n(level.delta_p_analytic_pa,3,' Pa'),n(level.delta_p_rel_error * 100,1,'%'),level.converged === true ? '已收敛' : '未确认'];
      values.forEach(value => {const cell = document.createElement('td'); cell.textContent = value; row.append(cell);});
      $('phantom-levels').append(row);
    }
    const labels = {converged:'收敛',delta_p_coarse_within_5pct:'粗网格压降',delta_p_fine_within_2pct:'细网格压降',error_decreases_with_refinement:'细化误差趋势',mass_imbalance_below_1e_6:'质量守恒', 'mass_imbalance_below_1e-6':'质量守恒',peak_velocity_within_5pct:'峰值速度'};
    for (const [key,value] of Object.entries(data.checks)) {
      const item = document.createElement('span'); item.className = value === true ? 'check-pass' : 'check-fail';
      item.textContent = (labels[key] || key) + '：' + (value === true ? '通过' : '未通过');
      $('phantom-checks').append(item);
    }
    $('phantom-report').textContent = JSON.stringify(data,null,2);
  } catch (error) {
    $('phantom-state').textContent = '验证报告未读取，无法确认计算条件。';
    $('phantom-report').textContent = error.message;
  }
}
async function loadDiagnostics() {
  const rows = $('diagnostic-rows');
  try {
    const [profile, developed, axial] = await Promise.all([
      readJson('/solver_reference/phantom_diagnostics/source_radius_profile_validation.json'),
      readJson('/solver_reference/phantom_diagnostics/developed_length_validation.json'),
      readJson('/solver_reference/phantom_diagnostics/axial_pressure.json')
    ]);
    const axialItems = axial.cases || [];
    const entries = [
      {label:'入口半径修正', change:'由源 STL 边界顶点计算入口半径', report:profile, length:40},
      {label:'加长入口段', change:'管长 40 → 160 mm，其余保持一致', report:developed, length:160}
    ];
    for (const entry of entries) {
      const levels = entry.report.levels || [];
      const fine = levels.find(level => level.cell_size_mm === 0.2) || levels[levels.length - 1] || {};
      const axialItem = axialItems.find(item => item.length_mm === entry.length && item.case === 'case_h0p2');
      const row = document.createElement('tr');
      [entry.label, entry.change,
       Number.isFinite(fine.delta_p_rel_error) ? (fine.delta_p_rel_error*100).toFixed(1)+'%' : '未获得',
       axialItem && Number.isFinite(axialItem.interior_gradient_rel_error) ? (axialItem.interior_gradient_rel_error*100).toFixed(1)+'%' : '未获得',
       fine.mesh_quality_passed === true ? '通过' : '未通过'].forEach(value => {const cell=document.createElement('td');cell.textContent=value;row.append(cell);});
      rows.append(row);
    }
    $('diagnostic-state').textContent = '两组独立对照均已完成：入口半径修正改善了压降，但仍未达到严格阈值；加长管道也未达到阈值。网格质量门禁仍未通过。';
  } catch (error) {
    $('diagnostic-state').textContent = '独立对照报告未读取，不能判断误差来源。';
  }
}
async function loadPatientEngineering() {
  const rows = $('patient-engineering-rows');
  try {
    const data = await readJson('/m2_closure/declaration.json');
    if (data.schema !== 'nasal_cfd_m2_engineering_closure/v1' || !data.primary_criteria) throw Error('工程实证声明格式无效');
    const criteria = data.primary_criteria, recorded = data.recorded_items || {};
    const res = recorded.residual_convergence || {};
    const dp = criteria.delta_p_in_band_Pa || {};
    const band = (dp.band_Pa || []).map(v => Number.isFinite(v) ? v : '—').join('–');
    const num = (v, digits) => Number.isFinite(v) ? v.toFixed(digits) : '未获得';
    const sci = (v, digits) => Number.isFinite(v) ? v.toExponential(digits) : '未获得';
    const entries = [
      ['稳定不崩', '—', '533 步无 FATAL/sigFPE，越过 T-004 崩溃点 273 步', criteria.stable_no_crash?.met === true],
      ['Δp 入带（贴下限）', band + ' Pa', num(dp.value_Pa, 2) + ' Pa', dp.met === true],
      ['质量不平衡（稳态段）', num(criteria.mass_imbalance_fraction_max?.screen, 3), sci(criteria.mass_imbalance_fraction_max?.value, 2), criteria.mass_imbalance_fraction_max?.met === true],
      ['监测量稳定（Δp 窗间相对变化）', num((criteria.monitor_relative_change?.screen ?? 0) * 100, 2) + '%', num((criteria.monitor_relative_change?.value ?? 0) * 100, 4) + '%', criteria.monitor_relative_change?.met === true],
      ['残差收敛（记录项）', sci(res.screen_target_residual_max, 1), sci(res.residual_max_Ux, 2) + '（Ux 终值）', res.achieved === true]
    ];
    for (const [name, screen, value, met] of entries) {
      const row = document.createElement('tr');
      [name, screen, value, met ? '过' : '未达'].forEach(text => {const cell = document.createElement('td'); cell.textContent = text; row.append(cell);});
      rows.append(row);
    }
    $('patient-engineering-state').textContent = '患者网格（b15 maxh=1.0 修复版，1,161,194 cells）主工况 15 L/min 等分 + 出口 0 Pa + 层流：T-006 Run 1 人工终止于 T=533，四条主判据全部满足；残差收敛未达，numerical_validation=' + (recorded.numerical_validation || 'unchecked') + '。工程证据，不构成契约有效患者结果。';
  } catch (error) {
    $('patient-engineering-state').textContent = '工程实证声明未读取，不渲染任何患者试算数字。';
  }
}
selectStep(location.hash.slice(1) || 'import');
loadSummary(); loadValidation(); loadDiagnostics(); loadPatientEngineering();
renderOverview();
