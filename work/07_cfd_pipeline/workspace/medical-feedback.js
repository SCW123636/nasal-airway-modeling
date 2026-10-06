'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const decisions = {pending:'未审核',accept:'通过',reject:'不通过',adjust:'需要调整',insufficient:'证据不足'};
  const stages = {landmarks:'切片点位复核',boundary:'边界与后续人工核验'};
  let catalog = [], uploaded = null, requestNumber = 0, catalogRequest = 0, toastTimer;
  let exporting = false, catalogLoading = false;
  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  }
  function toast(text) {
    $('medical-toast').textContent = text;
    $('medical-toast').hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {$('medical-toast').hidden = true;}, 7000);
  }
  async function api(url, options = {}) {
    const response = await fetch(url, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw Error(data.error || `请求失败（${response.status}）`);
    return data;
  }
  function download(blob, name) {
    const url = URL.createObjectURL(blob), link = node('a');
    link.href = url; link.download = name; document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function fillCases(select, preferred) {
    const before = preferred || select.value;
    select.replaceChildren();
    for (const entry of catalog) {
      const option = node('option', entry.label); option.value = entry.case; select.append(option);
    }
    if (catalog.some(entry => entry.case === before)) select.value = before;
  }
  const selected = id => [...$(id).querySelectorAll('input:checked')].map(input => input.value);
  function updateExportSelection() {
    const cases = selected('medical-export-cases').length, phases = selected('medical-export-stages').length;
    const count = cases * phases;
    $('medical-export-summary').textContent = `已选 ${cases} 个病例 · ${phases} 个阶段 · 共 ${count} 份复核材料`;
    $('medical-export-download').disabled = exporting || catalogLoading || count === 0;
    $('medical-export-download').textContent = count > 1 ? `批量导出（${count} 份）` : '导出复核包';
    $('medical-export-case-group').disabled = exporting || catalogLoading;
    $('medical-export-stage-group').disabled = exporting || catalogLoading;
  }
  function fillExportCases(preferred, reset) {
    const before = new Set(selected('medical-export-cases'));
    if (reset || !before.size) {
      before.clear(); before.add(catalog.some(entry => entry.case === preferred) ? preferred : catalog[0]?.case);
    }
    const box = $('medical-export-cases'); box.replaceChildren();
    for (const entry of catalog) {
      const label = node('label'), input = node('input'); input.type = 'checkbox'; input.value = entry.case;
      input.checked = before.has(entry.case); label.append(input, node('span', entry.label)); box.append(label);
    }
    updateExportSelection();
  }
  async function loadCatalog(preferred, resetExport = false) {
    const serial = ++catalogRequest;
    const result = await api('/api/medical-review/catalog');
    if (serial !== catalogRequest) return;
    catalog = result.cases;
    fillCases($('medical-feedback-case'), preferred || uploaded?.id);
    fillExportCases(preferred || uploaded?.id, resetExport);
  }
  function date(value) {
    const time = new Date(value);
    return Number.isFinite(time.getTime()) ? time.toLocaleString('zh-CN', {hour12:false}) : '时间未提供';
  }
  function vector(value) {return Array.isArray(value) ? value.map(n => n.toFixed(3)).join(', ') : '未提供';}
  function renderRecord(record, caseId) {
    const article = node('article', undefined, 'feedback-record'); article.setAttribute('role', 'listitem');
    const feedback = record.feedback;
    const heading = node('div', undefined, 'feedback-record-heading');
    const info = node('div'); info.append(node('h3', `${feedback.reviewer} · ${stages[feedback.stage]}`), node('p', date(feedback.reviewed_at), 'muted'));
    heading.append(info, node('span', record.current ? '当前版本' : '已过期', 'feedback-version ' + (record.current ? 'current' : 'stale')));
    article.append(heading);
    const checks = [], labels = new Map(record.manifest.items.map(item => [item.id, item.label]));
    const list = node('div', undefined, 'feedback-items');
    for (const item of feedback.items) {
      const row = node('div', undefined, 'feedback-item');
      const title = node('label', undefined, 'feedback-item-title');
      if (record.current && feedback.stage === 'landmarks' && ['accept','reject','adjust'].includes(item.decision)) {
        const check = node('input'); check.type = 'checkbox'; check.value = item.id;
        check.setAttribute('aria-label', '选择 ' + (labels.get(item.id) || item.id)); checks.push(check); title.append(check);
      }
      title.append(node('strong', labels.get(item.id) || item.id));
      row.append(title, node('span', decisions[item.decision], 'feedback-decision ' + item.decision));
      if (item.note) row.append(node('p', item.note, 'feedback-note'));
      if (item.decision === 'adjust' && feedback.stage === 'landmarks') {
        row.append(node('p', `建议 LPS/mm：${vector(item.adjusted_point_lps_mm)}；法向：${vector(item.adjusted_normal_lps)}`, 'feedback-note muted'));
      }
      list.append(row);
    }
    article.append(list);
    if (checks.length) {
      const actions = node('div', undefined, 'feedback-actions');
      const adopt = node('button', '下载所选审核记录'); adopt.disabled = true;
      const count = node('span', '已选 0 项', 'muted');
      checks.forEach(check => check.addEventListener('change', () => {
        const selected = checks.filter(c => c.checked).length; count.textContent = `已选 ${selected} 项`; adopt.disabled = !selected;
      }));
      adopt.onclick = async () => {
        adopt.disabled = true;
        try {
          const selected = checks.filter(c => c.checked).map(c => c.value);
          const result = await api(`/api/cases/${caseId}/medical-feedback/${record.id}/decisions`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({items:selected})});
          download(new Blob([JSON.stringify(result,null,2)+'\n'], {type:'application/json;charset=utf-8'}), `${caseId}_所选审核记录.json`);
          toast('所选审核记录已下载，可在切片审核中导入');
          $('medical-feedback-message').textContent = '所选审核记录已下载，等待切片页核对与保存。';
        } catch (error) {toast(error.message);}
        finally {adopt.disabled = !checks.some(check => check.checked);}
      };
      actions.append(adopt, count); article.append(actions);
      const saveHint = caseId.startsWith('u_') ? '保存本例审核' : '下载审核记录';
      article.append(node('p', `下载后进入“切片审核”，导入所选审核记录，核对后点击“${saveHint}”。已有结论需勾选覆盖才会替换。`, 'muted'));
    } else if (feedback.stage === 'boundary') {
      article.append(node('p', '边界意见已留存，请在边界草稿与后续人工校验中逐项核对并确认。', 'muted'));
    }
    return article;
  }
  async function loadFeedback() {
    const serial = ++requestNumber, caseId = $('medical-feedback-case').value;
    const box = $('medical-feedback-list'); box.replaceChildren(node('p', '正在读取反馈…', 'muted'));
    if (!caseId) {box.replaceChildren(node('p', '尚无可复核病例。', 'muted')); return;}
    try {
      const result = await api(`/api/cases/${caseId}/medical-feedback`);
      if (serial !== requestNumber) return;
      box.replaceChildren();
      if (!result.records.length) box.append(node('p', '此病例尚无医学复核反馈。', 'feedback-empty'));
      for (const record of result.records) box.append(renderRecord(record, caseId));
    } catch (error) {if (serial === requestNumber) box.replaceChildren(node('p', error.message, 'case-error'));}
  }
  $('medical-export').onclick = async () => {
    $('medical-export-message').textContent = '正在读取病例…';
    catalogLoading = true; updateExportSelection();
    $('medical-export-dialog').showModal();
    try {
      let preferred = uploaded?.id;
      const frame = window.nasalWorkspace.activeFrame('review');
      if (!preferred && frame?.contentDocument) preferred = frame.contentDocument.getElementById('case-title')?.textContent.split(' · ')[0];
      await loadCatalog(preferred, true);
      for (const input of $('medical-export-stages').querySelectorAll('input')) input.checked = input.value === (location.hash === '#boundary' ? 'boundary' : 'landmarks');
      $('medical-export-message').textContent = catalog.length ? '' : '尚无已生成候选的病例。';
    } catch (error) {$('medical-export-message').textContent = error.message; $('medical-export-cases').replaceChildren();}
    finally {catalogLoading = false; updateExportSelection();}
  };
  $('medical-export-cases').onchange = $('medical-export-stages').onchange = () => { $('medical-export-message').textContent = ''; updateExportSelection(); };
  for (const [id, checked] of [['medical-export-all', true], ['medical-export-clear', false]]) {
    $(id).onclick = () => {
      for (const input of $('medical-export-cases').querySelectorAll('input')) input.checked = checked;
      $('medical-export-message').textContent = ''; updateExportSelection();
    };
  }
  $('medical-export-close').onclick = () => $('medical-export-dialog').close();
  $('medical-export-form').onsubmit = async event => {
    event.preventDefault();
    const cases = selected('medical-export-cases'), phases = selected('medical-export-stages');
    if (exporting || catalogLoading || !cases.length || !phases.length) return;
    exporting = true; updateExportSelection();
    const count = cases.length * phases.length;
    $('medical-export-message').textContent = `正在打包 ${count} 份医学复核材料…`;
    try {
      const single = count === 1;
      const response = single
        ? await fetch(`/api/cases/${cases[0]}/medical-review-export?stage=${phases[0]}`)
        : await fetch('/api/medical-review/export', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({cases, stages:phases})});
      if (!response.ok) {const result = await response.json(); throw Error(result.error || '导出失败');}
      download(await response.blob(), single ? `${cases[0]}_${phases[0] === 'landmarks' ? '切片' : '边界'}_医学复核.html` : `医学复核_${cases.length}例_${count}份.zip`);
      $('medical-export-message').textContent = `${count} 份医学复核材料已导出。`;
    } catch (error) {$('medical-export-message').textContent = error.message;}
    finally {exporting = false; updateExportSelection();}
  };
  $('medical-import').onclick = () => {$('medical-feedback-file').value = ''; $('medical-feedback-file').click();};
  $('medical-feedback-file').onchange = async () => {
    const file = $('medical-feedback-file').files[0]; if (!file) return;
    $('medical-import').disabled = true;
    $('medical-feedback-message').textContent = '';
    try {
      if (file.size > 2 * 1024**2) throw Error('反馈文件超过 2 MB');
      const feedback = JSON.parse(await file.text());
      if (!/^(p[0-3]|p3t1|u_[0-9a-f]{16})$/.test(feedback.case || '')) throw Error('反馈病例编号无效');
      await api(`/api/cases/${feedback.case}/medical-feedback`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(feedback)});
      await loadCatalog(feedback.case);
      window.nasalWorkspace.navigate('feedback'); await loadFeedback();
      $('medical-feedback-message').textContent = '医学复核反馈已导入，等待逐项核对。'; toast('医学复核反馈已导入');
    } catch (error) {toast(error.message);}
    finally {$('medical-import').disabled = false;}
  };
  $('medical-feedback-case').onchange = () => {$('medical-feedback-message').textContent = ''; loadFeedback();};
  window.addEventListener('nasal-case-changed', event => {
    uploaded = event.detail;
    if (location.hash === '#feedback') loadCatalog().then(loadFeedback).catch(error => toast(error.message));
  });
  window.addEventListener('nasal-step-changed', event => {
    if (event.detail === 'feedback') loadCatalog().then(loadFeedback).catch(error => toast(error.message));
  });
  document.querySelector('.historical-feedback').addEventListener('toggle', event => {
    if (!event.target.open || $('historical-feedback-view').firstChild) return;
    const frame = node('iframe'); frame.title = '原有意见与 CT 对照'; frame.src = '/landmark-review/feedback_review/index.html?embedded=1'; $('historical-feedback-view').append(frame);
  });
  loadCatalog().then(loadFeedback).catch(error => {$('medical-feedback-message').textContent = error.message;});
})();
