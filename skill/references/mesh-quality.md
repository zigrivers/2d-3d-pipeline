### Mesh judge (v0.3.6+, item 18)

`generate.sh --judge-mesh` renders a turntable (default 8 views,
independent of `--preview`) of the cleaned GLB and scores it with the
same local VLM judge as Flow 1's concept judge: recognizable-as-object,
back-face plausibility, geometry artifacts (slivers/holes/floaters),
and texture coherence. It catches "bad but valid" meshes that heuristic
checks miss — a mesh can pass every structural check and still look
wrong to a person.

```bash
generate.sh -i concept/chest.png --judge-mesh
```

**Warn, don't block.** A below-floor verdict (default <2/10) flags the
asset as "likely degenerate — regenerate recommended" in meta.json and
the console output. It never fails the run — the GLB is still produced
and staged normally.

**Recognition signals.** Suggest `--judge-mesh` when the user is about
to commit an asset to their project and wants a sanity check, or has
seen degenerate output from this generator/prompt combination before.
Skip it for quick iteration passes where they'll eyeball the result
themselves anyway.

**Relay findings in plain language.** If `judge.mesh.notes` names a
specific artifact (e.g. "2 floating fragments near the base"), say
that — not the raw score. If `cleanup.loose_elements_deleted` is
non-zero, mention that cleanup already removed some loose geometry
before the judge ran, so a floater note may be describing something
already partly addressed.

**When NOT to suggest it:** `vlm-env` not installed; the user is mid
rapid-iteration and doesn't want the extra render+judge latency (a few
seconds of render plus judge time on top of the normal pipeline).

### Translation map (v0.3+ user-friendly language)

The wrappers and Claude both speak engine-jargon natively, but the
user does not. When relaying quality-check output, translate via
this table (cross-cutting principle 8 from improvement-spec.md):

| Engine term | User-facing translation |
|---|---|
| "non-manifold edge" / "boundary edge" | "small gap in the surface" |
| "is_watertight=true" | "fully sealed (good for printing)" |
| "is_watertight=false, hole_count=N" | "N small gap(s) in the surface — may still print" |
| "UV island" | "texture patch" |
| "decimate ratio 0.16" | "simplified mesh: 18,400 → 3,000 polygons" |
| "alpha_mean 0.42" | "subject takes up about 42% of the image" |
| "SigLIP similarity 0.16, band p50_or_better" | "image matches your prompt: very good" |
| "SigLIP similarity 0.04, band below_p10" | "image matches your prompt: weak — consider re-generating" |
| "non-manifold internal shell" | "hidden geometry inside the mesh" |
| "wall thickness 0.4mm" | "thinnest part is 0.4mm — may fail to print" |
| "extreme_aspect_ratio" | "image is unusually wide/tall — output mesh will be distorted" |
| "low_resolution" | "image is below 512px — output quality will suffer" |
| "image_reward 1.6" | "people-preference score: strong (ImageReward typically ranges roughly -2 to +2)" |
| "image_reward -0.3" | "people-preference score: weak — the image is technically on-prompt but doesn't look great" |
| "dreamsim_dupes: [[1, 3]]" | "variants 2 and 4 look like near-duplicates" |
| "dreamsim_dupes: []" | "all variants are visually distinct" |
| "judge.verdict 9, three_quarter_view 9" | "judge picked this one — good angle, clean composition (9/10)" |
| "judge.verdict 5, three_quarter_view 3, visible_faces: front only" | "judge flagged this — shot straight-on, no side visible, may hurt the 3D reconstruction" |
| "judge.rejected: true" | "judge thinks this one is likely unusable — consider regenerating" |
| "judge.mesh.verdict 8, geometry_artifacts 9" | "3D check: looks solid — clean geometry, recognizable shape (8/10)" |
| "judge.mesh.rejected: true, notes: '2 floating fragments...'" | "3D check flagged this one — 2 floating fragments near the base, likely worth regenerating" |
| "judge.mesh.scores.texture_coherence: null" | "mesh has no texture yet, so the judge only checked geometry" |

When a check emits a raw value (in `--json` mode), translate before
speaking to the user. The wrapper already pre-translates some lines
for stderr (`[pipeline] Mesh: fully sealed (good for printing)`),
but if you're reading meta.json directly, do the translation here.

### Mesh quality check (v0.3+)

After cleanup, the wrapper runs a watertight + scale sanity check
on the cleaned GLB. Output looks like:

```
[pipeline] Mesh: fully sealed (good for printing) — 0 holes
```

Or when problems:

```
[pipeline] Mesh: 3 small gap(s) in the surface (may still print)
[pipeline] Scale: ⚠ longest dim 0.0008 is outside the sane normalized range
```

Skill behaviour:

- `is_watertight=false` + low hole count (1–3) → mention to the user;
  print may still work via Orca's Auto Repair
- High hole count (> 10) → strongly recommend re-generation
- `scale.in_sane_range=false` → almost always a generator bug; offer
  to re-generate with a different seed

### Cleanup report (v0.3+)

