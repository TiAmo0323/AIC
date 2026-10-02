"""A conservative cartoon presentation profile for the local single Nailong rig.

This adapts an existing human dance; it does not add foot IK or facial animation.
Only the known single-character rig is supported. Original assets stay intact.
"""
import math

import bpy
from mathutils import Quaternion, Vector


def _mesh_points(obj):
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    return [evaluated.matrix_world @ vertex.co for vertex in evaluated.data.vertices]


def _adapt_rotations(rig, start, end):
    action = rig.animation_data.action
    settings = {
        "Bone01": (0.8, 35), "Bone01_Spine": (0.75, 15),
        "Bone01_Spine1": (0.75, 15), "Bone01_Head": (0.55, 25),
        **{f"Forearm_{side}_01": (0.72, 85) for side in ("L", "R")},
        **{f"Forearm_{side}_02": (0.60, 65) for side in ("L", "R")},
        **{f"Forearm_{side}_03": (0.50, 30) for side in ("L", "R")},
        **{f"Bone01_{side}_Thigh": (0.75, 45) for side in ("L", "R")},
        **{f"Bone01_{side}_Calf": (0.65, 35) for side in ("L", "R")},
    }
    details = []
    for name, (gain, limit) in settings.items():
        path = f'pose.bones["{name}"].rotation_quaternion'
        curves = [next((curve for curve in action.fcurves if curve.data_path == path and curve.array_index == index), None)
                  for index in range(4)]
        if any(curve is None for curve in curves):
            continue
        maximum_before = maximum_after = 0.0
        adjusted = []
        for frame in range(start, end + 1):
            q = Quaternion([curve.evaluate(frame) for curve in curves]).normalized()
            if q.w < 0:
                q.negate()
            angle = q.angle
            maximum_before = max(maximum_before, math.degrees(angle))
            factor = min(gain, math.radians(limit) / max(angle, 1e-8))
            result = Quaternion().slerp(q, factor)
            maximum_after = max(maximum_after, math.degrees(result.angle))
            adjusted.append(result)
        for frame, q in zip(range(start, end + 1), adjusted):
            for index, curve in enumerate(curves):
                point = curve.keyframe_points.insert(frame, q[index], options={"FAST"})
                point.interpolation = "LINEAR"
        for curve in curves:
            curve.update()
        details.append({"bone": name, "gain": gain, "limit_degrees": limit,
                        "max_before_degrees": maximum_before, "max_after_degrees": maximum_after})
    return details


def _ground_root(rig, body, start, end):
    groups = {group.index: group.name for group in body.vertex_groups}
    foot_indices = [v.index for v in body.data.vertices if v.co.z < 0.2 and any(
        groups.get(weight.group) in {"Bone01_L_Calf", "Bone01_R_Calf"} and weight.weight > 0.2 for weight in v.groups)]
    if not foot_indices:
        raise ValueError("Nailong foot mesh sample not found")
    root = rig.pose.bones["Bone01"]
    world_to_local = root.bone.matrix_local.to_3x3().inverted() @ rig.matrix_world.to_3x3().inverted()
    before, offsets = [], []
    for frame in range(start, end + 1):
        bpy.context.scene.frame_set(frame)
        evaluated = body.evaluated_get(bpy.context.evaluated_depsgraph_get())
        bottom = min((evaluated.matrix_world @ evaluated.data.vertices[index].co).z for index in foot_indices)
        correction = 0.008 - bottom
        before.append(bottom)
        offsets.append(correction)
        root.location += world_to_local @ Vector((0, 0, correction))
        root.keyframe_insert(data_path="location", frame=frame)
    for curve in rig.animation_data.action.fcurves:
        if curve.data_path == 'pose.bones["Bone01"].location':
            for point in curve.keyframe_points:
                point.interpolation = "LINEAR"
            curve.update()
    after = []
    for frame in range(start, end + 1):
        bpy.context.scene.frame_set(frame)
        evaluated = body.evaluated_get(bpy.context.evaluated_depsgraph_get())
        after.append(min((evaluated.matrix_world @ evaluated.data.vertices[index].co).z for index in foot_indices))
    return {"method": "whole-body root height from evaluated foot mesh; no foot IK",
            "sample_vertices": len(foot_indices), "before_min_m": min(before), "before_max_m": max(before),
            "after_min_m": min(after), "after_max_m": max(after), "max_correction_m": max(abs(x) for x in offsets)}


