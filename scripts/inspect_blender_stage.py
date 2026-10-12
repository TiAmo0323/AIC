"""Read optional Blender source/target geometry diagnostics without saving."""
import json
from pathlib import Path
import sys
import bpy
import numpy as np

output = Path(sys.argv[sys.argv.index('--')+1])
scene = bpy.context.scene
scene.frame_set(scene.frame_start)
rows = []
for obj in scene.objects:
    if obj.type == 'ARMATURE':
        rows.append({'name': obj.name, 'location': list(obj.location), 'scale': list(obj.scale),
            'bones': [{'name': b.name, 'length': b.length, 'head_world': list(obj.matrix_world @ b.head),
                       'tail_world': list(obj.matrix_world @ b.tail), 'local_location': list(b.location)} for b in obj.pose.bones]})
output.write_text(json.dumps(rows,indent=2), encoding='utf-8')
