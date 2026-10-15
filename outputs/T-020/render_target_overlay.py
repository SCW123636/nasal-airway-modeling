"""Render already-recorded exact loops and cap-boundary parent witnesses."""
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties

OUT=Path(__file__).resolve().parent
catalog=json.loads((OUT/'fixed_outlet_target_loop_catalog.json').read_text(encoding='utf-8'))
record=json.loads((OUT/'fixed_outlet_target_constraints.json').read_text(encoding='utf-8'))
start=json.loads((OUT/'target_trial_start.json').read_text(encoding='utf-8'))
spec=start['planes']['nasopharynx_outlet'];o=np.array(spec['point_lps_mm']);n=np.array(spec['normal_lps']);n/=np.linalg.norm(n)
helper=np.array([1.,0,0]);u=np.cross(n,helper);u/=np.linalg.norm(u);v=np.cross(n,u)
def project(p):
    p=np.asarray(p)-o
    return np.column_stack((p@u,p@v))
font=FontProperties(fname=r'C:\Windows\Fonts\msyh.ttc')
plt.rcParams.update({'font.family':font.get_name(),'axes.unicode_minus':False,'font.size':10})
fig,ax=plt.subplots(figsize=(12,6),layout='constrained')
colors=['#0072B2','#009E73','#CC79A7','#E69F00']
for loop,color in zip(catalog['loops'],colors):
    xy=project(loop['contour_lps_mm']);xy=np.vstack((xy,xy[0]))
    ax.plot(xy[:,0],xy[:,1],color=color,lw=1.8,label=f"环 {loop['id']} · {loop['area_mm2']:.3f} mm²")
for patch,marker in (('nostril_L','o'),('nostril_R','x')):
    pts=[x['prospective_cap_point_lps_mm'] for x in record['protected_witnesses'] if x['patch']==patch]
    xy=project(pts)
    ax.scatter(xy[:,0],xy[:,1],s=8,marker=marker,c='#D55E00',alpha=.55,
               label=('左' if patch.endswith('_L') else '右')+'鼻孔 cap 边界在此平面的投影')
ax.set_aspect('equal');ax.grid(alpha=.2);ax.set_xlabel('平面内 u 坐标 (mm)');ax.set_ylabel('平面内 v 坐标 (mm)')
ax.set_title('p0 自动提案 · 原出口切面固定：闭环与此前 cap 保护映射',fontproperties=font,fontsize=14)
ax.legend(loc='upper left',bbox_to_anchor=(1.01,1),prop=font,frameon=False)
signed=[x['outlet_signed_mm'] for x in record['protected_witnesses']]
note=(f"红色为此前 cap 边界的正交投影，并非出口平面上的点\n"
      f"774 个真实交点在出口删除侧：{min(signed):.3f} 至 {max(signed):.3f} mm\n"
      "环 0/2 共享负分量 0；环 1 属分量 1：均触达鼻孔 cap\n"
      "环 3 不触达 cap，但面积 12.218 mm²，低于工程下限 120\n"
      "工程出口面积带 120–500 mm² 未修改；未选择解剖目标环\n\n"
      f"LPS / mm · surface SHA {record['source_sha256'][:16]}…\n"
      f"plane SHA {record['binding']['plane_sha256'][:16]}…\n"
      "数学选区约束证据；不代表医学切面审核或患者 CFD 准入")
ax.text(1.01,.42,note,transform=ax.transAxes,va='top',fontproperties=font,fontsize=9,linespacing=1.8)
fig.savefig(OUT/'p0_fixed_plane_target_constraints.png',dpi=180)
print(str(OUT/'p0_fixed_plane_target_constraints.png'))
