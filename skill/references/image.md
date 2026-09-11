## Flow 1: Text → 2D image

Use `concept.sh` with the user's prompt. Default model is Z-Image Turbo
(commercial_safe, ~10-30s) — this default is unchanged by item 20; don't
switch it silently (principle P-A).

| Situation | Model | Why |
|---|---|---|
| Default | `z-image-turbo` | Fast, `commercial_safe`, good general quality |
| A FLUX-ecosystem LoRA is needed, or built-in instruction editing | `flux2-klein` (item 20) | Same checkpoint does generation + instruction edits; `commercial_safe` (Apache 2.0 — the FLUX.2 family's permissive exception; 9B/dev variants are NOT, don't substitute those) |
| A FLUX.1-era LoRA specifically is needed (legacy) | `flux-schnell` | `commercial_safe`; kept working, no longer the recommended LoRA path — prefer `flux2-klein` for new LoRA work |
| Prompt adherence is weak / 3/4-view compliance keeps failing on Z-Image | ~~`ernie-image`~~ **currently broken, see below** | Would be the strongest-at-release open t2i for prompt adherence; wired but non-functional pending an upstream fix |
| User accepts non-commercial output | `flux-dev` | Mention the `non_commercial` bucket explicitly |

**Z-Image Turbo's known weakness**: subjects tend to face the camera
head-on rather than at a 3/4 angle, even with the game-asset prompt
suffix. The suffix + `--judge`/`--best-of` (item 17) compensate for most
of this, but if a user keeps getting front-on results despite judge
rejections, suggest retrying with `flux2-klein` rather than just
re-rolling Z-Image seeds indefinitely — `ernie-image` would be the
other retry option but is currently broken (see below), so don't
suggest it yet.

**`ernie-image` is wired but currently non-functional** (verified live,
2026-08-12): mflux 0.18.1 (the latest release) expects a `text_encoder_2`
component that doesn't exist in either `baidu/ERNIE-Image`'s or
`baidu/ERNIE-Image-Turbo`'s actual current Hugging Face repo layout
(confirmed by listing both repos directly) — both fail identically with
`FileNotFoundError: No safetensors files found in .../text_encoder_2`.
This is an upstream mflux/HF-repo mismatch, not a pipeline bug, and not
fixable by re-wiring `concept.sh`. Don't suggest `-m ernie-image` to a
user until a newer mflux release fixes this — check `pip index versions
mflux` for a release past 0.18.1 first. The dispatch code stays in
place so no further wiring is needed once mflux does fix it.

**LoRA + FLUX.2/ERNIE**: FLUX.1 LoRAs (trained for `flux-schnell` /
`flux-dev`) are a different checkpoint architecture than `flux2-klein`
or `ernie-image` and are not interchangeable — `concept.sh` errors out
immediately with a message naming the mismatch rather than forwarding
it into a confusing mflux crash. If a user wants LoRA output on the
newer models, they need a LoRA actually trained for that model family;
there isn't a curated one in this pipeline yet.

For variations, use `-n N`. For specific names, `-o NAME`. Default output
is in `<project>/assets/concept/` or `~/3d-pipeline/workspace/concept/`.

The wrapper prints the absolute path as its last line — capture it for
chaining. If you're scripting, pass `--json` and parse the last stdout
line as JSON; `outputs[0]` is the first image.

### VLM judge + best-of-N (v0.3.5+, item 17)

`concept.sh` can score concepts against a rubric using a local VLM
(mlx-vlm + Qwen3-VL) instead of relying only on SigLIP/CLIP similarity.
The judge catches things prompt-adherence scoring misses — wrong camera
angle, cluttered background, harsh shadows — the exact failures that
later ruin image-to-3D reconstruction.

- `--judge` — score all generated variants (or the single image), write
  the ranking/verdict into meta.json's `judge` section, print it. Does
  not delete or move anything.
- `--best-of N` — generate N variants, judge them, keep the winner in
  `concept/`, move the rest to `concept/rejected/`. Implies `--judge`.

```bash
concept.sh "a treasure chest" --best-of 4
```

**Recognition signals.** Suggest `--best-of N` when the user wants "the
best one" from several tries, or has been regenerating the same concept
repeatedly hoping for a better angle/composition. Suggest plain
`--judge` when they want to see the scores but decide themselves.

