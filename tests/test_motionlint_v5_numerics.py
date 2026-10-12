"""Numeric counterexamples justifying v5 changes without threshold relaxation."""
from dataclasses import replace
import json
import numpy as np
from motionlint.benchmark.fixtures import standing
from motionlint.adapters.intergen_adapter import load_intergen_joints
from motionlint.adapters.bvh_adapter import load_bvh
from motionlint.bvh_writer import write_bvh
from motionlint.bvh_preserve import write_preserving_bvh
from motionlint.core.config import load_config
from motionlint.pipeline.inspector import inspect
from motionlint.core.rotation_rates import increments_degrees


def test_rotation_reversal_is_not_zero_acceleration(tmp_path):
    np.save(tmp_path/'p.npy',standing(4));m=load_intergen_joints(tmp_path/'p.npy')
    angle=np.radians([0,20,0,20])
    r=np.zeros((4,1,22,3,3));r[:]=np.eye(3)
    c,s=np.cos(angle),np.sin(angle)
    r[:,0,20,0,0]=c;r[:,0,20,1,1]=c;r[:,0,20,0,1]=-s;r[:,0,20,1,0]=s
    m=replace(m,rotation_matrices=r)
    result=next(t for t in inspect(m).tests if t.test_name=='motion_jerk')
    assert result.metrics['max_angular_acceleration_deg_s2']>35000
    assert any(i.joint_ids==[20] for i in result.issues)
    np.testing.assert_allclose(increments_degrees(r)[:,0,20,2],[20,-20,20],atol=1e-8)


def test_nonroot_translation_survives_bvh_read_and_preserving_write(tmp_path):
    path=tmp_path/'input.bvh'
    # Position channels hold absolute local positions (the PyMotion contract).
    path.write_text('HIERARCHY\nROOT Hips\n{\nOFFSET 0 0 0\nCHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation\nJOINT Head\n{\nOFFSET 0 1 0\nCHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation\nEnd Site\n{\nOFFSET 0 0 0\n}\n}\n}\nMOTION\nFrames: 4\nFrame Time: 0.0333333333333333\n'+'\n'.join('0 0 0 0 0 0 '+f'0 {1+frame*.01} 0 0 0 0' for frame in range(4))+'\n')
    m=load_bvh(path)
    np.testing.assert_allclose(m.positions[:,0,1,1],[1,1.01,1.02,1.03])
    written=tmp_path/'output.bvh';write_preserving_bvh(written,m)
    restored=load_bvh(written)
    np.testing.assert_array_equal(restored.channel_values,m.channel_values)
    np.testing.assert_allclose(restored.positions,m.positions,atol=1e-10)


def test_v4_policy_preserves_numeric_thresholds():
    from motionlint.core.config import DEFAULT_CONFIG
    old=load_config(DEFAULT_CONFIG.with_name('quality_v4.yaml'));new=load_config()
    for name,settings in old['tests'].items():
        for key,value in settings.items():assert new['tests'][name][key]==value,(name,key)
