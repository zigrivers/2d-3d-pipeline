"""
Headless Blender cleanup for AI-generated 3D assets.

Run from generate.sh, or manually via:
  /Applications/Blender.app/Contents/MacOS/Blender --background \
    --python clean_asset.py -- INPUT.glb OUTPUT.glb TARGET_POLY [up_axis]

up_axis: "y" (Unity-friendly, default) or "z" (Unreal-friendly)
"""
import bpy
import sys
from mathutils import Matrix

argv = sys.argv[sys.argv.index('--') + 1:]
input_path, output_path = argv[0], argv[1]
target_poly = int(argv[2])
up_axis = argv[3].lower() if len(argv) > 3 else "y"

# --- clean scene ---
bpy.ops.wm.read_factory_settings(use_empty=True)

# --- import ---
bpy.ops.import_scene.gltf(filepath=input_path)
meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
if not meshes:
    raise RuntimeError("No mesh found in input file")

# join if multiple parts
if len(meshes) > 1:
    bpy.ops.object.select_all(action='DESELECT')
    for m in meshes:
        m.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.join()

obj = bpy.context.view_layer.objects.active
obj.select_set(True)

# --- apply transforms ---
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

# --- mesh hygiene ---
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.mesh.remove_doubles(threshold=0.0001)
bpy.ops.mesh.normals_make_consistent(inside=False)
bpy.ops.mesh.delete_loose()
bpy.ops.mesh.fill_holes(sides=6)
bpy.ops.object.mode_set(mode='OBJECT')

# --- decimate to target polycount ---
current = len(obj.data.polygons)
if current > target_poly:
    mod = obj.modifiers.new(name="Decimate", type='DECIMATE')
    mod.ratio = target_poly / current
    bpy.ops.object.modifier_apply(modifier="Decimate")

# --- normalize: pivot at bottom of bounding box, scale to ~1m ---
bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')

local_min_z = min(v.co.z for v in obj.data.vertices)
obj.data.transform(Matrix.Translation((0, 0, -local_min_z)))
obj.location = (0, 0, 0)

dims = obj.dimensions
if max(dims) > 0:
    obj.scale = (1.0 / max(dims),) * 3
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

# --- export GLB with correct up-axis ---
bpy.ops.export_scene.gltf(
    filepath=output_path,
    export_format='GLB',
    export_apply=True,
    export_yup=(up_axis == "y"),
)

print(f"[clean_asset] OK -> {output_path}  ({len(obj.data.polygons)} polys)")
