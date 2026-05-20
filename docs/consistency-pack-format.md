# Consistency pack format

**Status:** v1 · Format defined first per v3 MMR finding (parser
implementation in P3.2c will validate against this contract).

A **consistency pack** is a directory containing everything the
ComfyUI backend needs to produce identity-locked 2D generations of a
single subject across multiple prompts / poses. Items 11 in the
pipeline improvement spec — Option A confirmed, ComfyUI as a second
2D backend behind `--backend comfyui`.

The pack is **passed by directory path**, not pickled or copied —
ComfyUI reads its contents directly. Distribution shape: a single
git-cloneable / zip-distributable folder.

## Directory layout

```
my-character/                       (pack name = directory basename)
├── pack.json                       (manifest — required)
├── pack.schema.json                (optional: schema this pack validates against)
├── references/                     (input images for IP-Adapter / ControlNet)
│   ├── identity.png                (1024x1024 PNG; IP-Adapter FaceID input)
│   ├── pose.png                    (1024x1024; ControlNet OpenPose input — optional)
│   └── canny.png                   (1024x1024; ControlNet Canny input — optional)
├── lora/                           (optional, character LoRA)
│   └── my-character.safetensors
└── README.md                       (optional, human-readable provenance)
```

The only required pieces are `pack.json` and `references/identity.png`.
Everything else is optional and toggled by the manifest.

## `pack.json` schema (v1)

```json
{
  "schema_version": 1,
  "name": "my-character",
  "description": "Hero character for Grithkin",
  "license_bucket": "commercial_threshold",
  "base_model": "sdxl-1.0",
  "negative_prompt_default": "blurry, low quality, watermark",
  "identity": {
    "model": "ip-adapter-faceid-sdxl",
    "reference": "references/identity.png",
    "weight": 0.8
  },
  "controlnets": [
    {
      "model": "controlnet-openpose-sdxl",
      "reference": "references/pose.png",
      "weight": 0.6
    }
  ],
  "lora": {
    "path": "lora/my-character.safetensors",
    "weight": 1.0
  }
}
```

### Field reference

| Field | Required | Type | Description |
|---|---|---|---|
| `schema_version` | yes | integer | Always 1 today. Bumps follow the same rules as meta.json's schema versioning (see `scripts/meta_helper.py`). |
| `name` | yes | string | Pack identity; used in manifest entries + result filenames. Should match the directory basename. |
| `description` | no | string | Human-readable summary. |
| `license_bucket` | yes | enum | The OUTPUT bucket. Today's only valid choices are `commercial_safe`, `commercial_threshold`, `non_commercial`, `source_available_restricted`, `unclear_risky`. SDXL outputs default to `commercial_threshold` (CreativeML Open RAIL-M). Override if the LoRA introduces stricter terms. |
| `base_model` | yes | enum | Currently only `sdxl-1.0`. Future packs may target other base checkpoints; the workflow file enforces which models it understands. |
| `negative_prompt_default` | no | string | Appended to every generation; the wrapper may concatenate user-supplied negatives. |
| `identity` | yes | object | IP-Adapter face / object identity reference. `model` is the IP-Adapter checkpoint name; `reference` is a path relative to the pack root; `weight` ∈ [0, 1.5]. |
| `identity.model` | yes | enum | `ip-adapter-faceid-sdxl` (default; characters with faces) or `ip-adapter-plus-sdxl` (general identity, no face landmarks). |
| `controlnets` | no | array | Zero or more ControlNet conditioners. Each entry: `{model, reference, weight}`. Common models: `controlnet-openpose-sdxl`, `controlnet-canny-sdxl`, `controlnet-depth-sdxl`. |
| `lora` | no | object | Optional character LoRA. `path` is relative to the pack root; `weight` ∈ [0, 1.5]. |

## JSON Schema (formal)

The JSON Schema at `scripts/consistency_pack_schema.json` formalises
the above for tooling (P3.2c's wrapper will validate against it
before invoking ComfyUI). When the schema evolves, follow the same
versioning practice as `meta_schema.json`: bump `schema_version`,
ship a migration registered in `scripts/meta_helper.py`-style.

## License-bucket guidance

The output license bucket of a consistency-pack generation is the
**most restrictive** of:

1. The pack's declared `license_bucket`
2. The base model's bucket (SDXL = `commercial_threshold`)
3. The LoRA's bucket (if any — packs with `unclear_risky` LoRAs
   should declare so explicitly)

The wrapper records the resolved bucket on every generation and
warns to stderr exactly like the existing mflux non_commercial
warning.

## How packs are distributed

Today: hand-built in `~/3d-pipeline/consistency-packs/`. Each pack
is a directory; users can copy / share / zip them. There's no
auto-download mechanism in v0.3.2 — the only "distribution" is
filesystem.

If the pack ships with a `pack.schema.json` (formal schema embedded
alongside the manifest), the wrapper validates against the embedded
schema first; falls back to `scripts/consistency_pack_schema.json`
otherwise. This lets future pack formats validate without requiring
the user to upgrade the pipeline.

## Example pack — Grithkin hero

```
~/3d-pipeline/consistency-packs/grithkin-hero/
├── pack.json
├── references/
│   ├── identity.png         (front-on portrait of the character)
│   └── pose.png             (OpenPose skeleton extracted from a reference)
└── lora/
    └── grithkin-hero.safetensors
```

`pack.json`:
```json
{
  "schema_version": 1,
  "name": "grithkin-hero",
  "description": "Adult male warrior, Grithkin project's hero character",
  "license_bucket": "commercial_threshold",
  "base_model": "sdxl-1.0",
  "identity": {
    "model": "ip-adapter-faceid-sdxl",
    "reference": "references/identity.png",
    "weight": 0.8
  },
  "controlnets": [
    {"model": "controlnet-openpose-sdxl", "reference": "references/pose.png", "weight": 0.6}
  ],
  "lora": {"path": "lora/grithkin-hero.safetensors", "weight": 1.0}
}
```

Generation call (P3.2c, ships next):
```bash
concept.sh "the grithkin hero swinging a sword, dramatic lighting" \
    --backend comfyui \
    --consistency-pack ~/3d-pipeline/consistency-packs/grithkin-hero
```
