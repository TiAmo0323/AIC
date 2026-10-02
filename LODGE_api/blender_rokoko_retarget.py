# 该脚本由 Blender 的 Python 解释器执行，不应直接用普通 Python 启动。
# 它读取任务 manifest，导入 BVH/FBX，配置 Rokoko 骨骼映射，执行重定向、
# 相机灯光、旋转平滑、脚步锁定和可选碰撞修正，最后渲染 MP4 并写报告。
import argparse
import json
import math
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector


ADDON_CANDIDATES = [
    "io_anim_bvh",
    "io_scene_fbx",
    "rokoko-studio-live-blender-1-4-2",
    "rokoko_studio_live_blender",
    "rokoko",
    "rsl",
]


def parse_args():
    parser = argparse.ArgumentParser(description="Run Blender/Rokoko retarget from a manifest file.")
    parser.add_argument("--manifest", required=True)
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    return parser.parse_args(argv)


def load_manifest(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def enable_addons(report: dict) -> None:
    for addon in ADDON_CANDIDATES:
        try:
            bpy.ops.preferences.addon_enable(module=addon)
        except Exception as exc:
            report.setdefault("addon_errors", []).append(f"{addon}: {exc}")
    report["enabled_addons"] = sorted(bpy.context.preferences.addons.keys())


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def import_fbx(path: Path) -> list:
    before = set(bpy.data.objects.keys())
    bpy.ops.import_scene.fbx(filepath=str(path))
    imported = [obj for obj in bpy.data.objects if obj.name not in before]
    kenney_skin = path.parent.parent / "Skins" / "skaterMaleA.png"
    for obj in imported:
        if obj.type != "MESH":
            continue
        for slot in obj.material_slots:
            material = slot.material
            if material is None:
                continue
            material.use_nodes = True
            material.blend_method = "OPAQUE"
            material.diffuse_color[3] = 1.0
            principled = next((node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"), None)
            if principled is None:
                continue
            # Some FBX files import with an unlinked alpha value of zero, making
            # a correctly retargeted character entirely invisible in the render.
            if not principled.inputs["Alpha"].is_linked:
                principled.inputs["Alpha"].default_value = 1.0
            if path.name == "characterMedium.fbx" and kenney_skin.is_file():
                texture = material.node_tree.nodes.new("ShaderNodeTexImage")
                texture.image = bpy.data.images.load(str(kenney_skin), check_existing=True)
                material.node_tree.links.new(texture.outputs["Color"], principled.inputs["Base Color"])
    return imported


def import_bvh(path: Path, fps: int) -> list:
    before = set(bpy.data.objects.keys())
    bpy.ops.import_anim.bvh(filepath=str(path), frame_start=1, global_scale=1.0, update_scene_fps=True)
    bpy.context.scene.render.fps = fps
    return [obj for obj in bpy.data.objects if obj.name not in before]


def find_armatures(objects=None) -> list:
    pool = objects if objects is not None else bpy.data.objects
    return [obj for obj in pool if obj.type == "ARMATURE"]


def clean_mapping(mapping_path: Path, report: dict) -> dict:
    """清洗骨骼映射并过滤空值，避免无效映射进入 Rokoko 操作器。"""
    if not mapping_path.exists():
        return {}
    data = json.loads(mapping_path.read_text(encoding="utf-8"))
    bones = data.get("bones", [])
    seen_targets = set()
    cleaned = []
    removed = []
    for bone in bones:
        target = bone.get("DestinationBoneName") or bone.get("destination") or bone.get("target")
        source = bone.get("SourceBoneName") or bone.get("source")
        if not source or not target:
            removed.append({"reason": "missing source or target", "bone": bone})
            continue
        if target in seen_targets:
            removed.append({"reason": "duplicate target", "target": target, "source": source})
            continue
        seen_targets.add(target)
        cleaned.append(bone)
    data["bones"] = cleaned
    report["mapping_bone_count"] = len(cleaned)
    report["mapping_removed"] = removed
    return data


def set_possible_scene_attr(scene, names, value, report):
    for name in names:
        if hasattr(scene, name):
            try:
                setattr(scene, name, value)
                report.setdefault("scene_attrs_set", []).append(name)
                return True
            except Exception as exc:
                report.setdefault("scene_attr_errors", []).append(f"{name}: {exc}")
    return False


def configure_rokoko_scene(source, target, report: dict) -> None:
    scene = bpy.context.scene
    set_possible_scene_attr(
        scene,
        [
            "rsl_retargeting_armature_source",
            "rsl_retarget_armature_source",
            "rsl_source_armature",
            "source_armature",
        ],
        source,
        report,
    )
    set_possible_scene_attr(
        scene,
        [
            "rsl_retargeting_armature_target",
            "rsl_retarget_armature_target",
            "rsl_target_armature",
            "target_armature",
        ],
        target,
        report,
    )

    bpy.ops.object.select_all(action="DESELECT")
    source.select_set(True)
    target.select_set(True)
    bpy.context.view_layer.objects.active = target


def apply_mapping_to_rokoko_bone_list(mapping_data: dict, source, target, report: dict) -> int:
    bone_list = getattr(bpy.context.scene, "rsl_retargeting_bone_list", None)
    if bone_list is None:
        report["mapping_applied"] = False
        report["mapping_message"] = "Rokoko bone list property not found"
        return 0

    bone_list.clear()
    applied = 0
    skipped = []
    for bone in mapping_data.get("bones", []):
        source_name = bone.get("SourceBoneName") or bone.get("source")
        target_name = bone.get("DestinationBoneName") or bone.get("target")
        if not source_name or not target_name:
            skipped.append({"source": source_name, "target": target_name, "reason": "missing name"})
            continue
        if source.pose.bones.get(source_name) is None:
            skipped.append({"source": source_name, "target": target_name, "reason": "source bone not found"})
            continue
        if target.pose.bones.get(target_name) is None:
            skipped.append({"source": source_name, "target": target_name, "reason": "target bone not found"})
            continue
        item = bone_list.add()
        item.bone_name_key = bone.get("name") or source_name
        item.bone_name_source = source_name
        item.bone_name_target = target_name
        if hasattr(item, "is_custom"):
            item.is_custom = True
        applied += 1

    report["mapping_applied"] = True
    report["mapping_applied_count"] = applied
    report["mapping_skipped"] = skipped[:100]
    return applied


def discover_operators(prefixes=("rsl", "rokoko")) -> list:
    found = []
    for prefix in prefixes:
        ops_group = getattr(bpy.ops, prefix, None)
        if ops_group is None:
            continue
        for name in dir(ops_group):
            if not name.startswith("_"):
                found.append(f"{prefix}.{name}")
    return sorted(found)


def call_operator(op_name: str):
    group_name, func_name = op_name.split(".", 1)
    group = getattr(bpy.ops, group_name)
    return getattr(group, func_name)()


def run_rokoko_retarget(source, target, mapping_data: dict, report: dict) -> bool:
    configure_rokoko_scene(source, target, report)
    mapped_count = apply_mapping_to_rokoko_bone_list(mapping_data, source, target, report)
    report["operators_discovered"] = discover_operators()
    if mapped_count > 0:
        candidates = [
            "rsl.retarget_animation",
            "rsl.build_bone_list",
            "rsl.retarget_animation",
        ]
    else:
        candidates = [
            "rsl.build_bone_list",
            "rsl.retarget_animation",
            "rokoko.build_bone_list",
            "rokoko.retarget_animation",
            "rsl.save_custom_bones_retargeting",
            "rsl.retarget_animation",
        ]
    success = False
    for op_name in candidates:
        report.setdefault("operators_tried", []).append(op_name)
        try:
            result = call_operator(op_name)
            report.setdefault("operator_results", []).append(f"{op_name}: {result}")
            if "retarget_animation" in op_name:
                success = True
                break
        except Exception as exc:
            report.setdefault("operator_errors", []).append(f"{op_name}: {exc}")
    return success


def _target_related_objects(target) -> list:
    related = [target]
    for obj in bpy.data.objects:
        if obj == target:
            continue
        if obj.parent == target:
            related.append(obj)
            continue
        for modifier in getattr(obj, "modifiers", []):
            if getattr(modifier, "type", None) == "ARMATURE" and getattr(modifier, "object", None) == target:
                related.append(obj)
                break
    return related


def _object_world_points(obj) -> list:
    points = []
    if getattr(obj, "bound_box", None):
        points.extend(obj.matrix_world @ Vector(corner) for corner in obj.bound_box)
    if obj.type == "ARMATURE":
        for bone in obj.pose.bones:
            points.append(obj.matrix_world @ bone.head)
            points.append(obj.matrix_world @ bone.tail)
    return points


def _world_bounds(objects) -> tuple[Vector, Vector]:
    points = []
    for obj in objects:
        if obj.hide_render:
            continue
        points.extend(_object_world_points(obj))
    if not points:
        return Vector((-1.0, -1.0, 0.0)), Vector((1.0, 1.0, 2.0))
    min_v = Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points)))
    max_v = Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points)))
    return min_v, max_v


