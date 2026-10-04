# -*- coding: utf-8 -*-
"""把 _axial.json 包成自包含 HTML 复核页"""
import os, json

CAL = r"D:\项目\鼻腔建模\work\03_calib"
data = open(os.path.join(CAL, "_axial.json"), encoding="utf-8").read()

HTML = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>鼻腔 CT 标定复核 —— 切在哪，一眼可见</title>
<style>
*{box-sizing:border-box}
body{background:#0d1726;color:#ecf5fc;font-family:system-ui,"Microsoft YaHei",sans-serif;margin:0}
main{max-width:1180px;margin:auto;padding:14px 18px 40px}
h1{font-size:22px;margin:12px 0 6px}
h2{font-size:17px;margin:22px 0 8px;border-left:4px solid #4a9eff;padding-left:9px}
.legend{background:#14263a;padding:11px 14px;border-radius:7px;margin:12px 0;line-height:1.9;font-size:14px}
.sw{display:inline-block;width:13px;height:13px;border-radius:3px;vertical-align:-1px;margin-right:5px}
.alert{border-left:5px solid #fa9a5e;background:#332724;padding:12px 15px;line-height:1.7;border-radius:5px;margin:12px 0;font-size:14px}
.tbl{width:100%;border-collapse:collapse;margin:10px 0;font-size:14px}
.tbl th,.tbl td{border:1px solid #2c4a66;padding:7px 10px;text-align:left}
.tbl th{background:#1c3350}
.tbl td.num{font-family:ui-monospace,Consolas,monospace}
.ok{color:#5ddb8f}.bad{color:#ff7a7a}.warn{color:#ffc861}
.viewer{display:grid;grid-template-columns:1fr 260px;gap:16px;margin-top:12px}
@media(max-width:820px){.viewer{grid-template-columns:1fr}}
canvas{width:100%;max-width:512px;background:#000;border-radius:6px;display:block;image-rendering:auto}
.panel{background:#14263a;border-radius:7px;padding:12px}
.panel label{display:block;font-size:13px;margin:9px 0 3px;color:#b9d2e5}
input[type=range]{width:100%}
.btnrow{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
button{background:#203a51;color:#fff;border:1px solid #668aa5;border-radius:5px;padding:5px 9px;cursor:pointer;font-size:13px}
button:hover{background:#2b4d6b}
.mono{font-family:ui-monospace,Consolas,monospace}
#info{background:#1a2f43;border:1px solid #426580;padding:10px;border-radius:6px;margin-top:10px;font-size:13px;line-height:1.7;min-height:52px}
.bar{position:relative;height:26px;background:#132538;border-radius:4px;margin:8px 0;overflow:hidden}
.bar .seg{position:absolute;top:0;bottom:0;opacity:.55}
.bar .mk{position:absolute;top:0;bottom:0;width:2px;background:#fff}
</style></head><body><main>

<h1>鼻腔 CT 标定复核</h1>
<div class="alert">
<b>本页是"看位置对不对"的工具，不是分割结论。</b>
红色 = 本方法识别的<b>体内空气</b>（被组织包围，从图像边缘连通不到）；黄色 = 当前 v9 分割掩膜。
两者对比，可以直接看出 v9 切在了哪里、漏掉了什么。<b>红色里仍含口腔/鼻窦等非鼻腔空气</b>，需按解剖再筛。
</div>

<div class="legend">
<span class="sw" style="background:#ff5050"></span>体内空气（被组织包围）　
<span class="sw" style="background:#ffff00"></span>v9 分割掩膜　
<span class="sw" style="background:#888"></span>CT 骨窗
</div>

<h2>一、为什么之前的定位会失败</h2>
<div class="tbl-wrap">
<table class="tbl">
<tr><th>判据</th><th>v9 取值</th><th>实测鼻腔主体</th><th>后果</th></tr>
<tr><td>max_size</td><td class="num bad">8000</td><td class="num">77,000 – 89,000</td><td class="bad">量级差 10 倍，主气道被"太大"拒掉</td></tr>
<tr><td>触边判据</td><td class="bad">剔除</td><td>必然触边</td><td class="bad">鼻腔连到咽部/气管，与解剖事实冲突</td></tr>
<tr><td>aspect</td><td class="num">≥1.4</td><td class="num">恒为 1.00</td><td class="bad">对主体完全无分辨力</td></tr>
<tr><td>左右对称比</td><td class="num bad">0.175</td><td class="num">应 ≥0.7</td><td class="bad">左 302,834 / 右 53,073，差 5.7 倍</td></tr>
<tr><td>bbox 捕获率</td><td class="num bad">0.413</td><td class="num">应 ≥0.9</td><td class="bad">漏掉 59% 的空气</td></tr>
<tr><td>掩膜 HU 纯净度</td><td class="num ok">frac>0 = 0</td><td class="num">—</td><td class="ok">无组织混入，这点没问题</td></tr>
</table>
</div>

<h2>二、解剖锚点（自动推定，待你目视确认）</h2>
<div class="tbl-wrap">
<table class="tbl">
<tr><th>锚点</th><th>z 层</th><th>毫米 z</th><th>含义</th></tr>
<tr><td>鼻孔入口</td><td class="num" id="t_nos"></td><td class="num" id="t_nosm"></td><td>面积上升沿起点</td></tr>
<tr><td>最宽层</td><td class="num" id="t_wid"></td><td class="num" id="t_widm"></td><td>鼻腔段 x 跨度最大</td></tr>
<tr><td>鼻腔峰值</td><td class="num" id="t_pk"></td><td class="num" id="t_pkm"></td><td>横截面积最大（鼻甲区）</td></tr>
<tr><td>鼻咽过渡</td><td class="num" id="t_nas"></td><td class="num" id="t_nasm"></td><td>最强下降沿</td></tr>
</table>
</div>
<p style="font-size:14px;color:#b9d2e5">
<b>交叉验证</b>：鼻腔跨度 = <span class="mono" id="t_span"></span> mm。
成人鼻腔解剖长度约 50–70 mm —— 落在此区间，是标定正确性的独立佐证。
</p>

<div class="bar" id="profbar"></div>

<h2>三、逐层复核</h2>
<div class="viewer">
  <div>
    <canvas id="cv" width="512" height="512"></canvas>
    <input type="range" id="sl" min="0" max="393" value="146" step="1">
    <div id="info"></div>
  </div>
  <div class="panel">
    <label>层 z = <span class="mono" id="zl"></span>　（毫米 z = <span class="mono" id="zm"></span>）</label>
    <label>快速跳转</label>
    <div class="btnrow">
      <button data-z="62">鼻孔入口</button>
      <button data-z="132">最宽</button>
      <button data-z="146">鼻腔峰值</button>
      <button data-z="208">鼻咽过渡</button>
    </div>
    <div class="btnrow">
      <button id="prev">◀ 上一层</button>
      <button id="next">下一层 ▶</button>
    </div>
    <label>跳转区间（复核重点）</label>
    <div class="btnrow">
      <button id="j1">z 55–105（鼻孔）</button>
      <button id="j2">z 195–220（鼻咽）</button>
    </div>
    <label>步进</label>
    <div class="btnrow">
      <button data-step="1">1</button>
      <button data-step="5">5</button>
      <button data-step="10">10</button>
    </div>
  </div>
</div>

<h2>四、怎么用这一页</h2>
<div class="legend">
<b>1. 确认鼻孔入口。</b>拖到 z=62 附近，看红色区域是否"正好从鼻前庭开始"。
若更靠后（比如 z≈85）才出现鼻腔，说明锚点偏早，需要调整。<br>
<b>2. 确认鼻咽过渡。</b>拖到 z=208 附近，看红色是否从"鼻腔宽腔"转为"咽部窄腔"。<br>
<b>3. 看 v9 错在哪。</b>在 z=100–200 区间，黄色（v9）应只是红色（体内空气）中的<b>一小条</b>。
红色中没被黄色覆盖的部分，就是被漏掉的鼻腔主体。<br>
<b>4. 排除非鼻腔空气。</b>红色中若出现在口腔（下颌后方）或鼻窦位置的色块，
说明还需要按解剖位置进一步筛除。
</div>

</main><script>
const D = __DATA__;
const A = D.anchors;
const SP = D.spacing, ORG = D.origin;
const cv = document.getElementById('cv'), ctx = cv.getContext('2d');
const sl = document.getElementById('sl');
const imgs = {};
let cur = 146, step = 1;

function fmtZ(z){ return z; }
function mmz(z){ return (ORG[2] + z*SP[2]).toFixed(2); }

// 锚点表
const g = id => document.getElementById(id);
g('t_nos').textContent = A.z_nostril_entry.z;
g('t_nosm').textContent = A.z_nostril_entry.mm_z;
g('t_wid').textContent = A.z_widest.z;
g('t_widm').textContent = A.z_widest.mm_z;
g('t_pk').textContent = A.z_nasal_peak.z;
g('t_pkm').textContent = A.z_nasal_peak.mm_z;
g('t_nas').textContent = A.z_nasopharynx.z;
g('t_nasm').textContent = A.z_nasopharynx.mm_z;
const span = (A.z_nasopharynx.z - A.z_nostril_entry.z) * SP[2];
g('t_span').textContent = span.toFixed(2);

// 剖面条
(function(){
  const bar = g('profbar');
  const zs = Object.keys(D.axial).map(Number).sort((a,b)=>a-b);
  const segs = [
    [0, A.z_nostril_entry.z, '#1b3a55', '下颈部'],
    [A.z_nostril_entry.z, A.z_nasal_peak.z, '#2e6b3f', '鼻腔'],
    [A.z_nasal_peak.z, A.z_nasopharynx.z, '#6b4a2e', '鼻咽'],
    [A.z_nasopharynx.z, D.nz, '#1b3a55', '咽/喉'],
  ];
  const zmax = D.nz;
  segs.forEach(([a,b,c])=>{
    if(b<=a) return;
    const d = document.createElement('div');
    d.className='seg'; d.style.left=(a/zmax*100)+'%';
    d.style.width=((b-a)/zmax*100)+'%'; d.style.background=c;
    bar.appendChild(d);
  });
  [A.z_nostril_entry.z, A.z_nasal_peak.z, A.z_nasopharynx.z].forEach(z=>{
    const m=document.createElement('div'); m.className='mk';
    m.style.left=(z/zmax*100)+'%'; bar.appendChild(m);
  });
  const cur = document.createElement('div'); cur.id='barmark';
  cur.className='mk'; cur.style.background='#ffd75e'; cur.style.width='3px';
  bar.appendChild(cur);
})();

function nearestKey(z){
  let best=null, bd=1e9;
  for(const k in D.axial){
    const d=Math.abs(Number(k)-z);
    if(d<bd){bd=d;best=k;}
  }
  return best;
}

function draw(){
  const k = nearestKey(cur);
  const showZ = Number(k);
  const render = () => {
    // 画到 canvas，并叠加当前层标注
    ctx.drawImage(imgs[k], 0, 0, 512, 512);
    ctx.strokeStyle='#ffd75e'; ctx.lineWidth=1.6;
    ctx.strokeRect(1,1,510,510);
    ctx.fillStyle='rgba(0,0,0,0.65)'; ctx.fillRect(6,6,236,26);
    ctx.fillStyle='#ffd75e'; ctx.font='15px ui-monospace,Consolas,monospace';
    ctx.fillText('z='+showZ+'  ('+mmz(showZ)+' mm)', 12, 25);
    sl.value = showZ;
    g('zl').textContent = showZ;
    g('zm').textContent = mmz(showZ);
    const bm = document.getElementById('barmark');
    if(bm) bm.style.left = (showZ/D.nz*100)+'%';
    // 位置判定
    let pos='';
    if(showZ < A.z_nostril_entry.z) pos='<span class="warn">位于鼻腔入口之前</span>（下方颈部/下颌）';
    else if(showZ < A.z_nasal_peak.z) pos='<span class="ok">鼻腔段（前部→鼻甲区）</span>';
    else if(showZ < A.z_nasopharynx.z) pos='<span class="warn">鼻腔后段→鼻咽过渡</span>';
    else pos='<span class="bad">鼻咽之后（咽/喉）</span>';
    g('info').innerHTML = '当前 <span class="mono">z='+showZ+'</span>，'+
      '毫米 z=<span class="mono">'+mmz(showZ)+'</span>，解剖位置：'+pos+
      '<br>距鼻孔入口 <span class="mono">'+((showZ-A.z_nostril_entry.z)*SP[2]).toFixed(2)+'</span> mm，'+
      '距鼻咽过渡 <span class="mono">'+((A.z_nasopharynx.z-showZ)*SP[2]).toFixed(2)+'</span> mm';
  };
  if(imgs[k]){ render(); return; }
  const loader = new Image();
  loader.onload = () => { imgs[k]=loader; render(); };
  loader.onerror = () => { g('info').textContent = '第 '+k+' 层图像加载失败'; };
  loader.src = 'data:image/png;base64,'+D.axial[k];
}

sl.addEventListener('input', e=>{ cur=Number(e.target.value); draw(); });
g('prev').onclick=()=>{ cur=Math.max(0,cur-step); draw(); };
g('next').onclick=()=>{ cur=Math.min(D.nz-1,cur+step); draw(); };
document.querySelectorAll('[data-z]').forEach(b=>b.onclick=()=>{cur=Number(b.dataset.z);draw();});
document.querySelectorAll('[data-step]').forEach(b=>b.onclick=()=>{step=Number(b.dataset.step);});
g('j1').onclick=()=>{ cur=55; draw(); };
g('j2').onclick=()=>{ cur=195; draw(); };

sl.max = D.nz-1;
draw();
</script></body></html>
"""

html = HTML.replace("__DATA__", data)
out = os.path.join(CAL, "鼻腔标定复核.html")
with open(out, "w", encoding="utf-8") as f:
    f.write(html)
print("WROTE", out)
print(f"size = {os.path.getsize(out)/1048576:.1f} MB")