**Relay the verdict in plain language**, not raw scores — see the
[quality-result translation table](mesh-quality.md#translation-map-v03-user-friendly-language). If a variant's `visible_faces` shows only one
face (e.g. `"front only"`), that's why `three_quarter_view` scored low;
mention it if the user asks why a variant lost.

**Cost.** The default judge model is the 30B-A3B MoE tier (~17 GB,
first-use download), not the smaller 8B tier — R0.3's spike found the
8B tier does not reliably catch camera-angle violations, even with an
explicit reasoning-first rubric; the 30B tier does. Mention this before
suggesting `--best-of` on a laptop with limited disk. Judge latency is
a few seconds per image after the model is loaded once.

**When NOT to suggest it:** a single one-off generation the user is
already happy with; `vlm-env` not installed and the user wants to
generate right now (offer it as a follow-up instead).

**Concept doctor (v0.6.1, `--auto-retry`).** With `--best-of N`, if the
judge rejects every variant (all below the floor), `--auto-retry` sends
the prompt plus the judge's scores to an OpenAI-compatible chat endpoint
(`$PIPELINE_PROMPT_DOCTOR_ENDPOINT`) which rewrites the prompt to target
the lowest-scoring dimensions (most commonly forcing a real 3/4 view),
then regenerates once with the rewritten prompt. Opt-in twice over: the
flag AND the endpoint must both be present, and a retry never retries
again. If the doctor endpoint is unset or fails, the run keeps the
rejected winner exactly as before.

**Remote judge endpoint (v0.6.1).** If `PIPELINE_JUDGE_ENDPOINT` is set
(or `vlm_judge.py --endpoint URL`), judge calls go to an OpenAI-compatible
vision chat server (e.g. `mlx_vlm server` on another machine) instead of
loading the model in-process — same rubric, temperature-0 sampling, and
scoring. With an endpoint set, `vlm-env` isn't required at all; an
unreachable endpoint warns and falls back to the in-process path. This is
generic wiring: nothing in the pipeline assumes any particular server
exists, and with the env var unset nothing changes. All wrappers
(`concept.sh`, `generate.sh`, `benchmark.sh`) inherit it automatically.
**Image mode only**: mesh judging (`--judge-mesh`) always runs
in-process — the served multi-image path was measured to produce
different (wrong) scores on identical inputs, so it is deliberately
never used (v0.6.2).

### Consistency mode (v0.3.2+, ComfyUI backend)

When the user needs **identity-locked** generations across multiple
prompts (multiple poses of one character, weapon-family variants, a
coherent prop set), route through ComfyUI instead of mflux:

```bash
concept.sh "the hero swinging a sword" \
    --backend comfyui \
    --consistency-pack ~/3d-pipeline/consistency-packs/grithkin-hero
```

**Recognition signals.** Use consistency mode when the user says:
- "generate multiple poses of [character]"
- "make N variants of the same [character / weapon / prop]"
- "this should look like the same [character] across all images"
- mentions a specific named character they want to keep consistent

A consistency pack is a directory containing `pack.json`, reference
images for IP-Adapter / ControlNet, and an optional LoRA. Format
spec: `docs/consistency-pack-format.md`. Users build their own packs
once per character / asset family.

**License bucket.** The pack's `pack.json` declares the bucket; the
wrapper resolves the most-restrictive of (pack-declared, base-model
default). SDXL defaults to `commercial_threshold`; an
`unclear_risky` LoRA in the pack would bump it higher. State the
resolved bucket inline (same convention as picking SPAR3D over SF3D
in Flow 2).

**Prerequisites.** ComfyUI must be installed (section 10 in both
setup guides) and running on `http://127.0.0.1:8188`. The
dispatcher fails with `comfyui_server_unreachable` if it isn't.
Tell the user to start it first:

```bash
source ~/3d-pipeline/comfyui-env/bin/activate
cd ~/3d-pipeline/ComfyUI && python main.py --port 8188
```

**Speed.** SDXL via ComfyUI is 15–30s per image vs. 5–10s for
mflux. Mention this when offering consistency mode; if the user
only needs one variant, mflux + LoRA is faster and uses less disk.

**When NOT to suggest consistency mode:**

- User has only one prompt and won't iterate on the same subject
  later — mflux is sufficient
- User explicitly wants the variation that mflux gives them
  (e.g., "8 different chest designs" — those aren't supposed to
  be the same chest)
- ComfyUI isn't installed and the user wants to start generating
  immediately — installation is 10+ GB and takes a while; offer
  mflux now and consistency mode after install

## Prompt-writing tips

For 3D-bound 2D prompts, describe:
- **Subject** with specific material/style ("ornate wooden chest with brass
  fittings" > "chest")
- **View** that captures 3D form (3/4 isometric > pure side > pure front)
- **Lighting** that's even, not dramatic
- **Background** that's clean (the default suffix handles this)
