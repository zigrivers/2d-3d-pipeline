"""
Headless Blender script: prepare an AI-generated GLB for 3D printing.

Steps:
  1. Import the clean GLB
  2. Try to enable the 3D Print Toolbox add-on (bundled with Blender)
  3. Mesh hygiene pass: weld vertices, fix normals, fill holes,
     dissolve degenerate faces, kill loose geometry
  4. Manifold pass (3D Print Toolbox if available; basic ops otherwise)
  5. Scale to real-world millimeters (longest side = TARGET_SIZE_MM)
  6. Orient: lowest point at Z=0, base on the build plate
  7. Validate final dimensions on every axis against the Snapmaker U1 build
     volume (270 mm). If any axis exceeds, exit non-zero unless
     allow_oversize is passed.
  8. Write a sidecar `<output>.print_meta.json` with dims/fits info that
     print.sh reads to emit its --json result.
  9. Export binary STL.

Run from print.sh, or manually:
  /Applications/Blender.app/Contents/MacOS/Blender --background \\
    --python prepare_for_print.py -- \\
        INPUT.glb OUTPUT.stl SIZE_MM ORIENTATION ALLOW_OVERSIZE
"""
import bpy
import json
import sys
from mathutils import Matrix


# ---------- parse arguments ----------
argv = sys.argv[sys.argv.index('--') + 1:]
input_path = argv[0]
output_path = argv[1]
target_size_mm = float(argv[2])
orientation = argv[3].lower() if len(argv) > 3 else "auto"
allow_oversize = (argv[4].lower() in ("true", "1", "yes")) if len(argv) > 4 else False


# ---------- enable 3D Print Toolbox if available ----------
def try_enable_print_toolbox():
    """Best-effort enabling of Blender's 3D Print Toolbox.
    The module name has changed across Blender versions, so try several.
    Returns True if the add-on is active and its operators are available."""
    candidate_modules = [
        "bl_ext.blender_org.print3d_toolbox",  # 4.2+ extensions system
        "bl_ext.system.print3d_toolbox",
        "print3d_toolbox",
        "object_print3d_utils",                # legacy bundled add-on
    ]
    for mod in candidate_modules:
        try:
            bpy.ops.preferences.addon_enable(module=mod)
            # Check if a known operator exists
            if hasattr(bpy.ops.mesh, "print3d_clean_non_manifold"):
                return True
        except Exception:
            continue
    # Operator may exist even if enable failed silently
    return hasattr(bpy.ops.mesh, "print3d_clean_non_manifold")


has_3dprint = try_enable_print_toolbox()


# ---------- clean scene & import ----------
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=input_path)

meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
if not meshes:
    raise RuntimeError(f"No mesh found in {input_path}")

# Join multiple parts into a single mesh — required for a single STL solid
if len(meshes) > 1:
    bpy.ops.object.select_all(action='DESELECT')
    for m in meshes:
        m.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.join()

obj = bpy.context.view_layer.objects.active
obj.select_set(True)
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)


# ---------- mesh hygiene & manifold pass ----------
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')

# 1. Weld coincident vertices (kills duplicates from generator)
bpy.ops.mesh.remove_doubles(threshold=0.0001)

# 2. Recalculate normals outward — printing needs consistent winding
bpy.ops.mesh.normals_make_consistent(inside=False)

# 3. Delete loose geometry (floating verts/edges with no face)
bpy.ops.mesh.delete_loose()

# 4. Dissolve zero-area faces (slicers choke on these)
bpy.ops.mesh.dissolve_degenerate()

# 5. Fill holes — close gaps in the surface
bpy.ops.mesh.fill_holes(sides=12)

# 6. If 3D Print Toolbox is enabled, run its make-manifold operator
#    which handles cases the basic ops miss (overlapping faces,
#    self-intersections, internal walls)
if has_3dprint:
    try:
        bpy.ops.mesh.print3d_clean_non_manifold()
    except Exception as e:
        print(f"[prepare_for_print] 3D Print Toolbox cleanup skipped: {e}")

bpy.ops.object.mode_set(mode='OBJECT')


# ---------- scale to real-world millimeters ----------
# After clean_asset.py, longest dim should already be ~1.0 (normalized).
# We treat Blender units as millimeters here and scale so the longest
# dimension equals target_size_mm.
current_max = max(obj.dimensions)
if current_max <= 0:
    raise RuntimeError("Mesh has zero dimensions after cleanup")

scale_factor = target_size_mm / current_max
obj.scale = (scale_factor,) * 3
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)


# ---------- orient for printing: lowest point on bed ----------
# Slicers expect Z-up and the model resting on Z=0.
# clean_asset.py exported Y-up GLB, but the importer should convert.
# We additionally translate so the lowest vertex sits at Z=0.
local_min_z = min(v.co.z for v in obj.data.vertices)
obj.data.transform(Matrix.Translation((0, 0, -local_min_z)))
obj.location = (0, 0, 0)


# ---------- check final dimensions on every axis ----------
dims_mm = tuple(round(d, 2) for d in obj.dimensions)
poly_count = len(obj.data.polygons)
vert_count = len(obj.data.vertices)

