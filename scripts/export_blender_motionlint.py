"""Read evaluated character bones from an existing .blend without saving it."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import bpy
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument("--manifest", required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
manifest_path = Path(args.manifest)
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
mapping = json.loads(Path(manifest["mapping_file"]).read_text(encoding="utf-8"))["bones"]
names = [item["SourceBoneName"] for item in mapping]
target_names = [item["DestinationBoneName"] for item in mapping]
targets = [bpy.data.objects[f"Retarget_Target_{index + 1}"] for index in range(len(manifest["source_bvh_files"]))]
scene = bpy.context.scene
frames = list(range(scene.frame_start, scene.frame_end + 1))
positions = np.zeros((len(frames), len(targets), len(names), 3))
rotations = np.zeros((len(frames), len(targets), len(names), 3, 3))
# Right-handed Blender Z-up -> analysis Y-up, in scene metres.
transform = np.array([[1., 0., 0.], [0., 0., 1.], [0., -1., 0.]])
unit_scale = float(scene.unit_settings.scale_length)
for time_index, frame in enumerate(frames):
    scene.frame_set(frame)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for actor, target in enumerate(targets):
        evaluated = target.evaluated_get(depsgraph)
        for joint, bone_name in enumerate(target_names):
            bone = evaluated.pose.bones[bone_name]
            world = evaluated.matrix_world @ bone.matrix
            positions[time_index, actor, joint] = transform @ np.asarray(world.translation) * unit_scale
            rotation = np.asarray(world.to_quaternion().to_matrix())
            rotations[time_index, actor, joint] = transform @ rotation @ transform.T
parents = []
for bone_name in target_names:
    bone = targets[0].data.bones[bone_name]
    parent = bone.parent
    while parent is not None and parent.name not in target_names:
        parent = parent.parent
    parents.append(target_names.index(parent.name) if parent else -1)
output = Path(args.output)
output.parent.mkdir(parents=True, exist_ok=True)
np.savez_compressed(output, positions=positions, world_rotation_matrices=rotations,
                    joint_names=np.array(names), parents=np.array(parents))
info = {"geometry_source": "evaluated_blender_character_bone_heads", "blend_path": bpy.data.filepath,
        "blend_sha256": hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest(),
        "manifest_path": str(manifest_path), "video_path": manifest["output_mp4"],
        "frame_start": frames[0], "frame_end": frames[-1],
        "fps": scene.render.fps / scene.render.fps_base,
        "scene_unit_scale_to_metres": unit_scale, "target_names": [obj.name for obj in targets],
        "coordinate_transform": transform.tolist(),
        "input_stage": manifest.get("motionlint_input_stage", "raw_export"),
        "source_bvh_files": manifest["source_bvh_files"],
        "limits": "Evaluated bone-head geometry; skinned mesh triangle collision is not checked."}
output.with_suffix(".json").write_text(json.dumps(info, indent=2), encoding="utf-8")
print("Exported", output, positions.shape)
