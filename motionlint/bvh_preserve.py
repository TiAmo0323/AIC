"""Write a BVH candidate while retaining the input hierarchy and channel order."""
from pathlib import Path
import numpy as np


def write_preserving_bvh(path, motion, actor=0):
    from pymotion.rotations import quat
    if motion.local_positions is None or motion.channel_values is None:
        raise ValueError('Preserving BVH export requires the original local positions and channels')
    metadata=motion.metadata
    labels=metadata.get('actor_bvh_channel_labels',[metadata['bvh_channel_labels']]*motion.actor_count)[actor]
    orders=metadata.get('actor_bvh_rotation_orders',[metadata['bvh_rotation_order']]*motion.actor_count)[actor]
    header=metadata.get('actor_bvh_headers',[metadata['bvh_hierarchy_text']]*motion.actor_count)[actor]
    values=motion.channel_values[:,actor].copy()
    scale=float(metadata['unit_scale_to_metres'])
    cursor=0
    for joint,channels in enumerate(labels):
        count=len(channels)
        old_angles=values[:,cursor+count-3:cursor+count]
        order=np.broadcast_to(np.asarray(orders[joint]),old_angles.shape)
        original=quat.to_matrix(quat.normalize(quat.from_euler(np.radians(old_angles),order=order)))
        changed=np.any(np.abs(original-motion.rotation_matrices[:,actor,joint])>1e-10,axis=(-2,-1))
        if changed.any():
            angles=np.degrees(quat.to_euler(quat.from_matrix(motion.rotation_matrices[:,actor,joint]),order=order))
            angles=np.degrees(np.unwrap(np.radians(angles),axis=0))
            values[changed,cursor+count-3:cursor+count]=angles[changed]
        if count==6:
            position=motion.root_translation[:,actor] if joint==0 else motion.local_positions[:,actor,joint]
            for offset,label in enumerate(channels[:3]):
                new=position[:, 'XYZ'.index(label[0])]/scale
                different=np.abs(new-values[:,cursor+offset])>1e-10
                values[different,cursor+offset]=new[different]
        cursor+=count
    output=Path(path);output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('w',encoding='utf-8') as f:
        f.write(header.rstrip()+'\nMOTION\n')
        f.write(f'Frames: {motion.frame_count}\nFrame Time: {metadata["frame_time"]:.15g}\n')
        for frame in values:
            f.write(' '.join(f'{v:.15g}' for v in frame)+'\n')
    return output
