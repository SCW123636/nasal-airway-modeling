'use strict';
(() => {
  const $ = id => document.getElementById(id);
  if (!$('simulation-case')) return;
  const running = job => ['queued', 'running'].includes(job?.status);
  const statusLabels = {queued:'排队中',running:'运行中',completed:'已执行',failed:'失败',interrupted:'已中断',pending:'未开始',waiting:'等待',blocked:'受阻',not_started:'未开始',unavailable:'不可用',not_approved:'未准入',not_admitted:'未准入',awaiting_review:'待复核',not_generated:'未生成',candidate_only:'候选几何，待确认',runner_generated_reference:'由本次参考任务生成',generated_on_new_run:'启动新任务时生成',engineering_only:'工程试算',available:'求解环境可用',ready:'已准备',passed:'通过',unchecked:'未检查'};
  const stageLabels = {queued:'排队',waiting_cpu:'等待 CPU 车道',preflight:'准备检查',reference_execution:'参考求解',export:'产物导出',viewer_export:'三维字段导出',results:'结果整理',completed:'执行结束',failed:'失败',interrupted:'运行中断'};
  const checkLabels = {wsl_environment:'WSL 环境',python3:'Python 运行时',blockMesh:'体网格工具 blockMesh',checkMesh:'网格检查 checkMesh',simpleFoam:'流场求解 simpleFoam',foamToVTK:'字段导出 foamToVTK',native_linux_workspace:'Linux 本地工作目录',tutorial_dictionary:'参考求解配置',reference_runner:'参考执行脚本',patient_admission:'患者计算准入'};
  let cases = [], jobs = [], selectedCaseId = null, selectedJobId = null, detail = null;
  let timer = null, busy = false, refreshing = false, catalogReady = false, detailVersion = 0, desiredUpload = null;
  const label = value => statusLabels[value] || String(value || '未读取');
  const el = (tag, text, className) => {const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node;};
  function message(text, error = false) { $('simulation-message').textContent = text; $('simulation-message').className = 'simulation-message' + (error ? ' is-error' : ''); }
  function visible() { return !$('panel-validation').hidden && !document.hidden; }
  const activeCase = () => cases.find(item => item.id === selectedCaseId);
  function safeUrl(raw) {
    if (typeof raw !== 'string' || !raw.startsWith('/') || raw.startsWith('//')) return null;
    try { const url = new URL(raw, location.origin); return url.origin === location.origin ? url.pathname + url.search + url.hash : null; } catch { return null; }
  }
  function renderAssets(target, artifacts) {
    target.replaceChildren();
    const entries = Array.isArray(artifacts) ? artifacts : Object.entries(artifacts || {}).map(([name,url]) => ({name,label:name,url}));
    for (const item of entries) {
      const url = safeUrl(typeof item === 'string' ? item : item.url);
      if (!url) continue;
      const link = el('a', item.label || item.name || '查看产物', 'simulation-asset');
      link.href = url; link.target = '_blank'; link.rel = 'noopener';
      // Viewer links remain pages; the asset endpoint decides file disposition.
      target.append(link);
    }
  }
  function statusValue(value) { if (value && typeof value === 'object') return value.detail || value.message || label(value.status); return label(value); }
  function parameterText(parameters) {
    if (!parameters) return '固定工程参考参数由实际求解脚本提供；准备检查后显示。';
    const parts = [];
    const add = (key, name, factor, unit) => { if (Number.isFinite(parameters[key])) parts.push(`${name} ${(parameters[key] * factor).toLocaleString('zh-CN', {maximumSignificantDigits:6})} ${unit}`); };
    add('bulk_U_m_s','平均速度',1,'m/s'); add('gap_H_m','板间距',1000,'mm'); add('L_m','长度',1000,'mm');
    if (Number.isFinite(parameters.Q_L_min)) add('Q_L_min','流量',1,'L/min'); else add('Q_m3_s','流量',60000,'L/min');
    add('outlet_gauge_p_Pa','出口表压',1,'Pa');
    return (parts.length ? parts.join(' · ') : '参数详见本次运行清单') + '。平行板层流参考；这些参数不能作为患者工况。';
  }
  function buttons() {
    const item = activeCase();
    const hasActiveRun = jobs.some(job => job.action === 'run_reference' && running(job));
    $('simulation-refresh').disabled = refreshing;
    $('simulation-preflight').disabled = !catalogReady || !item || busy;
    $('simulation-run').disabled = !catalogReady || !item || busy || item.kind !== 'reference' || item.run_allowed !== true || hasActiveRun;
    $('simulation-run').textContent = item?.kind === 'patient' ? '患者模拟待准入' : hasActiveRun ? '参考模拟运行中' : '启动参考模拟';
    $('simulation-level').disabled = busy || hasActiveRun;
  }
  function renderCase() {
    const item = activeCase();
    if (item) $('simulation-case').value = selectedCaseId;
    $('simulation-kind').textContent = item ? item.kind === 'reference' ? '非患者参考' : '患者数据' : '未读取';
    $('simulation-kind').dataset.state = item?.run_allowed ? 'available' : 'blocked';
    $('simulation-source').textContent = item ? item.source_detail || item.source || (item.kind === 'reference' ? '来源：独立平行板参考几何，使用真实 OpenFOAM 求解。' : `来源：本机病例 ${item.id}。准入状态按实际审核与几何证据读取。`) : '来源尚未读取。';
    const facts = $('simulation-readiness'); facts.replaceChildren();
    for (const [name, key] of [['几何','geometry_status'],['体网格','mesh_status'],['求解','solver_status']]) {const row = el('div'); row.append(el('dt', name), el('dd', item ? statusValue(item[key]) : '未读取')); facts.append(row);}
    const blockers = $('simulation-blockers'); blockers.replaceChildren();
    if (item) {
      const reasons = item.blocking_reasons || [];
      blockers.append(el('strong', item.run_allowed === true ? '本对象可启动参考任务' : '当前计算受阻'));
      if (reasons.length) {const list = el('ul'); reasons.forEach(reason => list.append(el('li', typeof reason === 'string' ? reason : reason.detail || reason.name || JSON.stringify(reason)))); blockers.append(list);}
      else blockers.append(el('p', item.run_allowed === true ? '先准备检查可查看环境和来源；启动将创建一个新的真实任务。' : '尚无可用运行许可；准备检查可读取具体条件。'));
      blockers.dataset.state = item.run_allowed === true ? 'ready' : 'blocked';
    }
    $('simulation-reference-settings').hidden = item?.kind !== 'reference';
    $('simulation-parameters').textContent = parameterText(item?.fixed_parameters || item?.parameters);
    $('simulation-next').textContent = !item ? '' : item.kind === 'patient' ? '下一步：运行准备检查，按未满足项完善切片审核、边界草稿与几何准入；参考算例可独立验证计算链路。' : '下一步：准备检查 → 新参考求解 → 查日志、守恒与压降 → 打开三维产物。';
    renderAssets($('simulation-case-assets'), item?.artifacts);
    buttons();
  }
  function saveSelection() { try { localStorage.setItem('nasal_simulation_case', selectedCaseId || ''); if (selectedJobId) localStorage.setItem('nasal_simulation_job_' + selectedCaseId, selectedJobId); else localStorage.removeItem('nasal_simulation_job_' + selectedCaseId); } catch {} }
  function saved(key) { try {return localStorage.getItem(key);} catch {return null;} }
  function selectCase(id) {
    if (!cases.some(item => item.id === id)) return;
    selectedCaseId = id; $('simulation-case').value = id; detailVersion++; detail = null;
    const remembered = saved('nasal_simulation_job_' + id);
    selectedJobId = jobs.some(job => job.id === remembered && job.case_id === id) ? remembered : jobs.find(job => job.case_id === id)?.id || null;
    saveSelection(); renderCase(); renderJobs(); renderDetail();
    if (selectedJobId) readDetail(selectedJobId);
    schedule();
  }
  function renderJobs() {
    const box = $('simulation-jobs'); box.replaceChildren();
    const filtered = $('simulation-show-all').checked ? jobs : jobs.filter(job => job.case_id === selectedCaseId);
    if (!filtered.length) {box.append(el('p', '本对象尚无任务。准备检查和新求解会分别保存记录。', 'simulation-empty')); return;}
    for (const job of filtered) {
      const button = el('button', undefined, 'simulation-job-row'); button.type = 'button'; button.dataset.jobId = job.id;
      button.classList.toggle('is-active', job.id === selectedJobId);
      button.setAttribute('aria-pressed', String(job.id === selectedJobId));
      const title = el('span'); title.append(el('strong', (job.action === 'preflight' ? '准备检查' : '参考求解') + ' · ' + (cases.find(item => item.id === job.case_id)?.label || job.case_id)), el('small', `${job.id} · ${formatDate(job.created_at)}`));
      const state = el('span', label(job.status), 'simulation-badge'); state.dataset.state = job.status;
      button.append(title, state); button.addEventListener('click', () => { if (job.case_id !== selectedCaseId) selectCase(job.case_id); selectedJobId = job.id; detailVersion++; detail = null; saveSelection(); renderJobs(); renderDetail(); readDetail(job.id); });
      box.append(button);
    }
  }
  function formatDate(value) { if (!value) return '时间未记录'; const date = new Date(value); return Number.isNaN(date.valueOf()) ? String(value) : date.toLocaleString('zh-CN', {timeZone:'Asia/Shanghai',hour12:false}); }
  function renderChecks(preflight) {
    const box = $('simulation-checks'); box.replaceChildren(); if (!preflight) return;
    box.append(el('h5', preflight.passed === true ? '准备检查通过' : '准备检查未通过'));
    for (const check of preflight.checks || []) { const row = el('div', undefined, 'simulation-check'); row.dataset.state = check.passed === true ? 'passed' : check.passed === false ? 'failed' : 'unchecked'; row.append(el('strong', `${check.passed === true ? '通过' : check.passed === false ? '未通过' : '未确定'} · ${checkLabels[check.name] || check.name}`), el('span', check.detail || '无补充信息')); if (check.source) row.append(el('small', '证据：' + check.source)); box.append(row); }
    if (preflight.blocking_reasons?.length) {const list = el('ul', undefined, 'simulation-failure-list'); preflight.blocking_reasons.forEach(reason => list.append(el('li', reason))); box.append(list);}
  }
  function number(value, digits = 4) { return Number.isFinite(value) ? value.toLocaleString('zh-CN', {maximumSignificantDigits:digits}) : '未获得'; }
  function renderResult(result, job) {
    const box = $('simulation-result'); box.replaceChildren();
    if (!result || !Array.isArray(result.cases) || !result.cases.length) {
      if (job.action === 'run_reference') box.append(el('p', running(job) ? '本次求解尚未返回数值结果。' : '本次没有可读取的数值结果。', 'simulation-empty'));
      return;
    }
    box.append(el('h5', result.patient_data === false ? '非患者参考 · 本次数值结果' : '本次数值结果'));
    box.append(el('p', result.validation_status === 'awaiting_independent_review' ? '已获得运行产物，等待独立验收。运行完成不等于验证通过。' : '验证状态：' + (result.validation_status || '未记录'), 'simulation-result-notice'));
    if (result.parameters) box.append(el('p', parameterText(result.parameters), 'simulation-note'));
    const scroll = el('div', undefined, 'table-scroll'), table = el('table');
    const head = el('thead'), hr = el('tr'); ['网格','单元数','压降 Pa','质量不平衡','求解收敛'].forEach(text => hr.append(el('th',text))); head.append(hr); table.append(head);
    const body = el('tbody');
    for (const row of result.cases) {const tr = el('tr'); [row.level || '未记录', number(row.cells,8), number(row.delta_p_boundary_Pa,6), Number.isFinite(row.mass_imbalance_fraction) ? row.mass_imbalance_fraction.toExponential(3) : '未获得', row.converged === true ? '已收敛' : row.converged === false ? '未收敛' : '未确定'].forEach(text => tr.append(el('td',text))); body.append(tr);}
    table.append(body); scroll.append(table); box.append(scroll);
  }
  function renderDetail() {
    const job = detail;
    $('simulation-job-empty').hidden = !!job; $('simulation-job-detail').hidden = !job;
    $('simulation-job-status').textContent = job ? label(job.status) : selectedJobId ? '读取中' : '未选择任务';
    $('simulation-job-status').dataset.state = job?.status || 'pending';
    if (!job) { $('simulation-job-empty').textContent = selectedJobId ? '正在读取任务详情…' : '选择对象后可运行准备检查，或从任务列表打开已有记录。'; $('simulation-log').textContent = '尚无日志'; $('simulation-result').replaceChildren(); $('simulation-job-assets').replaceChildren(); return; }
    $('simulation-job-meta').textContent = `${job.id} · 创建 ${formatDate(job.created_at)} · 更新 ${formatDate(job.updated_at)}`;
    const stages = $('simulation-stages'); stages.replaceChildren();
    stages.append(el('li', '当前阶段：' + (stageLabels[job.stage] || job.stage || '未记录')));
    if (job.exit_code !== null && job.exit_code !== undefined) stages.append(el('li', '原始退出码：' + job.exit_code));
    $('simulation-job-error').hidden = !job.error; $('simulation-job-error').textContent = job.error || '';
    renderChecks(job.preflight); renderResult(job.result, job); renderAssets($('simulation-job-assets'), job.artifacts);
    $('simulation-preflight-detail').hidden = !job.preflight;
    if ($('simulation-preflight-detail').dataset.job !== job.id) { $('simulation-preflight-detail').open = job.action === 'preflight' || job.preflight?.passed === false; $('simulation-preflight-detail').dataset.job = job.id; }
    $('simulation-log').textContent = job.log_excerpt || '当前阶段尚无日志输出。';
  }
  async function api(url, options = {}) {
    const response = await fetch(url, {...options, cache:'no-store'});
    const data = await response.json().catch(() => null);
    if (!response.ok) throw Error(data?.error || data?.message || `计算服务请求失败（${response.status}）`);
    if (!data) throw Error('计算服务未返回有效 JSON'); return data;
  }
  async function readDetail(id) {
    const version = ++detailVersion, caseId = selectedCaseId;
    try {
      const job = await api('/api/simulation/jobs/' + encodeURIComponent(id));
      if (version !== detailVersion || selectedJobId !== id || selectedCaseId !== caseId) return;
      if (job.case_id !== caseId) throw Error('任务病例与当前对象不一致');
      detail = job; jobs = jobs.map(item => item.id === job.id ? job : item); renderJobs(); renderDetail(); buttons();
    } catch (error) { if (version !== detailVersion) return; detail = null; renderDetail(); $('simulation-job-empty').textContent = '任务详情未读取：' + error.message; message(error.message, true); }
    finally { schedule(); }
  }
  async function refresh() {
    if (refreshing) return;
    refreshing = true; buttons(); clearTimeout(timer);
    const [catalog, history] = await Promise.allSettled([api('/api/simulation/catalog'), api('/api/simulation/jobs')]);
    let problems = [];
    if (catalog.status === 'fulfilled' && Array.isArray(catalog.value.cases)) {
      cases = catalog.value.cases; catalogReady = true; const select = $('simulation-case'); select.replaceChildren();
      for (const [kind,title] of [['patient','患者病例'],['reference','非患者参考']]) { const group = el('optgroup'); group.label = title; cases.filter(item => item.kind === kind).forEach(item => {const option = el('option', item.label || item.id); option.value = item.id; group.append(option);}); if (group.children.length) select.append(group); }
      select.disabled = !cases.length;
    } else { catalogReady = false; cases = []; const select = $('simulation-case'); select.replaceChildren(el('option', '计算目录未读取')); select.disabled = true; problems.push(catalog.status === 'rejected' ? catalog.reason.message : '计算目录格式无效'); }
    if (history.status === 'fulfilled' && Array.isArray(history.value.jobs)) jobs = history.value.jobs.slice().sort((a,b) => String(b.created_at).localeCompare(String(a.created_at)));
    else {jobs = []; problems.push(history.status === 'rejected' ? history.reason.message : '任务列表格式无效');}
    refreshing = false;
    if (catalogReady) {
      const desired = desiredUpload || selectedCaseId || saved('nasal_simulation_case');
      const chosen = cases.some(item => item.id === desired) ? desired : cases.find(item => item.kind === 'patient')?.id || cases[0]?.id;
      if (chosen && chosen !== selectedCaseId) selectCase(chosen);
      else {renderCase(); renderJobs(); if (!selectedJobId) {const first = jobs.find(job => job.case_id === selectedCaseId); if (first) {selectedJobId = first.id; saveSelection();}} if (selectedJobId) await readDetail(selectedJobId); else renderDetail();}
    } else {detailVersion++; detail = null; renderCase(); renderDetail(); buttons(); renderJobs();}
    message(problems.length ? '未读取完整计算状态：' + problems.join('；') + '。可刷新重试。' : '已同步本机计算条件与任务记录。', !!problems.length);
    schedule();
  }
  async function createJob(action) {
    const item = activeCase(); if (!item || busy || !catalogReady) return;
    if (action === 'run_reference' && (item.kind !== 'reference' || item.run_allowed !== true)) return;
    busy = true; buttons(); message(action === 'preflight' ? '正在创建准备检查…' : '正在创建新的真实参考求解任务…');
    const caseId = item.id;
    try {
      const level = $('simulation-level').value;
      const settings = item.kind === 'reference' ? {levels:level === 'all' ? ['coarse','medium','fine'] : [level]} : {};
      const job = await api('/api/simulation/jobs', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({case_id:caseId,action,settings})});
      jobs.unshift(job);
      if (selectedCaseId === caseId) {selectedJobId = job.id; detailVersion++; detail = job; saveSelection(); renderJobs(); renderDetail();}
      message('任务已创建并保存：' + job.id + '。状态按实际运行更新。');
    } catch (error) { message(error.message, true); }
    finally {busy = false; buttons(); schedule();}
  }
  function schedule() { clearTimeout(timer); timer = null; if (!visible() || !jobs.some(running)) return; timer = setTimeout(refresh, 2000); }
  $('simulation-refresh').addEventListener('click', refresh);
  $('simulation-case').addEventListener('change', () => {desiredUpload = null; selectCase($('simulation-case').value);});
  $('simulation-show-all').addEventListener('change', renderJobs);
  $('simulation-preflight').addEventListener('click', () => createJob('preflight'));
  $('simulation-run').addEventListener('click', () => createJob('run_reference'));
  window.addEventListener('nasal-step-changed', () => {if (visible()) refresh(); else {clearTimeout(timer);timer = null;}});
  window.addEventListener('nasal-case-changed', event => { desiredUpload = event.detail?.id || null; if (visible()) refresh(); });
  document.addEventListener('visibilitychange', () => {if (visible()) refresh(); else {clearTimeout(timer);timer = null;}});
  if (visible()) refresh();
})();
