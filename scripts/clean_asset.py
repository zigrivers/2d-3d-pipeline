"""
Headless Blender cleanup for AI-generated 3D assets.

Run from generate.sh, or manually via:
  /Applications/Blender.app/Contents/MacOS/Blender --background \
    --python clean_asset.py -- INPUT.glb OUTPUT.glb TARGET_POLY [up_axis] [meta_path]

up_axis: "y" (Unity-friendly, default) or "z" (Unreal-friendly)
meta_path (v0.3+): when provided, the script instruments each pass and
writes a `cleanup` section into the per-asset meta.json via
scripts/meta_helper.py (assumed to sit alongside this file). Empty
means skip the meta write — v0.2 behaviour preserved.
"""
import bpy
import json
import subprocess
import sys
import time
from mathutils import Matrix
from pathlib import Path

argv = sys.argv[sys.argv.index('--') + 1:]
input_path, output_path = argv[0], argv[1]
target_poly = int(argv[2])
up_axis = argv[3].lower() if len(argv) > 3 else "y"
meta_path = argv[4] if len(argv) > 4 else ""

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

# --- mesh hygiene with instrumentation (v0.3+) ---
t0 = time.time()
verts_before = len(obj.data.vertices)
edges_before = len(obj.data.edges)
faces_before = len(obj.data.polygons)


def _boundary_edge_count(mesh) -> int:
    """Edges shared by < 2 faces — proxy for "hole edges" in a closed surface."""
    counts = {}
    for poly in mesh.polygons:
        for i in range(len(poly.vertices)):
            a = poly.vertices[i]
            b = poly.vertices[(i + 1) % len(poly.vertices)]
            key = (a, b) if a < b else (b, a)
            counts[key] = counts.get(key, 0) + 1
    return sum(1 for c in counts.values() if c == 1)


boundary_before = _boundary_edge_count(obj.data)

bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.mesh.remove_doubles(threshold=0.0001)
bpy.ops.mesh.normals_make_consistent(inside=False)
bpy.ops.mesh.delete_loose()
bpy.ops.mesh.fill_holes(sides=6)
bpy.ops.object.mode_set(mode='OBJECT')

verts_after_hygiene = len(obj.data.vertices)
edges_after_hygiene = len(obj.data.edges)
boundary_after_hygiene = _boundary_edge_count(obj.data)

# --- decimate to target polycount ---
current = len(obj.data.polygons)
decimate_before = current
decimate_after = current
decimate_ratio = 1.0
decimate_error = None
if current > target_poly:
    try:
        mod = obj.modifiers.new(name="Decimate", type='DECIMATE')
        mod.ratio = target_poly / current
        bpy.ops.object.modifier_apply(modifier="Decimate")
        decimate_after = len(obj.data.polygons)
        decimate_ratio = round(decimate_after / decimate_before, 4) if decimate_before else 1.0
    except Exception as e:
        decimate_error = str(e)
        decimate_after = len(obj.data.polygons)

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

duration = round(time.time() - t0, 2)
duplicate_vertices_removed = max(0, verts_before - verts_after_hygiene)
loose_elements_deleted = max(0, edges_before - edges_after_hygiene)
holes_filled = max(0, boundary_before - boundary_after_hygiene)

print(f"[clean_asset] OK -> {output_path}  ({len(obj.data.polygons)} polys)")
print(
    f"[clean_asset] cleanup: dedup_verts={duplicate_vertices_removed} "
    f"loose={loose_elements_deleted} holes_filled={holes_filled} "
    f"decimate={decimate_before}->{decimate_after} ({duration}s)"
)

# --- v0.3: merge cleanup section into per-asset meta.json ---
if meta_path:
    here = Path(__file__).resolve().parent
    helper = here / "meta_helper.py"
    if not helper.exists():
        # Fall back to global workspace install path
        helper = Path(input_path).resolve().parent.parent / "meta_helper.py"
    if helper.exists():
        cleanup_section = {
            "duplicate_vertices_removed": duplicate_vertices_removed,
            "loose_elements_deleted": loose_elements_deleted,
            "holes_filled": holes_filled,
            "decimate": {
                "before": decimate_before,
                "after": decimate_after,
                "ratio": decimate_ratio,
                "error": decimate_error,
            },
            "duration_seconds": duration,
        }
        try:
            subprocess.run(
                [
                    sys.executable, str(helper), "merge", meta_path,
                    "--section", "cleanup",
                    "--data", json.dumps(cleanup_section),
                ],
                check=False,
            )
        except Exception as e:
            print(f"[clean_asset] could not write cleanup section to meta.json: {e}",
                  file=sys.stderr)