# Snapmaker U1 build volume: 270 mm cube. Validate X, Y, AND Z.
U1_LIMIT = 270.0
oversized_axes = [a for a, d in zip("XYZ", dims_mm) if d > U1_LIMIT]
fits = not oversized_axes


def write_meta(fits: bool):
    """Write a sidecar JSON file alongside the STL output so print.sh can
    read the structured results without parsing this script's stdout."""
    meta = {
        "final_dimensions_mm": {
            "x": float(dims_mm[0]),
            "y": float(dims_mm[1]),
            "z": float(dims_mm[2]),
        },
        "fits_snapmaker_u1": fits,
        "oversized_axes": oversized_axes,
        "u1_limit_mm": U1_LIMIT,
        "polygons": int(poly_count),
        "vertices": int(vert_count),
        "print_toolbox_enabled": bool(has_3dprint),
    }
    try:
        with open(output_path + ".print_meta.json", "w") as fh:
            json.dump(meta, fh, indent=2, sort_keys=True)
            fh.write("\n")
    except OSError as exc:  # don't kill the run just because we can't write meta
        print(f"[prepare_for_print] could not write sidecar meta: {exc}")


if oversized_axes and not allow_oversize:
    # Fail BEFORE exporting STL so we don't leave a misleading file behind.
    print(f"[prepare_for_print] ERROR: dimensions {dims_mm} mm exceed "
          f"Snapmaker U1 build volume ({U1_LIMIT} mm) on axes: {oversized_axes}")
    print("[prepare_for_print] Re-run with --allow-oversize to bypass this check.")
    write_meta(fits=False)
    sys.exit(3)

if oversized_axes:
    # allow_oversize: keep the warning but proceed.
    print(f"[prepare_for_print] WARNING: dimensions {dims_mm} mm exceed "
          f"Snapmaker U1 build volume ({U1_LIMIT} mm) on axes: {oversized_axes}. "
          f"Continuing because --allow-oversize was passed.")


# ---------- export STL ----------
# Blender 4.x: bpy.ops.wm.stl_export
# Blender 3.x: bpy.ops.export_mesh.stl
def export_stl_compat(filepath):
    # Try 4.x API first
    try:
        bpy.ops.wm.stl_export(
            filepath=filepath,
            export_selected_objects=False,
            global_scale=1.0,
            forward_axis='Y',
            up_axis='Z',
            ascii_format=False,
            apply_modifiers=True,
        )
        return "4.x"
    except (AttributeError, TypeError):
        pass
    # Fall back to 3.x API
    try:
        bpy.ops.export_mesh.stl(
            filepath=filepath,
            global_scale=1.0,
            ascii=False,
            use_mesh_modifiers=True,
        )
        return "3.x"
    except (AttributeError, RuntimeError) as e:
        raise RuntimeError(f"STL export failed: {e}")


api_used = export_stl_compat(output_path)

# Sidecar JSON is the authoritative source for print.sh's --json result.
write_meta(fits=fits)


# ---------- v0.3: mesh quality check on the printable STL ----------
# Runs in pipeline-tools-env (trimesh + numpy). Writes to the STL's
# meta.json next to it. Silent when the venv / helper aren't present.
import subprocess as _sp
import os as _os
_meta_path = output_path + ".meta.json"
_here = _os.path.dirname(_os.path.abspath(__file__))
_check = _os.path.join(_here, "mesh_quality_check.py")
if not _os.path.exists(_check):
    _check = _os.path.expanduser("~/3d-pipeline/workspace/mesh_quality_check.py")
_helper_py = _os.path.expanduser("~/3d-pipeline/pipeline-tools-env/bin/python")
if _os.path.exists(_check) and _os.path.exists(_helper_py):
    try:
        _sp.run(
            [_helper_py, _check,
             "--input", output_path,
             "--meta", _meta_path,
             "--mode", "mm"],
            check=False,
            timeout=60,
        )
    except Exception as _e:
        print(f"[prepare_for_print] mesh_quality_check skipped: {_e}")

# v0.3: print structural gates (wall thickness, COM, base contact, etc.)
_struct = _os.path.join(_here, "print_structural_check.py")
if not _os.path.exists(_struct):
    _struct = _os.path.expanduser("~/3d-pipeline/workspace/print_structural_check.py")
if _os.path.exists(_struct) and _os.path.exists(_helper_py):
    try:
        _sp.run(
            [_helper_py, _struct,
             "--input", output_path,
             "--meta", _meta_path],
            check=False,
            timeout=120,
        )
    except Exception as _e:
        print(f"[prepare_for_print] print_structural_check skipped: {_e}")


# ---------- report ----------
print(f"[prepare_for_print] OK -> {output_path}")
print(f"  Dimensions:        {dims_mm[0]} x {dims_mm[1]} x {dims_mm[2]} mm")
print(f"  Polygons:          {poly_count:,}")
print(f"  Vertices:          {vert_count:,}")
print(f"  3D Print Toolbox:  {'enabled' if has_3dprint else 'fallback to basic ops'}")
print(f"  STL API:           Blender {api_used}")
print(f"  Fits U1 (<=270mm): {'yes' if not oversized_axes else 'NO — ' + ','.join(oversized_axes)}")
