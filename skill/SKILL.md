---
name: asset-pipeline
description: Generate local 2D images, 3D game assets, and printable STL files; edit concepts or process textures, compare models, reconstruct multiple views, or use the Studio job queue.
---

# Asset Pipeline

Use the local Apple Silicon pipeline for the requested asset operation.

## When to run setup

For installation, drift reconciliation, or new optional components, use
`asset-pipeline-setup` instead. Do not run its installation workflow for an
ordinary generation task.

## Select the task

Read only the selected operation guides. A complete game asset from a prompt
uses image → mesh; a printable asset adds print preparation. Show intermediate
results as progress and continue when the requested final asset already
authorizes the chain. Pause only for an explicit concept-review request,
unresolved material intent, or a next stage outside agreed cost/license limits.

| Request | Guide |
|---|---|
| Text → image, variants, LoRA, best-of, or consistent characters | [Image](references/image.md) |
| Image → game GLB, full text → 3D chain, or Blender destination | [Mesh](references/mesh.md) |
| Existing GLB → STL, or a full printable asset | [Print](references/print.md), plus image/mesh when generation is needed |
| Inspect, upscale, paint, or add PBR textures | [Texture](references/texture.md) |
| Compare generators or prompt suites | [Benchmark](references/benchmark.md) |
| Submit a two-machine batch (Studio only; experimental) | [Queue](references/queue.md) |
| Reconstruct one subject from 3+ views | [Multi-view](references/multiview.md) |
| Instruction edit or camera-angle views | [Edit](references/edit.md) |

If the requested deliverable remains unclear, ask one short question. For
example, “make a chest for my game” selects image → mesh; “make a 50mm
printable chest” selects image → mesh → print.

## Shared operating rules

- Detect hardware from `~/3d-pipeline/.config`: `hardware_tier = studio` or
  `laptop`; missing or invalid values mean `laptop`. Never infer it from hostname.
  Both tiers use the same wrappers and safe defaults; recommend the queue only
  for Studio. Read [configuration](references/configuration.md) for tier-specific
  lanes, project detection, output paths, per-project settings, or setup-doc paths.
- Let wrappers detect the project; tell the user where outputs will land.
  Clean GLBs remain canonical in `assets/clean/`, with engine copies staged
  automatically for Unity/Unreal. Outside a project, use `~/3d-pipeline/workspace/`.
- On a fresh installation, run the read-only
  `~/3d-pipeline/workspace/pipeline_doctor.py --check all` directly if accessible.
  Read [diagnostics](references/diagnostics.md) for missing components or failures.
  Ask for manual execution only when this environment cannot reach the install.
  Cache warming and heavy optional downloads are separate from read-only checks.
- When chaining or scripting, pass `--json`. Parse the wrapper's JSON on stdout;
  human-readable progress is on stderr. Use actual reported paths and metadata.
- After each generation, follow [manifest recording](references/manifest.md),
  unless the user explicitly declines tracking. Preserve provenance, license,
  hardware tier, and source-wrapper results.
- Consult [troubleshooting](references/troubleshooting.md) for a matching failure.
  Paths beginning `docs/` or `context/` in these guides refer to the maintained
  repository; installed command paths remain as written.

## License buckets

Use these exact names in conversation, manifest entries, and JSON output:

| Bucket                          | Models                                              |
| ------------------------------- | --------------------------------------------------- |
| `commercial_safe`               | z-image-turbo, flux-schnell, qwen-image, trellis2   |
| `commercial_threshold`          | sf3d, spar3d                                        |
| `non_commercial`                | flux-dev, trellis                                   |
| `source_available_restricted`   | (reserved; nothing default-mapped here yet)         |
| `unclear_risky` / `unknown`     | LoRAs and anything not explicitly tagged            |

The wrappers print a `[license] WARNING` to stderr when the user picks a
`non_commercial` model. Don't block the user — relay the warning and
proceed if they accepted the restriction.

When recommending a model outside the default lane (anything other than
z-image-turbo → SF3D → Blender), **always mention the license bucket** in
the conversation so the user is making an informed call:

> "I'll use SPAR3D this time — license bucket `commercial_threshold`, same
> as SF3D, so usable in Grithkin and GripCraft. Sound good?"

---

## When NOT to stage to engine folder

`--no-engine-stage` is the right move when:
- User is experimenting and explicitly says "don't add it to the project yet"
- User is generating placeholder/test assets they'll delete
- User wants to inspect the clean GLB in isolation before exposing it
  to their game

Otherwise, the auto-staging is what they want — assets appear in Unity
or Unreal automatically.

If you suspect the engine asset already exists, **don't** reflexively
pass `--overwrite-engine`. Let the wrapper's auto-increment do its thing
(default) or honour the user's `auto_increment_collisions=false` setting.

---

## What not to do

- Don't try to detect projects yourself — let the wrappers do it. They
  print context as their first action.
- Don't call `print.sh` on a raw, uncleaned GLB from `raw/`. Always use
  the cleaned version from `clean/`.
- Don't promise multi-color printing from the mesh alone. That's a
  slicer-side operation.
- Don't suggest non-U1 slicers unless asked.
- Don't quietly skip the size question for prints.
- Don't pass `--project` explicitly when the user is already in a project
  directory — let auto-detection do its job. Pass it only when the user
  is somewhere else (e.g., their home directory) but wants outputs in a
  specific project.
- Don't recommend the queue on the laptop tier.
- Don't silently switch to flux-dev or trellis as a default. They're
  non-commercial.
- Don't pass `--allow-oversize` without confirming the user understands
  why the model exceeded the build volume.
- Don't pass `--overwrite-engine` reflexively. Default behaviour is safer.

## Bundled resources

- `scripts/update_manifest.py` — manifest updater (v3-aware)
