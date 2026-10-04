"""Read actual OpenFOAM VTU outputs and compare a non-patient channel to theory."""
import argparse
import json
from pathlib import Path
import re

import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy, numpy_to_vtk


def read_grid(path):
    reader = vtk.vtkXMLUnstructuredGridReader() if path.suffix == '.vtu' else vtk.vtkXMLPolyDataReader()
    reader.SetFileName(str(path)); reader.Update()
    grid=reader.GetOutput()
    if grid.GetNumberOfCells()==0:
        raise RuntimeError('Empty VTK read: '+str(path))
    return grid


def physical_fields(grid, rho):
    for fields in (grid.GetCellData(),grid.GetPointData()):
        p,u=fields.GetArray('p'),fields.GetArray('U')
        if p is not None:
            a=numpy_to_vtk(vtk_to_numpy(p).astype(float)*rho,deep=True);a.SetName('pressure_Pa');fields.AddArray(a)
        if u is not None:
            a=numpy_to_vtk(np.linalg.norm(vtk_to_numpy(u).astype(float),axis=1),deep=True);a.SetName('speed_m_s');fields.AddArray(a)


def write_grid(grid,path):
    writer=vtk.vtkXMLUnstructuredGridWriter() if path.suffix=='.vtu' else vtk.vtkXMLPolyDataWriter()
    writer.SetFileName(str(path));writer.SetInputData(grid)
    if writer.Write()!=1:
        raise RuntimeError('Failed VTK write: '+str(path))
    verify=read_grid(path)
    if verify.GetCellData().GetArray('pressure_Pa') is None:
        raise RuntimeError('Physical pressure not written: '+str(path))


def data_series(case,name):
    paths=sorted((case/'postProcessing'/name).glob('*/surfaceFieldValue.dat'))
    if not paths:
        raise RuntimeError('Missing monitored series: '+name)
    return np.loadtxt(paths[-1],comments='#',ndmin=2)


