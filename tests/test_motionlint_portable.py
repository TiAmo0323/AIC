"""Meaningful package, malformed-input, coverage and regression contracts."""
from pathlib import Path
import json
import numpy as np
import pytest
import yaml
from motionlint.benchmark.fixtures import standing, build
from motionlint.benchmark.evaluation import match_events
from motionlint.cli.main import main, load_motion
from motionlint.pipeline.inspector import inspect
from motionlint.pipeline.regression import compare
from motionlint.core.quality_gate import evaluate_gate
from motionlint.core.motion_sequence import MotionSequence
from motionlint.core.config import DEFAULT_CONFIG
from motionlint.pipeline.repair_pipeline import repair


def test_cli_real_exit_codes_and_hashes(tmp_path):
    path=tmp_path/"clean.npy"
    np.save(path,standing())
    assert main(["check",str(path),"--output-dir",str(tmp_path/"clean")])==0
    report=json.loads((tmp_path/"clean/motionlint_report.json").read_text(encoding="utf-8"))
    assert report["metadata"]["input_sha256"][str(path.resolve())]
    assert report["metadata"]["config_sha256"]
    damaged=standing();damaged[120:,:,0]+=.4
    np.save(tmp_path/"bad.npy",damaged)
    assert main(["check",str(tmp_path/"bad.npy"),"--output-dir",str(tmp_path/"bad")])==1
    damaged[0,0,0]=np.nan;np.save(tmp_path/"nan.npy",damaged)
    assert main(["check",str(tmp_path/"nan.npy")])==2
    assert main(["check",str(path),"--unit-scale","-1"] )==2
    assert main(["check",str(tmp_path/"missing.npy")])==2


def test_missing_joints_and_short_sequence_cannot_pass():
    motion=MotionSequence("test",30,1,1,positions=np.zeros((1,1,2,3)),joint_names=["Root","Tip"],metadata={"parents":[-1,0]})
    report=inspect(motion)
    assert report.metadata["evaluation_coverage"]["collision"]=="unavailable"
    assert report.metadata["evaluation_coverage"]["temporal_continuity"]=="unavailable"
    assert evaluate_gate(report).status=="FAIL"


def test_configuration_reaches_repair_and_batch(tmp_path):
    path=tmp_path/"clean.npy";np.save(path,standing())
    config=yaml.safe_load(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    config["version"]=44
    config["gate"]["overall_min_score"]=101
    policy=tmp_path/"quality.yaml";policy.write_text(yaml.safe_dump(config))
    outcome=repair(load_motion(path),config_path=policy)
    assert outcome.after.metadata["config_version"]==44
    manifest=tmp_path/"manifest.json";manifest.write_text(json.dumps([{"input":"clean.npy"}]))
    assert main(["batch",str(manifest),"--config",str(policy),"--output-dir",str(tmp_path/"batch")])==1


def test_cross_policy_comparison_rejected(tmp_path):
    path=tmp_path/"clean.npy";np.save(path,standing())
    first=inspect(load_motion(path));second=inspect(load_motion(path))
    second.metadata["config_sha256"]="different"
    with pytest.raises(ValueError,match="config_sha256"):
        compare(first,second)


def test_repair_preserves_input_and_records_all_trials(tmp_path):
    build(tmp_path)
    path=tmp_path/"foot_sliding_00.npy"
    original=path.read_bytes()
    result=repair(load_motion(path))
    assert path.read_bytes()==original
    assert all(step["status"] in {"no_op","unsupported","accepted","rejected","failed"} for step in result.steps)
    assert all("candidate_trials" in step for step in result.steps if step["status"] in {"accepted","rejected","failed"})


def test_one_prediction_cannot_match_two_distinct_events():
    truth=[{"test_name":"collision","actor_id":0,"start_frame":0,"end_frame":9},
           {"test_name":"collision","actor_id":0,"start_frame":11,"end_frame":20}]
    predicted=[{"test_name":"collision","actor_id":0,"start_frame":0,"end_frame":20}]
    counts=match_events(truth,predicted,threshold=.4)
    assert counts=={"tp":1,"fp":0,"fn":1}


def test_batch_cannot_hide_bad_inputs_or_overwrite_other_reports(tmp_path):
    clean=tmp_path/'clean.npy';np.save(clean,standing())
    for payload in ([], [{'name':'..','input':str(clean)}],
                    [{'name':'a/b','input':str(clean)},{'name':'a_b','input':str(clean)}],
                    [{'input':str(clean),'fps':0}]):
        manifest=tmp_path/'batch.json';manifest.write_text(json.dumps(payload))
        assert main(['batch',str(manifest),'--output-dir',str(tmp_path/'reports')])==2


def test_second_actor_nan_and_nonfinite_policy_are_input_errors(tmp_path):
    first=tmp_path/'a.npy';second=tmp_path/'b.npy'
    np.save(first,standing());bad=standing();bad[0,0,0]=np.inf;np.save(second,bad)
    assert main(['check',str(first),'--actor2',str(second)])==2
    config=yaml.safe_load(DEFAULT_CONFIG.read_text(encoding='utf-8'))
    config['gate']['overall_min_score']=float('nan')
    policy=tmp_path/'invalid.yaml';policy.write_text(yaml.safe_dump(config))
    assert main(['check',str(first),'--config',str(policy)])==2


def test_bvh_mapping_and_centimetres_are_explicit(tmp_path):
    from motionlint.adapters.bvh_adapter import load_bvh
    path=tmp_path/'custom.bvh'
    path.write_text('''HIERARCHY
ROOT Pelvis
{
 OFFSET 0 0 0
 CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation
 JOINT Toe
 {
  OFFSET 0 -100 0
  CHANNELS 3 Zrotation Xrotation Yrotation
  End Site
  {
   OFFSET 0 0 0
  }
 }
}
MOTION
Frames: 3
Frame Time: 0.0333333333
0 100 0 0 0 0 0 0 0
0 100 0 0 0 0 0 0 0
0 100 0 0 0 0 0 0 0
''')
    motion=load_bvh(path,unit_scale=.01,joint_mapping={'Pelvis':'Hips','Toe':'LeftToe'})
    assert motion.joint_names==['Hips','LeftToe']
    np.testing.assert_allclose(motion.positions[:,0,0,1],1)
    np.testing.assert_allclose(motion.positions[:,0,1,1],0)
    assert motion.metadata['foot_joint_ids']==[1]
    assert inspect(motion).metadata['evaluation_coverage']['collision']=='unavailable'
    with pytest.raises(ValueError,match='missing BVH names'):
        load_bvh(path,joint_mapping={'Absent':'Head'})