def _look_at(obj, target_point: Vector) -> None:
    direction = target_point - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def setup_camera_and_lights(targets, report: dict):
    """根据所有目标角色的世界包围盒自动布置相机和基础灯光。"""
    if not isinstance(targets, (list, tuple)):
        targets = [targets]
    related = []
    for target in targets:
        related.extend(_target_related_objects(target))
    min_v, max_v = _world_bounds(related)
    center = (min_v + max_v) * 0.5
    extent = max_v - min_v
    height = max(float(extent.z), 1.5)
    width = max(float(extent.x), float(extent.y), 1.0)

    distance_scale = float(bpy.context.scene.get("retarget_camera_distance_scale", 1.0))
    distance = max(height * 2.3, width * 2.0, 4.5) * distance_scale
    camera_height = center.z + height * 0.08

    bpy.ops.object.light_add(type="AREA", location=(center.x, center.y - distance * 0.45, center.z + height * 1.2))
    light = bpy.context.object
    light.name = "Retarget_Key_Light"
    light.data.energy = 900
    light.data.size = max(5.0, height * 2.2)

    bpy.ops.object.camera_add(location=(center.x, center.y - distance, camera_height))
    camera = bpy.context.object
    camera.data.lens = 35
    camera.data.angle = math.radians(45)
    _look_at(camera, center)
    bpy.context.scene.camera = camera

    report["camera"] = {
        "mode": "auto_fit_bounds",
        "target_armatures": [obj.name for obj in targets],
        "target_related_objects": [obj.name for obj in related],
        "bounds_min": [round(v, 4) for v in min_v],
        "bounds_max": [round(v, 4) for v in max_v],
        "center": [round(v, 4) for v in center],
        "extent": [round(v, 4) for v in extent],
        "location": [round(v, 4) for v in camera.location],
        "lens": camera.data.lens,
        "angle_degrees": round(math.degrees(camera.data.angle), 2),
    }


def _parse_render_size(raw: str, default=(1080, 1080)) -> tuple[int, int]:
    value = (raw or "").lower().strip()
    if "x" not in value:
        return default
    try:
        width_s, height_s = value.split("x", 1)
        return max(320, int(width_s)), max(320, int(height_s))
    except Exception:
        return default


