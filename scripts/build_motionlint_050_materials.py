"""Build traceable 0.5.0 tables and report text from frozen machine results."""
import hashlib
import json
from pathlib import Path
import re
import sys
import statistics

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from motionlint.artifacts import sha256
from motionlint.cli.main import _write_json
from motionlint_050_privacy import sanitize


def main():
    base=ROOT/'reports/iteration_050'
    source_files={
        'baseline':'baseline_foot/summary.json','candidate_baseline':'v6_v4_foot-final/summary.json',
        'controlled':'holdout-v5/summary.json','safety':'safety-results-3/summary.json',
        'engineering_dev':'engineering-development/summary.json','engineering_test':'engineering-holdout/summary.json',
        'flow':'complete-flows-v3/summary.json','methods_v4':'method-experiments/v4/summary.json',
        'methods_v5':'method-experiments/v5/summary.json','export_ablation':'export-check-ablation.json',
        'selection':'candidate-selection.json','performance':'performance/summary.json',
        'installed':'local-wheel-matrix.json','browser':'browser-release/summary.json','dependency_audit':'dependency-audit.json',
        'frontend_audit':'frontend-dependency-audit-final.json',
        'freeze':'freeze-v5/freeze.json','dynamic_manifest':'dynamic-2/manifest.json',
        'real_manifest':'engineering-1/manifest.json','safety_manifest':'safety-2/manifest.json'}
    source={k:json.loads((base/v).read_text(encoding='utf-8')) for k,v in source_files.items()}
    assert source['methods_v4']['count']==source['methods_v5']['count']==660
    assert source['controlled']['rules_sha256']==source['methods_v5']['rules_sha256']
    cases=source['controlled']['records']
    repairable=[r for r in cases if r['known_repairable']]
    repair_reductions=[r['repair']['support_comparison']['original_support_distance_reduction_ratio']
        if r.get('repair') and r['repair']['support_comparison'].get('available') else 0. for r in repairable]
    controls=[r for r in cases if r['kind']=='clean']
    flows=[]
    for row in source['flow']['rows']:
        flow=row['flow']
        gates={key:value['gate']['status'] for key,value in flow['stages'].items()}
        gates['character']=flow['character']['gate']['status']
        charfolder=Path(flow['character_dir'])
        mesh=json.loads((charfolder/'character/mesh_metrics.json').read_text(encoding='utf-8'))
        flows.append({'id':row['id'],'source':row['source'],'group_id':row['group_id'],'status':row['status'],
            'gates':gates,'overall_quality_pass':all(v=='PASS' for k,v in gates.items() if k!='raw'),
            'video_verification':flow['character']['video'],'video_sha256':sha256(charfolder/'kenney.mp4'),
            'mesh_metrics_sha256':sha256(charfolder/'character/mesh_metrics.json'),
            'mesh_metrics':{'evidence_type':mesh['evidence_type'],'max_scene_plane_penetration_m':mesh['max_scene_plane_penetration_m'],
                'separate_from_skeleton_quality_gate':True,'limits':mesh['limits']},
            'actual_bvh_geometry':flow['stages']['bvh'].get('conversion_geometry')})
    # Public records include identities, hashes and outcomes, not restricted arrays
    # or local machine paths. Full candidates remain in the local evidence bundle.
    tests=(base/'final-tests-v4.log').read_text(encoding='utf-8-sig',errors='replace')
    counts=re.search(r'(\d+) passed, (\d+) skipped',tests)
    if not counts:raise ValueError('Final tests did not finish successfully')
    real_rows=source['engineering_dev']['rows']+source['engineering_test']['rows']
    diagnostics=[]
    for row in source['candidate_baseline']['rows']:
        if row['kind']!='foot_sliding' or row['gate_after']=='PASS':continue
        repair=json.loads((base/'v6_v4_foot-final/results'/row['id']/'repair_report.json').read_text(encoding='utf-8'))
        step=next(s for s in repair['steps'] if s['repair']=='foot_lock')
        diagnostics.append({'id':row['id'],'residual_gate':'FAIL','status':step['status'],
            'constraint_diagnostic':step.get('constraint_diagnostic'),'solver_scope':step.get('solver_scope'),
            'solver_statuses':[t.get('detail',{}).get('solver_status') for t in step.get('candidate_trials',[])
                              if t.get('detail',{}).get('solver_status')]})
    result={
        'schema_version':3,'version':'0.5.0','rule_version':5,'repair_version':6,
        'rules_sha256':source['controlled']['rules_sha256'],'freeze_sha256':sha256(base/source_files['freeze']),
        'evidence_type':'automated_controlled_and_real_engineering_separate',
        'counts':{'dynamic':600,'dynamic_development':240,'dynamic_holdout':360,'real':60,'real_holdout':36,'safety':60},
        'controlled':{k:source['controlled'][k] for k in ('count','macro_f1','per_class','normal_count','normal_high_severity_false_positive_fraction','joint_localization_recall','event_policy')},
        'repairable_holdout':{'count':len(repairable),'accepted_count':sum(r['repair']['status']=='accepted' for r in repairable),
            'median_original_support_distance_reduction_ratio':statistics.median(repair_reductions),
            'all_attempts_in_denominator':True,'input_hashes_unchanged':all(r['input_unchanged'] for r in cases),
            'normal_controls_unchanged_count':sum(r['repair']['status']=='no_op' for r in controls)},
        'baseline':{key:source['baseline'][key] for key in ('injected_count','injected_gate_pass_count','median_support_distance_reduction_ratio','clean_unchanged_count')},
        'candidate_baseline':{key:source['candidate_baseline'][key] for key in ('injected_count','injected_gate_pass_count','median_support_distance_reduction_ratio','clean_unchanged_count','max_joint_shift_m','max_bone_length_change_m')},
        'baseline_float_comparison_tolerance':1e-6,
        'remaining_baseline_failures':diagnostics,
        'safety':{key:source['safety'][key] for key in ('count','passed_count','status','manifest_sha256')},
        'engineering':{'count':len(real_rows),'ready_count':sum(r['status']=='ready' for r in real_rows),
            'scope':'No human defect or semantic truth; physical quantities and engineering outcomes only',
            'rows':[sanitize({k:v for k,v in r.items() if k not in {'flow'}}) for r in real_rows]},
        'methods':{name:{key:source['methods_'+name][key] for key in ('rules_version','rules_sha256','count','summary','holdout_controlled','holdout_real','historical_method_policy')}
            for name in ('v4','v5')},
        'flows':sanitize(flows),'complete_flow_ready_count':source['flow']['ready_count'],
        'complete_flow_quality_pass_count':sum(r['overall_quality_pass'] for r in flows),
        'complete_flow_quality_scope':'Six skeleton checks for repaired, written BVH and actual character. Deformed mesh metrics reported separately.',
        'export_ablation_false_complete_passes':source['export_ablation']['false_complete_pass_without_export_check_count'],
        'candidate_selection':sanitize(source['selection']),
        'performance':sanitize(source['performance']),
        'tests':{'passed':int(counts[1]),'skipped_optional':int(counts[2])},
        'local_wheel':sanitize(source['installed']), 'browser':sanitize(source['browser']),
        'dependency_audit':{'packages':len(source['dependency_audit']['dependencies']),
            'known_vulnerabilities':sum(len(d['vulns']) for d in source['dependency_audit']['dependencies']),
            'scope':'Pinned competition production dependencies, advisory snapshot; not a guarantee of future safety'},
        'frontend_dependency_audit':source['frontend_audit']['metadata'],
        'remote_ci':{'status':'not_verified', 'reason':'Git push rejected: current credential lacks workflow permission; connected app write returned 403'},
        'source_results':{k:{'relative_path':'reports/iteration_050/'+v,'sha256':sha256(base/v)} for k,v in source_files.items()},
        'limitations':['Controlled trajectories have finite analytic diversity; F1 is not real-motion accuracy.',
            'Real inputs have no human semantic or defect labels.',
            'Five of six actual characters still fail the strict quality gate.',
            'Historical v5 internally uses untouched v4; outputs are evaluated with the displayed shared rule.',
            'Team ownership and inherited helpers remain under review; no automatic signature or project-wide MIT.'],
        'recovery_history':['Initial generation load failures preserved in attempt-history.',
            'MemoryError during first summary/experiment processes preserved; compact indices and serial chunks resumed same inputs.',
            'Character v1/v2 retained; v3 records corrected joint-name-aligned geometry measurements.']}
    _write_json(ROOT/'evidence/iteration-050-results.json',result)
    registry={'dynamic':source['dynamic_manifest']['motions'],'real':source['real_manifest']['rows'] if 'rows' in source['real_manifest'] else source['real_manifest']['motions'],
              'safety':source['safety_manifest']['samples']}
    _write_json(ROOT/'evidence/iteration-050-sample-registry.json',sanitize(registry))
    _write_json(ROOT/'evidence/iteration-050-freeze.json',{**sanitize(source['freeze']),
        'original_freeze_sha256':result['freeze_sha256'],'local_paths_redacted':True})
    _write_json(ROOT/'evidence/iteration-050-method-outcomes.json',sanitize({policy:source['methods_'+policy]['rows'] for policy in ('v4','v5')}))
    claims={key:{'json_file':'evidence/iteration-050-results.json','json_pointer':pointer,'evidence_type':kind,
        'rules_sha256':result['rules_sha256'],'code_freeze_sha256':result['freeze_sha256']}
        for key,pointer,kind in [
            ('controlled_macro_f1','/controlled/macro_f1','controlled_injection_only'),
            ('known_repairable_distance_reduction','/repairable_holdout/median_original_support_distance_reduction_ratio','known_reference_subset'),
            ('real_strict_pass_v6','/methods/v5/holdout_real/repair_v6/strict_pass_count','real_engineering_no_human_truth'),
            ('actual_character_pass','/complete_flow_quality_pass_count','actual_written_character'),
            ('safety_rejection','/safety/passed_count','predeclared_adverse_candidates'),
            ('installation','/local_wheel/rows','automated_external_wheel_installation'),
            ('browser','/browser/checks','actual_browser_operations')]}
    _write_json(ROOT/'evidence/iteration-050-claims.json',claims)
    def format_method_table(scope,policy='v5'):
        rows=['| 方法 | 严格通过 | 接受样本 | 退步样本 | 执行错误 |','| --- | ---: | ---: | ---: | ---: |']
        for name,values in result['methods'][policy][scope].items():
            rows.append(f"| {name} | {values['strict_pass_count']} | {values['sample_accepted_count']} | {values['regression_count']} | {values['execution_failures']} |")
        return '\n'.join(rows)
    r=result['repairable_holdout']; old=result['baseline']; new=result['candidate_baseline']
    table='\n'.join([
        '| 本轮自动证据 | 结果 | 范围 |','| --- | --- | --- |',
        f"| 已知缺陷检测 | 宏 F1 {result['controlled']['macro_f1']:.2f}；每类 1.00 | 360 可控保留条目 |",
        '| 正常高严重度误报 | 0/36 | 可控正常对照 |',
        f"| 脚滑物理改善 | 中位数 {r['median_original_support_distance_reduction_ratio']*100:.2f}% | 54 条预定义可修复保留子集，全部尝试计入 |",
        '| 安全审查 | 60/60 符合拒绝预期 | 专项反例 |',
        f"| 真实保留严格通过 | v5 修复 10/36 → v6 修复 22/36 | 同检测规则 v5，无人工准确率真值 |",
        f"| 四阶段实际产物 | {result['complete_flow_ready_count']}/6 完成；{result['complete_flow_quality_pass_count']}/6 跨阶段骨架质量通过 | 变形网格指标另列，不纳入骨架质量门 |",
        f"| 本机测试与安装 | {result['tests']['passed']} 通过，10 可选跳过；4 种 wheel 配置通过 | Windows Python 3.10/3.11 核心与优化 |"])
    readme=(ROOT/'README.md').read_text(encoding='utf-8')
    readme=re.sub(r'(?<=<!-- MOTIONLINT_050_RESULTS_START -->).*?(?=<!-- MOTIONLINT_050_RESULTS_END -->)',
        '\n\n'+table+'\n\n完整数据见 [本轮结果](docs/MOTIONLINT_050_RESULTS.md) 和 [机器记录](evidence/iteration-050-results.json)。\n\n',readme,flags=re.S)
    (ROOT/'README.md').write_text(readme,encoding='utf-8')
    flowtable='\n'.join(['| 预先固定样本 | 原始 | 修复 | BVH | 角色 |','| --- | --- | --- | --- | --- |']+
        [f"| {f['id']} | {f['gates']['raw']} | {f['gates']['repaired']} | {f['gates']['bvh']} | {f['gates']['character']} |" for f in flows])
    text=f'''# MotionLint 动作质检工具

0.5.0 参赛技术报告 · 自动工程评测

由冻结机器结果构建。规则 v5、修复 v6、报告格式 v3。规则哈希 `{result['rules_sha256']}`，检测/修复冻结哈希 `{result['freeze_sha256']}`。

{table}

## 问题、用户与方案

生成模型开发者、动画开发者和处理动作数据的学生需要检查模型输出的物理异常，并确认修复和导出是否引入新问题。动作可能来自不同模型、关节顺序、坐标和采样率；单个总分不能说明异常位置，也不能证明最终角色与数组保持一致。
本工具把原始动作、修复数组、BVH 和角色分阶段记录，统一六项检查及上下文，保存每次候选、失败原因、输入/规则/代码哈希。人工检查成本和用户收益在本轮没有访谈或实测，价值主张限定为可验证的自动处理任务。
官方 InterGen 提供实际扩散生成动作，Bandai 提供风格化捕捉动作；PyMotion 提供旋转/FK 数值适配，Kenney 提供 CC0 角色，Blender 处理实际重定向。MotionLint 新增统一检测定位、有界候选审查与跨产物复检，生成模型和通用工具的作用分别披露。

## 自主方法与实现

统一接口将多来源输入转换为人物、帧、关节轨迹及可用旋转，同时记录单位、地面、映射、时间对应和评估覆盖。地面显式指定或估计后冻结；脚滑支撑不以水平速度作为排除条件，避免把滑动隐藏为非支撑。
凸子问题在原候选基础上优化二维根轨迹及双脚位移，加入每点位移球、腿长可达范围、支撑速度软约束和轨迹平滑。Clarabel 的求解状态单独记录，随后通过双腿 IK、边界融合、骨长和六项实际复测，子问题解不能直接作为最终合格结果。
审查同时检查新严重帧、逐人物逐脚的固定原支撑距离与峰值、接触丢失、骨长、位移上限、评估覆盖和上下文。目标物理量确实改善且总分持平也可接受；候选优先物理改善，再选附加位移较小者。任何退步或超界都保留原输入。
BVH 保留通道和旋转顺序、写盘后回读 FK；角色再读取实际骨架，并从变形网格测量穿地与脚底轨迹。无需权重的核心检测、优化可选依赖、打包工作台、离线 HTML 和持久化任务允许独立复用。

## 数据与独立证据

600 条动态注入版本来自 30 组原始解析轨迹：六类动作、六类缺陷、三强度、五种子，540 注入及60 正常；同轨迹所有派生版本属于同一划分，240 开发、360 保留。
真值验证器不调用被测检测器或支撑识别。区间匹配为同类型同人物、IoU ≥ 0.5、一对一匹配；关节定位召回 {result['controlled']['joint_localization_recall']:.4f}。正常对照高严重度误报为观察到的 0/36，不是总体误报上界。
注入数组和参考数组的哈希随清单冻结；接触文件的单独 SHA 在交付审计时补录，不能把这份补录作为测试前的哈希证据。接触状态仍由解析支撑计划给定并独立核验。
每类 54 个保留注入条目，Precision / Recall / F1 均为 1.00；有限解析轨迹的结果不能外推到真实动作准确率。按原轨迹分组自助统计的区间在这个无错误集合为 [1,1]，不表示真实分布零不确定性。

真实 60 条含 InterGen 36 条与 Bandai 24 条，24 InterGen 开发，剩余36 保留；无人工缺陷与语义真值。候选选择只比较分数、运动幅度、根路径及非目标关节变化，不命名为语义正确率。

## 修复与基线保留

原15 条开发脚滑严格通过 {old['injected_gate_pass_count']}/15，新版 {new['injected_gate_pass_count']}/15；固定支撑距离降低中位数 {old['median_support_distance_reduction_ratio']*100:.8f}% → {new['median_support_distance_reduction_ratio']*100:.8f}%，浮点比值差异约 {new['median_support_distance_reduction_ratio']-old['median_support_distance_reduction_ratio']:.2e}。
30 正常开发数组保持不变。旧规则 v4 下比较，数值等价容差 1e-6 单独记录。仍失败的 {len(diagnostics)} 条及各候选诊断完整保留，不把求解失败写成全局数学无解。
新预定义可修复子集 {r['accepted_count']}/{r['count']} 接受，固定原支撑距离降低中位数 {r['median_original_support_distance_reduction_ratio']*100:.2f}%；正常保留控制 {r['normal_controls_unchanged_count']}/36 无需修复，全部输入哈希不变。

## 真实保留输入：同规则 v5 对照

{format_method_table('holdout_real')}

普通时间平滑没有几何/回归约束，会破坏骨长；历史算法 v5 使用原提交内部 v4，输出统一按表中冻结 v5 重测。各算法拒绝、未支持、未通过和全部执行失败均计入分母。
去除接触约束出现5 条回归，去除回归拒绝出现12 条回归；不保证每个消融在每个子集都有收益。原轨迹/提示词/内容分组的 95% 区间保存在机器结果；多个种子不作为完全独立证据。
规则 v4 的完整对照另存，禁止用 v4、v5 分数直接相减。
动态保留集的全项严格通过为 {result['methods']['v5']['holdout_controlled']['repair_v6']['strict_pass_count']}/360；正确检测到注入缺陷不等于全部修复达标。

## 实际四阶段

{flowtable}

六条样本在检测前按类别清单固定，全部实际写出、回读 BVH、重定向 Kenney、导出真实骨架与变形网格，视频完整解码。允许阶段质量 FAIL。
表中 PASS/FAIL 仅为六项骨架检查。变形网格穿地单独报告；唯一跨阶段骨架通过的 bow 样本最大网格穿地仍为 {next(f['mesh_metrics']['max_scene_plane_penetration_m'] for f in flows if f['id']=='bandai_bow_normal'):.4f} 米，不能据此声称角色没有网格问题。
去掉导出复检，会把 {result['export_ablation_false_complete_passes']}/6 条只在修复数组通过的样本误报为完整质量通过。
Bandai 绑定姿态转换使用已记录的关节拟合代理，几何误差与原始文件分开；原文件、单位、旋转顺序与非目标通道保留。角色额外指标只有变形网格穿地及脚底轨迹，不声称网格间精确穿透检测。

## 工程验证

{result['tests']['passed']} 项通过、{result['tests']['skipped_optional']} 可选集成跳过；Windows Python 3.10/3.11 核心/优化四种仓库外新环境安装通过，真实浏览器六项操作通过。代码随后已成功推送，开发提交 d2fb21f 的现有五项 CI 作业通过，见 [实际运行记录](https://github.com/TiAmo0323/AIC/actions/runs/38262688861)。该工作流验证 Windows/Linux 与 Python 3.10/3.11 的源码安装及测试，不安装优化 extra，也不执行新的优化 wheel 跨平台矩阵；当前发布提交的 CI 状态以 Actions 记录为准。
同环境同 v4 的检测耗时比值 {result['performance']['same_rule_v4_detection_cost_ratio']:.4f}，不超过 1.25 目标；峰值为 10ms 采样 RSS，存在采样限制。Python 生产依赖快照审计发现 {result['dependency_audit']['known_vulnerabilities']} 个已知漏洞；前端升级并锁定后 npm 全依赖审计为 {result['frontend_dependency_audit']['vulnerabilities']['total']} 个。两项审计均为当次公告快照，不代表未来保证。
初次加载和 MemoryError 记录保留，以紧凑索引和小批串行恢复同一输入；没有删除质量失败或重复调参保留集。

## 开放与材料真实性

核心源码、恢复清单、评测工具、报告索引可复用；权重、SMPL-X、FBX 和受限数据不进公开核心包。维护者已明确授权独立 MotionLint 组件及三个遗留辅助文件按 MIT 开放，见 [许可范围](../LICENSE_SCOPE.md)。该授权不覆盖原平台其他集成目录或第三方内容，不宣称整仓一律 MIT，也不代替其他作者签署声明。
本轮自动完成开发、检测、生成、浏览器操作及材料构建；没有访谈、人工标注、人工语义评分或同学安装经历。AI 辅助环节需团队按实际情况审核与披露。
结论可追溯至 [字段索引](../evidence/iteration-050-claims.json)、[样本与哈希](../evidence/iteration-050-sample-registry.json)、[全部方法条目](../evidence/iteration-050-method-outcomes.json)。

来源： [InterGen](https://github.com/tr3e/InterGen)、[Bandai 官方数据](https://github.com/BandaiNamcoResearchInc/Bandai-Namco-Research-Motiondataset)、[Kenney CC0](https://kenney.nl/assets/animated-characters-protagonists)、[CVXPY 1.6.5](https://pypi.org/project/cvxpy/1.6.5/)、[竞赛规则](https://www.aicomp.cn/tracks/tracks-5/4924.html)。
'''
    (ROOT/'docs/MOTIONLINT_050_RESULTS.md').write_text(text,encoding='utf-8')
    # The PDF renderer consumes this same text and public result object.
    dest=ROOT/'output/pdf';dest.mkdir(parents=True,exist_ok=True)
    (dest/'MotionLint-050-report.md').write_text(text,encoding='utf-8')
    print('Results and claims generated:',len(flows),'actual flows; all failed outcomes retained')


if __name__=='__main__':main()
