/* T-063：从已核验流线 HTML 提取 LINE_DATA → lines.json
 * 源 = streamlines_b15_anat_t600.html（T-058 解剖斜切扩展域，当前 manifest 口径，
 * 与 t058_b15.json 模型同切面：出口帽 125.85 mm²）。
 * 供 t058_cmp 的 sa/sb 参数叠加流线层。pos/spd 保持 base64（Uint8Array→base64），
 * JS 端 atob 解码为 Float32Array。
 * 只读源 HTML，唯一写出 = lines.json。
 */
const fs = require('fs');
const path = require('path');

const SRC = path.resolve(__dirname, '../../work/07_cfd_pipeline/workspace/pro/artifacts/streamlines_b15_anat_t600.html');
const OUT = path.resolve(__dirname, '../../work/07_cfd_pipeline/workspace/pro/artifacts/streamlines_b15_anat_t600.lines.json');

const html = fs.readFileSync(SRC, 'utf-8');
const i = html.indexOf('LINE_DATA:[');
if (i < 0) throw new Error('LINE_DATA not found');
const s = html.lastIndexOf('<script>', i);
const e = html.indexOf('</script>', i);
let code = html.slice(s + '<script>'.length, e);
if (!code.includes('const DATA =')) throw new Error('unexpected script block');
/* 在该 IIFE 后追加序列化输出 */
code += '\n;const __out = {lines: DATA.LINE_DATA.map(L => ({side: L.side, reason: L.reason, length_mm: L.length_mm, pos: b64(L.pos.buffer), spd: L.spd ? b64(L.spd.buffer) : null})), meta: {spd_p2: DATA.META.spd_p2, spd_max: DATA.META.spd_max, p_p2: DATA.META.p_p2, p_max: DATA.META.p_max, bbox: DATA.META.bbox}};';
function b64(buf) { return Buffer.from(buf).toString('base64'); }
const fn = new Function('b64', code + '\n;return __out;');
const out = fn(b64);

const payload = {
  schema: 'nasal-streamlines-lines-v1',
  case: 'b15',
  extracted_from: 'streamlines_b15_anat_t600.html（T-058 解剖斜切扩展域，当前工作台 manifest 口径；与 t058_b15.json 模型同切面）',
  source_field: 'b15 解剖斜切扩展域 t600 收敛场，vtkStreamTracer，seed=7 每侧 60',
  units: 'LPS mm（与 t058_*.json 模型同坐标系同单位；显示变换由 cmp 页端做）',
  clinical_status: 'generalisation_test_only_no_human_review',
  n_lines: out.lines.length,
  meta: out.meta,
  lines: out.lines,
};
fs.writeFileSync(OUT, JSON.stringify(payload));
const reasons = {};
out.lines.forEach(l => reasons[l.reason] = (reasons[l.reason] || 0) + 1);
console.log('lines:', out.lines.length, '| reasons:', JSON.stringify(reasons));
console.log('out size:', (fs.statSync(OUT).size / 1e6).toFixed(2), 'MB');