def _as_bool(value, default=False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def apply_target_spacing(targets, spacing: float, report: dict) -> None:
    if not isinstance(targets, (list, tuple)) or len(targets) <= 1 or spacing <= 0:
        return

    center_index = (len(targets) - 1) * 0.5
    offsets = []
    for index, target in enumerate(targets):
        offset_x = (index - center_index) * spacing
        target.location.x += offset_x
        offsets.append({"target": target.name, "offset_x": round(offset_x, 4)})
    report["target_spacing"] = {
        "spacing": spacing,
        "axis": "X",
        "offsets": offsets,
    }


def _normalized_quaternion(values, fallback=None) -> Quaternion:
    quaternion = Quaternion(values)
    if quaternion.magnitude <= 1e-6:
        return fallback.copy() if fallback is not None else Quaternion((1.0, 0.0, 0.0, 0.0))
    quaternion.normalize()
    return quaternion


def _make_quaternions_sign_continuous(quaternions: list) -> tuple[list, int]:
    if not quaternions:
        return [], 0
    continuous = [quaternions[0].copy()]
    flips = 0
    for quaternion in quaternions[1:]:
        aligned = quaternion.copy()
        if continuous[-1].dot(aligned) < 0.0:
            aligned.negate()
            flips += 1
        continuous.append(aligned)
    return continuous, flips


def _weighted_slerp_mean(quaternions: list, center_index: int, radius: int) -> Quaternion:
    order = [center_index]
    for distance in range(1, radius + 1):
        if center_index - distance >= 0:
            order.append(center_index - distance)
        if center_index + distance < len(quaternions):
            order.append(center_index + distance)

    result = quaternions[center_index].copy()
    total_weight = float(radius + 1)
    for index in order[1:]:
        distance = abs(index - center_index)
        weight = float(radius + 1 - distance)
        candidate = quaternions[index].copy()
        if result.dot(candidate) < 0.0:
            candidate.negate()
        result = result.slerp(candidate, weight / (total_weight + weight))
        result.normalize()
        total_weight += weight
    return result


def _slerp_smooth_quaternions(quaternions: list, window: int) -> list:
    if window <= 1 or len(quaternions) < 3:
        return [quaternion.copy() for quaternion in quaternions]
    radius = max(1, int(window) // 2)
    return [
        _weighted_slerp_mean(quaternions, index, radius)
        for index in range(len(quaternions))
    ]


def _limit_quaternion_rotation_steps(quaternions: list, max_degrees: float) -> tuple[list, int]:
    if not quaternions or max_degrees <= 0.0:
        return [quaternion.copy() for quaternion in quaternions], 0

    max_angle = math.radians(max_degrees)
    limited = [quaternions[0].copy()]
    clamped_count = 0
    for quaternion in quaternions[1:]:
        candidate = quaternion.copy()
        if limited[-1].dot(candidate) < 0.0:
            candidate.negate()
        dot = max(-1.0, min(1.0, limited[-1].dot(candidate)))
        angle = 2.0 * math.acos(dot)
        if angle > max_angle:
            candidate = limited[-1].slerp(candidate, max_angle / angle)
            clamped_count += 1
        candidate.normalize()
        limited.append(candidate)
    return limited, clamped_count


def _quaternion_step_degrees(previous: Quaternion, current: Quaternion) -> float:
    dot = max(-1.0, min(1.0, abs(previous.dot(current))))
    return math.degrees(2.0 * math.acos(dot))


def _limit_quaternion_angular_acceleration(
    quaternions: list,
    max_acceleration_degrees: float,
) -> tuple[list, int]:
    if len(quaternions) < 2 or max_acceleration_degrees <= 0.0:
        return [quaternion.copy() for quaternion in quaternions], 0

    continuous, _ = _make_quaternions_sign_continuous(quaternions)
    original_steps = [
        _quaternion_step_degrees(previous, current)
        for previous, current in zip(continuous, continuous[1:])
    ]
    limited_steps = list(original_steps)

    # Start from rest, then compute the greatest speed profile below the
    # original one whose adjacent values differ by at most the configured cap.
    limited_steps[0] = min(limited_steps[0], max_acceleration_degrees)
    for index in range(1, len(limited_steps)):
        limited_steps[index] = min(
            limited_steps[index],
            limited_steps[index - 1] + max_acceleration_degrees,
        )
    for index in range(len(limited_steps) - 2, -1, -1):
        limited_steps[index] = min(
            limited_steps[index],
            limited_steps[index + 1] + max_acceleration_degrees,
        )

    result = [continuous[0].copy()]
    identity = Quaternion((1.0, 0.0, 0.0, 0.0))
    clamped_count = 0
    for index, (previous, current) in enumerate(zip(continuous, continuous[1:])):
        original_step = original_steps[index]
        selected_step = limited_steps[index]
        if selected_step + 1e-6 < original_step:
            clamped_count += 1
        delta = previous.rotation_difference(current)
        if original_step > 1e-8:
            delta = identity.slerp(delta, selected_step / original_step)
        candidate = result[-1] @ delta
        candidate.normalize()
        result.append(candidate)

    result, _ = _make_quaternions_sign_continuous(result)
    return result, clamped_count


def _quaternion_sequence_stats(quaternions: list) -> dict:
    if not quaternions:
        return {}
    norms = [quaternion.magnitude for quaternion in quaternions]
    angle_steps = []
    for previous, current in zip(quaternions, quaternions[1:]):
        dot = max(-1.0, min(1.0, abs(previous.dot(current))))
        angle_steps.append(math.degrees(2.0 * math.acos(dot)))
    sorted_steps = sorted(angle_steps)
    angular_accelerations = [
        abs(current - previous)
        for previous, current in zip(angle_steps, angle_steps[1:])
    ]
    sorted_accelerations = sorted(angular_accelerations)
    p95_index = min(len(sorted_steps) - 1, int(round((len(sorted_steps) - 1) * 0.95))) if sorted_steps else 0
    acceleration_p95_index = (
        min(len(sorted_accelerations) - 1, int(round((len(sorted_accelerations) - 1) * 0.95)))
        if sorted_accelerations
        else 0
    )
    return {
        "norm_mean": round(sum(norms) / len(norms), 6),
        "norm_min": round(min(norms), 6),
        "norm_max": round(max(norms), 6),
        "rotation_step_mean_degrees": round(sum(angle_steps) / len(angle_steps), 4) if angle_steps else 0.0,
        "rotation_step_p95_degrees": round(sorted_steps[p95_index], 4) if sorted_steps else 0.0,
        "rotation_step_max_degrees": round(max(angle_steps), 4) if angle_steps else 0.0,
        "angular_acceleration_p95_degrees_per_frame2": (
            round(sorted_accelerations[acceleration_p95_index], 4) if sorted_accelerations else 0.0
        ),
        "angular_acceleration_max_degrees_per_frame2": (
            round(max(angular_accelerations), 4) if angular_accelerations else 0.0
        ),
    }


def apply_core_rotation_smoothing(
    targets,
    profiles: dict,
    report: dict,
) -> None:
    """对核心骨骼四元数做符号连续化、球面插值平滑和旋转步长限制。"""
    if not profiles:
        return
    core_keywords = ("hips", "spine", "waist", "pelvis", "abdomen", "chest", "neck", "head")
    pelvis_keywords = ("hips", "waist", "pelvis", "abdomen")

    def profile_name(data_path: str) -> str:
        lowered = data_path.lower()
        if any(keyword in lowered for keyword in pelvis_keywords):
            return "hips"
        if "head" in lowered:
            return "head"
        if "neck" in lowered:
            return "neck"
        if any(keyword in lowered for keyword in ("spine2", "chest", "upperchest")):
            return "chest"
        return "spine"

    details = []
    skipped = []
    for target in targets:
        action = getattr(getattr(target, "animation_data", None), "action", None)
        if action is None:
            continue

        curve_groups = {}
        for fcurve in action.fcurves:
            data_path = fcurve.data_path.lower()
            if "rotation_quaternion" not in data_path or not any(keyword in data_path for keyword in core_keywords):
                continue
            curve_groups.setdefault(fcurve.data_path, {})[fcurve.array_index] = fcurve

        for data_path, indexed_curves in curve_groups.items():
            if set(indexed_curves) != {0, 1, 2, 3}:
                skipped.append({"target": target.name, "data_path": data_path, "reason": "incomplete quaternion channels"})
                continue

            frames = sorted({point.co.x for curve in indexed_curves.values() for point in curve.keyframe_points})
            if len(frames) < 3:
                continue

            quaternions = []
            previous = None
            for frame in frames:
                values = [indexed_curves[index].evaluate(frame) for index in range(4)]
                quaternion = _normalized_quaternion(values, fallback=previous)
                quaternions.append(quaternion)
                previous = quaternion

            quaternions, sign_flips = _make_quaternions_sign_continuous(quaternions)
            before_stats = _quaternion_sequence_stats(quaternions)
            selected_profile_name = profile_name(data_path)
            selected_profile = profiles[selected_profile_name]
            selected_window = int(selected_profile.get("window", 1))
            smoothed = _slerp_smooth_quaternions(quaternions, selected_window)
            smoothed, post_smooth_flips = _make_quaternions_sign_continuous(smoothed)
            sign_flips += post_smooth_flips
            selected_limit = float(selected_profile.get("max_rotation_degrees_per_frame", 0.0))
            smoothed, clamped_count = _limit_quaternion_rotation_steps(smoothed, selected_limit)
            selected_acceleration_limit = float(
                selected_profile.get("max_acceleration_degrees_per_frame2", 0.0)
            )
            smoothed, acceleration_clamped_count = _limit_quaternion_angular_acceleration(
                smoothed,
                selected_acceleration_limit,
            )
            smoothed, final_clamped_count = _limit_quaternion_rotation_steps(smoothed, selected_limit)
            clamped_count += final_clamped_count

            smoothed = [_normalized_quaternion(quaternion) for quaternion in smoothed]
            frame_values = {
                frame: tuple(smoothed[index])
                for index, frame in enumerate(frames)
            }
            for channel, fcurve in indexed_curves.items():
                for point in fcurve.keyframe_points:
                    value = frame_values[point.co.x][channel]
                    point.co.y = value
                    point.handle_left.y = value
                    point.handle_right.y = value
                    point.interpolation = "LINEAR"
                fcurve.update()

            details.append({
                "target": target.name,
                "data_path": data_path,
                "profile": selected_profile_name,
                "window": selected_window,
                "max_rotation_degrees_per_frame": selected_limit,
                "max_acceleration_degrees_per_frame2": selected_acceleration_limit,
                "sign_flips_corrected": sign_flips,
                "rotation_steps_clamped": clamped_count,
                "angular_accelerations_clamped": acceleration_clamped_count,
                "before": before_stats,
                "after": _quaternion_sequence_stats(smoothed),
            })

    if details:
        report["core_rotation_smoothing"] = {
            "method": "sign-continuous weighted SLERP with angular velocity and acceleration limits",
            "profiles": profiles,
            "quaternion_group_count": len(details),
            "fcurve_count": len(details) * 4,
            "details": details,
            "skipped": skipped,
        }


def _collect_world_bone_quaternions(target, bone, frame_start: int, frame_end: int) -> list:
    scene = bpy.context.scene
    quaternions = []
    for frame in range(frame_start, frame_end + 1):
        scene.frame_set(frame)
        world_matrix = target.matrix_world @ bone.matrix
        quaternions.append(_normalized_quaternion(world_matrix.to_quaternion()))
    quaternions, _ = _make_quaternions_sign_continuous(quaternions)
    return quaternions


def apply_head_world_rotation_stabilization(
    targets,
    frame_start: int,
    frame_end: int,
    enabled: bool,
    window: int,
    max_rotation_degrees_per_frame: float,
    max_acceleration_degrees_per_frame2: float,
    report: dict,
) -> None:
    if not enabled or frame_end < frame_start:
        return

    details = []
    skipped = []
    scene = bpy.context.scene
    for target in targets:
        neck = _find_pose_bone(target, ("neck",))
        head = _find_pose_bone(target, ("head",))
        if neck is None:
            skipped.append({"target": target.name, "reason": "neck bone not found"})
            continue

        neck_before = _collect_world_bone_quaternions(target, neck, frame_start, frame_end)
        head_before = (
            _collect_world_bone_quaternions(target, head, frame_start, frame_end)
            if head is not None
            else []
        )
        desired = _slerp_smooth_quaternions(neck_before, window)
        desired, _ = _make_quaternions_sign_continuous(desired)
        desired, speed_clamped = _limit_quaternion_rotation_steps(
            desired,
            max_rotation_degrees_per_frame,
        )
        desired, acceleration_clamped = _limit_quaternion_angular_acceleration(
            desired,
            max_acceleration_degrees_per_frame2,
        )
        desired, final_speed_clamped = _limit_quaternion_rotation_steps(
            desired,
            max_rotation_degrees_per_frame,
        )
        speed_clamped += final_speed_clamped

        helper = bpy.data.objects.new(f"{target.name}_NeckWorldStabilizer", None)
        bpy.context.scene.collection.objects.link(helper)
        helper.rotation_mode = "QUATERNION"
        helper.hide_render = True
        helper.empty_display_type = "ARROWS"
        helper.empty_display_size = 0.12
        for offset, quaternion in enumerate(desired):
            frame = frame_start + offset
            helper.rotation_quaternion = quaternion
            helper.keyframe_insert(data_path="rotation_quaternion", frame=frame, group="NeckWorldStabilizer")
        helper_action = getattr(getattr(helper, "animation_data", None), "action", None)
        if helper_action is not None:
            for fcurve in helper_action.fcurves:
                for point in fcurve.keyframe_points:
                    point.interpolation = "LINEAR"

        constraint = neck.constraints.new(type="COPY_ROTATION")
        constraint.name = "Retarget_NeckWorldStabilizer"
        constraint.target = helper
        constraint.owner_space = "WORLD"
        constraint.target_space = "WORLD"
        if hasattr(constraint, "mix_mode"):
            constraint.mix_mode = "REPLACE"

        neck_after = _collect_world_bone_quaternions(target, neck, frame_start, frame_end)
        head_after = (
            _collect_world_bone_quaternions(target, head, frame_start, frame_end)
            if head is not None
            else []
        )
        details.append({
            "target": target.name,
            "bone": neck.name,
            "helper": helper.name,
            "window": int(window),
            "max_rotation_degrees_per_frame": float(max_rotation_degrees_per_frame),
            "max_acceleration_degrees_per_frame2": float(max_acceleration_degrees_per_frame2),
            "rotation_steps_clamped": int(speed_clamped),
            "angular_accelerations_clamped": int(acceleration_clamped),
            "neck_before": _quaternion_sequence_stats(neck_before),
            "neck_desired": _quaternion_sequence_stats(desired),
            "neck_after": _quaternion_sequence_stats(neck_after),
            "head_before": _quaternion_sequence_stats(head_before),
            "head_after": _quaternion_sequence_stats(head_after),
        })

    scene.frame_set(frame_start)
    report["head_world_rotation_stabilization"] = {
        "enabled": True,
        "method": "world-space neck COPY_ROTATION driven by a filtered quaternion track",
        "details": details,
        "skipped": skipped,
    }


def _numeric_stats(values: list) -> dict:
    if not values:
        return {"mean": 0.0, "p95": 0.0, "max": 0.0}
    ordered = sorted(float(value) for value in values)
    p95_index = min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95)))
    return {
        "mean": round(sum(ordered) / len(ordered), 6),
        "p95": round(ordered[p95_index], 6),
        "max": round(ordered[-1], 6),
    }


