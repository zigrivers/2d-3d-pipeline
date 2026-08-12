# Decision — Marigold-IID license bucket (gate G4)

**Status:** decided · **Decision date:** 2026-08-12 ·
**Signatory:** Ken Allred (zigrivers@gmail.com)

## Subject

[`prs-eth/marigold-iid-appearance-v1-1`](https://huggingface.co/prs-eth/marigold-iid-appearance-v1-1)
— the roughness/metallic decomposition model behind item 24's
`texture.sh --mode pbr` pass (albedo → StableDelight → Marigold-IID).

## License found

R0.6 spike (see `docs/spike-report-generation-refresh.md`): HF model
card states "License: CreativeML Open RAIL++-M License" — the same
license family as Stable Diffusion 2's model license, matching the
spec's own expectation exactly.

OpenRAIL++-M permits commercial use but carries the RAIL family's
standard **behavioral-use restrictions** (an attached use-restriction
exhibit prohibiting things like generating illegal content, exploiting
minors, generating misinformation intended to harm, etc. — the same
category of restriction already present on Marigold's own SD2 base).

## Decision

**Bucket: `commercial_safe`, with a use-restriction footnote in the
license map** (`scripts/_pipeline_lib.sh::license_bucket_for_model`).
Not `unclear_risky` and not a plain unconditional `commercial_safe` —
the restriction is real but narrow (behavioral misuse, not a
commercial-use or MAU gate like the `commercial_threshold` bucket
family), so it doesn't change how the pipeline treats the model
functionally. It changes what gets said to the user: mention the
OpenRAIL++-M behavioral restrictions inline whenever the PBR pass is
recommended, same as how `commercial_threshold` buckets get their MAU
threshold mentioned inline.

## Rationale

- Both target projects (Grithkin, GripCraft) are conventional game
  asset pipelines — nothing in their use case touches OpenRAIL++-M's
  restricted categories.
- The restriction is on *use*, not on *output ownership* or
  *commercial distribution* — shipped textures processed through this
  pass are the user's own, same as every other bucket in this pipeline.
- Treating this as `unclear_risky` (the spec's cautious default for an
  unverified license) would be strictly more conservative than the
  actual, now-verified license text supports — the same
  stronger-than-expected pattern seen at gate G3 (R2.2, Multiple-Angles
  LoRA: verified `commercial_safe` against a cautious `unclear_risky`
  default).

## Re-review triggers

- `prs-eth/marigold-iid-appearance-v1-1`'s license text changes on HF.
- The pipeline's use case expands into anything touching OpenRAIL++-M's
  restricted-use categories (none currently planned).
