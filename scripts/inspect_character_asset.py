"""Run in Blender to inspect an imported character without changing its source.

blender -b --disable-autoexec --python inspect_character_asset.py --
    --input character.fbx --output inspection.json
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector


def inspect_asset(source):
    suffix = source.suffix.lower()
    if suffix == ".blend":
        bpy.ops.wm.open_mainfile(filepath=str(source), use_scripts=False)
    else:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        if suffix == ".fbx":
            bpy.ops.import_scene.fbx(filepath=str(source))
        elif suffix in {".glb", ".gltf"}:
            bpy.ops.import_scene.gltf(filepath=str(source))
        elif suffix == ".obj":
            bpy.ops.wm.obj_import(filepath=str(source))
        else:
            raise ValueError("Expected FBX, GLB, GLTF, BLEND or OBJ")
    bpy.context.view_layer.update()
    armatures, meshes = [], []
    corners = []
    for obj in bpy.context.scene.objects:
        if obj.type == "ARMATURE":
            armatures.append({"name": obj.name, "bones": [
                {"name": bone.name, "parent": bone.parent.name if bone.parent else None,
                 "deform": bone.use_deform, "head_local": list(bone.head_local),
                 "tail_local": list(bone.tail_local)} for bone in obj.data.bones]})
        if obj.type != "MESH":
            continue
        obj.data.calc_loop_triangles()
        corners.extend(obj.matrix_world @ Vector(corner) for corner in obj.bound_box)
        targets = [mod.object.name for mod in obj.modifiers if mod.type == "ARMATURE" and mod.object]
        bound_bones = {bone.name for mod in obj.modifiers if mod.type == "ARMATURE" and mod.object
                       for bone in mod.object.data.bones if bone.use_deform}
        groups = {group.index: group.name for group in obj.vertex_groups}
        weighted = sum(any(group.weight > 0 and groups.get(group.group) in bound_bones
                           for group in vertex.groups) for vertex in obj.data.vertices)
        meshes.append({"name": obj.name, "vertices": len(obj.data.vertices),
            "triangles": len(obj.data.loop_triangles), "armature_targets": targets,
            "weighted_vertices": weighted, "unweighted_vertices": len(obj.data.vertices) - weighted,
            "vertex_groups": list(groups.values()),
            "materials": [slot.material.name if slot.material else None for slot in obj.material_slots]})
    materials = []
    for material in bpy.data.materials:
        textures = []
        if material.use_nodes:
            for node in material.node_tree.nodes:
                if node.type != "TEX_IMAGE" or not node.image:
                    continue
                image = node.image
                absolute = Path(bpy.path.abspath(image.filepath)) if image.filepath else None
                textures.append({"name": image.name, "path": str(absolute) if absolute else None,
                    "packed": bool(image.packed_file), "exists": bool(image.packed_file or absolute and absolute.is_file()),
                    "size": list(image.size)})
        materials.append({"name": material.name, "diffuse_color": list(material.diffuse_color), "textures": textures})
    bounds = None
    if corners:
        minimum = [min(corner[axis] for corner in corners) for axis in range(3)]
        maximum = [max(corner[axis] for corner in corners) for axis in range(3)]
        bounds = {"minimum": minimum, "maximum": maximum,
                  "dimensions": [high-low for high, low in zip(maximum, minimum)]}
    return {"source": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "blender_version": bpy.app.version_string, "armatures": armatures, "meshes": meshes,
        "materials": materials, "world_bounds": bounds,
        "has_armature": bool(armatures), "has_skin_weights": any(mesh["weighted_vertices"] for mesh in meshes),
        "notes": "Skeleton and weights only establish a rig candidate. Retarget mapping, rest pose and deformation must be checked before animation."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    source = args.input.resolve(strict=True)
    report = inspect_asset(source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(args.output), "meshes": len(report["meshes"]),
                      "armatures": len(report["armatures"]), "has_skin_weights": report["has_skin_weights"]}))