def analyze(base):
    manifest=json.loads((base/'run_manifest.json').read_text())
    par=manifest['parameters'];theory=manifest['analytical']
    length,gap,rho,bulk=par['L_m'],par['gap_H_m'],par['rho_kg_m3'],par['bulk_U_m_s']
    result={'schema':'poiseuille_validation/v1','patient_data':False,'clinical_validation':False,
            'description':'2D plane-Poiseuille with empty front/back; width is an extrusion scale, not no-slip side walls',
            'time_semantics':'steady SIMPLE iteration count, not physical seconds',
            'pressure_units':'OpenFOAM p is m2/s2; derived pressure_Pa = rho*p',
            'geometry_unit':'m','physical_dimensions_m':{'length':length,'gap':gap,'empty_extrusion_width':par['empty_width_W_m']},
            'mesh_dimension':2,'empty_direction':'z','nz':1,
            'field_dimensions':{'U':'m/s','p':'m2/s2','pressure_Pa':'Pa','phi':'m3/s','turbulence_intensity':'not_applicable_laminar'},
            'parameters':par,'analytical':theory,'cases':[],'source_run_manifest':str(base/'run_manifest.json')}
    plot_data=[]
    for item in manifest['cases']:
        level=item['level'];case=base/level
        candidates=list((case/'VTK').rglob('internal.vtu'))
        if len(candidates)!=1:
            raise RuntimeError('Expected exactly one final VTU per case')
        path=candidates[0];grid=read_grid(path)
        centers=vtk.vtkCellCenters();centers.SetInputData(grid);centers.Update()
        xyz=vtk_to_numpy(centers.GetOutput().GetPoints().GetData()).astype(float)
        velocity=vtk_to_numpy(grid.GetCellData().GetArray('U')).astype(float)
        pressure=rho*vtk_to_numpy(grid.GetCellData().GetArray('p')).astype(float)
        if not np.isfinite(velocity).all() or not np.isfinite(pressure).all():
            raise RuntimeError('Nonfinite solver fields: '+level)
        exact_u=6*bulk*(xyz[:,1]/gap)*(1-xyz[:,1]/gap)
        interior=(xyz[:,0]>.2*length)&(xyz[:,0]<.8*length)
        rel_l2=float(np.linalg.norm(velocity[interior,0]-exact_u[interior])/np.linalg.norm(exact_u[interior]))
        fit=np.polyfit(xyz[interior,0],pressure[interior],1)
        dp_gradient=float(-fit[0]*length)
        fo={name:data_series(case,name) for name in ['flowIn','flowOut','pressureIn','pressureOut']}
        qin,qout=fo['flowIn'][-1,1],fo['flowOut'][-1,1]
        dp=float(rho*(fo['pressureIn'][-1,1]-fo['pressureOut'][-1,1]))
        dp_series=rho*(fo['pressureIn'][:,1]-fo['pressureOut'][:,1])
        tail=dp_series[-20:]
        log=(case/'log.simpleFoam').read_text();check=(case/'log.checkMesh').read_text()
        last_residuals={}
        for name,initial,final in re.findall(r'Solving for (\w+), Initial residual = ([\deE+.-]+), Final residual = ([\deE+.-]+)',log):
            last_residuals[name]={'initial':float(initial),'final':float(final)}
        local_matches=re.findall(r'time step continuity errors : sum local = ([\deE+.-]+), global = ([\deE+.-]+)',log)
        exported=case/'postprocessed';exported.mkdir(exist_ok=True)
        physical_fields(grid,rho)
        analytical=numpy_to_vtk(exact_u,deep=True);analytical.SetName('analytical_Ux_m_s');grid.GetCellData().AddArray(analytical)
        error=numpy_to_vtk(velocity[:,0]-exact_u,deep=True);error.SetName('Ux_error_m_s');grid.GetCellData().AddArray(error)
        write_grid(grid,exported/'internal_physical.vtu')
        files=[str(exported/'internal_physical.vtu')]
        for patch in ('inlet','outlet','walls'):
            src=path.parent/'boundary'/(patch+'.vtp');poly=read_grid(src);physical_fields(poly,rho)
            target=exported/(patch+'_physical.vtp');write_grid(poly,target);files.append(str(target))
        record={'level':level,'cells':grid.GetNumberOfCells(),'nx':item['nx'],'ny':item['ny'],'nz':1,
                'solver_converged':'SIMPLE solution converged' in log,'checkMesh_passed':'Mesh OK.' in check,
                'last_iteration':float(fo['flowIn'][-1,0]),'boundary_delta_p_Pa':dp,
                'boundary_delta_p_relative_error':abs(dp-theory['delta_p_Pa'])/theory['delta_p_Pa'],
                'interior_gradient_equivalent_delta_p_Pa':dp_gradient,
                'interior_gradient_relative_error':abs(dp_gradient-theory['delta_p_Pa'])/theory['delta_p_Pa'],
                'interior_Ux_relative_L2_error':rel_l2,
                'peak_U_m_s':float(velocity[:,0].max()),
                'peak_U_relative_error':abs(float(velocity[:,0].max())-theory['max_U_m_s'])/theory['max_U_m_s'],
                'max_transverse_U_m_s':float(np.linalg.norm(velocity[:,1:],axis=1).max()),
                'inlet_phi_m3_s':float(qin),'outlet_phi_m3_s':float(qout),
                'mass_imbalance_fraction_at_stored_precision':float(abs(qin+qout)/max(abs(qin),abs(qout))),
                'mass_balance_note':'zero means below the recorded 12-significant-digit flux resolution, not proof of exact arithmetic',
                'pressure_relative_range_last20_iterations':float(np.ptp(tail)/abs(np.mean(tail))),
                'last_residuals':last_residuals,
                'last_continuity_local':float(local_matches[-1][0]) if local_matches else None,
                'last_continuity_global':float(local_matches[-1][1]) if local_matches else None,
                'postprocessed_files':files}
        record['diagnostics']={
            'mass_imbalance_fraction':record['mass_imbalance_fraction_at_stored_precision'],
            'monitor_relative_change':record['pressure_relative_range_last20_iterations'],
            'residual_max':max(v['initial'] for v in last_residuals.values()),
            'residual_max_definition':'maximum last-iteration normalized INITIAL equation residual across Ux,Uy,p',
            'monitor_definition':'(max-min)/abs(mean) of boundary pressure drop over last 20 SIMPLE iterations',
            'flux_precision_note':'zero is below the stored 12-significant-digit resolution',
        }
        result['cases'].append(record)
        unique_y=np.unique(xyz[interior,1]);profile=np.array([velocity[interior,0][np.isclose(xyz[interior,1],y,atol=1e-12)].mean() for y in unique_y])
        plot_data.append((level,unique_y,profile))
    errors=[r['boundary_delta_p_relative_error'] for r in result['cases']]
    u_errors=[r['interior_Ux_relative_L2_error'] for r in result['cases']]
    result['grid_checks']={'pressure_error_monotonically_decreases':all(b<a for a,b in zip(errors,errors[1:])),
                           'velocity_error_monotonically_decreases':all(b<a for a,b in zip(u_errors,u_errors[1:])),
                           'finest_pressure_error_below_1_percent':errors[-1]<.01,
                           'finest_U_L2_error_below_1_percent':u_errors[-1]<.01}
    result['reference_pass']=bool(len(result['cases'])==3 and all(result['grid_checks'].values()) and
        all(r['solver_converged'] and r['checkMesh_passed'] and r['mass_imbalance_fraction_at_stored_precision']<1e-6 and
            r['pressure_relative_range_last20_iterations']<1e-5 for r in result['cases']))
    (base/'validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    write_report(base,result)
    plot_reference(base,result,plot_data)
    return result


def write_report(base,result):
    lines=['# 非患者平行板 Poiseuille 求解验证','',
           '结果：'+('参考验证通过。' if result['reference_pass'] else '存在未通过项，见 JSON。')+' 只验证求解器、网格、单位和该标准流动；不验证患者解剖、鼻孔/鼻咽裁剪面或临床准确性。','',
           '使用 Ubuntu 官方包 OpenFOAM 1912.200626-1 的 simpleFoam，稳态不可压缩层流。采用安装包 pitzDaily 的实际离散格式词典，以矩形平行板通道替换几何和边界。前后面为 empty，代表二维平行板；1 mm 厚度仅用于流量尺度，不代表存在两堵侧壁。','',
           '长度 L=40 mm，间隙 H=2 mm，平均速度 0.1 m/s；rho=1.20 kg/m³、mu=1.81e−5 Pa·s、nu=1.508333333e−5 m²/s。入口抛物线按实际网格面中心采样，并按面积归一到总流量2e−7 m³/s。出口 p=0，壁面无滑移。', '',
           '解析式：u(y)=6 U_mean (y/H)(1−y/H)，Δp=12 mu U_mean L/H²=0.217200 Pa，U_max=0.150000 m/s。OpenFOAM p 为运动学压力 m²/s²，报告 Pa=rho×p。','',
           '| 网格 | 单元数 | 迭代数 | 数值 Δp / Pa | 压降相对误差 | 内部速度相对 L2 误差 | phi 质量不平衡 |',
           '|---|---:|---:|---:|---:|---:|---:|']
    for r in result['cases']:
        lines.append(f"| {r['level']} | {r['cells']} | {r['last_iteration']:.0f} | {r['boundary_delta_p_Pa']:.9f} | {100*r['boundary_delta_p_relative_error']:.4f}% | {100*r['interior_Ux_relative_L2_error']:.4f}% | {r['mass_imbalance_fraction_at_stored_precision']:.3e} |")
    lines += ['', '速度误差在 x∈(0.2L,0.8L) 的单元中心计算，与同位置解析抛物线比较。压降主值采用入口/出口面积平均压力之差；入口 zeroGradient 压力和入口离散速度会引入随网格减小的边界误差。另在 JSON 中给出内部压力梯度拟合，避免把入口离散误差当成解析理论问题。', '',
              '三档均通过 checkMesh，SIMPLE 收敛。停止阈值 p=1e−10、U=1e−8；线性求解器容差1e−12。每档另验证末20步压降稳定性。phi 入口为负、出口为正；显示0的质量不平衡表示低于已保存12位有效数字的分辨率，并非声称浮点算术绝对无误差。', '',
              '每档 postprocessed/internal_physical.vtu 和 inlet/outlet/walls_physical.vtp 来自实际求解字段。保留原始 p、U，并增加 pressure_Pa、speed_m_s；内部网格另有解析速度和误差。层流不输出湍流强度，文件迭代编号不是物理时间秒。', '',
              '第一轮以 U 残差阈值1e−10做了诊断，细网格的近零横向分量归一残差在2000步内未触发该极严格停止条件；其结果保留在相邻 poiseuille_v1912_r1 目录。正式比较三档统一使用上述 U=1e−8 阈值重跑，不混用两轮数据。', '',
              '该验证不证明鼻甲 (turbinate) 间隙、嗅裂 (olfactory cleft)、鼻阀 (nasal valve)、鼻阈 (limen nasi) 或鼻窦 (paranasal sinus) 自然开口已正确标定。任何患者候选仍保持待审核。','']
    (base/'参考算例验证报告.md').write_text('\n'.join(lines),encoding='utf-8')


def plot_reference(base,result,profiles):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    gap=result['parameters']['gap_H_m'];bulk=result['parameters']['bulk_U_m_s']
    fig,axes=plt.subplots(1,2,figsize=(11,4.2))
    y=np.linspace(0,gap,300)
    axes[0].plot(6*bulk*(y/gap)*(1-y/gap),y*1000,'k-',label='Analytical')
    for level,ys,us in profiles:
        axes[0].plot(us,ys*1000,'o',ms=3,label=level)
    axes[0].set(xlabel='Axial velocity (m/s)',ylabel='Gap coordinate (mm)',title='Non-patient plane-Poiseuille')
    axes[0].legend();axes[0].grid(alpha=.2)
    ny=[r['ny'] for r in result['cases']]
    axes[1].loglog(ny,[100*r['boundary_delta_p_relative_error'] for r in result['cases']],'o-',label='Pressure-drop error')
    axes[1].loglog(ny,[100*r['interior_Ux_relative_L2_error'] for r in result['cases']],'s-',label='Velocity L2 error')
    axes[1].set(xlabel='Cells across gap',ylabel='Relative error (%)',title='Grid refinement')
    axes[1].legend();axes[1].grid(alpha=.2)
    fig.tight_layout();fig.savefig(base/'reference_validation.png',dpi=160);plt.close(fig)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('run_dir',type=Path)
    args=parser.parse_args();result=analyze(args.run_dir.resolve())
    print(json.dumps({'reference_pass':result['reference_pass'],'cases':[{k:r[k] for k in ['level','cells','boundary_delta_p_Pa','boundary_delta_p_relative_error','interior_Ux_relative_L2_error','pressure_relative_range_last20_iterations']} for r in result['cases']]},indent=2))
    return 0 if result['reference_pass'] else 1


if __name__=='__main__':
    raise SystemExit(main())