def _appearance(meshes):
    pupil = next(obj for obj in meshes if obj.name.startswith("Mod_LMSHK_Suit_21_eye1"))
    if not pupil.get("nailong_iris_adjusted"):
        for sign in (-1, 1):
            vertices = [v for v in pupil.data.vertices if v.co.x * sign > 0]
            center = sum((v.co for v in vertices), Vector()) / len(vertices)
            for vertex in vertices:
                vertex.co.x = center.x + (vertex.co.x - center.x) * 1.28
                vertex.co.z = center.z + (vertex.co.z - center.z) * 1.28
                vertex.co.y -= 0.004
        pupil["nailong_iris_adjusted"] = True
    seen = set()
    for obj in meshes:
        for material in obj.data.materials:
            if material is None or material.name in seen:
                continue
            seen.add(material.name)
            material.use_nodes = True
            nodes = material.node_tree.nodes
            old_shader = next((node for node in nodes if node.type == "BSDF_PRINCIPLED"), None)
            base = old_shader.inputs["Base Color"] if old_shader else None
            texture = base.links[0].from_node.image if base and base.is_linked and base.links[0].from_node.type == "TEX_IMAGE" else None
            color = tuple(base.default_value) if base else tuple(material.diffuse_color)
            nodes.clear()
            output = nodes.new("ShaderNodeOutputMaterial")
            diffuse = nodes.new("ShaderNodeBsdfDiffuse")
            emission = nodes.new("ShaderNodeEmission")
            mix = nodes.new("ShaderNodeMixShader")
            mix.inputs[0].default_value = 0.65
            emission.inputs["Strength"].default_value = 1.0
            diffuse.inputs["Color"].default_value = color
            emission.inputs["Color"].default_value = color
            if texture:
                node = nodes.new("ShaderNodeTexImage")
                node.image = texture
                material.node_tree.links.new(node.outputs["Color"], diffuse.inputs["Color"])
                material.node_tree.links.new(node.outputs["Color"], emission.inputs["Color"])
            material.node_tree.links.new(diffuse.outputs[0], mix.inputs[1])
            material.node_tree.links.new(emission.outputs[0], mix.inputs[2])
            material.node_tree.links.new(mix.outputs[0], output.inputs["Surface"])


def apply_single_nailong_profile(rig, start, end, report):
    if rig.get("nailong_profile_version") == 1:
        return
    if not rig.animation_data or not rig.animation_data.action or "Bone01" not in rig.pose.bones:
        raise ValueError("Expected an animated local Nailong rig")
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and any(
        modifier.type == "ARMATURE" and modifier.object == rig for modifier in obj.modifiers)]
    body = next(obj for obj in meshes if obj.name.startswith("Mod_LMSHK_Suit_21") and len(obj.data.vertices) == 4949)
    profile = {"version": 1, "frame_start": start, "frame_end": end,
               "rotation_adaptation": _adapt_rotations(rig, start, end)}
    profile["grounding"] = _ground_root(rig, body, start, end)
    _appearance(meshes)
    scene = bpy.context.scene
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1
    if not scene.world:
        scene.world = bpy.data.worlds.new("Nailong Studio World")
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes.get("Background")
    background.inputs["Color"].default_value = (0.7, 0.75, 0.8, 1)
    background.inputs["Strength"].default_value = 0.35
    for obj in bpy.context.scene.objects:
        if obj.type == "LIGHT":
            obj.data.energy = 120
            if obj.data.type == "AREA":
                obj.data.size = 4
    bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, 0))
    plane = bpy.context.object
    plane.name = "Nailong Studio Ground"
    ground = bpy.data.materials.new("Nailong Ground")
    ground.use_nodes = True
    shader = ground.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (0.63, 0.68, 0.73, 1)
    shader.inputs["Roughness"].default_value = 0.85
    plane.data.materials.append(ground)
    # Fit the complete adapted dance, keeping the same camera for every frame.
    points = []
    for frame in range(start, end + 1, 15):
        scene.frame_set(frame)
        points.extend(_mesh_points(body))
    minimum = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    maximum = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    center = (minimum + maximum) / 2
    extent = maximum - minimum
    camera = scene.camera
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = max(extent.z * 1.35, extent.x * 1.4, 1.8)
    camera.location = center + Vector((0.2, -4, 0.6))
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
    profile["appearance"] = {"color_transform": "Standard", "body_shader": "65% texture emission + 35% diffuse",
                             "iris_geometry_scale": 1.28, "ground_plane": True}
    profile["camera"] = {"type": "ORTHO", "scale": camera.data.ortho_scale, "sampled_dance_bounds": [list(minimum), list(maximum)]}
    profile["limitations"] = ["Whole-body grounding can suppress source jumps; this is a cartoon preview profile",
                              "No independent foot IK or facial expression animation", "Source mesh proportions remain a simplified fan model"]
    rig["nailong_profile_version"] = 1
    scene.frame_set(start)
    report["nailong_character_profile"] = profile
