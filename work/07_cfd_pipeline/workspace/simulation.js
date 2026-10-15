'use strict';
(() => {
  const $ = id => document.getElementById(id);
  if (!$('simulation-case')) return;
  const running = job => ['queued', 'running'].includes(job?.status);
  const statusLabels = {queued:'排队中',running:'运行中',completed:'已执行',failed:'失败',interrupted:'已中断',pending:'未开始',waiting:'等待',blocked:'受阻',not_started:'未开始',unavailable:'不可用',not_approved:'未准入',not_admitted:'未准入',awaiting_review:'待复核',not_generated:'未生成',candidate_only:'候选几何，待确认',runner_generated_reference:'由本次参考任务生成',generated_on_new_run:'启动新任务时生成',engineering_only:'工程试算',available:'求解环境可用',ready:'已准备',passed:'通过',unchecked:'未检查'};
  const stageLabels = {queued:'排队',waiting_cpu:'等待 CPU 车道',preflight:'准备检查',reference_execution:'参考求解',pressure_feedback:'共同压力反馈',patient_execution:'患者工程试算',mesh:'体网格',solver:'流场求解',export:'产物导出',viewer_export:'三维字段导出',results:'结果整理',completed:'执行结束',failed:'失败',interrupted:'运行中断'};
  const checkLabels = {wsl_environment:'WSL 环境',python3:'Python 运行时',blockMesh:'体网格工具 blockMesh',checkMesh:'网格检查 checkMesh',simpleFoam:'流场求解 simpleFoam',foamToVTK:'字段导出 foamToVTK',native_linux_workspace:'Linux 本地工作目录',tutorial_dictionary:'参考求解配置',reference_runner:'参考执行脚本',patient_admission:'患者计算准入'};
  let cases = [], jobs = [], selectedCaseId = null, selectedJobId = null, detail = null;
  let timer = null, busy = false, refreshing = false, catalogReady = false, detailVersion = 0, desiredUpload = null;
  const label = value => statusLabels[value] || String(value || '未读取');
  const el = (tag, text, className) => {const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node;};
  function message(text, error = false) { $('simulation-message').textContent = text; $('simulation-message').className = 'simulation-message' + (error ? ' is-error' : ''); }
  function visible() { return !$('panel-validation').hidden && !document.hidden; }
  const activeCase = () => cases.find(item => item.id === selectedCaseId);
  const runActions = new Set(['run_reference', 'run_pressure_feedback', 'run_patient_engineering']);
  const runAction = item => item?.run_action || (item?.id === 'reference_channel' ? 'run_reference' : null);
  const runTitle = action => ({run_reference:'参考模拟',run_pressure_feedback:'共同压力反馈',run_patient_engineering:'患者工程试算'}[action] || '模拟');
  function jobSettings(item) {
    const action = runAction(item);
    if (action === 'run_reference') {const level = $('simulation-level').value; return {levels:level === 'all' ? ['coarse','medium','fine'] : [level]};}
    if (action === 'run_pressure_feedback') {const scenario = $('simulation-scenario').value; return {scenarios:scenario === 'all' ? ['unequal','symmetric','swapped_labels'] : [scenario]};}
    return {};
  }
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
  function validationLabel(value, fallback = '未记录') { return ({not_validated:'未验证',unchecked:'未检查',awaiting_independent_review:'待独立验收',passed:'通过',failed:'未通过',validated:'已验证',not_applicable:'不适用'}[value] || value || fallback); }
  function appendChecks(box, checks, title) {
    if (!checks) return;
    const list = Array.isArray(checks) ? checks : Object.entries(checks).map(([name,value]) => typeof value === 'object' && value !== null ? {name,...value} : {name,passed:typeof value === 'boolean' ? value : undefined,detail:typeof value === 'boolean' ? '' : String(value)});
    if (!list.length) return;
    if (title) box.append(el('h5',title));
    for (const check of list) {const row = el('div',undefined,'simulation-check'); row.dataset.state = check.passed === true ? 'passed' : check.passed === false ? 'failed' : 'unchecked'; row.append(el('strong',`${check.passed === true ? '通过' : check.passed === false ? '未通过' : '未确定'} · ${checkLabels[check.name] || check.name}`),el('span',check.detail || '无补充信息')); if (check.source) row.append(el('small','证据：' + check.source)); box.append(row);}
  }
  function parameterText(parameters) {
    if (!parameters) return '固定工程参考参数由实际求解脚本提供；准备检查后显示。';
    const parts = [];
    const add = (key, name, factor, unit) => { if (Number.isFinite(parameters[key])) parts.push(`${name} ${(parameters[key] * factor).toLocaleString('zh-CN', {maximumSignificantDigits:6})} ${unit}`); };
    add('bulk_U_m_s','平均速度',1,'m/s'); add('gap_H_m','板间距',1000,'mm'); add('L_m','长度',1000,'mm');
    if (Number.isFinite(parameters.Q_L_min)) add('Q_L_min','流量',1,'L/min'); else add('Q_m3_s','流量',60000,'L/min');
    add('target_flow_L_min','目标总流量',1,'L/min');
    add('outlet_gauge_p_Pa','出口表压',1,'Pa');
    return (parts.length ? parts.join(' · ') : '参数详见本次运行清单') + (parameters.boundary_strategy === 'common_inlet_pressure_feedback' ? '。共同静压反馈工程参考；这些参数不能作为患者工况。' : '。平行板层流参考；这些参数不能作为患者工况。');
  }
  function buttons() {
    const item = activeCase();
    const action = runAction(item), hasActiveRun = jobs.some(job => runActions.has(job.action) && running(job));
    $('simulation-refresh').disabled = refreshing;
    $('simulation-preflight').disabled = !catalogReady || !item || busy;
    $('simulation-run').disabled = !catalogReady || !item || busy || !runActions.has(action) || item.run_allowed !== true || hasActiveRun;
    $('simulation-run').textContent = hasActiveRun ? '计算任务运行中' : item?.run_allowed === true && runActions.has(action) ? '启动' + runTitle(action) : item?.kind === 'patient' ? '患者工程试算待准入' : '模拟待准入';
    $('simulation-level').disabled = busy || hasActiveRun;
    $('simulation-scenario').disabled = busy || hasActiveRun;
  }
  function renderCase() {
    const item = activeCase();
    if (item) $('simulation-case').value = selectedCaseId;
    $('simulation-kind').textContent = item ? item.kind === 'reference' ? '非患者参考' : '患者数据' : '未读取';
    $('simulation-kind').dataset.state = item?.run_allowed ? 'available' : 'blocked';
    $('simulation-source').textContent = item ? item.source_detail || item.source || (item.kind === 'reference' ? '来源：独立工程参考几何，使用真实 OpenFOAM 求解。' : `来源：本机病例 ${item.id}。准入状态按实际审核与几何证据读取。`) : '来源尚未读取。';
    const facts = $('simulation-readiness'); facts.replaceChildren();
    for (const [name, key] of [['几何','geometry_status'],['体网格','mesh_status'],['求解','solver_status']]) {const row = el('div'); row.append(el('dt', name), el('dd', item ? statusValue(item[key]) : '未读取')); facts.append(row);}
    const blockers = $('simulation-blockers'); blockers.replaceChildren();
    if (item) {
      const reasons = item.blocking_reasons || [];
      blockers.append(el('strong', item.run_allowed === true ? '可启动' + runTitle(runAction(item)) : '当前计算受阻'));
      if (reasons.length) {const list = el('ul'); reasons.forEach(reason => list.append(el('li', typeof reason === 'string' ? reason : reason.detail || reason.name || JSON.stringify(reason)))); blockers.append(list);}
      else blockers.append(el('p', item.run_allowed === true ? '先准备检查可查看环境和来源；启动将创建一个新的真实任务。' : '尚无可用运行许可；准备检查可读取具体条件。'));
      blockers.dataset.state = item.run_allowed === true ? 'ready' : 'blocked';
    }
    $('simulation-reference-settings').hidden = runAction(item) !== 'run_reference';
    $('simulation-feedback-settings').hidden = runAction(item) !== 'run_pressure_feedback';
    const engineering = $('simulation-engineering-checks'); engineering.replaceChildren();
    if (item?.kind === 'patient') engineering.append(el('p','患者工程试算仅供工程验证；临床验证：' + validationLabel(item.clinical_validation, '未验证') + '。','simulation-result-notice'));
    appendChecks(engineering, item?.engineering_checks, '工程准入条件');
    $('simulation-parameters').textContent = parameterText(item?.fixed_parameters || item?.parameters);
    $('simulation-feedback-parameters').textContent = parameterText(item?.fixed_parameters || item?.parameters);
    $('simulation-next').textContent = !item ? '' : item.kind === 'patient' ? '准备检查 → 满足工程准入条件 → 患者工程试算 → 查看真实日志与结果。计算完成不代表临床验证。' : runAction(item) === 'run_pressure_feedback' ? '准备检查 → 共同入口静压反馈 → 核对目标总流量、自然左右分流与守恒。此对象为非患者参考。' : '准备检查 → 新参考求解 → 查日志、守恒与压降 → 打开三维产物。';
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
      const title = el('span'); title.append(el('strong', (job.action === 'preflight' ? '准备检查' : runTitle(job.action)) + ' · ' + (cases.find(item => item.id === job.case_id)?.label || job.case_id)), el('small', `${job.id} · ${formatDate(job.created_at)}`));
      const state = el('span', label(job.status), 'simulation-badge'); state.dataset.state = job.status;
      button.append(title, state); button.addEventListener('click', () => { if (job.case_id !== selectedCaseId) selectCase(job.case_id); selectedJobId = job.id; detailVersion++; detail = null; saveSelection(); renderJobs(); renderDetail(); readDetail(job.id); });
      box.append(button);
    }
  }
  function formatDate(value) { if (!value) return '时间未记录'; const date = new Date(value); return Number.isNaN(date.valueOf()) ? String(value) : date.toLocaleString('zh-CN', {timeZone:'Asia/Shanghai',hour12:false}); }
  function renderChecks(preflight) {
    const box = $('simulation-checks'); box.replaceChildren(); if (!preflight) return;
    box.append(el('h5', preflight.passed === true ? '准备检查通过' : '准备检查未通过'));
    appendChecks(box, preflight.checks);
    if (preflight.clinical_validation) box.append(el('p','临床验证：' + validationLabel(preflight.clinical_validation),'simulation-result-notice'));
    if (preflight.blocking_reasons?.length) {const list = el('ul', undefined, 'simulation-failure-list'); preflight.blocking_reasons.forEach(reason => list.append(el('li', reason))); box.append(list);}
  }
  function number(value, digits = 4) { return Number.isFinite(value) ? value.toLocaleString('zh-CN', {maximumSignificantDigits:digits}) : '未获得'; }
  const flag = value => value === true ? '通过' : value === false ? '未通过' : '未获得';
  const percent = value => Number.isFinite(value) ? number(value * 100,5) + '%' : '未获得';
  const flow = value => Number.isFinite(value) ? number(value * 60000,6) : '未获得';
  function resultTable(box, headers, rows) {const scroll = el('div',undefined,'table-scroll'), table = el('table'), head = el('thead'), hr = el('tr'), body = el('tbody'); headers.forEach(text => hr.append(el('th',text))); head.append(hr); table.append(head); for (const row of rows) {const tr = el('tr'); row.forEach(text => tr.append(el('td',text))); body.append(tr);} table.append(body); scroll.append(table); box.append(scroll);}
  function renderFeedback(box, result) {
    const scenarios = result.scenarios || (result.scenario ? {patient_engineering:result.scenario} : null);
    if (!scenarios || typeof scenarios !== 'object') return false;
    const entries = Object.entries(scenarios), titles = {unequal:'非对称阻力',symmetric:'对称阻力',swapped_labels:'左右标签互换',patient_engineering:'患者工程 · 共同压力反馈'};
    if (!entries.length) return false;
    for (const [name, scenario] of entries) {
      const solved = scenario.result || {}, evaluations = scenario.evaluations || [], evaluation = evaluations.find(item => item.pressure_pa === solved.pressure_pa) || (result.execution_status === 'failed' ? evaluations[evaluations.length-1] : null), diagnostics = evaluation?.diagnostics || scenario.diagnostics || result.diagnostics || {}, finalIteration = (solved.iterations || []).find(item => item.pressure_pa === solved.pressure_pa) || {};
      box.append(el('h5',titles[name] || name));
      if (solved.status === 'quality_rejected_not_converged') box.append(el('p','质量未通过 / 未收敛，仅原始诊断。下列值未形成有效气流结果，不能作为生理或临床判断。','simulation-diagnostic-failure'));
      else if (result.execution_status === 'failed') box.append(el('p','本次执行失败；仅显示已获得的原始诊断，未形成有效气流结果，不代表共同压力反馈达标。','simulation-diagnostic-failure'));
      const facts = el('dl',undefined,'simulation-feedback-facts');
      for (const [title,value] of [['共同入口静压 Pa',number(solved.pressure_pa,6)],['目标总流量 L/min',flow(solved.target_m3_s)],['实测总流量 L/min',flow(solved.q_total_m3_s)],['左侧流量 L/min',flow(solved.q_left_m3_s)],['右侧流量 L/min',flow(solved.q_right_m3_s)],['出口流量 L/min',flow(solved.q_out_m3_s)],['左侧自然分流',percent(solved.left_fraction)],['目标流量相对误差',percent(solved.relative_flow_error)],['真实求解评估次数',number(solved.evaluation_count,8)]]) {const row = el('div'); row.append(el('dt',title),el('dd',value)); facts.append(row);} box.append(facts);
      resultTable(box,['守恒不平衡','最大残差','监测相对变化','网格质量','残差判据'],[[percent(diagnostics.flux?.mass_imbalance_frac),number(diagnostics.residual_max,6),percent(diagnostics.monitor_relative_change),flag(diagnostics.mesh_quality_passed ?? solved.mesh_quality_passed ?? evaluation?.evaluation?.mesh_quality_passed),flag(finalIteration.residuals_passed ?? solved.residuals_passed ?? evaluation?.evaluation?.residuals_passed ?? diagnostics.residuals_passed)]]);
      const iterations = solved.iterations || [];
      if (iterations.length) {const details = el('details'), summary = el('summary','压力反馈迭代记录 · ' + iterations.length + ' 次'); details.append(summary); resultTable(details,['迭代','共同静压 Pa','总流量 L/min','左流量 L/min','右流量 L/min','目标误差'],iterations.map((item,index)=>[String(index+1),number(item.pressure_pa,6),flow(item.q_total_m3_s),flow(item.q_left_m3_s),flow(item.q_right_m3_s),percent(item.relative_flow_error)])); box.append(details);}
    }
    appendChecks(box,result.checks,'运行检查');
    return true;
  }
  function renderResult(result, job) {
    const box = $('simulation-result'); box.replaceChildren();
    const scenarios = result?.scenarios || (result?.scenario ? {patient_engineering:result.scenario} : {});
    const qualityRejected = Object.values(scenarios).some(scenario => scenario?.result?.status === 'quality_rejected_not_converged');
    box.classList.toggle('is-diagnostic-failure',qualityRejected || job.status === 'failed' || result?.execution_status === 'failed');
    if (!result) {
      if (runActions.has(job.action)) box.append(el('p', running(job) ? '本次求解尚未返回数值结果。' : '本次没有可读取的数值结果。', 'simulation-empty'));
      return;
    }
    box.append(el('h5', result.patient_data === false ? '非患者参考 · 本次数值结果' : result.patient_data === true ? '患者工程试算 · 非临床结果' : '本次数值结果 · 数据类型未记录'));
    box.append(el('p','数值验证：' + validationLabel(result.numerical_validation) + ' · 临床验证：' + validationLabel(result.clinical_validation) + '。运行完成不等于验证通过。','simulation-result-notice'));
    if (typeof result.viewer_export_error === 'string' && result.viewer_export_error) box.append(el('p','本次三维流场导出失败：' + result.viewer_export_error + '。本任务未提供可用的三维流场入口。','simulation-diagnostic-failure'));
    if (result.validation_status) box.append(el('p','验收状态：' + validationLabel(result.validation_status),'simulation-result-notice'));
    if (result.backend) box.append(el('p','实际计算后端：' + result.backend,'simulation-note'));
    if (renderFeedback(box,result)) return;
    if (!Array.isArray(result.cases) || !result.cases.length) {box.append(el('p','本次没有可读取的数值结果。','simulation-empty')); return;}
    if (result.parameters && result.patient_data === false) box.append(el('p', parameterText(result.parameters), 'simulation-note'));
    const scroll = el('div', undefined, 'table-scroll'), table = el('table');
    const head = el('thead'), hr = el('tr'); ['网格','单元数','压降 Pa','质量不平衡','求解收敛'].forEach(text => hr.append(el('th',text))); head.append(hr); table.append(head);
    const body = el('tbody');
    for (const row of result.cases) {const tr = el('tr'); [row.level || '未记录', number(row.cells,8), number(row.delta_p_boundary_Pa,6), Number.isFinite(row.mass_imbalance_fraction) ? row.mass_imbalance_fraction.toExponential(3) : '未获得', row.converged === true ? '已收敛' : row.converged === false ? '未收敛' : '未确定'].forEach(text => tr.append(el('td',text))); body.append(tr);}
    table.append(body); scroll.append(table); box.append(scroll);
  }
  function renderDetail() {
    const job = detail;
    renderLiveProgress(job);
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
  function renderLiveProgress(job) {
    const progress = job?.live_progress, present = progress && typeof progress === 'object';
    $('simulation-live-progress').hidden = !present && !running(job);
    const value = raw => raw === null || raw === undefined || raw === '' ? '未获得' : String(raw);
    const steps = {blockMesh:'blockMesh · 体网格',checkMesh:'checkMesh · 网格检查',simpleFoam:'simpleFoam · 流场求解',foamToVTK:'foamToVTK · 字段导出'};
    $('simulation-live-step').textContent = steps[progress?.actual_step] || value(progress?.actual_step);
    $('simulation-live-evaluation').textContent = value(progress?.evaluation);
    $('simulation-live-iteration').textContent = value(progress?.iteration);
    $('simulation-live-updated').textContent = '实际记录更新：' + (progress?.updated_at ? formatDate(progress.updated_at) : '未获得') + ' · 阶段：' + (stageLabels[progress?.stage] || value(progress?.stage)) + ' · 执行状态：' + (progress?.runner_status ? label(progress.runner_status) : '未获得') + '。以最后记录为准。';
    $('simulation-live-log').textContent = typeof progress?.log_tail === 'string' && progress.log_tail ? progress.log_tail : '尚未获得原始日志';
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
    if (action !== 'preflight' && (!runActions.has(action) || action !== runAction(item) || item.run_allowed !== true)) return;
    busy = true; buttons(); message(action === 'preflight' ? '正在创建准备检查…' : '正在创建新的真实' + runTitle(action) + '任务…');
    const caseId = item.id;
    try {
      const settings = jobSettings(item);
      const job = await api('/api/simulation/jobs', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({case_id:caseId,action,settings})});
      jobs.unshift(job);
      if (selectedCaseId === caseId) {selectedJobId = job.id; detailVersion++; detail = job; saveSelection(); renderJobs(); renderDetail();}
      message('任务已创建并保存：' + job.id + '。状态按实际运行更新。');
    } catch (error) { message(error.message, true); }
    finally {busy = false; buttons(); schedule();}
  }
  function schedule() { clearTimeout(timer); timer = null; if (!visible() || !jobs.some(running)) return; timer = setTimeout(refresh, 3000); }
  $('simulation-refresh').addEventListener('click', refresh);
  $('simulation-case').addEventListener('change', () => {desiredUpload = null; selectCase($('simulation-case').value);});
  $('simulation-show-all').addEventListener('change', renderJobs);
  $('simulation-preflight').addEventListener('click', () => createJob('preflight'));
  $('simulation-run').addEventListener('click', () => createJob(runAction(activeCase())));
  window.addEventListener('nasal-step-changed', () => {if (visible()) refresh(); else {clearTimeout(timer);timer = null;}});
  window.addEventListener('nasal-case-changed', event => { desiredUpload = event.detail?.id || null; if (visible()) refresh(); });
  document.addEventListener('visibilitychange', () => {if (visible()) refresh(); else {clearTimeout(timer);timer = null;}});
  if (visible()) refresh();
})();
