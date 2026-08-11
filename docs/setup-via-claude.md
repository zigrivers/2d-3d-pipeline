# Setup via Claude Code

A walkthrough of installing the pipeline on a fresh Mac (laptop or studio
tier) using the `asset-pipeline-setup` Claude Code skill. The alternative
copy-paste install via [`asset-pipeline-guide.html`](asset-pipeline-guide.html)
remains supported.

## Prerequisites

The skill verifies these but won't install them. On a fresh machine,
install in this order:

- **Homebrew** (`https://brew.sh`)
- **Python 3.12** (`brew install python@3.12`)
- **git** (ships with Xcode Command Line Tools; `xcode-select --install`)
- **huggingface-cli** (`pip install huggingface_hub[cli]`)
- **pip ≥ 23.1** (`python3 -m pip install --upgrade pip`)

## First install

Clone the catalog repo somewhere stable:

```sh
git clone https://github.com/<user>/2d-3d-pipeline ~/dev/2d-3d-pipeline
cd ~/dev/2d-3d-pipeline
```

In Claude Code, invoke the setup skill:

> Run the asset-pipeline-setup skill.

The skill will:

1. Confirm the repo path.
2. Ask whether this machine is **laptop** or **studio** tier.
3. Run `pipeline_doctor.py --apply --only prereqs` and surface any
   missing binaries.
4. Ask which optional feature_sets to include
   (`hunyuan3d-paint`, `comfyui`, `multiview`).
5. If any selected model requires HuggingFace authentication, walk
   you through `huggingface-cli login` and verify per-repo access.
6. Show disk + download estimates; ask before proceeding.
7. Run `pipeline_doctor.py --apply --tier <tier> --yes` end-to-end.

Typical bootstrap time on a laptop with broadband: ~15–30 minutes
plus model downloads.

## Audit / re-sync after repo updates

When the catalog repo gains new scripts, models, or venvs, re-invoke the
setup skill on each deployed machine:

> Run the asset-pipeline-setup audit loop.

The skill will:

1. `git fetch` the catalog repo; show the commit range and **ask
   before pulling** (no silent fast-forward).
2. Run `pipeline_doctor.py --check installed --json` against the
   freshly pulled catalog.
3. Render a stage-grouped drift report. For each stage with drift,
   ask one multi-select prompt (`a` for all, comma ranges, or `s`
   to skip the stage). Worst case is one prompt per stage (≤8).
4. For each user choice, run the engine's suggested `fix_command`.

## Studio tier — multi-machine specifics

The studio tier supports two machines sharing an SMB-mounted workspace.
Before the skill applies the `studio_extras` stage:

- The shared store must be mounted. The skill verifies the mount; it
  does not mount it for you.
- If a worker is running on the *other* studio (heartbeat in
  `<workspace>/queue/.heartbeat-<machine>` younger than 90 seconds),
  the skill refuses to touch the shared queue directory until you
  confirm.
- The launchd plist for auto-starting the worker is **opt-in**.
  Declining is sticky — the audit loop won't re-prompt until you run
  `pipeline_doctor.py --apply --only studio_extras --reconsider-optionals`.

## Troubleshooting

Most failures surface a `fix_command` from the engine. Re-run that
command and re-invoke the audit loop. Common cases:

- **Wheel build failure on Apple Silicon** (torch/onnxruntime): the
  engine auto-retries after `pip install --upgrade pip setuptools wheel`.
  If the second attempt also fails, the engine prints the failing
  package; install it manually from the venv and re-run.
- **HuggingFace 401 on a gated repo:** the engine names the repo and
  the access URL. Click through, request access, then re-run.
- **Killed download:** HF downloads use `huggingface_hub` native resume;
  direct-URL downloads use a `.part` file with `Range:` headers.
  Re-running `--apply --only models` continues from the byte offset.

For non-Claude installs, the [HTML guide](asset-pipeline-guide.html)
remains the canonical copy-paste fallback. Both consume the same catalog.
