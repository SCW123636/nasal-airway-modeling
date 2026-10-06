'use strict';
const params = new URLSearchParams(location.search);
const caseId = params.get('case');
const $ = id => document.getElementById(id);
let state = null;
let manifest = null;
let draftId = null;
function setMessage(value, error = true) { $('message').textContent = value || ''; $('message').className = error ? 'error' : 'success'; }
async function api(url, options = {}) {
  const response = await fetch(url, options);
  let data = null; try { data = await response.json(); } catch {}
  if (!response.ok) throw Error(data?.error || `请求失败：${response.status}`);
  return data;
}
function asset(name) { return `/boundary-assets/${caseId}/${draftId}/${name}`; }
function renderEvidence() {
  const box = $('evidence'); box.replaceChildren();
  if (!manifest || !draftId) return;
  for (const [key, label] of [['axial','轴向'],['coronal','冠状'],['sagittal','矢状'],['oral_overlay','口腔叠加'],['sinus_overlay','鼻窦叠加'],['openings_overlay','开口叠加']]) {
    const figure = document.createElement('figure'); const image = document.createElement('img');
    image.src = asset(key); image.alt = label + '边界证据';
    image.addEventListener('click', () => { $('lightbox-image').src = image.src; $('lightbox-image').alt = image.alt; $('lightbox').hidden = false; });
    const caption = document.createElement('figcaption'); caption.textContent = label;
    figure.append(image, caption); box.append(figure);
  }
  const grid = manifest.panels?.axial?.[0]?.grid;
  const size = grid?.size || [];
  $('meta').textContent = `草稿 ${draftId} · ${size.length ? size.join(' x ') + ' 像素' : '高分辨率'} · 参数 ${manifest.parameters_sha256} · CFD locked`;
  $('save').disabled = false;
}
function renderState(data) {
  state = data; $('case-label').textContent = `病例 ${caseId || '缺少编号'}`;
  if (!data) return;
  const preview = data.boundary_preview;
  if (preview?.status === 'generated') {
    draftId = preview.draft_id; manifest = data.boundary_preview_manifest;
    renderEvidence(); $('status').textContent = '已有绑定草稿，可复核证据并保存决定。';
  } else $('status').textContent = data.status === 'review_recorded' ? '点位审核完成，等待掩膜和边界草稿。' : '当前病例尚未完成点位审核。';
  const mask = data.boundary_inputs?.sinus_exclusion_mask;
  $('mask-name').textContent = mask ? `已上传掩膜 · ${mask.sha256}` : '尚未上传鼻窦排除掩膜';
  $('generate').disabled = !(data.status === 'review_recorded' && !!mask);
}
async function load() {
  if (!/^u_[0-9a-f]{16}$/.test(caseId || '')) { setMessage('缺少有效病例编号'); return; }
  try { renderState(await api(`/api/cases/${caseId}/boundary-preview`)); } catch (error) { setMessage(error.message); }
}
$('upload-mask').onclick = async () => {
  const file = $('mask').files[0]; if (!file) { setMessage('请选择鼻窦排除掩膜'); return; }
  try {
    $('upload-mask').disabled = true;
    renderState(await api(`/api/cases/${caseId}/boundary-mask`, {method:'PUT', headers:{'Content-Type':'application/octet-stream'}, body:file}));
    setMessage('掩膜已上传', false);
  } catch (error) { setMessage(error.message); } finally { $('upload-mask').disabled = false; }
};
$('generate').onclick = async () => {
  if (!$('oral-confirmed').checked || !$('sinus-confirmed').checked) { setMessage('请先确认口腔排除和鼻窦策略'); return; }
  try {
    $('generate').disabled = true;
    const data = await api(`/api/cases/${caseId}/boundary-preview`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({oral_exclusion_confirmed:true, sinus_policy_confirmed:true})});
    renderState(data); setMessage('草稿已生成，可查看六类证据', false);
  } catch (error) { setMessage(error.message); } finally { if (state?.boundary_inputs) $('generate').disabled = false; }
};
$('save').onclick = async () => {
  const reviewer = $('reviewer').value.trim();
  if (!reviewer) { setMessage('请填写复核人'); return; }
  if (!manifest || !draftId || !$('oral-confirmed').checked || !$('sinus-confirmed').checked) { setMessage('请完成策略确认并生成草稿'); return; }
  const controls = manifest.controls;
  const record = {schema:'boundary_review/v1', case:manifest.binding.case, patient_id:manifest.binding.patient_id,
    revision:manifest.binding.revision, coordinate_system:'LPS', unit:'mm', status:'confirmed', method:'human', reviewer,
    reviewed_at:new Date().toISOString(), source:{...manifest.binding, draft_preview_sha256:state.boundary_preview.sha256,
      parameters_sha256:manifest.parameters_sha256}, openings:controls.openings,
    oral_exclusion:{confirmed:true, mode:'same_as_nasopharynx_outlet', boundary_ref:'nasopharynx_outlet', evidence:'CT 叠加复核'},
    sinus_policy:{confirmed:true, policy:'exclude_sinuses', regions:['maxillary','frontal','ethmoid','sphenoid'], evidence:'CT 叠加与排除掩膜复核', mask_sha256:controls.sinus_policy.mask_sha256},
    evidence_sha256:Object.fromEntries(['axial','coronal','sagittal','oral_overlay','sinus_overlay','openings_overlay'].map(key => [key, manifest.outputs[key].sha256]))};
  try {
    $('save').disabled = true;
    const data = await api(`/api/cases/${caseId}/boundary-review`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({draft_id:draftId, record})});
    state = data; $('saved').textContent = '边界审核已保存；几何、网格和患者 CFD 仍需后续阶段。'; setMessage('', false);
  } catch (error) { setMessage(error.message); $('save').disabled = false; }
};
$('back').onclick = () => { if (window.parent !== window) window.parent.postMessage({type:'nasal-workspace-navigate',step:'review'}, location.origin); else history.back(); };
$('lightbox').onclick = () => { $('lightbox').hidden = true; $('lightbox-image').removeAttribute('src'); };
load();
