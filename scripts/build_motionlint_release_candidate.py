"""Allowlisted local candidate and evidence bundles; never publish or relicense."""
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/packages'
STAGING=OUT/'source_candidate_0.4.0'
DOCS=['MOTIONLINT_QUICKSTART.md','MOTIONLINT_MIGRATION_V4.md','MOTIONLINT_COMPARATORS.md',
      'MOTIONLINT_HUMAN_VALIDATION.md','MOTIONLINT_RELEASE_REVIEW.md','MOTIONLINT_MAINTENANCE.md',
      'MOTIONLINT_CI.md','MOTIONLINT_IMPLEMENTATION_STATUS.md','MOTIONLINT_REPORT_V4.md',
      'MOTIONLINT_DEMO_V4.md','MOTIONLINT_CLASSMATE_HANDOFF.md']


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True,exist_ok=True);STAGING.mkdir(exist_ok=True)
    files=list((ROOT/'motionlint').rglob('*.py'))+list((ROOT/'motionlint/configs').glob('*.yaml'))
    files+=[ROOT/'pyproject.toml',ROOT/'LICENSE_REVIEW_PENDING.md',ROOT/'.github/workflows/motionlint.yml',
            ROOT/'tests/test_motionlint_portable.py',ROOT/'experiments/human_validation_templates.json',
            ROOT/'tools/annotation/index.html']
    files += [ROOT/'docs'/name for name in DOCS]
    scripts=['audit_motionlint_study_stages.py','build_motionlint_annotation_pack.py',
        'build_motionlint_release_candidate.py','build_motionlint_report.py',
        'check_motionlint_ci_regression.py','evaluate_motionlint_annotations.py',
        'export_blender_motionlint.py','freeze_motionlint_baseline.py',
        'generate_motionlint_study.py','prepare_motionlint_adjudication.py',
        'prepare_motionlint_study.py','prepare_motionlint_ui_demo.py',
        'run_motionlint_benchmark.py','run_motionlint_comparisons.py',
        'summarize_motionlint_experiments.py','verify_motionlint_controlled_truth.py',
        'verify_motionlint_engineering.py','verify_motionlint_study_videos.py',
        'verify_motionlint_wheel.py','patch_lodge_checkpoint_loading.py',
        'patch_lodge_song_parsing.py','finalize_motionlint_ui_evidence.py',
        'run_motionlint_installation.py','audit_motionlint_delivery.py',
        'build_motionlint_narrated_demo.py']
    files += [ROOT/'scripts'/name for name in scripts]
    # Integration scripts retain their original runtime/evidence requirements;
    # only the core CLI and self-authored fixtures are the standalone contract.
    package_manifest=[]
    for path in sorted(set(files)):
        if not path.is_file():raise ValueError(f'Missing candidate file: {path}')
        name=path.relative_to(ROOT).as_posix()
        target=STAGING/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,target)
        package_manifest.append({'path':name,'sha256':sha(path)})
    readme=STAGING/'README.md'
    readme.write_text('# MotionLint 0.4.0 - local review candidate\n\nStart with docs/MOTIONLINT_QUICKSTART.md. Core CPU check/repair/compare/batch and procedural examples run without models or platform services. Platform generation, rendering and study scripts require the original workspace and separately obtained resources.\n\nThis candidate has NOT been published. Licensing review remains pending: read LICENSE_REVIEW_PENDING.md and docs/MOTIONLINT_RELEASE_REVIEW.md. No weights, model files, characters, music or real generated study inputs are bundled.\n',encoding='utf-8')
    package_manifest.append({'path':'README.md','sha256':sha(readme)})
    source_manifest={'status':'local_review_candidate_not_published','version':'0.4.0',
        'license_status':'review_pending','files':package_manifest,'excluded':['weights','SMPL-X','FBX','music','real motion datasets','credentials','task videos']}
    (STAGING/'MANIFEST.json').write_text(json.dumps(source_manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    source_zip=OUT/'motionlint-0.4.0-source-candidate.zip'
    with zipfile.ZipFile(source_zip,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for row in package_manifest:archive.write(STAGING/row['path'],row['path'])
        archive.write(STAGING/'MANIFEST.json','MANIFEST.json')
    evidence_candidates=[ROOT/'reports/first_prize/controlled/summary.json',
        ROOT/'reports/first_prize/controlled/inputs/manifest.json',ROOT/'reports/first_prize/controlled/inputs/truth_verification.json',
        ROOT/'reports/first_prize/study/protocol.json',ROOT/'reports/first_prize/study/generation.json',
        ROOT/'reports/first_prize/study/music/manifest.json',ROOT/'reports/first_prize/study/video_verification.json',
        ROOT/'reports/first_prize/study/comparisons/development/aggregate.json',
        ROOT/'reports/first_prize/study/comparisons/development/summary.json',
        ROOT/'reports/first_prize/portable/verification.json',ROOT/'reports/first_prize/engineering_verification.json',
        ROOT/'reports/first_prize/portable311/verification.json',
        ROOT/'reports/first_prize/browser/verification.json',ROOT/'reports/first_prize/report_validation.json',
        ROOT/'reports/first_prize/browser/video_verification.json',
        ROOT/'reports/first_prize/browser/demo_provenance.json',
        ROOT/'reports/first_prize/cli_demo/installation.json',
        ROOT/'reports/first_prize/browser/narrated_video_verification.json']
    evidence_candidates+=list((ROOT/'reports/first_prize/lodge_loading').glob('*.json'))
    evidence_candidates+=list((ROOT/'reports/first_prize/lodge_loading').glob('*.patch'))
    def sanitize(text):
        for variant,replacement in [(str(ROOT),'[repo]'),(str(ROOT.parent/'HumanAction-runtime'),'[runtime]'),
            ('C:\\Users\\zzz','[user-home]')]:
            for source in (variant,variant.replace('\\','/'),variant.replace('\\','\\\\')):
                text=text.replace(source,replacement)
        return text
    evidence_manifest=[]
    evidence_zip=OUT/'motionlint-0.4.0-evidence-candidate.zip'
    with zipfile.ZipFile(evidence_zip,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for path in evidence_candidates:
            if not path.is_file():continue
            name=path.relative_to(ROOT).as_posix()
            sanitized=sanitize(path.read_text(encoding='utf-8')).encode('utf-8')
            archive.writestr(name,sanitized)
            evidence_manifest.append({'path':name,'source_sha256':sha(path),'packaged_sha256':hashlib.sha256(sanitized).hexdigest()})
        archive.writestr('EVIDENCE_MANIFEST.json',json.dumps({'status':'local_review_only','redaction':'Machine paths redacted; source and packaged hashes retained','human_evaluation':'pending','files':evidence_manifest},ensure_ascii=False,indent=2))
    wheel=OUT/'motionlint-0.4.0-py3-none-any.whl'
    classmate_zip=OUT/'motionlint-classmate-install.zip'
    if not wheel.is_file():raise ValueError('Build the core wheel before the installation handoff')
    with zipfile.ZipFile(classmate_zip,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        members=[(wheel,wheel.name),(ROOT/'scripts/run_motionlint_installation.py','run_motionlint_installation.py'),
            (ROOT/'docs/MOTIONLINT_CLASSMATE_HANDOFF.md','README.md'),
            (ROOT/'experiments/human_validation_templates.json','human_validation_templates.json'),
            (ROOT/'LICENSE_REVIEW_PENDING.md','LICENSE_REVIEW_PENDING.md')]
        for path,name in members:archive.write(path,name)
        archive.writestr('SHA256SUMS.txt',''.join(f'{sha(path)}  {name}\n' for path,name in members))
    outputs=[source_zip,evidence_zip,wheel,classmate_zip]
    (OUT/'SHA256SUMS.txt').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in outputs),encoding='ascii')
    snapshot={'status':'engineering_snapshot_not_blind_evaluation_freeze','version':'0.4.0',
        'source_files':package_manifest,'artifacts':[{'name':p.name,'sha256':sha(p),'bytes':p.stat().st_size} for p in outputs],
        'blind_evaluation':'not_run; await independent development annotation and final rule freeze'}
    snapshot_path=ROOT/'reports/first_prize/engineering_snapshot_v4.json'
    snapshot_path.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'candidate_source_files':len(package_manifest),'evidence_files':len(evidence_manifest),'artifacts':snapshot['artifacts']},indent=2))


if __name__=='__main__':main()