After `clean_asset.py` runs (always — it's in v0.2), the wrapper now
emits a one-line summary if the meta.json has a `cleanup` section:

```
[pipeline] Cleanup: removed 47 duplicate points, filled 2 small gap(s),
                    simplified mesh: 18,400 → 3,000 polygons
```

Use this as a signal of generator output quality. Heuristics:

- `holes_filled > 5` or `duplicate_vertices_removed > 1,000` →
  raw mesh was poor; mention this to the user before they commit
  the asset to their project (re-generation often helps)
- `decimate ratio < 0.05` → raw mesh was extremely dense; current
  generator settings may be overkill; suggest a higher polycount
  target if the user wants more detail
- All counts ≈ 0 → raw mesh was already clean; nothing to flag

For prints (Flow 4 / 5): higher cleanup counts correlate with
slicer trouble. Worth surfacing when the destination is a printer.

### LOD chain + UV re-unwrap (v0.4+, item 23)

```bash
generate.sh -i concept/chest.png --lods "3000,1000,300"
generate.sh -i concept/chest.png --reuv
```

**`--lods "N,N,N"`** (descending target polycounts) emits
`clean/<name>_lod{0,1,2}.glb` via `gltfpack`, plus runs a gltfpack
optimize pass (no quantization) on the base clean GLB itself. Engine
staging copies the whole LOD set alongside the main GLB when
applicable, same `_lod0`/`_lod1`/... suffix.

**Real finding worth relaying to the user:** gltfpack's default
quality cap (`-se`, 1% max deviation) means the *actual* resulting
polycount can land well above the target, especially for aggressive
reductions — `generate.sh` uses `-sa` (aggressive) to get closer, but
still won't hit the exact number. Each `cleanup.lods[]` entry in
meta.json records both `polycount` (actual) and `polycount_target`
(requested) — check both, don't assume they match. Requires
`gltfpack` on PATH; **no Homebrew formula exists** — it's a prebuilt
binary from
[meshoptimizer's GitHub Releases](https://github.com/zeux/meshoptimizer/releases).
`--lods` fails clearly (`status=error error=not_installed`) rather
than silently skipping when missing.

**`--reuv`** re-unwraps UVs from scratch via `xatlas` when item 13's
UV check (`quality.uv.occupancy_ratio`) reports low occupancy
(< 40%) or a high island count. **Warn-suggested, never automatic**
— only run it when the user asks or you've flagged low occupancy and
they agree.

**Hard refusal, not just a warning:** `generate.sh` checks
`quality.textures.textures_present` (already computed by the quality
checks that run before this) and refuses with
`status=error error=already_textured` if the mesh already has baked
textures — re-unwrapping would invalidate them. `--reuv` is only for
untextured meshes (vertex-color-only output, or before a
`texture.sh --mode paint` pass — same "before paint" rule as item
19's paint-mode refusal). Relay the refusal message; don't retry.

**Known ceiling:** the re-unwrapped mesh does not preserve vertex
colors if the input had them (`cleanup.reuv.vertex_colors_discarded`
in meta.json) — reuv's own worldview is "about to be freshly
textured," not "the vertex colors are the final look."

### Quad retopo — QuadWild bi-MDF (v0.4+, item 25)

```bash
generate.sh -i concept/chest.png --retopo quad
generate.sh -i concept/chest.png --retopo quad --retopo-timeout 300
```

Opt-in, replaces the mesh's decimated tri-soup topology with a
quad-dominant retopology via [QuadWild bi-MDF](https://github.com/cgg-bern/quadwild-bimdf)
(`quadwild` + `quad_from_patches`, both required on PATH — GPL-3 CLI,
`commercial_safe` bucket: tool-side copyleft only, no shipped weights,
generated GLB outputs unaffected). Suggest it for assets headed to
sculpt, animation, or close-up — not for background props, where the
default decimated mesh is fine.

**Same "before paint, never after" ordering rule as item 23.** Hard
refusal (not a warning) on an already-textured mesh — retopo discards
topology and any UV layout unconditionally. Same
`quality.textures.textures_present`-based refusal mechanism as
`--reuv` and paint mode. **In practice this means SF3D's own output
already has baked textures at generation time**, so `--retopo` refuses
immediately after a default SF3D run — it needs an untextured
mesh, same constraint `--reuv` already has. Relay the refusal
message; don't retry.

QuadWild's own output OBJ carries no UV data at all (verified by
inspection — zero `vt` lines), so run `--reuv` right after a
successful `--retopo quad` to give the new topology a UV layout before
any texture pass.

**Real finding worth relaying to the user:** `quad_from_patches`'s
exit code is not a reliable success/failure signal on its own —
`retopo_quad.py` checks for the actual expected output file instead.
Records `cleanup.retopo: {method, faces_before, faces_after,
quad_fraction, watertight}` in meta.json.

**Timeout:** pathological input meshes can hang the solver — each of
QuadWild's two steps (prep/remesh, then quadrangulation) is killed
after `--retopo-timeout` seconds (default 600) and reported as
`status=error stage=retopo error=timeout`. Requires both `quadwild`
and `quad_from_patches` on PATH; **no Homebrew formula exists** — both
binaries ship together in the prebuilt
[macOS release zip](https://github.com/cgg-bern/quadwild-bimdf/releases)
(arm64+x86_64 universal). `--retopo` fails clearly
(`status=error error=not_installed`) rather than silently skipping
when missing.

