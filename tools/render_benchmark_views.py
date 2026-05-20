"""v0.3 — synthetic benchmark dataset builder (Option C in P3.1a.1).

Renders a glTF/GLB asset to N calibrated views per a view-config JSON,
then prepares the per-subject directory the multi-view benchmark
expects (front/right/back/left.png + a 45° concept.png for Option B,
plus a ground_truth.glb symlink and a meta.json).

Run via Blender headless:

  blender --background --python tools/render_benchmark_views.py -- \
      --source PATH.glb \
      --output-dir tests/multiview-bench/subjects/subject-N-X-synthetic/ \
      --view-config tests/multiview-bench/view_configs/canonical_4view.json \
      [--resolution 1024] [--samples 32]

Reuses the same three-point light rig + camera framing logic as
scripts/turntable_render.py (P1.7) for visual consistency between
preview renders and benchmark inputs.

This is a maintainer tool; lives in /tools, NOT subject to the
canonical-vs-embedded rule.
"""
import bpy
import json
import math
import os
import sys
from mathutils import Vector


def _parse_args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    opts: dict = {}
    i = 0
    while i < len(argv):
        k = argv[i]
        if k.startswith("--"):
            v = argv[i + 1] if i + 1 < len(argv) else ""
            opts[k.lstrip("-")] = v
            i += 2
        else:
            i += 1
    return opts


def _setup_scene(input_path: str):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=input_path)
    scene = bpy.context.scene
    meshes = [o for o in scene.objects if o.type == 'MESH']
    if not meshes:
        raise RuntimeError(f"no mesh in {input_path}")
    if len(meshes) > 1:
        bpy.ops.object.select_all(action='DESELECT')
        for m in meshes:
            m.select_set(True)
        bpy.context.view_layer.objects.active = meshes[0]
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    return scene, obj


def _bbox(obj):
    bb = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    center = sum(bb, Vector()) / 8.0
    longest = max(
        max(p.x for p in bb) - min(p.x for p in bb),
        max(p.y for p in bb) - min(p.y for p in bb),
        max(p.z for p in bb) - min(p.z for p in bb),
    )
    return center, longest


def _make_lights(scene, target, dist):
    def add(name, energy, x, y, z):
        ld = bpy.data.lights.new(name=name, type='AREA')
        ld.energy = energy
        ld.size = max(dist * 0.3, 0.5)
        o = bpy.data.objects.new(name, ld)
        o.location = (x, y, z)
        scene.collection.objects.link(o)
        c = o.constraints.new('TRACK_TO')
        c.target = target
        c.track_axis = 'TRACK_NEGATIVE_Z'
        c.up_axis = 'UP_Y'
        return o
    cx, cy, cz = target.location.x, target.location.y, target.location.z
    add("Key",  600, cx + dist * 0.7, cy - dist * 0.5, cz + dist * 0.5)
    add("Fill", 300, cx - dist * 0.6, cy - dist * 0.3, cz + dist * 0.2)
    add("Rim",  400, cx,              cy + dist * 0.8, cz + dist * 0.5)


def _make_camera(scene):
    cam_data = bpy.data.cameras.new("BenchCam")
    cam_data.lens = 50.0
    cam = bpy.data.objects.new("BenchCam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    return cam


def _aim_camera(cam, center: Vector, azimuth_deg: float, elevation_deg: float, dist: float):
    az = math.radians(azimuth_deg)
    el = math.radians(elevation_deg)
    cx = center.x + dist * math.cos(az) * math.cos(el)
    cy = center.y + dist * math.sin(az) * math.cos(el)
    cz = center.z + dist * math.sin(el)
    cam.location = (cx, cy, cz)
    direction = (center - Vector((cx, cy, cz))).normalized()
    cam.rotation_mode = 'XYZ'
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()


def _setup_render(scene, resolution: int, samples: int):
    engines = {e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items}
    scene.render.engine = 'BLENDER_EEVEE_NEXT' if 'BLENDER_EEVEE_NEXT' in engines else 'BLENDER_EEVEE'
    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.film_transparent = True
    try:
        scene.eevee.taa_render_samples = samples
    except Exception:
        pass


def main() -> int:
    opts = _parse_args()
    source = opts.get("source")
    output_dir = opts.get("output-dir") or opts.get("output_dir")
    view_config_path = opts.get("view-config") or opts.get("view_config")
    resolution = int(opts.get("resolution", "1024"))
    samples = int(opts.get("samples", "32"))

    if not (source and output_dir and view_config_path):
        print("Usage: blender --background --python render_benchmark_views.py -- "
              "--source PATH.glb --output-dir DIR --view-config PATH.json "
              "[--resolution 1024] [--samples 32]", file=sys.stderr)
        return 2

    view_config = json.loads(open(view_config_path).read())
    os.makedirs(output_dir, exist_ok=True)

    scene, obj = _setup_scene(source)
    center, longest = _bbox(obj)
    dist = max(longest * 1.7, 0.05)

    cam = _make_camera(scene)
    _make_lights(scene, obj, dist)
    _setup_render(scene, resolution, samples)

    rendered: list[dict] = []
    for view in view_config["views"]:
        name = view["name"]
        az = float(view["azimuth_deg"])
        el = float(view.get("elevation_deg", 0))
        _aim_camera(cam, center, az, el, dist)
        out = os.path.join(output_dir, f"{name}.png")
        scene.render.filepath = out
        bpy.ops.render.render(write_still=True)
        rendered.append({"name": name, "path": out, "azimuth_deg": az, "elevation_deg": el})

    # Concept image for Option B: a single 45° view at elevation 15°.
    _aim_camera(cam, center, 45, 15, dist)
    concept_path = os.path.join(output_dir, "concept.png")
    scene.render.filepath = concept_path
    bpy.ops.render.render(write_still=True)

    # Copy the source GLB into the subject dir as ground_truth.glb so the
    # benchmark can find it without a path lookup. Hard copy (not symlink)
    # so the subject dir is self-contained for git-archive style snapshots.
    import shutil as _sh
    gt_path = os.path.join(output_dir, "ground_truth.glb")
    if os.path.abspath(source) != os.path.abspath(gt_path):
        _sh.copyfile(source, gt_path)

    meta = {
        "input_pipeline": "synthetic",
        "source_glb": os.path.basename(source),
        "view_config": view_config["name"],
        "views": rendered,
        "concept_path": concept_path,
        "ground_truth_glb": gt_path,
        "resolution": resolution,
        "samples": samples,
    }
    with open(os.path.join(output_dir, "meta.json"), "w") as fh:
        json.dump(meta, fh, indent=2, sort_keys=True)
        fh.write("\n")

    print(f"[render-views] wrote {len(rendered)} views + concept to {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
