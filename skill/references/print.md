## Flow 4: GLB → printable STL

### Step 1 — Identify the source GLB

The user might reference:
- A name from the manifest: `chest_clean`
- A path: `~/games/grithkin/assets/clean/chest_clean.glb` (project) or
  `~/3d-pipeline/workspace/clean/chest_clean.glb` (global)
- An image they want generated and then printed (chain through flows 1+2 first)

If it's a name only, expand within the active project's `assets/clean/`
first, then fall back to the global workspace if not found.

### Step 2 — Ask about target size

Real-world print size in millimeters. **Always ask if not specified** —
print size is a strong creative choice. Suggest:

> "What size should it be? Common choices: 25mm (small token), 50mm
> (tabletop figure), 100mm (large miniature), 150–200mm (display piece).
> The Snapmaker U1 build volume is 270mm on each axis."

Use 50mm as a fallback only if the user explicitly says "you pick".

### Step 3 — Run print.sh

```bash
~/3d-pipeline/workspace/print.sh -i <path> -s <SIZE_MM>
```

Or in JSON mode for chaining:

```bash
~/3d-pipeline/workspace/print.sh -i <path> -s <SIZE_MM> --json
```

`print.sh` validates final dimensions on **every axis** post-scale. If
*any* axis exceeds 270mm, it exits with error 3 and writes NO STL,
**unless** `--allow-oversize` is passed. Pass that flag only when the
user has acknowledged they're printing in pieces or has a larger
printer in mind.

STL is the only output format by design — the Snapmaker U1's color
capability lives in Orca's paint tool, not in the mesh, so 3MF would add
complexity without unlocking new capability. Don't suggest 3MF as a
fallback when an STL doesn't slice well; fix the mesh upstream instead.

### Step 4 — Verify output and report fit

The script reports final dimensions in mm and whether the asset fits
within the 270×270×270 U1 build volume. The `--json` result has:

```json
"final_dimensions_mm": {"x": 50.0, "y": 32.4, "z": 28.9},
"fits_snapmaker_u1": true,
"oversized_axes": []
```

(There's also a `<output.stl>.print_meta.json` sidecar with the same
information; useful for the manifest update.)

### Step 5 — Guide the user into Snapmaker Orca

The pipeline produces single-mesh STL. The U1's multi-color capability is
unlocked **in the slicer**, not from mesh data:

1. Open **Snapmaker Orca**
2. **File → Import → 3D Model** → select the STL
3. To use multiple colors: select the model, click the **Paint** tool
4. Use the brushes (Sphere / Triangle / Fill / Height Range) to paint regions
5. Each painted region maps to one of the 4 toolheads with its loaded filament
6. The color reference image (saved alongside the STL) is a guide for what
   each region should look like
7. Slice and print

Mention the color reference image specifically — users often miss it exists.
**Never claim multi-color mesh output**; U1 color painting is slicer-side.

## Flow 5: Text → 2D → 3D → STL

A request for a complete printable asset authorizes [image](image.md) → [mesh](mesh.md) → STL. Show intermediate outputs as progress and continue within that scope. Still resolve an unspecified size, an explicitly requested concept review, a material ambiguity, or a cost/license limit before the dependent stage.


For printable assets, also avoid:
- Heavy overhangs (need support material)
- Thin spikes / delicate filaments (snap during printing)
- Multi-color prompts (color comes from filament in Snapmaker Orca,
  not the mesh)

If the user describes something hard to print, mention it before generating.

