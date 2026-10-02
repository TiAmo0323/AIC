"""Prepare the downloaded Nailong rig for the existing Blender/Rokoko pipeline.

Run with Blender, not system Python. Originals stay untouched; the output FBX
contains normalized geometry, repaired materials and rigid face skin weights.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector


# The original has no separate shoulders, neck, feet or toe deform bones.
# Map only real joints. Bone01 moves both the pelvis and the spine branches.
BONE_MAPPING = {
    "Hips": "Bone01", "Spine": "Bone01_Spine", "Spine1": "Bone01_Spine1",
    "Head": "Bone01_Head",
    "LeftArm": "Forearm_L_01", "LeftForeArm": "Forearm_L_02", "LeftHand": "Forearm_L_03",
    "RightArm": "Forearm_R_01", "RightForeArm": "Forearm_R_02", "RightHand": "Forearm_R_03",
    "LeftUpLeg": "Bone01_L_Thigh", "LeftLeg": "Bone01_L_Calf",
    "RightUpLeg": "Bone01_R_Thigh", "RightLeg": "Bone01_R_Calf",
}


def material(name, texture=None, color=(1, 1, 1, 1), roughness=0.55):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.diffuse_color = color
    shader = mat.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = color
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Metallic"].default_value = 0
    shader.inputs["Alpha"].default_value = 1
    if texture:
        node = mat.node_tree.nodes.new("ShaderNodeTexImage")
        node.image = bpy.data.images.load(str(texture), check_existing=True)
        node.image.pack()
        mat.node_tree.links.new(node.outputs["Color"], shader.inputs["Base Color"])
    return mat


def prepare(source, output, mapping_path, report_path, height):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(source))
    bpy.context.view_layer.update()  # FBX parent matrices are initially stale.
    rigs = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    if len(rigs) != 1:
        raise ValueError(f"Expected exactly one armature, got {len(rigs)}")
    rig = rigs[0]
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not meshes or any(rig.data.bones.get(name) is None for name in BONE_MAPPING.values()):
        raise ValueError("The source is not the expected rigged Nailong FBX")
    rig.animation_data_clear()
    for bone in rig.pose.bones:
        bone.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()
    worlds = {obj: obj.matrix_world.copy() for obj in [rig, *meshes]}
    # This FBX's geometry uses Y up while its bind skeleton uses Z up. The
    # identity pose therefore shows the mesh sideways even before retargeting.
    # Correct geometry only: +Y becomes +Z and the face's +Z becomes -Y.
    mesh_bind_correction = Matrix.Rotation(math.pi / 2, 4, "X")
    for obj in meshes:
        worlds[obj] = mesh_bind_correction @ worlds[obj]
    corners = [worlds[obj] @ Vector(corner) for obj in meshes for corner in obj.bound_box]
    lo = Vector(tuple(min(p[i] for p in corners) for i in range(3)))
    hi = Vector(tuple(max(p[i] for p in corners) for i in range(3)))
    # The source's root bone uses Z up once its FBX hierarchy is evaluated.
    up = (worlds[rig].to_3x3() @ Vector((0, 0, 1))).normalized()
    if up.dot(Vector((0, 0, 1))) < 0.99:
        raise ValueError(f"Unexpected source up axis: {list(up)}")
    scale = height / (hi.z - lo.z)
    normalization = Matrix.Translation(Vector((0, 0, -lo.z * scale))) @ Matrix.Scale(scale, 4)
    # Flatten the imported helper hierarchy, baking the same transform into
    # bone rest matrices and all meshes so their skin relationship is preserved.
    for obj in [rig, *meshes]:
        obj.parent = None
        obj.matrix_parent_inverse = Matrix.Identity(4)
        obj.matrix_world = Matrix.Identity(4)
        obj.data.transform(normalization @ worlds[obj])
        obj.animation_data_clear()
    rig.name = "Nailong_Rig"
    repairs = []
    for obj in meshes:
        obj.parent = rig
        obj.matrix_parent_inverse = Matrix.Identity(4)
        obj.matrix_basis = Matrix.Identity(4)
        modifiers = [mod for mod in obj.modifiers if mod.type == "ARMATURE"]
        if not modifiers:
            modifiers = [obj.modifiers.new("Nailong Skin", "ARMATURE")]
        for mod in modifiers:
            mod.object = rig
        if not obj.vertex_groups:
            if "eye" in obj.name:
                groups = {name: obj.vertex_groups.new(name=name) for name in ("Face_eye01", "Face_eye02")}
                for vertex in obj.data.vertices:
                    name = "Face_eye01" if vertex.co.x < 0 else "Face_eye02"
                    groups[name].add([vertex.index], 1, "REPLACE")
            elif "yachi" in obj.name:
                name = "Face_Teeh01" if obj.name.endswith("up") else "Face_Teeh02"
                obj.vertex_groups.new(name=name).add(list(range(len(obj.data.vertices))), 1, "REPLACE")
            else:
                raise ValueError(f"Unknown unweighted mesh: {obj.name}")
            repairs.append({"mesh": obj.name, "weighted_vertices": len(obj.data.vertices)})
    body = material("Nailong Body", source.parent / "Cn_Tex_LMSuit_21_D.png")
    eyes = material("Nailong Eyes", source.parent / "Cn_Tex_LMSuit_21_D_eye.png", roughness=0.24)
    teeth = material("Nailong Teeth", color=(0.95, 0.91, 0.8, 1))
    tongue = material("Nailong Tongue", color=(0.65, 0.1, 0.16, 1))
    for obj in meshes:
        mat = eyes if "eye" in obj.name else teeth if "yachi" in obj.name else tongue if "shrtou" in obj.name else body
        obj.data.materials.clear()
        obj.data.materials.append(mat)
        for polygon in obj.data.polygons:
            polygon.material_index = 0
            polygon.use_smooth = True
    for obj in list(bpy.context.scene.objects):
        if obj not in [rig, *meshes]:
            bpy.data.objects.remove(obj, do_unlink=True)
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action="SELECT")
    bpy.context.view_layer.objects.active = rig
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.fbx(filepath=str(output), use_selection=True, object_types={"ARMATURE", "MESH"},
        axis_forward="-Y", axis_up="Z", add_leaf_bones=False, bake_anim=False,
        path_mode="COPY", embed_textures=True)
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    mapping_path.write_text(json.dumps({"bones": [{"name": src, "SourceBoneName": src,
        "DestinationBoneName": dest} for src, dest in BONE_MAPPING.items()]}, indent=2), encoding="utf-8")
    report = {"source": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "output": str(output), "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "mapping_file": str(mapping_path), "height_m": height, "scale_factor": scale,
        "original_world_bounds": {"min": list(lo), "max": list(hi)}, "rigid_mesh_repairs": repairs,
        "mesh_bind_axis_correction_degrees_x": 90,
        "bone_count": len(rig.data.bones), "mapping_count": len(BONE_MAPPING),
        "limitations": ["No separate foot/toe deform bones or finger bones", "No facial animation clips"]}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--height", type=float, default=1.2)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if args.height <= 0:
        parser.error("Height must be positive")
    if args.input.resolve() == args.output.resolve():
        parser.error("Output must not overwrite the original")
    prepare(args.input.resolve(strict=True), args.output.resolve(), args.mapping.resolve(), args.report.resolve(), args.height)
