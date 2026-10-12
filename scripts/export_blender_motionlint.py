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
names = [item.get('CanonicalName', item["SourceBoneName"]) for item in mapping]
target_names = [item["DestinationBoneName"] for item in mapping]
targets = [bpy.data.objects[f"Retarget_Target_{index + 1}"] for index in range(len(manifest["source_bvh_files"]))]
scene = bpy.context.scene
frames = list(range(scene.frame_start, scene.frame_end + 1))
positions = np.zeros((len(frames), len(targets), len(names), 3))
rotations = np.zeros((len(frames), len(targets), len(names), 3, 3))
# Right-handed Blender Z-up -> analysis Y-up, in scene metres.
transform = np.array([[1., 0., 0.], [0., 0., 1.], [0., -1., 0.]])
unit_scale = float(scene.unit_settings.scale_length)
mesh_min_height = np.full((len(frames), len(targets)), np.nan)
mesh_penetration_fraction = np.full_like(mesh_min_height, np.nan)
sole_positions = np.full((len(frames), len(targets), 2, 3), np.nan)
mesh_records, sole_indices = [], {}
for actor, target in enumerate(targets):
    meshes = [obj for obj in scene.objects if obj.type == 'MESH' and
              any(mod.type == 'ARMATURE' and mod.object == target for mod in obj.modifiers)]
    mesh_records.append(meshes)
    for obj in meshes:
        group_ids = [{obj.vertex_groups[name].index for name in (prefix + 'Foot', prefix + 'Toes')
                      if name in obj.vertex_groups} for prefix in ('Left', 'Right')]
        for side, groups in enumerate(group_ids):
            ids = [vertex.index for vertex in obj.data.vertices
                   if sum(g.weight for g in vertex.groups if g.group in groups) >= .25]
            sole_indices[(actor, obj.name, side)] = ids
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
        all_vertices, side_vertices = [], [[], []]
        for obj in mesh_records[actor]:
            evaluated_mesh_obj = obj.evaluated_get(depsgraph)
            mesh = evaluated_mesh_obj.to_mesh()
            try:
                local = np.array([vertex.co[:] for vertex in mesh.vertices])
                matrix = np.asarray(evaluated_mesh_obj.matrix_world)
                points = (local @ matrix[:3, :3].T + matrix[:3, 3]) @ transform.T * unit_scale
                all_vertices.append(points)
                for side in range(2):
                    ids = sole_indices[(actor, obj.name, side)]
                    if not ids or max(ids) >= len(points):
                        continue
                    if time_index == 0:
                        # Freeze sole vertex IDs across all frames.
                        low = float(points[ids, 1].min())
                        ids = [i for i in ids if points[i, 1] <= low + .012]
                        sole_indices[(actor, obj.name, side)] = ids
                    side_vertices[side].append(points[ids])
            finally:
                evaluated_mesh_obj.to_mesh_clear()
        if all_vertices:
            combined = np.concatenate(all_vertices)
            mesh_min_height[time_index, actor] = combined[:, 1].min()
            mesh_penetration_fraction[time_index, actor] = np.mean(combined[:, 1] < 0.)
        for side, items in enumerate(side_vertices):
            if items:
                sole_positions[time_index, actor, side] = np.concatenate(items).mean(axis=0)
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
                    joint_names=np.array(names), parents=np.array(parents), mesh_min_height_m=mesh_min_height,
                    mesh_penetration_vertex_fraction=mesh_penetration_fraction, sole_positions=sole_positions)
info = {"geometry_source": "evaluated_blender_character_bone_heads", "blend_path": bpy.data.filepath,
        "blend_sha256": hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest(),
        "manifest_path": str(manifest_path), "video_path": manifest["output_mp4"],
        "frame_start": frames[0], "frame_end": frames[-1],
        "fps": scene.render.fps / scene.render.fps_base,
        "scene_unit_scale_to_metres": unit_scale, "target_names": [obj.name for obj in targets],
        "coordinate_transform": transform.tolist(),
        "input_stage": manifest.get("motionlint_input_stage", "raw_export"),
        "source_bvh_files": manifest["source_bvh_files"],
        "mesh_measurement": {'geometry_source': 'actual_evaluated_deformed_mesh_vertices', 'floor_height_m': 0.,
            'floor_basis': 'Blender scene Z=0 plane; metres after scene scale',
            'sole_vertex_ids': [{'actor_id': a, 'mesh': n, 'side': s, 'vertex_ids': ids}
                                for (a,n,s),ids in sole_indices.items()],
            'sole_basis': 'Foot/Toes skin weight >=0.25; first-frame lowest 12mm vertices frozen across animation'},
        "limits": "Measured skinned vertices against the scene plane; mesh-to-mesh triangle penetration is not checked."}
output.with_suffix(".json").write_text(json.dumps(info, indent=2), encoding="utf-8")
print("Exported", output, positions.shape)
