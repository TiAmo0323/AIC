"""Bake the evaluated reference, apply toe-aware leg IK, save a candidate scene."""
import argparse
import json
from pathlib import Path
import sys
import bpy
import numpy as np
from mathutils import Matrix, Vector

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

parser = argparse.ArgumentParser()
parser.add_argument("--plan", required=True)
parser.add_argument("--manifest", required=True)
parser.add_argument("--render", action="store_true")
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
scene = bpy.context.scene
start = int(plan["frame_start"])
end = start + int(plan["frames"]) - 1
transform = np.array([[1., 0., 0.], [0., 0., 1.], [0., -1., 0.]])
reference = np.array(plan["reference_positions"])
corrections = np.array(plan["corrections_xz_m"])
rotations = np.array(plan["foot_world_rotations"])
mapping = json.loads(Path(manifest["mapping_file"]).read_text(encoding="utf-8"))["bones"]
bone_names = [item["DestinationBoneName"] for item in mapping]
targets = [bpy.data.objects[name] for name in plan["target_names"]]

for target in targets:
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.mode_set(mode="POSE")
    bpy.ops.pose.select_all(action="SELECT")
    bpy.ops.nla.bake(frame_start=start, frame_end=end, step=1, only_selected=False,
                    visual_keying=True, clear_constraints=True, use_current_action=False, bake_types={"POSE"})
    bpy.ops.object.mode_set(mode="OBJECT")

# Reject a bake that changes the evaluated source before adding any repair.
maximum_bake_error = 0.
for offset, frame in enumerate(range(start, end + 1)):
    scene.frame_set(frame)
    for actor, target in enumerate(targets):
        for joint, name in enumerate(bone_names):
            position = transform @ np.asarray(target.matrix_world @ target.pose.bones[name].head)
            maximum_bake_error = max(maximum_bake_error, float(np.linalg.norm(position - reference[offset, actor, joint])))
if maximum_bake_error > 1e-4:
    raise RuntimeError(f"Visual bake changed geometry by {maximum_bake_error} m")

for actor, target in enumerate(targets):
    for side, chain in enumerate(plan["chains"]):
        lower_leg = target.pose.bones[bone_names[chain[1]]]
        foot = target.pose.bones[bone_names[chain[2]]]
        bpy.ops.object.empty_add(type="PLAIN_AXES")
        goal = bpy.context.object
        goal.name = f"MotionLint_{actor}_{side}_FootGoal"
        goal.hide_render = True
        goal.rotation_mode = "QUATERNION"
        ik = lower_leg.constraints.new("IK")
        ik.name = "MotionLintSupportIK"
        ik.target = goal
        ik.chain_count = 2
        ik.use_tail = True
        ik.use_stretch = False
        lower_leg.ik_stretch = 0
        lower_leg.parent.ik_stretch = 0
        orientation = foot.constraints.new("COPY_ROTATION")
        orientation.name = "MotionLintPreserveFootWorldRotation"
        orientation.target = goal
        orientation.owner_space = "WORLD"
        orientation.target_space = "WORLD"
        for offset, frame in enumerate(range(start, end + 1)):
            scene.frame_set(frame)
            point = reference[offset, actor, chain[2]].copy()
            point[[0, 2]] += corrections[offset, actor, side]
            goal.location = Vector(transform.T @ point)
            goal.rotation_quaternion = Matrix(transform.T @ rotations[offset, actor, side] @ transform).to_quaternion()
            goal.keyframe_insert(data_path="location", frame=frame)
            goal.keyframe_insert(data_path="rotation_quaternion", frame=frame)
            ik.influence = float(plan["active"][offset][actor][side])
            ik.keyframe_insert(data_path="influence", frame=frame)
        for obj in (target, goal):
            if obj.animation_data and obj.animation_data.action:
                for curve in obj.animation_data.action.fcurves:
                    for point in curve.keyframe_points:
                        point.interpolation = "LINEAR"

report = {"visual_bake_max_position_error_m": maximum_bake_error,
          "maximum_requested_correction_m": float(np.linalg.norm(corrections, axis=-1).max()),
          "support_metrics": plan["support_metrics"], "method": "bounded toe-aware support IK with observed foot-world rotation"}
scene.frame_start, scene.frame_end = start, end
scene.frame_set(start)
if args.render:
    from LODGE_api.blender_rokoko_retarget import render_output
    report["render_settings"] = {}
    render_output(Path(manifest["output_mp4"]), fps=int(plan["fps"]), frame_end=end, report=report)
bpy.ops.wm.save_as_mainfile(filepath=manifest["debug_blend"])
Path(manifest["debug_blend"]).with_suffix(".foot_repair.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
