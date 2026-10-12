"""Build review source, wheel and redacted evidence archives with full checksums.

Original local reports remain immutable. Redacted copies carry both the source
SHA256 and copied-file SHA256; restricted motion arrays and weights are excluded.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from zipfile import ZipFile,ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from motionlint.artifacts import sha256
from motionlint.benchmark.fixtures import build
from motionlint_050_privacy import sanitize, PRIVATE_PATH, CREDENTIAL


def redact(value):
    return sanitize(value)


def encode(value):return (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8')


def write_archive(path,entries,scope,*,redaction_index=False):
    index=[]
    with ZipFile(path,'w',ZIP_DEFLATED,compresslevel=6) as archive:
        for name,source in entries:
            if name.startswith('/') or '..' in Path(name).parts:raise ValueError('Unsafe archive path')
            if isinstance(source,tuple):
                file,kind=source;assert kind=='redacted_json'
                source_hash=sha256(file)
                data=encode(redact(json.loads(file.read_text(encoding='utf-8'))))
            elif isinstance(source,bytes):data=source;source_hash=None
            else:data=source.read_bytes();source_hash=sha256(source)
            digest=hashlib.sha256(data).hexdigest()
            archive.writestr(name,data)
            index.append({'path':name,'sha256':digest,'bytes':len(data),'source_sha256':source_hash})
        if redaction_index:
            archive.writestr('REDACTION_INDEX.json',encode({'schema_version':3,'originals_preserved':True,
                'files':[{'path':r['path'],'original_local_sha256':r['source_sha256'],'redacted_sha256':r['sha256']} for r in index if r['source_sha256']]}))
        archive.writestr('CONTENT_MANIFEST.json',encode({'schema_version':3,'scope':scope,'files':index}))
    with ZipFile(path) as archive:
        assert archive.testzip() is None
        for entry in index:assert hashlib.sha256(archive.read(entry['path'])).hexdigest()==entry['sha256']
    return {'file':path.name,'sha256':sha256(path),'bytes':path.stat().st_size,'entries':len(index)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'output/release/MotionLint-0.5.0-candidate')
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    base=ROOT/'reports/iteration_050'
    result=json.loads((ROOT/'evidence/iteration-050-results.json').read_text(encoding='utf-8'))
    audit=json.loads((ROOT/'evidence/iteration-050-release-audit.json').read_text(encoding='utf-8'))
    video=json.loads((ROOT/'evidence/iteration-050-video-validation.json').read_text(encoding='utf-8'))
    assert audit['protected_sample_count']==audit['unchanged_sample_count']==720
    wheel=next((base/'dist').glob('motionlint-0.5.0-*.whl'))
    matrix=json.loads((base/'local-wheel-matrix.json').read_text(encoding='utf-8'))
    assert len(matrix['rows'])==4 and all(row['status']=='PASS' and row['wheel_sha256']==sha256(wheel) for row in matrix['rows'])
    assert result['browser']['status']=='PASS' and video['status']=='PASS'
    assert result['frontend_dependency_audit']['vulnerabilities']['total']==0
    with ZipFile(wheel) as archive:
        names=archive.namelist()
        forbidden=[name for name in names if Path(name).suffix.lower() in {'.npy','.npz','.fbx','.blend','.ckpt','.pth','.pt'}]
        assert not forbidden
        assert any(name.endswith('/licenses/THIRD_PARTY_LICENSES.txt') for name in names)
    examples=out/'examples';build(examples)
    example_entries=[]
    for name in ('clean_00.npy','foot_sliding_00.npy'):
        example_entries.append(('examples/'+name,examples/name))
    (out/'START_HERE.md').write_text('''# MotionLint 0.5.0 审阅候选

本目录包含独立安装包、源码候选、全部结果索引、脱敏候选记录、真实操作视频及报告。整体许可仍待团队确认；不是已发布到 PyPI 或已签署权属声明的正式版本。

安装：`python -m pip install "motionlint-0.5.0-py3-none-any.whl[competition]"`

执行：`motionlint check examples/clean_00.npy --output-dir clean-report`；`motionlint repair examples/foot_sliding_00.npy --output-dir repaired`；`motionlint compare examples/clean_00.npy examples/foot_sliding_00.npy --output-dir regression`；`motionlint serve --data-dir ./tasks`。

核心示例无需模型、GPU、SMPL-X 或 Blender。首次 pip 安装仍需获取依赖；离线环境须先根据 locks 下载对应平台的依赖 wheel。生成、Blender/Rokoko 与 Kenney 通过恢复清单和现有仓库资源显式配置，不包含这些运行时文件。

720 条输入哈希保持不变，24 条 BVH 回读验证通过。可控保留集 F1 不代表真实检测准确率。36 条真实保留输入中新修复严格通过22条；六条完整流程都有实际产物，仅1条跨阶段骨架通过，网格指标另列。全部失败保留。

Windows Python 3.10/3.11 的核心/优化四种安装已验证。GitHub 当前授权缺少 workflow 权限，远程 Windows/Linux 矩阵尚未验证，不能把候选视作已完成远程交付验收。视频录制使用本轮已验证产物，属于自动操作，无人工访谈或外部用户安装经历。

证据包的 JSON/CSV 副本已脱敏；CONTENT_MANIFEST.json 记录副本哈希，REDACTION_INDEX.json 记录本机原始报告哈希。原报告、失败日志和受限原始输入继续保存在本机，未被覆盖。模型权重、人体模型、FBX 和原始受限动作不进入公开候选。
''',encoding='utf-8')
    tracked=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT).decode('utf-8').split('\0')
    root_files={'README.md','pyproject.toml','LICENSE_REVIEW_PENDING.md','THIRD_PARTY_NOTICES.md','THIRD_PARTY_LICENSES.txt',
                'LODGE_api/blender_rokoko_retarget.py','.github/workflows/motionlint.yml'}
    directories=('motionlint/','tests/','resources/','locks/','project/src/','project/scripts/')
    docs={'docs/MOTIONLINT_QUICKSTART.md','docs/MOTIONLINT_MIGRATION_V5.md','docs/MOTIONLINT_050_ITERATION.md',
          'docs/MOTIONLINT_050_RESULTS.md','docs/MOTIONLINT_RELEASE_REVIEW.md'}
    scripts={name for name in tracked if name.startswith('scripts/') and
             ('050' in name or Path(name).name in {'package_workbench.py','collect_frontend_licenses.py',
                'setup_intergen_resources.py','generate_intergen_engineering.py','build_real_input_manifest.py',
                'freeze_motionlint_baseline.py','run_historical_repair.py','measure_motionlint_performance.py',
                'verify_motionlint_installed.py','verify_wheel_local.py','ci_wheel_matrix.py','wait_motionlint_server.py',
                'verify_motionlint_browser.py','browser_verify_motionlint.js','export_blender_motionlint.py',
                'check_motionlint_ci_regression.py','synthesize_motionlint_narration.ps1'})}
    source=[]
    for name in sorted(set(tracked)):
        if not name:continue
        file=ROOT/name
        if not file.is_file():continue
        if name in root_files or name in docs or name in scripts or name.startswith(directories) or name in {'project/package.json','project/package-lock.json','project/index.html','project/vite.config.js'}:
            if file.suffix.lower() in {'.npy','.npz','.bvh','.fbx','.blend','.ckpt','.pth','.pt','.env'}:raise ValueError('Restricted source artifact: '+name)
            source.append((name,file))
    source+=example_entries+[('START_HERE.md',out/'START_HERE.md')]
    artifacts=[write_archive(out/'MotionLint-0.5.0-source-candidate.zip',source,'Review source; inherited helper rights pending; no project-wide MIT claim')]
    evidence=[(p.relative_to(ROOT).as_posix(),p) for p in sorted((ROOT/'evidence').glob('iteration-050*.json'))]
    redaction_count=0
    # Include every full candidate audit for controlled and real-input methods,
    # including rejected candidates. Restricted source arrays are excluded.
    report_roots=['holdout-v5','engineering-development','engineering-holdout','v6_v4_foot-final',
                  'complete-flows-v3','method-experiments/v4','method-experiments/v5','safety-results-3']
    allowed_names={'repair.json','repair_report.json','motionlint_report.json','quality_gate.json','comparison.json',
                   'manifest.json','result.json','mesh_metrics.json','render_transform.json','summary.json'}
    for sub in report_roots:
        for path in sorted((base/sub).rglob('*.json')):
            if path.name not in allowed_names or 'attempt' in path.name:continue
            name='reports/'+path.relative_to(base).as_posix()
            evidence.append((name,(path,'redacted_json')))
            redaction_count+=1
    for sub in report_roots:
        for path in sorted((base/sub).rglob('metrics.csv')):
            content=path.read_text(encoding='utf-8')
            if PRIVATE_PATH.search(content):raise ValueError('Unexpected private path in metrics CSV')
            evidence.append(('reports/'+path.relative_to(base).as_posix(),path))
    for name in ('local-wheel-matrix.json','performance/summary.json','frontend-dependency-audit-final.json','dependency-audit.json'):
        evidence.append(('validation/'+name,(base/name,'redacted_json')))
    artifacts.append(write_archive(out/'MotionLint-0.5.0-evidence.zip',evidence,'Automated evidence; no human or semantic truth; restricted arrays excluded',redaction_index=True))
    for path in (wheel,ROOT/'output/pdf/MotionLint-050-report.pdf',ROOT/'output/video/MotionLint-050-demo.mp4'):
        dest=out/path.name;shutil.copyfile(path,dest)
        artifacts.append({'file':dest.name,'sha256':sha256(dest),'bytes':dest.stat().st_size})
    files_manifest={'schema_version':3,'status':'LOCAL_REVIEW_CANDIDATE','remote_ci':'NOT_VERIFIED: credential permission required',
        'license':'Team and inherited-code review pending; full third-party notices preserved',
        'source_git_head_at_build':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'source_worktree_receipt':'Source archive CONTENT_MANIFEST records every candidate file; Git commit binding follows final commit.',
        'artifacts':artifacts,'formal_pdf_bytes':(out/'MotionLint-050-report.pdf').stat().st_size,
        'video_duration_seconds':video['duration_seconds'],'input_and_bvh_audit_sha256':sha256(ROOT/'evidence/iteration-050-release-audit.json')}
    (out/'RELEASE_MANIFEST.json').write_bytes(encode(files_manifest))
    for path in sorted(out.rglob('*')):
        if path.is_file() and path.name!='SHA256SUMS.txt':
            content=path.read_bytes()
            if path.suffix in {'.md','.json','.txt'} and CREDENTIAL.search(content):raise ValueError('Credential-like string in delivery')
    (out/'SHA256SUMS.txt').write_text(''.join(sha256(p)+'  '+p.relative_to(out).as_posix()+'\n' for p in sorted(out.rglob('*')) if p.is_file()),encoding='utf-8')
    print('Delivery archives verified:',len(source),'source files;',redaction_count,'redacted full reports;',out)


if __name__=='__main__':main()
