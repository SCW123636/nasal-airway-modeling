"""Compare raw ASCII double-precision fields for a non-patient gauge shift."""
import argparse
import json
from pathlib import Path
import re

import numpy as np


def latest_time(case):
    times=[]
    for path in case.iterdir():
        if not path.is_dir():continue
        try:times.append((float(path.name),path))
        except ValueError:pass
    return max(times)[1]


def internal_field(path):
    text=path.read_text()
    m=re.search(r'internalField\s+nonuniform\s+List<(scalar|vector)>\s+(\d+)\s*\((.*?)\)\s*;',text,re.S)
    if not m:raise RuntimeError('Expected nonuniform ASCII internal field: '+str(path))
    components=1 if m.group(1)=='scalar' else 3;n=int(m.group(2))
    values=np.fromstring(m.group(3).replace('(',' ').replace(')',' '),sep=' ',dtype=np.float64)
    if values.size!=n*components:raise RuntimeError('Field count mismatch: '+str(path))
    return values if components==1 else values.reshape(n,components)


def monitored(case,name):
    path=next((case/'postProcessing'/name).glob('*/surfaceFieldValue.dat'))
    return np.loadtxt(path,comments='#',ndmin=2)


def run_state(case):
    text=(case/'log.simpleFoam').read_text()
    residuals={}
    for name,initial,final in re.findall(r'Solving for (\w+), Initial residual = ([\deE+.-]+), Final residual = ([\deE+.-]+)',text):
        residuals[name]={'initial':float(initial),'final':float(final)}
    qin,qout=monitored(case,'flowIn')[-1,1],monitored(case,'flowOut')[-1,1]
    pin,pout=monitored(case,'pressureIn'),monitored(case,'pressureOut')
    dp=1.2*(pin[:,1]-pout[:,1]);tail=dp[-20:]
    return {'SIMPLE_automatic_stopping_satisfied':'SIMPLE solution converged' in text,
            'last_iteration':float(pin[-1,0]),'last_residuals':residuals,
            'maximum_pressure_linear_iterations':max(int(n) for n in re.findall(r'Solving for p,.*No Iterations (\d+)',text)),
            'inlet_signed_phi_m3_s':float(qin),'outlet_signed_phi_m3_s':float(qout),
            'mass_imbalance_fraction_at_saved_precision':float(abs(qin+qout)/max(abs(qin),abs(qout))),
            'inlet_area_average_static_pressure_Pa':float(1.2*pin[-1,1]),
            'outlet_area_average_static_pressure_Pa':float(1.2*pout[-1,1]),
            'pressure_drop_Pa':float(dp[-1]),
            'last20_pressure_drop_relative_range':float(np.ptp(tail)/abs(np.mean(tail)))}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--shifted',type=Path,required=True)
    parser.add_argument('--out-dir',type=Path,required=True)
    args=parser.parse_args()
    baseline,shifted=args.baseline.resolve(),args.shifted.resolve()
    ta,tb=latest_time(baseline),latest_time(shifted)
    pa,pb=internal_field(ta/'p'),internal_field(tb/'p')
    ua,ub=internal_field(ta/'U'),internal_field(tb/'U')
    if pa.shape!=pb.shape or ua.shape!=ub.shape:raise RuntimeError('Comparison grid dimensions do not match')
    execution=json.loads((shifted/'execution.json').read_text())
    matched_pair=execution.get('comparison_mode')=='matched_numerical_settings_pair'
    state_a,state_b=run_state(baseline),run_state(shifted)
    shift=1.2*(pb-pa);du=ub-ua
    values={'cells':len(pa),'expected_uniform_pressure_shift_Pa':18.,
        'observed_pressure_shift_mean_Pa':float(shift.mean()),
        'observed_pressure_shift_min_Pa':float(shift.min()),
        'observed_pressure_shift_max_Pa':float(shift.max()),
        'pressure_shift_max_absolute_deviation_Pa':float(np.max(np.abs(shift-18.))),
        'velocity_vector_max_absolute_difference_m_s':float(np.linalg.norm(du,axis=1).max()),
        'velocity_vector_relative_L2_difference':float(np.linalg.norm(du)/np.linalg.norm(ua)),
        'pressure_drop_absolute_difference_Pa':abs(state_b['pressure_drop_Pa']-state_a['pressure_drop_Pa']),
        'pressure_drop_relative_difference':abs(state_b['pressure_drop_Pa']-state_a['pressure_drop_Pa'])/abs(state_a['pressure_drop_Pa']),
        'inlet_signed_flow_change_m3_s':state_b['inlet_signed_phi_m3_s']-state_a['inlet_signed_phi_m3_s'],
        'outlet_signed_flow_change_m3_s':state_b['outlet_signed_phi_m3_s']-state_a['outlet_signed_phi_m3_s']}
    checks={'only_outlet_pressure_input_changed':execution['changed_input_files']==['0/p'],
            'baseline_inputs_unchanged':execution['baseline_inputs_unchanged'],
            'pressure_shift_uniform_within_1e_minus6_Pa':values['pressure_shift_max_absolute_deviation_Pa']<1e-6,
            'velocity_difference_below_1e_minus7_relative':values['velocity_vector_relative_L2_difference']<1e-7,
            'pressure_drop_difference_below_1e_minus6_relative':values['pressure_drop_relative_difference']<1e-6,
            'mass_imbalance_below_1e_minus6':state_b['mass_imbalance_fraction_at_saved_precision']<1e-6,
            'last20_pressure_drop_stable_below_1e_minus6':state_b['last20_pressure_drop_relative_range']<1e-6}
    invariance=all(checks.values())
    result={'schema':'fixed_flow_pressure_reference_shift/v1','patient_data':False,'clinical_validation':False,
            'status':('invariance_observed_with_residual_stopping_warning' if not state_b['SIMPLE_automatic_stopping_satisfied'] else 'invariance_observed') if invariance else 'comparison_not_passed',
            'invariance_checks_pass':invariance,'checks':checks,'baseline_case':str(baseline),'shifted_case':str(shifted),
            'raw_fields_compared':[str(ta/'p'),str(tb/'p'),str(ta/'U'),str(tb/'U')],
            'comparison_mode':execution.get('comparison_mode','original_verified_numeric_settings'),
            'same_numerical_settings_as_original_verified':not matched_pair,
            'shared_pair_numerical_settings':execution.get('shared_numerical_settings'),
            'comparison_precision':'raw OpenFOAM ASCII fields read as float64; not float32 VTK export',
            'rho_kg_m3':1.2,'outlet_kinematic_pressure_before':0.,'outlet_kinematic_pressure_after':15.,
            'baseline':state_a,'shifted':state_b,'field_comparison':values,
            'scope':'constant-property incompressible non-patient channel with prescribed inlet flow and one outlet pressure reference',
            'independent_inlet_pressure_added':False,'same_as_total_0_static_outlet_plus18_pressure_driven_case':False,
            'limitation':'This does not validate the recording with total-pressure inlet 0 and static-pressure outlet +18 Pa, and says nothing about patient anatomy.'}
    args.out_dir.mkdir(parents=True,exist_ok=True)
    (args.out_dir/'pressure_shift_comparison.json').write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
    setup_note=('本轮比较新建的0/18 Pa匹配数值设置对照组。两组均复制已验证中网格，并统一采用压力/速度线性容差1e−10、SIMPLE停止p=1e−8、U=1e−6。它不是与原verified基线仅改一处的比较；但在本对照组内部，输入hash证明只有0/p出口压力值不同。原verified文件未改。' if matched_pair else '独立复制已验证中网格，仅将唯一出口静压从0改为+18 Pa；网格、流量、物性及数值设置保持不变。基线输入SHA-256未改变。')
    lines=['# 固定流量下出口压力参考平移：非患者实测','',setup_note,
        '本密度rho=1.2下，18 Pa对应运动学压力15 m²/s²。入口仍为固定速度剖面和zeroGradient压力，没有新增入口压力约束。','',
        '| 指标 | 基线 | 出口+18 Pa |','|---|---:|---:|',
        f"| 入口有符号流量 m³/s | {state_a['inlet_signed_phi_m3_s']:.12e} | {state_b['inlet_signed_phi_m3_s']:.12e} |",
        f"| 出口有符号流量 m³/s | {state_a['outlet_signed_phi_m3_s']:.12e} | {state_b['outlet_signed_phi_m3_s']:.12e} |",
        f"| 入口面积平均静压 Pa | {state_a['inlet_area_average_static_pressure_Pa']:.12f} | {state_b['inlet_area_average_static_pressure_Pa']:.12f} |",
        f"| 出口面积平均静压 Pa | {state_a['outlet_area_average_static_pressure_Pa']:.12f} | {state_b['outlet_area_average_static_pressure_Pa']:.12f} |",
        f"| 压降 Pa | {state_a['pressure_drop_Pa']:.12f} | {state_b['pressure_drop_Pa']:.12f} |",'',
        f"全部{len(pa)}个同序单元的压力平均平移{values['observed_pressure_shift_mean_Pa']:.12f} Pa，偏离均匀18 Pa的最大误差为{values['pressure_shift_max_absolute_deviation_Pa']:.3e} Pa。速度矢量最大差为{values['velocity_vector_max_absolute_difference_m_s']:.3e} m/s，相对L2差为{values['velocity_vector_relative_L2_difference']:.3e}。压降相对差为{values['pressure_drop_relative_difference']:.3e}。",'',
        '以上使用原始OpenFOAM双精度ASCII字段，避免VTK导出float32后对较大压力偏置的量化影响。零流量差或零波动均按已保存数据精度解释。','',
        f"平移算例自动SIMPLE停止条件满足：{state_b['SIMPLE_automatic_stopping_satisfied']}；末迭代数{state_b['last_iteration']:.0f}；末20步压降相对范围{state_b['last20_pressure_drop_relative_range']:.3e}。",'',
        '最初的严格设置试验使用1e−12压力线性容差，出现约4.5e−12数值精度下限和每步1000次压力内迭代，已定向停止并保留日志。随后另建上述匹配对照，两侧同设容差；没有改动原verified参考，也没有把被停止的初次试验伪装成SIMPLE收敛。','',
        '适用范围仅为本次常物性、不可压缩、理想通道、固定入口流量、唯一出口压力参考。它说明在这些条件下出口参考平移不会产生独立的新压降约束。不能推广到录屏中“入口总压0 + 出口静压+18 Pa”的双压力驱动设置，更不能用作患者几何或吸气方向验收。','']
    (args.out_dir/'压力参考平移实测.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'status':result['status'],'invariance_checks_pass':invariance,'field_comparison':values,'shifted_state':state_b},indent=2))
    return 0 if invariance else 1


if __name__=='__main__':raise SystemExit(main())
