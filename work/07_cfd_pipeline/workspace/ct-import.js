'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const folder = $('ct-folder'), single = $('ct-file'), start = $('upload-start');
  if (!folder || !single) return;
  let files = [], kind = null, current = null, timer = null, uploading = false, uploadSession = null;
  const formatBytes = n => n < 1024 ** 2 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1024 ** 2).toFixed(1)} MB`;
  const message = (text, error = false) => { $('upload-message').textContent = text; $('upload-message').className = error ? 'case-error' : ''; };
  const errorText = err => err?.message || '导入失败，请检查文件后重试';
  function selected(nextFiles, nextKind) {
    files = [...nextFiles]; kind = nextKind;
    uploadSession = null; start.textContent = '上传并开始处理'; message('');
    $('upload-selection').textContent = files.length ? `${files.length} 个文件，共 ${formatBytes(files.reduce((n, f) => n + f.size, 0))}；将先检查序列和几何。` : '选择后先检查序列，再进行自动分割。每次最多 8 GB。';
    $('hu-option').hidden = kind !== 'nifti';
    start.disabled = !files.length || (kind === 'nifti' && !$('hu-confirmed').checked);
  }
  folder.addEventListener('change', () => { single.value = ''; selected(folder.files, 'dicom'); });
  single.addEventListener('change', () => {
    folder.value = '';
    const file = single.files[0];
    if (!file) return selected([], null);
    const lower = file.name.toLowerCase();
    selected([file], lower.endsWith('.zip') ? 'zip' : 'nifti');
  });
  $('hu-confirmed').addEventListener('change', () => { start.disabled = !files.length || (kind === 'nifti' && !$('hu-confirmed').checked); });
  function stages(data) {
    const names = [['import','导入 CT'],['segmentation','自动分割'],['candidates','粗定位与精标定'],['review','人工复核'],['geometry','几何确认'],['mesh','体网格'],['solver','流场计算'],['results','结果检验']];
    const list = $('pipeline-stages'); list.replaceChildren();
    for (const [id, label] of names) { const li = document.createElement('li'); li.dataset.state = data.stages?.[id] || 'pending'; li.innerHTML = `<span>${label}</span><small>${({done:'已完成',running:'进行中',waiting:'等待人工',failed:'失败',pending:'未开始'}[li.dataset.state] || li.dataset.state)}</small>`; list.append(li); }
  }
  function show(data) {
    current = data; stages(data); $('case-run').hidden = false; $('run-title').textContent = `上传病例 · ${data.id.slice(-6)}`; $('run-message').textContent = data.message || '';
    $('run-facts').replaceChildren();
    const geometry = data.geometry;
    const facts = [geometry ? `${geometry.size_xyz.join(' × ')} 体素` : null,
      geometry ? `间距 ${geometry.spacing_xyz_mm.map(n => Number(n).toFixed(3)).join(' × ')} mm` : null,
      data.landmark_count ? `${data.landmark_count} 个候选点` : null,
      data.current_revision ? `候选版本 ${data.versions?.length || 1}` : null];
    facts.filter(Boolean).forEach(text => $('run-facts').append(Object.assign(document.createElement('span'), {textContent:text})));
    $('case-error').hidden = !data.error; $('case-error').textContent = data.error || '';
    $('retry-case').hidden = !['failed','interrupted'].includes(data.status);
    const canRegenerate = ['awaiting_review','review_recorded'].includes(data.status) && data.artifacts?.review;
    $('regenerate-case').hidden = !canRegenerate;
    $('regenerate-case-inline').hidden = !canRegenerate;
    $('series-choice').hidden = data.status !== 'awaiting_series';
    $('case-open-actions').hidden = !data.artifacts?.viewer;
    $('review-handoff').hidden = !data.artifacts?.review;
    const localization = data.localization_summary;
    $('run-localization').hidden = !localization;
    if (localization) {
      const states = {search_prior:'已采用粗定位参考',display_only:'粗定位预计点仅供显示',unavailable:'粗定位不适用，使用本例 CT',not_generated:'尚无粗定位记录'};
      const delta = localization.max_refinement_delta_mm;
      $('run-localization').textContent = `${states[localization.status] || '待检查粗定位'}；${localization.independent_reference_patients} 位独立参考患者，${localization.search_prior_points} 点可搜索或对照，${localization.fallback_landmarks.length} 点局部失败后回退。` + (Number.isFinite(delta) ? `最大粗→精偏移 ${delta.toFixed(2)} mm。` : '') + '请在切片复核中检查本例精调候选。';
    }
    if (data.status === 'awaiting_series') {
      const box = $('series-options'); box.replaceChildren();
      (data.series || []).filter(s => s.valid).forEach((series, index) => {
        const label = document.createElement('label'); label.className = 'series-option'; label.innerHTML = `<input type="radio" name="series" value="${series.id}" ${index === 0 ? 'checked' : ''}><span>${series.label} · ${series.slice_count} 张 · ${series.spacing_xyz_mm?.map(n => Number(n).toFixed(2)).join(' × ')} mm</span>`; box.append(label);
      });
    }
    const active = $('active-case');
    if (active && ![...active.options].some(o => o.value === data.id)) { const option = document.createElement('option'); option.value = data.id; option.textContent = `上传病例 · ${data.id.slice(-6)}`; active.append(option); }
    if (active) active.value = data.id;
    $('active-case-state').textContent = data.message;
    window.nasalWorkspace.setUploadedCase(data);
    localStorage.setItem('nasal_active_uploaded_case', data.id);
    const url = new URL(location.href);url.searchParams.set('case',data.id);window.history.replaceState(null,'',url);
  }
  async function api(url, options = {}) { const response = await fetch(url, options); const data = await response.json().catch(() => ({})); if (!response.ok) throw Error(data.error || `请求失败（${response.status}）`); return data; }
  async function createAndUpload() {
    if (uploading) return;
    uploading = true; folder.disabled = single.disabled = $('hu-confirmed').disabled = true;
    const chosenFiles = [...files];
    start.disabled = true; message('正在创建本机病例…'); $('upload-progress').hidden = false; $('upload-progress').value = 0;
    try {
      const data = uploadSession?.data || await api('/api/cases', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({kind, hu_confirmed:$('hu-confirmed').checked, files:chosenFiles.map(f => ({name:f.name,size:f.size}))})});
      uploadSession ||= {data, completed:0};
      show(data); let done = chosenFiles.slice(0,uploadSession.completed).reduce((sum,f) => sum + f.size,0);
      for (let i = uploadSession.completed; i < chosenFiles.length; i++) {
        const file = chosenFiles[i]; message(`正在上传 ${i + 1}/${chosenFiles.length}`);
        await sendFile(`/api/cases/${data.id}/files/${i}`, file, bytes => $('upload-progress').value = Math.round((done + bytes) / data.total_bytes * 100));
        done += file.size; uploadSession.completed = i + 1; $('upload-progress').value = Math.round(done / data.total_bytes * 100);
      }
      await begin(data.id); uploadSession = null; message('文件已上传，自动处理已进入队列。');
      folder.value = single.value = ''; files = []; kind = null; $('hu-option').hidden = true; start.textContent = '上传并开始处理';
      history();
    } catch (err) { message(errorText(err), true); start.disabled = false; start.textContent = uploadSession ? '继续上传并处理' : '上传并开始处理'; }
    finally { uploading = false; folder.disabled = single.disabled = $('hu-confirmed').disabled = false; }
  }
  function sendFile(url, file, progress) { return new Promise((resolve,reject) => {
    const request = new XMLHttpRequest(); request.open('PUT',url); request.setRequestHeader('Content-Type','application/octet-stream'); request.timeout = 180000;
    request.upload.onprogress = event => progress(event.loaded);
    request.onerror = request.ontimeout = () => reject(Error('上传中断，可点击“继续上传并处理”重试'));
    request.onload = () => { let data; try {data = JSON.parse(request.responseText);} catch {return reject(Error('上传响应无效'));} request.status < 300 ? resolve(data) : reject(Error(data.error || '文件上传失败')); };
    request.send(file);
  }); }
  async function begin(id, series = null) { clearTimeout(timer); const data = await api(`/api/cases/${id}/start`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(series ? {series} : {})}); show(data); poll(); }
  async function poll() { if (!current) return; const id = current.id; try { const data = await api(`/api/cases/${id}`); if (current?.id !== id) return; show(data); } catch {} if (current?.id === id && ['queued','running'].includes(current.status)) timer = setTimeout(poll, 1800); else {timer = null; history();} }
  start.addEventListener('click', createAndUpload);
  $('confirm-series').addEventListener('click', async () => { const selected = document.querySelector('input[name=series]:checked'); if (!selected) return; try { await begin(current.id, selected.value); } catch (err) { message(errorText(err), true); } });
  $('retry-case').addEventListener('click', async () => { try { await begin(current.id); } catch (err) { show({...current, error:errorText(err)}); } });
  async function regenerate() {
    if (!current) return;
    const buttons = [$('regenerate-case'), $('regenerate-case-inline')]; buttons.forEach(button => {button.disabled = true;});
    try { show(await api(`/api/cases/${current.id}/regenerate`, {method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})); poll(); }
    catch (err) { $('active-case-state').textContent = errorText(err); }
    finally { buttons.forEach(button => {button.disabled = false;}); }
  }
  $('regenerate-case').addEventListener('click', regenerate);
  $('regenerate-case-inline').addEventListener('click', regenerate);
  $('open-case-geometry').addEventListener('click', () => { window.nasalWorkspace.setUploadedCase(current); location.hash = 'geometry'; });
  $('open-case-review').addEventListener('click', () => { window.nasalWorkspace.setUploadedCase(current); location.hash = 'review'; });
  async function deleteCase(item, button) {
    if (!window.confirm(`确定删除导入病例 ${item.id.slice(-6)}？此操作会删除该病例的原始 CT 和处理结果。`)) return;
    button.disabled = true;
    try {
      await api(`/api/cases/${encodeURIComponent(item.id)}`, {method:'DELETE'});
      if (current?.id === item.id) {
        clearTimeout(timer); timer = null; current = null;
        $('case-run').hidden = true; $('regenerate-case').hidden = true;
        $('active-case').value = 'existing'; $('active-case-state').textContent = '可查看已有候选';
        localStorage.removeItem('nasal_active_uploaded_case');
        const url = new URL(location.href); url.searchParams.delete('case'); window.history.replaceState(null, '', url);
        window.nasalWorkspace.setUploadedCase(null);
      }
      await history();
      message('病例已删除。');
    } catch (err) { button.disabled = false; message(errorText(err), true); }
  }
  $('active-case').addEventListener('change', () => { clearTimeout(timer); const value = $('active-case').value; if (value === 'existing') { current = null; $('case-run').hidden = true; $('regenerate-case').hidden = true; $('active-case-state').textContent = '可查看已有候选'; localStorage.removeItem('nasal_active_uploaded_case'); const url=new URL(location.href);url.searchParams.delete('case');window.history.replaceState(null,'',url); window.nasalWorkspace.setUploadedCase(null); return; } api(`/api/cases/${value}`).then(data => { show(data); poll(); }).catch(err => message(errorText(err), true)); });
  $('save-case-review').addEventListener('click', async () => {
    const button = $('save-case-review'); button.disabled = true;
    try {
      const frame = window.nasalWorkspace.activeFrame('review');
      if (!frame?.contentWindow?.exportReview) throw Error('切片复核页面尚未就绪');
      const decisions = frame.contentWindow.exportReview(true);
      const data = await api(`/api/cases/${current.id}/review`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(decisions)});
      show(data); $('active-case-state').textContent = '审核已保存'; history();
    } catch(err) { $('active-case-state').textContent = errorText(err); }
    finally {button.disabled = false;}
  });
  async function history() {
    try {
      const data = await api('/api/cases'), box = $('case-history'); box.replaceChildren();
      window.dispatchEvent(new CustomEvent('nasal-upload-summary', {detail:{scans:data.cases.filter(c => c.ct_sha256).length,points:data.cases.reduce((n,c) => n + (c.landmark_count || 0),0)}}));
      if (!data.cases.length) box.append(Object.assign(document.createElement('p'), {className:'muted', textContent:'还没有导入病例。'}));
      for (const option of [...$('active-case').options]) {
        if (option.value !== 'existing' && !data.cases.some(item => item.id === option.value)) option.remove();
      }
      for (const item of data.cases) {
        const select = $('active-case');
        if (![...select.options].some(o => o.value === item.id)) {const option = document.createElement('option');option.value = item.id;option.textContent = `上传病例 · ${item.id.slice(-6)}`;select.append(option);}
        const row = document.createElement('div'); row.className = 'history-item';
        const button = document.createElement('button'); button.className = 'history-select'; button.type = 'button';
        button.classList.toggle('is-active',item.id===current?.id);
        const date = new Date(item.updated_at || item.created_at);
        for(const [tag,text] of [['strong',`上传病例 · ${item.id.slice(-6)}`],['span',item.message || item.status],['small',date.toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})]]) button.append(Object.assign(document.createElement(tag),{textContent:text}));
        button.addEventListener('click', () => { clearTimeout(timer); show(item); poll(); });
        const remove = document.createElement('button'); remove.className = 'history-delete'; remove.type = 'button'; remove.textContent = '删除'; remove.title = `删除病例 ${item.id}`;
        remove.addEventListener('click', () => deleteCase(item, remove)); row.append(button, remove); box.append(row);
      }
    } catch (err) { $('case-history').textContent = errorText(err); }
  }
  history();
  const saved = new URLSearchParams(location.search).get('case') || localStorage.getItem('nasal_active_uploaded_case');
  if (/^u_[0-9a-f]{16}$/.test(saved || '')) api(`/api/cases/${saved}`).then(data => {show(data);poll();}).catch(() => localStorage.removeItem('nasal_active_uploaded_case'));
})();
