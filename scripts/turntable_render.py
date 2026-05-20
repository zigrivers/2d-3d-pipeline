"""v0.3 — turntable preview renderer (Blender headless).

Renders a glTF asset to a hero PNG (single frame) and/or a 12-frame
turntable. Frames are written to <preview_dir>/<name>_NN.png. A
Pillow-based GIF assembly is left to the caller (generate.sh) when
mode=gif; this script does NOT depend on Pillow so it runs inside
Blender's bundled Python without extra setup.

Run from generate.sh:

  blender --background --python turntable_render.py -- \
      INPUT.glb PREVIEW_DIR ASSET_NAME MODE FRAMES RESOLUTION SAMPLES META_PATH

  MODE       : png | gif | none
  FRAMES     : 1 for png, 12 for gif (other values accepted)
  RESOLUTION : square px (e.g. 1024 for hero, 512 for gif)
  SAMPLES    : Eevee samples per frame (e.g. 32)
  META_PATH  : per-asset meta.json (optional; "" to skip)

Camera is auto-framed at a 30° elevation, distance = 1.7 × longest
bbox dim. Three-point light rig (key, fill, rim) in Eevee for speed.
"""
import bpy
import json
import math
import os
import subprocess
import sys
import time
from mathutils import Vector

argv = sys.argv[sys.argv.index('--') + 1:]
input_path = argv[0]
preview_dir = argv[1]
name = argv[2]
mode = argv[3]
frames = int(argv[4])
resolution = int(argv[5])
samples = int(argv[6])
meta_path = argv[7] if len(argv) > 7 else ""

os.makedirs(preview_dir, exist_ok=True)
t0 = time.time()

# --- empty scene ---
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

# --- import ---
bpy.ops.import_scene.gltf(filepath=input_path)
meshes = [o for o in scene.objects if o.type == 'MESH']
if not meshes:
    print(f"[turntable] ERROR: no mesh in {input_path}", file=sys.stderr)
    sys.exit(1)
if len(meshes) > 1:
    bpy.ops.object.select_all(action='DESELECT')
    for m in meshes:
        m.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.join()
obj = bpy.context.view_layer.objects.active

# Compute target centre + distance from bbox.
bb = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
center = sum(bb, Vector()) / 8.0
extents = Vector((
    max(p.x for p in bb) - min(p.x for p in bb),
    max(p.y for p in bb) - min(p.y for p in bb),
    max(p.z for p in bb) - min(p.z for p in bb),
))
longest = max(extents)
dist = max(longest * 1.7, 0.05)
elev = math.radians(30.0)

# --- camera ---
cam_data = bpy.data.cameras.new("PreviewCam")
cam = bpy.data.objects.new("PreviewCam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
cam_data.lens = 50.0

# --- three-point lights ---
def make_light(name, energy, x, y, z):
    ld = bpy.data.lights.new(name=name, type='AREA')
    ld.energy = energy
    ld.size = max(longest * 0.5, 0.5)
    obj_l = bpy.data.objects.new(name, ld)
    obj_l.location = (x, y, z)
    scene.collection.objects.link(obj_l)
    return obj_l

key = make_light("Key", 600, center.x + dist * 0.7, center.y - dist * 0.5, center.z + dist * 0.5)
fill = make_light("Fill", 300, center.x - dist * 0.6, center.y - dist * 0.3, center.z + dist * 0.2)
rim = make_light("Rim", 400, center.x, center.y + dist * 0.8, center.z + dist * 0.5)
for light in (key, fill, rim):
    constraint = light.constraints.new('TRACK_TO')
    constraint.target = obj
    constraint.track_axis = 'TRACK_NEGATIVE_Z'
    constraint.up_axis = 'UP_Y'

# --- render settings (Eevee for speed) ---
scene.render.engine = 'BLENDER_EEVEE_NEXT' if 'BLENDER_EEVEE_NEXT' in {e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items} else 'BLENDER_EEVEE'
scene.render.resolution_x = resolution
scene.render.resolution_y = resolution
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGBA'
scene.render.film_transparent = True
try:
    scene.eevee.taa_render_samples = samples
except Exception:
    pass

# Auto-fit camera by adjusting distance per frame. Centre look-at.
hero_path = ""
gif_frame_paths = []

def position_camera(angle_rad: float):
    cx = center.x + dist * math.cos(angle_rad)
    cy = center.y + dist * math.sin(angle_rad)
    cz = center.z + dist * math.sin(elev) * 0.5
    cam.location = (cx, cy, cz)
    direction = (center - Vector((cx, cy, cz))).normalized()
    cam.rotation_mode = 'XYZ'
    # Compute Euler that aims -Z at target
    rot_quat = direction.to_track_quat('-Z', 'Y')
    cam.rotation_euler = rot_quat.to_euler()

if mode == "none" or frames < 1:
    pass
else:
    if mode == "png":
        position_camera(math.radians(45))
        hero_path = os.path.join(preview_dir, f"{name}.png")
        scene.render.filepath = hero_path
        bpy.ops.render.render(write_still=True)
    else:  # gif or any frame count > 1
        # Render N frames + a hero (first frame at 45°)
        for i in range(frames):
            angle = math.radians(i * 360.0 / frames)
            position_camera(angle)
            frame_path = os.path.join(preview_dir, f"{name}_f{i:02d}.png")
            scene.render.filepath = frame_path
            bpy.ops.render.render(write_still=True)
            gif_frame_paths.append(frame_path)
        # Hero = first frame
        if gif_frame_paths:
            hero_path = os.path.join(preview_dir, f"{name}.png")
            try:
                import shutil as _shutil
                _shutil.copyfile(gif_frame_paths[0], hero_path)
            except Exception:
                hero_path = gif_frame_paths[0]

duration = round(time.time() - t0, 2)

# Manifest (read by generate.sh; the GIF assembly happens there using Pillow).
manifest = {
    "mode": mode,
    "hero_png_path": hero_path or None,
    "gif_path": None,  # filled by generate.sh after assembly
    "frame_paths": gif_frame_paths,
    "frames": len(gif_frame_paths) if gif_frame_paths else (1 if hero_path else 0),
    "resolution": resolution,
    "duration_seconds": duration,
}
manifest_path = os.path.join(preview_dir, f"{name}_preview_manifest.json")
with open(manifest_path, "w") as fh:
    json.dump(manifest, fh, indent=2, sort_keys=True)

# Merge a preliminary entry into meta.json (gif_path stays null until
# generate.sh assembles it).
if meta_path:
    here = os.path.dirname(os.path.abspath(__file__))
    helper = os.path.join(here, "meta_helper.py")
    if not os.path.exists(helper):
        helper = os.path.expanduser("~/3d-pipeline/workspace/meta_helper.py")
    if os.path.exists(helper):
        preview_section = {
            "mode": mode,
            "hero_png_path": hero_path or None,
            "gif_path": None,
            "frames": manifest["frames"],
            "resolution": resolution,
            "duration_seconds": duration,
        }
        try:
            subprocess.run(
                [sys.executable, helper, "merge", meta_path,
                 "--section", "preview",
                 "--data", json.dumps(preview_section)],
                check=False,
            )
        except Exception:
            pass

print(f"[turntable] mode={mode} frames={manifest['frames']} duration={duration}s")
print(f"[turntable] manifest={manifest_path}")
if hero_path:
    print(f"[turntable] hero={hero_path}")
