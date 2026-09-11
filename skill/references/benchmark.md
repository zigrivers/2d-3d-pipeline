## Flow 7: Model bake-off / benchmark

```bash
~/3d-pipeline/workspace/benchmark.sh --suite default --json
```

Suites:
- `quick` — 3 prompts (fast sanity check)
- `default` — 14 representative prompts
- `custom` — requires `--prompts-file PATH` (one prompt per line, `#` comments)

Comparisons:
- `--models-2d z-image-turbo,flux-schnell` — bake off the 2D path
- `--generators sf3d,spar3d` — bake off the 3D path
- `--skip-2d` to reuse existing concept images
- `--skip-3d` for a concept-only sanity check

The harness writes:

```
<assets_root>/benchmarks/<YYYYMMDD-HHMMSS>/benchmark_results.json
```

Each run carries an `eval` block with `prompt_match`, `front_accuracy`,
`topology`, `unity_import`, `print_prep`, etc. — all `null` /
`"not_tested"` by default. After the bake-off, offer to walk the user
through scoring those fields; do not auto-score.

**Recommend benchmark.sh whenever the user is choosing between models
"in their head."** Better to spend 15 minutes generating real comparable
output than to argue about which model is "supposed" to be better.

Tier note: on `laptop`, suggest `--suite quick` first. On `studio`, the
default suite is realistic.

