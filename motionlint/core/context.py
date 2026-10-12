"""Freeze numerical context separately from content and processing stage."""
from dataclasses import replace
import hashlib
import json
import numpy as np
from motionlint.core.floor import floor_heights
from motionlint.core.provenance import rule_hash


def freeze_floor(motion, config):
    feet=motion.metadata.get('foot_joint_ids',[])
    if not feet or motion.positions is None or motion.metadata.get('floor_height_m') is not None:
        return motion
    up=int(motion.metadata.get('up_axis',1))
    floor,source=floor_heights(motion,motion.positions[:,:,feet,up],config['tests']['ground_contact'])
    return replace(motion,metadata={**motion.metadata,'floor_height_m':floor.tolist(),'floor_origin':source})


def freeze_pair(original,candidate,config):
    old=freeze_floor(original,config)
    if candidate.metadata.get('floor_height_m') is None and old.metadata.get('floor_height_m') is not None:
        candidate=replace(candidate,metadata={**candidate.metadata,'floor_height_m':old.metadata['floor_height_m'],
                                              'floor_origin':'frozen_baseline_floor'})
    return old,candidate


def evaluation_context(motion,config):
    frozen=freeze_floor(motion,config)
    context={'rules_sha256':rule_hash(config),'fps':motion.fps,'frame_count':motion.frame_count,'actor_count':motion.actor_count,
             'joint_names':motion.joint_names,'parents':motion.metadata.get('parents'),'foot_joint_ids':motion.metadata.get('foot_joint_ids'),
             'up_axis':motion.metadata.get('up_axis',1),'normalized_unit':'metres','floor_height_m':np.broadcast_to(frozen.metadata['floor_height_m'],(motion.actor_count,)).astype(float).tolist() if frozen.metadata.get('floor_height_m') is not None else None,
             'stored_unit_scale_to_metres':motion.metadata.get('unit_scale_to_metres',1.),
             'joint_mapping':motion.metadata.get('joint_mapping',{}),
             'non_anatomical_bone_ids':motion.metadata.get('non_anatomical_bone_ids',[]),
             'geometry_source':motion.metadata.get('geometry_source','native_joint_positions' if motion.source=='intergen' else 'bvh_fk'),
             'allowed_contacts':motion.metadata.get('allowed_contacts',[]) if config['tests']['collision'].get('explicit_contact_intervals') else [],
             'time_origin_seconds':motion.metadata.get('time_origin_seconds',0.)}
    serialized=json.dumps(context,sort_keys=True,separators=(',',':'),allow_nan=False)
    return context,hashlib.sha256(serialized.encode()).hexdigest()