def _percentile(values: list, fraction: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def _find_pose_bone(target, suffixes) -> object:
    lowered_suffixes = tuple(suffix.lower() for suffix in suffixes)
    for bone in target.pose.bones:
        if bone.name.lower().endswith(lowered_suffixes):
            return bone
    return None


def _collect_world_bone_heads(target, bone, frame_start: int, frame_end: int) -> list:
    scene = bpy.context.scene
    positions = []
    for frame in range(frame_start, frame_end + 1):
        scene.frame_set(frame)
        positions.append((target.matrix_world @ bone.head).copy())
    return positions


def _detect_contact_segments(
    positions: list,
    height_threshold: float,
    velocity_threshold: float,
    min_frames: int,
) -> tuple[list, float]:
    if len(positions) < max(3, min_frames):
        return [], 0.0
    floor_height = _percentile([position.z for position in positions], 0.02)
    horizontal_speeds = []
    for index, position in enumerate(positions):
        if index == 0:
            delta = positions[1] - position
        elif index == len(positions) - 1:
            delta = position - positions[index - 1]
        else:
            delta = (positions[index + 1] - positions[index - 1]) * 0.5
        horizontal_speeds.append(math.hypot(delta.x, delta.y))

    contacts = [
        position.z <= floor_height + height_threshold and horizontal_speeds[index] <= velocity_threshold
        for index, position in enumerate(positions)
    ]
    segments = []
    start = None
    for index, is_contact in enumerate(contacts + [False]):
        if is_contact and start is None:
            start = index
        elif not is_contact and start is not None:
            if index - start >= min_frames:
                segments.append((start, index - 1))
            start = None
    return segments, floor_height


def _clamp_vector_length(vector: Vector, max_length: float) -> Vector:
    if max_length <= 0.0 or vector.length <= max_length:
        return vector
    return vector.normalized() * max_length


def _set_action_interpolation_linear(action, data_path_prefix: str = "") -> None:
    if action is None:
        return
    for fcurve in action.fcurves:
        if data_path_prefix and not fcurve.data_path.startswith(data_path_prefix):
            continue
        for point in fcurve.keyframe_points:
            point.interpolation = "LINEAR"
        fcurve.update()


def _create_foot_lock(
    target,
    side: str,
    frame_start: int,
    frame_end: int,
    height_threshold: float,
    velocity_threshold: float,
    min_contact_frames: int,
    blend_frames: int,
    max_correction: float,
) -> dict:
    foot = _find_pose_bone(target, (f"{side}Foot",))
    lower_leg = _find_pose_bone(target, (f"{side}Leg",))
    if foot is None or lower_leg is None:
        return {
            "side": side,
            "status": "skipped",
            "reason": "foot or lower-leg bone not found",
        }

    original_positions = _collect_world_bone_heads(target, foot, frame_start, frame_end)
    segments, floor_height = _detect_contact_segments(
        original_positions,
        height_threshold=height_threshold,
        velocity_threshold=velocity_threshold,
        min_frames=min_contact_frames,
    )
    if not segments:
        return {
            "side": side,
            "status": "skipped",
            "reason": "no stable contact segment detected",
            "floor_height": round(floor_height, 6),
        }

    desired_positions = [position.copy() for position in original_positions]
    influences = [0.0] * len(original_positions)
    correction_lengths = []
    segment_reports = []
    blend_frames = max(1, int(blend_frames))

    for start, end in segments:
        segment_positions = original_positions[start : end + 1]
        anchor = Vector((
            _percentile([position.x for position in segment_positions], 0.5),
            _percentile([position.y for position in segment_positions], 0.5),
            _percentile([position.z for position in segment_positions], 0.5),
        ))
        segment_max_correction = 0.0
        for index in range(start, end + 1):
            correction = _clamp_vector_length(anchor - original_positions[index], max_correction)
            desired_positions[index] = original_positions[index] + correction
            correction_length = correction.length
            correction_lengths.append(correction_length)
            segment_max_correction = max(segment_max_correction, correction_length)
            edge_distance = min(index - start, end - index)
            influences[index] = min(1.0, float(edge_distance + 1) / blend_frames)
        segment_reports.append({
            "start_frame": frame_start + start,
            "end_frame": frame_start + end,
            "frames": end - start + 1,
            "anchor": [round(value, 6) for value in anchor],
            "max_correction": round(segment_max_correction, 6),
        })

    bpy.ops.object.empty_add(type="PLAIN_AXES", location=desired_positions[0])
    lock_target = bpy.context.object
    lock_target.name = f"{target.name}_{side}_FootLock"
    lock_target.empty_display_size = 0.08
    lock_target.hide_render = True

    constraint = lower_leg.constraints.new(type="IK")
    constraint.name = f"Retarget_{side}_FootLock"
    constraint.target = lock_target
    constraint.chain_count = 2
    if hasattr(constraint, "use_tail"):
        constraint.use_tail = True
    lower_leg.ik_stretch = 0.0
    if lower_leg.parent is not None:
        lower_leg.parent.ik_stretch = 0.0

    scene = bpy.context.scene
    for offset, frame in enumerate(range(frame_start, frame_end + 1)):
        scene.frame_set(frame)
        lock_target.location = desired_positions[offset]
        lock_target.keyframe_insert(data_path="location", frame=frame)
        constraint.influence = influences[offset]
        constraint.keyframe_insert(data_path="influence", frame=frame)

    _set_action_interpolation_linear(getattr(getattr(lock_target, "animation_data", None), "action", None))
    target_action = getattr(getattr(target, "animation_data", None), "action", None)
    constraint_path = f'pose.bones["{lower_leg.name}"].constraints["{constraint.name}"]'
    _set_action_interpolation_linear(target_action, constraint_path)

    full_contact_errors = []
    evaluated_positions = {}
    for offset, frame in enumerate(range(frame_start, frame_end + 1)):
        if influences[offset] < 0.999:
            continue
        scene.frame_set(frame)
        evaluated_position = target.matrix_world @ foot.head
        evaluated_positions[offset] = evaluated_position.copy()
        full_contact_errors.append((evaluated_position - desired_positions[offset]).length)

    horizontal_steps_before = []
    horizontal_steps_after = []
    for offset in range(1, len(original_positions)):
        if offset not in evaluated_positions or offset - 1 not in evaluated_positions:
            continue
        before_delta = original_positions[offset] - original_positions[offset - 1]
        after_delta = evaluated_positions[offset] - evaluated_positions[offset - 1]
        horizontal_steps_before.append(math.hypot(before_delta.x, before_delta.y))
        horizontal_steps_after.append(math.hypot(after_delta.x, after_delta.y))

    scene.frame_set(frame_start)
    return {
        "side": side,
        "status": "applied",
        "foot_bone": foot.name,
        "lower_leg_bone": lower_leg.name,
        "constraint": constraint.name,
        "target": lock_target.name,
        "floor_height": round(floor_height, 6),
        "contact_frame_count": sum(1 for value in influences if value > 0.0),
        "full_lock_frame_count": sum(1 for value in influences if value >= 0.999),
        "segments": segment_reports,
        "requested_correction": _numeric_stats(correction_lengths),
        "full_contact_error_after_ik": _numeric_stats(full_contact_errors),
        "full_contact_horizontal_step_before": _numeric_stats(horizontal_steps_before),
        "full_contact_horizontal_step_after": _numeric_stats(horizontal_steps_after),
    }


def apply_foot_contact_locking(
    targets,
    frame_start: int,
    frame_end: int,
    enabled: bool,
    height_threshold: float,
    velocity_threshold: float,
    min_contact_frames: int,
    blend_frames: int,
    max_correction: float,
    report: dict,
) -> None:
    """从脚部高度和速度估计接触区间，并用临时约束减轻可见滑步。"""
    if not enabled:
        report["foot_contact_locking"] = {"enabled": False}
        return

    details = []
    for target in targets:
        for side in ("Left", "Right"):
            detail = _create_foot_lock(
                target,
                side=side,
                frame_start=frame_start,
                frame_end=frame_end,
                height_threshold=height_threshold,
                velocity_threshold=velocity_threshold,
                min_contact_frames=min_contact_frames,
                blend_frames=blend_frames,
                max_correction=max_correction,
            )
            detail["target_armature"] = target.name
            details.append(detail)

    report["foot_contact_locking"] = {
        "enabled": True,
        "method": "two-bone IK with animated contact targets",
        "height_threshold": height_threshold,
        "velocity_threshold_per_frame": velocity_threshold,
        "min_contact_frames": min_contact_frames,
        "blend_frames": blend_frames,
        "max_correction": max_correction,
        "details": details,
    }


def _find_target_body_mesh(target):
    meshes = [
        obj
        for obj in _target_related_objects(target)
        if obj.type == "MESH" and not obj.hide_render and len(obj.data.vertices) > 0
    ]
    if not meshes:
        return None
    return max(meshes, key=lambda obj: len(obj.data.vertices))


def _torso_proxy_vertex_indices(mesh, group_names: tuple, minimum_weight: float) -> tuple[list, list]:
    group_indices = {
        group.index
        for group in mesh.vertex_groups
        if any(group.name.lower().endswith(name.lower()) for name in group_names)
    }
    matched_names = [
        group.name for group in mesh.vertex_groups if group.index in group_indices
    ]
    vertex_indices = []
    for vertex in mesh.data.vertices:
        torso_weight = sum(
            assignment.weight
            for assignment in vertex.groups
            if assignment.group in group_indices
        )
        if torso_weight >= minimum_weight:
            vertex_indices.append(vertex.index)
    return vertex_indices, matched_names


def _ellipse_slice_bounds(points: list, longitudinal: float, half_height: float):
    selected = [point for point in points if abs(point.y - longitudinal) <= half_height]
    if len(selected) < 8:
        selected = sorted(points, key=lambda point: abs(point.y - longitudinal))[:32]
    if len(selected) < 4:
        return None
    xs = [point.x for point in selected]
    zs = [point.z for point in selected]
    center_x = (min(xs) + max(xs)) * 0.5
    center_z = (min(zs) + max(zs)) * 0.5
    radius_x = (max(xs) - min(xs)) * 0.5
    radius_z = (max(zs) - min(zs)) * 0.5
    if radius_x <= 1e-5 or radius_z <= 1e-5:
        return None
    return center_x, center_z, radius_x, radius_z, len(selected)


def _hand_proxy_correction(
    target,
    hips,
    hand,
    torso_world_points: list,
    side: str,
    slice_half_height: float,
    proxy_scale: float,
    clearance: float,
    penetration_threshold: float,
    max_correction: float,
) -> tuple[Vector, float, dict]:
    hips_world = target.matrix_world @ hips.matrix
    world_to_proxy = hips_world.inverted()
    torso_points = [world_to_proxy @ point for point in torso_world_points]
    head_world = target.matrix_world @ hand.head
    tail_world = target.matrix_world @ hand.tail
    sample_world = [
        head_world,
        head_world.lerp(tail_world, 0.5),
        tail_world,
    ]
    samples = [world_to_proxy @ point for point in sample_world]

    head_bounds = _ellipse_slice_bounds(
        torso_points,
        samples[0].y,
        slice_half_height,
    )
    if head_bounds is None:
        return Vector((0.0, 0.0, 0.0)), 0.0, {"sample_count": 0}

    center_x, center_z, radius_x, radius_z, _ = head_bounds
    radius_x *= proxy_scale
    radius_z *= proxy_scale
    relative_x = samples[0].x - center_x
    relative_z = samples[0].z - center_z
    normal = Vector((
        relative_x / max(radius_x * radius_x, 1e-8),
        relative_z / max(radius_z * radius_z, 1e-8),
    ))
    if normal.length <= 1e-6:
        normal = Vector((-1.0 if side == "Left" else 1.0, 0.0))
    else:
        normal.normalize()

    required_distance = 0.0
    maximum_penetration = 0.0
    inside_samples = 0
    sample_reports = []
    for sample_name, sample in zip(("head", "mid", "tail"), samples):
        bounds = _ellipse_slice_bounds(torso_points, sample.y, slice_half_height)
        if bounds is None:
            continue
        sample_center_x, sample_center_z, sample_radius_x, sample_radius_z, slice_count = bounds
        sample_radius_x *= proxy_scale
        sample_radius_z *= proxy_scale
        px = sample.x - sample_center_x
        pz = sample.z - sample_center_z
        normalized_radius = (
            (px / sample_radius_x) ** 2
            + (pz / sample_radius_z) ** 2
        )
        penetration = 0.0
        if normalized_radius < 1.0:
            coefficient_a = (
                (normal.x / sample_radius_x) ** 2
                + (normal.y / sample_radius_z) ** 2
            )
            coefficient_b = 2.0 * (
                px * normal.x / (sample_radius_x * sample_radius_x)
                + pz * normal.y / (sample_radius_z * sample_radius_z)
            )
            coefficient_c = normalized_radius - 1.0
            discriminant = max(
                0.0,
                coefficient_b * coefficient_b - 4.0 * coefficient_a * coefficient_c,
            )
            if coefficient_a > 1e-8:
                penetration = max(
                    0.0,
                    (-coefficient_b + math.sqrt(discriminant)) / (2.0 * coefficient_a),
                )
        if penetration > penetration_threshold:
            inside_samples += 1
            maximum_penetration = max(maximum_penetration, penetration)
            required_distance = max(required_distance, penetration + clearance)
        sample_reports.append({
            "sample": sample_name,
            "normalized_radius": round(normalized_radius, 6),
            "penetration": round(penetration, 6),
            "slice_vertex_count": slice_count,
        })

    local_correction = Vector((normal.x * required_distance, 0.0, normal.y * required_distance))
    world_origin = hips_world @ Vector((0.0, 0.0, 0.0))
    world_correction = (hips_world @ local_correction) - world_origin
    world_correction = _clamp_vector_length(world_correction, max_correction)
    return world_correction, maximum_penetration, {
        "inside_sample_count": inside_samples,
        "sample_count": len(sample_reports),
        "direction_proxy": [round(normal.x, 6), round(normal.y, 6)],
        "samples": sample_reports,
    }


def _smooth_vector_track(vectors: list, window: int, max_correction: float) -> list:
    if window <= 1 or len(vectors) < 3:
        return [vector.copy() for vector in vectors]
    radius = max(1, int(window) // 2)
    smoothed = []
    for index, original in enumerate(vectors):
        total = Vector((0.0, 0.0, 0.0))
        total_weight = 0.0
        for candidate_index in range(max(0, index - radius), min(len(vectors), index + radius + 1)):
            distance = abs(candidate_index - index)
            weight = float(radius + 1 - distance)
            total += vectors[candidate_index] * weight
            total_weight += weight
        candidate = total / max(total_weight, 1e-8)
        if original.length > 1e-6:
            candidate = original.lerp(candidate, 0.35)
            if candidate.length < original.length and candidate.length > 1e-6:
                candidate = candidate.normalized() * original.length
        smoothed.append(_clamp_vector_length(candidate, max_correction))
    return smoothed


def _collision_influences(active: list, blend_frames: int) -> list:
    blend_frames = max(1, int(blend_frames))
    influences = [1.0 if value else 0.0 for value in active]
    for index, value in enumerate(active):
        if not value:
            continue
        for distance in range(1, blend_frames + 1):
            influence = float(blend_frames + 1 - distance) / float(blend_frames + 1)
            if index - distance >= 0:
                influences[index - distance] = max(influences[index - distance], influence)
            if index + distance < len(influences):
                influences[index + distance] = max(influences[index + distance], influence)
    return influences


def _true_segments(mask: list, frame_start: int) -> list:
    segments = []
    start = None
    for index, value in enumerate(mask + [False]):
        if value and start is None:
            start = index
        elif not value and start is not None:
            segments.append({
                "start_frame": frame_start + start,
                "end_frame": frame_start + index - 1,
                "frames": index - start,
            })
            start = None
    return segments


def _scan_hand_torso_proxy(
    target,
    body_mesh,
    torso_vertex_indices: list,
    frame_start: int,
    frame_end: int,
    slice_half_height: float,
    proxy_scale: float,
    clearance: float,
    penetration_threshold: float,
    max_correction: float,
) -> dict:
    hips = _find_pose_bone(target, ("Hips",))
    hands = {
        side: _find_pose_bone(target, (f"{side}Hand",))
        for side in ("Left", "Right")
    }
    if hips is None or any(hand is None for hand in hands.values()):
        return {
            "status": "skipped",
            "reason": "hips or hand bone not found",
        }

    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()
    result = {
        side: {
            "positions": [],
            "corrections": [],
            "penetrations": [],
            "active": [],
            "sample_details": {},
        }
        for side in hands
    }
    for frame in range(frame_start, frame_end + 1):
        scene.frame_set(frame)
        depsgraph.update()
        evaluated_object = body_mesh.evaluated_get(depsgraph)
        evaluated_mesh = evaluated_object.to_mesh()
        mesh_world = evaluated_object.matrix_world
        torso_world_points = [
            mesh_world @ evaluated_mesh.vertices[index].co
            for index in torso_vertex_indices
        ]
        for side, hand in hands.items():
            position = (target.matrix_world @ hand.head).copy()
            correction, penetration, sample_detail = _hand_proxy_correction(
                target,
                hips,
                hand,
                torso_world_points,
                side=side,
                slice_half_height=slice_half_height,
                proxy_scale=proxy_scale,
                clearance=clearance,
                penetration_threshold=penetration_threshold,
                max_correction=max_correction,
            )
            result[side]["positions"].append(position)
            result[side]["corrections"].append(correction)
            result[side]["penetrations"].append(penetration)
            result[side]["active"].append(correction.length > 1e-6)
            if correction.length > 1e-6 and len(result[side]["sample_details"]) < 12:
                result[side]["sample_details"][str(frame)] = sample_detail
        evaluated_object.to_mesh_clear()
    scene.frame_set(frame_start)
    result["status"] = "completed"
    return result


def _create_hand_torso_ik(
    target,
    side: str,
    frame_start: int,
    frame_end: int,
    scan: dict,
    blend_frames: int,
    smoothing_window: int,
    max_correction: float,
) -> dict:
    hand = _find_pose_bone(target, (f"{side}Hand",))
    forearm = _find_pose_bone(target, (f"{side}ForeArm",))
    if hand is None or forearm is None or forearm.parent is None:
        return {
            "side": side,
            "status": "skipped",
            "reason": "hand, forearm, or upper-arm bone not found",
        }

    original_positions = scan["positions"]
    raw_corrections = scan["corrections"]
    smoothed_corrections = _smooth_vector_track(
        raw_corrections,
        window=smoothing_window,
        max_correction=max_correction,
    )
    influences = _collision_influences(scan["active"], blend_frames)
    desired_positions = [
        position + correction
        for position, correction in zip(original_positions, smoothed_corrections)
    ]
    if not any(value > 0.0 for value in influences):
        return {
            "side": side,
            "status": "skipped",
            "reason": "no hand-torso proxy penetration detected",
        }

    bpy.ops.object.empty_add(type="PLAIN_AXES", location=desired_positions[0])
    ik_target = bpy.context.object
    ik_target.name = f"{target.name}_{side}_HandTorsoAvoidance"
    ik_target.empty_display_size = 0.06
    ik_target.hide_render = True

    constraint = forearm.constraints.new(type="IK")
    constraint.name = f"Retarget_{side}_HandTorsoAvoidance"
    constraint.target = ik_target
    constraint.chain_count = 2
    if hasattr(constraint, "use_tail"):
        constraint.use_tail = True
    forearm.ik_stretch = 0.0
    forearm.parent.ik_stretch = 0.0

    scene = bpy.context.scene
    for offset, frame in enumerate(range(frame_start, frame_end + 1)):
        scene.frame_set(frame)
        ik_target.location = desired_positions[offset]
        ik_target.keyframe_insert(data_path="location", frame=frame)
        constraint.influence = influences[offset]
        constraint.keyframe_insert(data_path="influence", frame=frame)

    _set_action_interpolation_linear(
        getattr(getattr(ik_target, "animation_data", None), "action", None)
    )
    target_action = getattr(getattr(target, "animation_data", None), "action", None)
    constraint_path = f'pose.bones["{forearm.name}"].constraints["{constraint.name}"]'
    _set_action_interpolation_linear(target_action, constraint_path)

    evaluated_positions = []
    ik_errors = []
    for offset, frame in enumerate(range(frame_start, frame_end + 1)):
        scene.frame_set(frame)
        evaluated = (target.matrix_world @ hand.head).copy()
        evaluated_positions.append(evaluated)
        if influences[offset] >= 0.999:
            ik_errors.append((evaluated - desired_positions[offset]).length)

    displacement = [
        (evaluated - original).length
        for evaluated, original in zip(evaluated_positions, original_positions)
    ]
    scene.frame_set(frame_start)
    return {
        "side": side,
        "status": "applied",
        "hand_bone": hand.name,
        "forearm_bone": forearm.name,
        "upper_arm_bone": forearm.parent.name,
        "constraint": constraint.name,
        "target": ik_target.name,
        "candidate_frame_count": sum(1 for value in scan["active"] if value),
        "corrected_frame_count": sum(1 for value in influences if value > 0.0),
        "full_influence_frame_count": sum(1 for value in influences if value >= 0.999),
        "collision_segments": _true_segments(scan["active"], frame_start),
        "penetration_before": _numeric_stats(scan["penetrations"]),
        "requested_correction": _numeric_stats(
            [correction.length for correction in raw_corrections]
        ),
        "smoothed_correction": _numeric_stats(
            [correction.length for correction in smoothed_corrections]
        ),
        "wrist_displacement": _numeric_stats(displacement),
        "full_influence_ik_error": _numeric_stats(ik_errors),
        "sample_details": scan["sample_details"],
    }


def apply_hand_torso_collision_avoidance(
    targets,
    frame_start: int,
    frame_end: int,
    enabled: bool,
    torso_minimum_weight: float,
    slice_half_height: float,
    proxy_scale: float,
    clearance: float,
    penetration_threshold: float,
    blend_frames: int,
    smoothing_window: int,
    max_correction: float,
    report: dict,
) -> None:
    if not enabled:
        report["hand_torso_collision_avoidance"] = {"enabled": False}
        return

    details = []
    for target in targets:
        body_mesh = _find_target_body_mesh(target)
        if body_mesh is None:
            details.append({
                "target_armature": target.name,
                "status": "skipped",
                "reason": "target body mesh not found",
            })
            continue
        torso_vertex_indices, matched_groups = _torso_proxy_vertex_indices(
            body_mesh,
            group_names=("Hips", "Spine", "Spine1", "Spine2"),
            minimum_weight=torso_minimum_weight,
        )
        if len(torso_vertex_indices) < 32:
            details.append({
                "target_armature": target.name,
                "body_mesh": body_mesh.name,
                "status": "skipped",
                "reason": "not enough torso proxy vertices",
                "torso_vertex_count": len(torso_vertex_indices),
                "matched_vertex_groups": matched_groups,
            })
            continue

        before_scan = _scan_hand_torso_proxy(
            target,
            body_mesh,
            torso_vertex_indices,
            frame_start=frame_start,
            frame_end=frame_end,
            slice_half_height=slice_half_height,
            proxy_scale=proxy_scale,
            clearance=clearance,
            penetration_threshold=penetration_threshold,
            max_correction=max_correction,
        )
        if before_scan.get("status") != "completed":
            details.append({
                "target_armature": target.name,
                "body_mesh": body_mesh.name,
                **before_scan,
            })
            continue

        side_details = []
        for side in ("Left", "Right"):
            side_details.append(_create_hand_torso_ik(
                target,
                side=side,
                frame_start=frame_start,
                frame_end=frame_end,
                scan=before_scan[side],
                blend_frames=blend_frames,
                smoothing_window=smoothing_window,
                max_correction=max_correction,
            ))

        after_scan = _scan_hand_torso_proxy(
            target,
            body_mesh,
            torso_vertex_indices,
            frame_start=frame_start,
            frame_end=frame_end,
            slice_half_height=slice_half_height,
            proxy_scale=proxy_scale,
            clearance=clearance,
            penetration_threshold=penetration_threshold,
            max_correction=max_correction,
        )
        for side_detail in side_details:
            side = side_detail["side"]
            if after_scan.get("status") == "completed":
                side_detail["candidate_frame_count_after"] = sum(
                    1 for value in after_scan[side]["active"] if value
                )
                side_detail["penetration_after"] = _numeric_stats(
                    after_scan[side]["penetrations"]
                )

        details.append({
            "target_armature": target.name,
            "body_mesh": body_mesh.name,
            "body_mesh_vertex_count": len(body_mesh.data.vertices),
            "torso_proxy_vertex_count": len(torso_vertex_indices),
            "matched_vertex_groups": matched_groups,
            "sides": side_details,
        })

    bpy.context.scene.frame_set(frame_start)
    report["hand_torso_collision_avoidance"] = {
        "enabled": True,
        "method": "target-mesh torso ellipse proxy with animated two-bone arm IK",
        "torso_minimum_weight": torso_minimum_weight,
        "slice_half_height": slice_half_height,
        "proxy_scale": proxy_scale,
        "clearance": clearance,
        "penetration_threshold": penetration_threshold,
        "blend_frames": blend_frames,
        "smoothing_window": smoothing_window,
        "max_correction": max_correction,
        "details": details,
    }


def configure_render_settings(manifest: dict, report: dict) -> None:
    """将 manifest 中的尺寸、引擎、采样率和帧范围写入 Blender 场景。"""
    scene = bpy.context.scene
    requested_engine = str(manifest.get("render_engine") or "").strip()
    if requested_engine:
        scene.render.engine = requested_engine

    requested_samples = manifest.get("eevee_render_samples")
    if requested_samples is not None:
        samples = max(1, int(requested_samples))
        eevee = getattr(scene, "eevee", None)
        if eevee is None or not hasattr(eevee, "taa_render_samples"):
            raise RuntimeError(
                "This Blender version does not expose Eevee taa_render_samples."
            )
        eevee.taa_render_samples = samples

    requested_percentage = manifest.get("resolution_percentage")
    if requested_percentage is not None:
        scene.render.resolution_percentage = max(
            1,
            min(100, int(requested_percentage)),
        )

    eevee = getattr(scene, "eevee", None)
    report["render_settings"] = {
        "engine": scene.render.engine,
        "eevee_render_samples": (
            int(eevee.taa_render_samples)
            if eevee is not None and hasattr(eevee, "taa_render_samples")
            else None
        ),
        "resolution_percentage": int(scene.render.resolution_percentage),
    }


def render_output(output_path: Path, fps: int, frame_end: int, report: dict, frame_start: int = 1) -> None:
    scene = bpy.context.scene
    scene.frame_start = max(1, int(frame_start))
    scene.frame_end = max(scene.frame_start, int(frame_end))
    scene.render.fps = fps
    scene.render.filepath = str(output_path)
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    width, height = _parse_render_size(str(scene.get("retarget_render_size", "")))
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    report["render_settings"].update(
        {
            "resolution_x": int(scene.render.resolution_x),
            "resolution_y": int(scene.render.resolution_y),
            "fps": int(scene.render.fps),
            "frame_start": int(scene.frame_start),
            "frame_end": int(scene.frame_end),
            "output_format": scene.render.image_settings.file_format,
            "ffmpeg_format": scene.render.ffmpeg.format,
            "ffmpeg_codec": scene.render.ffmpeg.codec,
        }
    )
    bpy.ops.render.render(animation=True)


def action_frame_end(*armatures) -> int:
    frame_end = 1
    for armature in armatures:
        action = getattr(getattr(armature, "animation_data", None), "action", None)
        if action is not None:
            frame_end = max(frame_end, int(action.frame_range[1]))
    return frame_end


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.manifest).resolve()
    manifest = load_manifest(manifest_path)
    report_path = Path(manifest.get("report_path") or manifest_path.with_name("rokoko_retarget_report.json")).resolve()
    report = {
        "status": "running",
        "manifest": str(manifest_path),
    }

    try:
        target_fbx_files = [
            Path(path).resolve()
            for path in (manifest.get("target_fbx_files") or [manifest["target_fbx"]])
        ]
        mapping_files = [
            Path(path).resolve()
            for path in (manifest.get("mapping_files") or [manifest["mapping_file"]])
        ]
        if not target_fbx_files or not mapping_files:
            raise RuntimeError("Retarget manifest must provide target FBX and mapping resources")
        source_bvh_files = manifest.get("source_bvh_files") or [manifest["source_bvh"]]
        output_mp4 = Path(manifest["output_mp4"]).resolve()
        debug_blend = Path(manifest.get("debug_blend") or output_mp4.with_suffix(".blend")).resolve()
        fps = int(manifest.get("fps") or 30)
        max_render_frames = int(manifest.get("max_render_frames") or 0)
        report["motion_profile"] = str(manifest.get("motion_profile") or "default")
        report["motion_prompt"] = str(manifest.get("motion_prompt") or "")
        report["person_skin_ids"] = list(manifest.get("person_skin_ids") or [])

        clear_scene()
        configure_render_settings(manifest, report)
        enable_addons(report)
        imported_sources = []
        for source_bvh in source_bvh_files:
            imported_sources.extend(import_bvh(Path(source_bvh).resolve(), fps=fps))
        source_armatures = find_armatures(imported_sources)
        if not source_armatures:
            raise RuntimeError("No source BVH armature imported. Check source-bvh paths.")

        report["source_armatures"] = [obj.name for obj in source_armatures]
        target_armatures = []
        retarget_pairs = []
        for index, source in enumerate(source_armatures, start=1):
            resource_index = min(index - 1, len(target_fbx_files) - 1)
            mapping_index = min(index - 1, len(mapping_files) - 1)
            target_fbx = target_fbx_files[resource_index]
            mapping_file = mapping_files[mapping_index]
            imported_target = import_fbx(target_fbx)
            imported_target_armatures = find_armatures(imported_target)
            if not imported_target_armatures:
                raise RuntimeError(f"No target FBX armature imported: {target_fbx}")
            target = imported_target_armatures[0]
            target.name = f"Retarget_Target_{index}"
            target_armatures.append(target)

            pair_report = {
                "source": source.name,
                "target": target.name,
                "target_fbx": str(target_fbx),
                "mapping_file": str(mapping_file),
            }
            mapping_data = clean_mapping(mapping_file, pair_report)
            ok = run_rokoko_retarget(source, target, mapping_data, pair_report)
            retarget_pairs.append(pair_report)
            if not ok:
                report["retarget_pairs"] = retarget_pairs
                raise RuntimeError(f"No Rokoko retarget operator succeeded for source: {source.name}")

        report["target_armatures"] = [obj.name for obj in target_armatures]
        report["imported_armatures"] = [obj.name for obj in find_armatures()]
        report["retarget_pairs"] = retarget_pairs

        for obj in source_armatures:
            obj.hide_viewport = True
            obj.hide_render = True
        bpy.context.scene["retarget_camera_distance_scale"] = float(manifest.get("camera_distance_scale") or 1.0)
        bpy.context.scene["retarget_render_size"] = str(manifest.get("render_size") or "1080x1080")
        apply_target_spacing(target_armatures, float(manifest.get("target_spacing") or 0.0), report)
        if "target_spacing" in report:
            report["target_spacing"]["motion_profile"] = report["motion_profile"]
        hips_window = int(manifest.get("core_smoothing_window") or 0)
        spine_window_raw = manifest.get("spine_smoothing_window")
        spine_window = int(spine_window_raw) if spine_window_raw is not None else max(1, hips_window)
        max_rotation_raw = manifest.get("core_max_rotation_degrees_per_frame")
        max_rotation = 20.0 if max_rotation_raw is None else float(max_rotation_raw)
        spine_max_rotation_raw = manifest.get("spine_max_rotation_degrees_per_frame")
        spine_max_rotation = 20.0 if spine_max_rotation_raw is None else float(spine_max_rotation_raw)
        profiles = {
            "hips": {
                "window": hips_window,
                "max_rotation_degrees_per_frame": max_rotation,
                "max_acceleration_degrees_per_frame2": float(
                    manifest.get("core_max_acceleration_degrees_per_frame2", 6.0)
                ),
            },
            "spine": {
                "window": spine_window,
                "max_rotation_degrees_per_frame": spine_max_rotation,
                "max_acceleration_degrees_per_frame2": float(
                    manifest.get("spine_max_acceleration_degrees_per_frame2", 8.0)
                ),
            },
            "chest": {
                "window": int(manifest.get("chest_smoothing_window", 5)),
                "max_rotation_degrees_per_frame": float(
                    manifest.get("chest_max_rotation_degrees_per_frame", 18.0)
                ),
                "max_acceleration_degrees_per_frame2": float(
                    manifest.get("chest_max_acceleration_degrees_per_frame2", 8.0)
                ),
            },
            "neck": {
                "window": int(manifest.get("neck_smoothing_window", 7)),
                "max_rotation_degrees_per_frame": float(
                    manifest.get("neck_max_rotation_degrees_per_frame", 15.0)
                ),
                "max_acceleration_degrees_per_frame2": float(
                    manifest.get("neck_max_acceleration_degrees_per_frame2", 6.0)
                ),
            },
            "head": {
                "window": int(manifest.get("head_smoothing_window", 7)),
                "max_rotation_degrees_per_frame": float(
                    manifest.get("head_max_rotation_degrees_per_frame", 12.0)
                ),
                "max_acceleration_degrees_per_frame2": float(
                    manifest.get("head_max_acceleration_degrees_per_frame2", 6.0)
                ),
            },
        }
        apply_core_rotation_smoothing(
            target_armatures,
            profiles=profiles,
            report=report,
        )
        frame_end = action_frame_end(*(source_armatures + target_armatures))
        if max_render_frames > 0:
            frame_end = min(frame_end, max_render_frames)
        apply_head_world_rotation_stabilization(
            target_armatures,
            frame_start=1,
            frame_end=frame_end,
            enabled=_as_bool(manifest.get("head_world_stabilization_enabled"), True),
            window=int(manifest.get("head_world_smoothing_window", 3)),
            max_rotation_degrees_per_frame=float(
                manifest.get("head_world_max_rotation_degrees_per_frame", 20.0)
            ),
            max_acceleration_degrees_per_frame2=float(
                manifest.get("head_world_max_acceleration_degrees_per_frame2", 6.0)
            ),
            report=report,
        )
        apply_foot_contact_locking(
            target_armatures,
            frame_start=1,
            frame_end=frame_end,
            enabled=_as_bool(manifest.get("foot_lock_enabled"), False),
            height_threshold=float(manifest.get("foot_lock_height_threshold") or 0.065),
            velocity_threshold=float(manifest.get("foot_lock_velocity_threshold") or 0.08),
            min_contact_frames=int(manifest.get("foot_lock_min_contact_frames") or 3),
            blend_frames=int(manifest.get("foot_lock_blend_frames") or 2),
            max_correction=float(manifest.get("foot_lock_max_correction") or 0.15),
            report=report,
        )
        apply_hand_torso_collision_avoidance(
            target_armatures,
            frame_start=1,
            frame_end=frame_end,
            enabled=_as_bool(manifest.get("hand_torso_collision_enabled"), True),
            torso_minimum_weight=float(
                manifest.get("hand_torso_collision_torso_minimum_weight") or 0.5
            ),
            slice_half_height=float(
                manifest.get("hand_torso_collision_slice_half_height") or 0.05
            ),
            proxy_scale=float(
                manifest.get("hand_torso_collision_proxy_scale") or 0.95
            ),
            clearance=float(
                manifest.get("hand_torso_collision_clearance") or 0.025
            ),
            penetration_threshold=float(
                manifest.get("hand_torso_collision_penetration_threshold") or 0.005
            ),
            blend_frames=int(
                manifest.get("hand_torso_collision_blend_frames") or 4
            ),
            smoothing_window=int(
                manifest.get("hand_torso_collision_smoothing_window") or 5
            ),
            max_correction=float(
                manifest.get("hand_torso_collision_max_correction") or 0.12
            ),
            report=report,
        )
        setup_camera_and_lights(target_armatures, report)
        if (len(target_armatures) == 1 and target_fbx_files[0].name.lower() == "nailong.fbx"
                and _as_bool(manifest.get("nailong_profile_enabled"), True)):
            # Apply only to the known single Nailong asset. Preserve the full
            # adapted action in the saved scene even when preview frames are limited.
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from nailong_character_profile import apply_single_nailong_profile
            apply_single_nailong_profile(target_armatures[0], 1,
                action_frame_end(target_armatures[0]), report)
        render_output(output_mp4, fps=fps, frame_end=frame_end, report=report)

        debug_blend.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(debug_blend))

        report["status"] = "completed"
        report["message"] = "Rokoko retarget and render completed."
        report["output"] = str(output_mp4)
        report["debug_blend"] = str(debug_blend)
        write_report(report_path, report)
        return 0
    except Exception as exc:
        report["status"] = "failed"
        report["message"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
        write_report(report_path, report)
        print(report["traceback"])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
