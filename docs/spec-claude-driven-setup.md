# Claude-Code-driven pipeline setup — design (rev 3)

**Status:** Rev 3 — addresses two rounds of multi-model review.
Round 2 added 14 P1 and ~24 P2/P3 findings, all resolved or
explicitly deferred below. Not yet approved.
**Tracks:** v0.4 prep — converges the install path with the existing
audit path (`pipeline_doctor.py` + `model_manifest.json`).

## Problem

Today, installing the pipeline on a fresh Mac is a copy-paste exercise
out of `docs/asset-pipeline-guide{,-studio}.html`. That works, but:

1. **Two machines, two tiers.** Ken runs the pipeline on a laptop and
   on Mac Studios (potentially two). Each gets re-installed when
   something material changes; the manual flow has friction every time.
2. **No drift loop.** When canonical scripts change in this repo, the
   deployed machines don't know. The HTML guide is regenerated, but
   nobody re-pastes it. The CI workflow validates the *repo*, not the
   *deployed installs*.
3. **`pipeline_doctor.py` is read-only.** It already catalogs venvs,
   models, wrappers, and feature_sets. The catalog is the natural input
   for an installer — but no installer exists, and the `--fix` flag
   currently no-ops.

Goal: a Claude-Code-driven setup path (additive, not replacing the HTML
guide) plus an audit/fix loop that converges any deployed machine to
match the catalog in this repo.

Non-goal: replacing the HTML guide. It stays as the no-Claude
fallback.

---

## 1. Architecture

Four pieces, in three layers:

```
        ┌──────────────────────────────────────┐
        │  CATALOG  (declarative source of     │
        │  truth, lives in this repo)          │
        │  • scripts/model_manifest.json       │
        │  • tools/_embed_lib.py (EMBEDS)      │
        │  + small extensions (see §3)         │
        └──────────────────────────────────────┘
              │                       │
              │ consumed by           │ consumed by
              ▼                       ▼
   ┌─────────────────────┐   ┌──────────────────────┐
   │  ENGINE             │   │  HTML guide          │
   │  pipeline_doctor.py │   │  (existing, manual   │
   │  --check / --apply  │   │   copy-paste path —  │
   │  --only STAGE       │   │   unchanged)         │
   │  --json             │   └──────────────────────┘
   └─────────────────────┘
              │
              │ driven by
              ▼
   ┌─────────────────────────────────┐
   │  DRIVER SKILL                   │
   │  ~/.claude/skills/              │
   │     asset-pipeline-setup/       │
   │  • picks tier, runs git pull    │
   │  • walks HF auth                │
   │  • reads --check JSON, applies  │
   │  • asks before expensive steps  │
   └─────────────────────────────────┘
```

The catalog is the only thing that grows as the pipeline evolves.

### 1.1 Catalog vs EMBEDS — which is the source of truth for what

EMBEDS (`tools/_embed_lib.py`) is the canonical list of **files that
get materialized to `~/3d-pipeline/workspace/` and to the runtime
skill at `~/.claude/skills/asset-pipeline/`**. EMBEDS is already
authoritative for the HTML guide and for `make verify`. The new
installer **reuses EMBEDS verbatim**; it does not duplicate that list.

The manifest is the canonical source for **everything EMBEDS doesn't
describe**: venvs, pip packages (as lockfiles), models, prereqs,
tier defaults, studio extras.

**Files added by this design.** `scripts/_install_lib.py` (host-tool
recipes for smoke-warming) is **added to EMBEDS** because
`pipeline_doctor.py` imports it — without that addition, a no-Claude
HTML-fallback install would crash on the first `--apply --only
models`. The setup skill and launchd plist template are **not** in
EMBEDS — they're only consumed by Claude-driven installs and ship
via repo clone.

**Mutable-EMBED carve-out.** A new manifest field `mutable_embed_paths:
[<workspace path>, ...]` (default: `[]`) declares any EMBED whose
deployed copy is intentionally mutated at runtime; those paths drop
to T0 (advisory) drift instead of T1 (bytes-exact). Today the list
is empty — the workspace `model_manifest.json` is the catalog and is
not mutated; `update_manifest.py` operates on a different per-project
`asset_manifest.json`. The field exists so future runtime-mutable
EMBEDs (if any) have a clean declarative path.

**`--only scripts` vs `--only skill` partition.** `_embed_lib.py`
gains two derived constants — `EMBEDS_SCRIPTS` (entries whose
destination starts with `~/3d-pipeline/workspace/`) and
`EMBEDS_SKILL` (`~/.claude/skills/asset-pipeline/`). The engine's
`scripts` stage uses the first; `skill` uses the second. A
`--check structure` rule verifies every EMBED falls in exactly one
partition.

### 1.2 Why both an engine and a skill

| Concern                           | Engine (Python) | Skill (Claude) |
| --------------------------------- | --------------- | -------------- |
| Idempotent reconciliation         | ✓               |                |
| Runs in CI                        | ✓               |                |
| Runs without Claude Code          | ✓               |                |
| Asks "studio or laptop?"          |                 | ✓              |
| Walks `huggingface-cli login`     |                 | ✓              |
| Picks optional feature_sets       |                 | ✓              |
| Interprets failures (wheel error) |                 | ✓              |
| Targeted reapply on drift report  |                 | ✓              |

The skill is intentionally **thin**: it reads catalog metadata, calls
the engine, and interprets JSON output. Logic lives in the engine
where it is testable and CI-reachable.

---

## 2. Definition of "in sync"

`--check installed` decides drift across three tiers. `--apply` is the
inverse operation per tier.

| Tier                    | Resources                                              | Comparison                                                      | Drift means |
| ----------------------- | ------------------------------------------------------ | --------------------------------------------------------------- | ----------- |
| **T1 bytes-exact**      | scripts, runtime skill files, launchd plist, config (excluding `mutable_embed_paths`) | SHA-256 byte equality                                           | `--check installed` exits 1 |
| **T2 version-pinned**   | venvs (`pip freeze` ↔ lockfile bytes), prereq binaries | Lockfile equality (after `--exclude pip --exclude setuptools --exclude wheel`); binary `--version` within declared range | `--check installed` exits 1 |
| **T3 presence + size**  | models (literal `cache_dir/filename` or HF snapshot path per §3.5) | File exists at the declared layout; size within ±5%             | `--check installed` exits 1 |
| **T0 advisory**         | declined-optional items, `mutable_embed_paths` entries, auth-blocked models (`requires_hf_auth` true but auth absent) | recorded preference / status honoured | never fails the check |

A machine is "in sync" iff every in-scope T1/T2/T3 resource matches
the catalog. T0 is informational only.

**Limitation called out:** T3 cannot detect byte corruption that
preserves file size. A truncated-then-padded or partially-overwritten
model file the same declared size passes T3. We accept this for
lazy-managed files because the host tool (`rembg`, `huggingface_hub`)
performs its own integrity check on load. Direct-URL files with a
declared `sha256` get T1 byte equality instead. When `huggingface_hub`
exposes a per-file etag/oid (the snapshot blob hash), the engine
opportunistically promotes those to T1; this is best-effort and
documented as such.

---

## 3. Catalog extensions (manifest v2)

`scripts/model_manifest.json` bumps to `schema_version: 2`, **strictly
additive**. Concrete preservation rules, enforced by `--check
structure`:

- Every v1 field stays at its current path with its current semantics:
  `description`, `feature_sets`, `venvs[].{name,path,required,feature_set,size_gb,purpose,import_check}`,
  `models[].{id,filename,feature_set,license_bucket,size_mb,cache_dir,env_var,download_url,sha256,managed_by,notes}`,
  `wrappers`, `internal_scripts`.
- v1 readers (currently deployed `pipeline_doctor.py`) ignore unknown
  top-level keys (`tier_defaults`, `prereqs`, `studio_extras`,
  `mutable_embed_paths`) and unknown sub-keys on existing objects — no
  code change needed for read compatibility.
- **Schema-bump + CI-rule activation land in the same commit** so v1
  rules never silently disappear. Existing four `check_structure`
  rules run unconditionally; new v2-only rules are individually
  guarded inside `check_structure` by `if manifest.get("schema_version",
  1) >= 2:` blocks.

```jsonc
{
  "schema_version": 2,

  // existing keys unchanged: description, feature_sets, models,
  //                          wrappers, internal_scripts

  // -- new --
  "tier_defaults": {
    "laptop": { "include": [] },
    "studio": { "include": ["hunyuan3d-paint"] }  // illustrative; real picks set at adoption
  },

  "prereqs": [
    { "id": "python", "kind": "binary", "name": "python3",
      "min_version": "3.10", "max_version": "3.12",
      "install_hint": "brew install python@3.12",
      "max_version_severity": "warn" },        // see §3.6
    { "id": "brew",   "kind": "binary", "name": "brew",
      "install_hint": "see https://brew.sh" },
    { "id": "git",    "kind": "binary", "name": "git" },
    { "id": "huggingface-cli", "kind": "binary", "name": "huggingface-cli",
      "install_hint": "pip install huggingface_hub[cli]" }
  ],

  "venvs": [
    {
      "name": "mflux-env",
      // ...existing v1 fields...
      "python_version": "3.12",                  // major.minor
      "python_patch_pin": ".python-version",      // see §3.1
      "lockfile": "scripts/lockfiles/mflux-env.txt"
    }
  ],

  "models": [
    {
      "id": "u2net",
      // ...existing v1 fields...
      "requires_hf_auth": false,                 // see §3.2
      "hf_repo": null,                           // see §3.2/§3.5
      "storage_layout": "literal",               // "literal" | "hf_snapshot"
      "managed_by": "rembg",
      "warm_target": "u2net",                    // see §3.3
      "comfyui_kind": null                       // "checkpoint" | "ip_adapter" | "controlnet" | "lora" | null
    }
  ],

  "mutable_embed_paths": [],                     // §1.1 carve-out, default empty

  "studio_extras": {
    "queue_dirs": ["queue/pending", "queue/running",
                   "queue/done", "queue/failed"],
    "launchd_plist": {
      "label":     "com.kenallred.3dpipeline.queue-worker",   // see §3.7
      "template":  "scripts/launchd/queue-worker.plist.tmpl",
      "dest_path": "~/Library/LaunchAgents/com.kenallred.3dpipeline.queue-worker.plist",
      "optional":  true
    },
    "heartbeat_file": "queue/.heartbeat-<machine>",
    "heartbeat_max_age_seconds": 90,
    "heartbeat_write_timeout_seconds": 25       // §6.2
  }
}
```

Notes on what is **deliberately not** in the manifest:

- **Skill destinations.** The runtime skill lives in EMBEDS
  (`skill/SKILL.md` → `~/.claude/skills/asset-pipeline/SKILL.md`).
  The setup skill is repo-canonical only. The manifest does not
  declare skill destinations.
- **Per-model warm Python snippets (`warm_cmd`).** Imperative code does
  not belong in a declarative catalog. See §3.3.
- **`pip_packages` list.** Lockfiles only — see §3.1.

### 3.1 Lockfiles (T2 drift detection)

Each venv declares `lockfile: scripts/lockfiles/<venv-name>.txt`. **No
`pip_packages` field.** Lockfile-only avoids the rev-2 transient state
(both fields accepted, lockfile wins, then remove `pip_packages`).

Bootstrap workflow for adding a new venv:

1. Maintainer manually runs:
   ```
   python3 -m venv ~/3d-pipeline/<venv-name>
   source ~/3d-pipeline/<venv-name>/bin/activate
   pip install <starter packages>
   pip freeze --exclude pip --exclude setuptools --exclude wheel \
     > scripts/lockfiles/<venv-name>.txt
   ```
2. Add a venv entry to `model_manifest.json` pointing at the lockfile.
3. Commit both.

After that, `--apply --only venvs` is `pip install -r <lockfile>`,
which is reproducible. Drift detection compares
`pip freeze --exclude pip --exclude setuptools --exclude wheel`
against the lockfile bytes. The maintainer regenerates the lockfile
after deliberately bumping a package with the same one-liner.

**Python patch version pinning.** Each venv declares
`python_version: "3.12"` (major.minor) and the engine reads
`.python-version` (pyenv convention) at the venv root for the patch
version. `--apply --only venvs` refuses to proceed if the active
`python3` differs from the pinned patch — diagnostic message names
the expected version and points at `pyenv install 3.12.7` (or
equivalent). Cross-machine portability of lockfiles is the
maintainer's responsibility; the engine does **not** silently
regenerate.

CI's `--check structure` validates: every venv has a lockfile path,
the lockfile exists, parses as `pip freeze` format, and has no
`pip`/`setuptools`/`wheel` entries (which would indicate stale
generation).

### 3.2 HuggingFace auth gate — per-repo, not just whoami

Each model declares `requires_hf_auth: bool` (default `false`) and
`hf_repo: <org>/<name>` when downloads happen via huggingface_hub.

Before the `models` stage runs:

1. The engine enumerates every in-scope model with `requires_hf_auth:
   true`. For each, it calls
   `huggingface_hub.HfApi().model_info(model.hf_repo)` — this is the
   light, free, scoped check. A 401 on any specific repo aborts the
   stage with a message naming the repo and the exact
   `huggingface-cli login` (and if needed, "request access at
   `https://huggingface.co/<hf_repo>`") command.
2. `huggingface-cli whoami` is used only as an early pre-check
   ("is there any token at all?") before the per-repo checks. It is
   **not** sufficient on its own — the failure case "user is logged in
   but doesn't have access to a specific gated repo" is what motivates
   the per-repo call.

Models with `requires_hf_auth: false` skip the preflight even when HF
is the host (anonymous mirrors, public files).

The stage aborts **before any download starts**; no `.part` or
`.incomplete` files are created.

### 3.3 Smoke-warming for lazy-managed models

Models without a direct `download_url` are downloaded by their host
tool on first use (`rembg`, `open_clip`, `comfyui`,
`hunyuan3d-paint`). The engine triggers these via host-tool recipes
that live in code (`scripts/_install_lib.py`), keyed by `managed_by`
**and**, for tools with heterogeneous models, by `comfyui_kind`:

```python
# in _install_lib.py
RECIPES = {
  "rembg":   lambda model: ...,  # uses model.warm_target
  "open_clip": lambda model: ...,
  "hunyuan3d-paint": lambda model: ...,
  "comfyui": {                   # dispatched by comfyui_kind
    "checkpoint": lambda model: ...,
    "ip_adapter": lambda model: ...,
    "controlnet": lambda model: ...,
    "lora":       lambda model: ...,
  },
}
```

The manifest declares the model identifier within the tool and (for
ComfyUI) the kind:

```jsonc
{ "id": "u2net",       "managed_by": "rembg",   "warm_target": "u2net" },
{ "id": "sdxl-base",   "managed_by": "comfyui", "comfyui_kind": "checkpoint" },
{ "id": "ip-adapter-faceid-sdxl", "managed_by": "comfyui", "comfyui_kind": "ip_adapter" },
{ "id": "controlnet-openpose",    "managed_by": "comfyui", "comfyui_kind": "controlnet" }
```

Adding a new model under an existing `(managed_by, comfyui_kind)`
combination requires only a catalog edit. Adding a new `managed_by`
tool or a new `comfyui_kind` requires a recipe addition to
`_install_lib.py`. AC12 reflects this.

**Verification after warming.** A smoke command exiting 0 is
necessary but not sufficient. After every warm invocation, the
engine runs the T3 presence-and-size check per the model's
`storage_layout`. If the file is still missing or significantly
undersized, the warm result is `failed`, not `downloaded`.

### 3.4 `.install_state.json` — single role, single shape

After review, the rev-2 two-role design is collapsed to one role:
**stage outcome ledger** + **declined-optional registry**, in a
single JSON object. There is no `in_progress` flag; stages that
didn't complete simply don't have an `ok` marker and are eligible
for re-run.

```jsonc
{
  "stages": {
    "prereqs":   { "ok": true,  "ts": "...", "manifest_sha": "..." },
    "scripts":   { "ok": true,  "ts": "...", "manifest_sha": "..." },
    "venvs":     { "ok": false, "ts": "...", "error": "wheel build failed: torch" },
    // ...
  },
  "declined": {
    "studio_extras.launchd_plist": { "ts": "...", "reason": "user declined" }
  }
}
```

Rules:
- **Drift detection (`--check installed`) never reads this file** for
  T1/T2/T3 decisions. The file is metadata about prior runs, not
  about current disk state. Drift always re-reads disk.
- The `declined` map is the **only** thing that affects how
  `--check installed` reports T0 advisory items (declined-optional
  resources don't trigger drift warnings).
- An `ok: false` or missing stage entry causes the engine to log
  "previous stage incomplete; re-running" when the user invokes
  `--apply` covering that stage. The flock (§4.6) prevents
  concurrent re-runs.
- On SIGKILL/OOM, the file may be stale (an in-progress stage that
  completed but didn't write `ok`). Re-running that stage is
  idempotent (scripts/skill/config/dirs), or detected by drift
  (venvs/models/studio_extras), so staleness is self-healing.

### 3.5 Storage layouts (T3 detection)

Models declare `storage_layout: "literal" | "hf_snapshot"`:

- **`literal`** — the file lives at exactly `<cache_dir>/<filename>`.
  T3 stats that path directly. Used today by `u2net` (rembg controls
  `U2NET_HOME` to a literal directory).
- **`hf_snapshot`** — the file lives under HuggingFace's snapshot
  layout: `<cache_dir>/models--<org>--<repo>/snapshots/<commit-sha>/<filename>`
  (a symlink into `blobs/`). The engine uses
  `huggingface_hub.try_to_load_from_cache(<hf_repo>, <filename>)` or
  walks the latest snapshot directory. Used by anything downloaded
  via `huggingface_hub.hf_hub_download` (rembg's optional HF mirror,
  ComfyUI HF downloads, hunyuan3d-paint).

The manifest's `cache_dir` is interpreted as the HF cache root for
`hf_snapshot` models. The `filename` field stays useful: it's the
target file inside the snapshot.

### 3.6 Prereq version checks

`min_version` is a hard requirement (`--apply` exits 1 if not met).
`max_version` is a **warning** by default (`max_version_severity: "warn"`).
This lets Python 3.13 users install with a notice rather than a hard
block — the constraint exists because some wheels lag, not because
3.13 is forbidden. When a known incompatibility is discovered, the
maintainer sets `max_version_severity: "fail"` for that prereq.

### 3.7 Reverse-DNS namespace

This design establishes `com.kenallred.3dpipeline.*` as the launchd
label namespace for pipeline-related agents. Future agents
(heartbeat-checker, ComfyUI auto-start) reuse it.

---

## 4. Engine extensions to `pipeline_doctor.py`

Additive. All existing flags keep their behaviour.

### 4.1 New flags

```
--apply               # opposite of --check; reconciles to the catalog
--only STAGE,STAGE    # restrict --check or --apply to named stages
--yes                 # skip confirmation gates (for CI / re-runs)
--tier {laptop,studio}
                      # required when ~/3d-pipeline/.config is absent;
                      # otherwise read from .config and overridable
--reconsider-optionals
                      # opt-in; clears declined-optional state for this run
```

`--fix` becomes a deprecated alias for `--apply` (warns + forwards;
prints a notice). Removal scheduled for v0.5. Verified safe: no
script, CI workflow, or skill currently invokes `--fix`; the only
references are in `docs/improvement-spec.md` (stale planning doc,
fixed by §8) and in the HTML embed of `pipeline_doctor.py` (renders
automatically).

`--refresh-lockfiles` from rev 2 is **dropped** — lockfiles are
maintained by the manual workflow in §3.1, not by an engine flag.

`--repo-root` from rev 1 is **dropped** — the engine resolves the
repo via the script's own location.

### 4.2 Stage list with explicit prerequisites

Stages run in this order under `--apply`. `--only STAGE,...` always
runs in canonical (this) order regardless of CLI argument order.

| Stage           | Prerequisite stages | Tier-aware? | What `--apply` does                                                | Network | Drift tier(s) |
| --------------- | ------------------- | ----------- | ------------------------------------------------------------------ | ------- | ------------- |
| `prereqs`       | —                   | **no**      | Verifies python/brew/git/huggingface-cli presence + version range. Never installs. Reports hints. | no | T2 |
| `dirs`          | `prereqs`           | no          | Creates `~/3d-pipeline/{workspace,models,benchmarks}` tree.        | no      | (presence only) |
| `config`        | `prereqs`, `dirs`   | **yes**     | Writes `~/3d-pipeline/.config` with the chosen tier.               | no      | T1 |
| `scripts`       | `dirs`              | no          | Materializes every `EMBEDS_SCRIPTS` entry from the repo.           | no      | T1 |
| `skill`         | `dirs`              | no          | Materializes every `EMBEDS_SKILL` entry from the repo.             | no      | T1 |
| `venvs`         | `prereqs`, `dirs`   | no          | Creates each in-scope venv; runs `pip install -r <lockfile>`.      | yes     | T2 |
| `models`        | `venvs`             | yes (default scope) | HF-auth preflight (§3.2), warm via §3.3, T3 verify per §3.5.       | yes     | T3 (or T1 when sha256 known) |
| `studio_extras` | `dirs`, `scripts`   | **studio only** | Creates queue dirs; offers plist; configures heartbeat.            | no      | T1 + T0 |

`prereqs` is **tier-independent** by construction (the prereq list
makes no reference to tier). This resolves the rev-2 cold-start
ordering ambiguity: `prereqs` can safely run before tier is known.

`--only models` invoked without the required venvs in place
**fails fast** with: `error: stage 'models' requires stages
['venvs'] — run with --only venvs first, or drop --only.`

### 4.3 Cold-start contract

On a fresh machine where `~/3d-pipeline/.config` does not yet exist:

- `--tier` is **required** on the command line.
- The bootstrapping sequence is exactly: `--apply --tier laptop
  --only prereqs,dirs,config`, which establishes `.config`. After
  that, subsequent invocations can omit `--tier` and read from `.config`.

The skill handles this automatically; documenting it for CI and
manual users.

### 4.4 Drift detection (`--check installed`)

For each stage, runs the comparison declared in §2. Per-stage
contributions:

| Stage             | T1 items                                    | T2 items                          | T3 items |
| ----------------- | ------------------------------------------- | --------------------------------- | -------- |
| `prereqs`         | —                                           | binary presence + version range   | — |
| `config`          | `.config` SHA-256                            | —                                 | — |
| `scripts`         | every `EMBEDS_SCRIPTS` destination, SHA-256 (minus `mutable_embed_paths`) | —          | — |
| `skill`           | every `EMBEDS_SKILL` destination, SHA-256   | —                                 | — |
| `venvs`           | —                                           | filtered `pip freeze` ↔ lockfile  | — |
| `models`          | direct-URL models with declared sha256, or HF blob hashes when available | —          | lazy-managed models, file presence + size ±5% per `storage_layout` |
| `studio_extras`   | plist destination SHA-256 (if installed)    | —                                 | — |

Each drifted item carries:
- `current` and `expected` (one-line summaries)
- `fix_command`: literal CLI to run (e.g.
  `pipeline_doctor.py --apply --only scripts --target generate.sh`)
- `tier`: T1/T2/T3/T0

The skill renders the report grouped by stage, with one multi-select
prompt per stage (not per item — see §5.2).

### 4.5 Partial-failure handling for venvs

When `pip install -r <lockfile>` fails, the engine:

1. Runs `pip install --dry-run --report /tmp/pip-report.json -r <lockfile>`
   to obtain the structured failure record (stable JSON since pip
   23.1) — names the failing package without parsing stderr.
2. Records `stages.venvs.<name>` as `ok: false` in the state file
   with the failing package noted.
3. Retries **once** with `pip install --upgrade pip setuptools wheel`
   followed by the original install (the documented Apple-Silicon
   torch recipe from `UPGRADES-studio.md`).
4. On second failure, exits 1 with the failing package and the
   suggested manual command. `--check installed` sees the failed
   stage outcome and reports the venv as T2-drift.

CI structure check requires pip >= 23.1 as a prereq (added to
`prereqs`).

### 4.6 Reentrancy and lock

`--apply` takes an advisory `flock` on `~/3d-pipeline/.install.lock`
to prevent two concurrent applies on the same machine. **The lock
file must live on a local filesystem.** On startup the engine calls
`os.statvfs` on the lock path and refuses with a diagnostic if the
filesystem is recognized as network-mounted (SMB, NFS, AFP, SSHFS
via macOS `mount` output) — advisory locks on those are unreliable.

**Cross-machine queue safety** is via the heartbeat in §6.2, **not**
the lock.

Ctrl-C / SIGKILL during an apply: the lock releases on process exit.
The next apply re-runs any stage without an `ok` marker (§3.4).

### 4.7 Model downloads — resumable

The engine downloads models via two paths:

- **HuggingFace-hosted models** (any with `hf_repo` set or
  `storage_layout: "hf_snapshot"`): uses
  `huggingface_hub.hf_hub_download`, which natively supports `Range:`
  resume via `.incomplete` files, integrity check on completion, and
  the snapshot layout in §3.5.
- **Direct-URL models** (`download_url` set, `storage_layout:
  "literal"`): replace the rev-1 stdlib `urllib.request.urlopen +
  copyfileobj` flow with `requests` using `Range:` headers against
  the existing `.part` file. On size mismatch (server doesn't support
  range), falls back to restart-from-zero with a notice. After
  download, computes sha256 if declared.

This re-incorporates resume that rev 2 cut as "future work" — the
review showed the library functions make it a small change, and the
7 GB SDXL / 5 GB Hunyuan3D-Paint sizes make restart-from-zero a real
UX problem on flaky links.

### 4.8 Exit codes

- `0` — every requested stage reached `ok`.
- `1` — any T1/T2/T3 drift or any apply failure.
- `2` — usage / catalog-parse error (current convention).

---

## 5. Driver skill

New skill at `setup-skill/` in this repo, deployed to
`~/.claude/skills/asset-pipeline-setup/` (sibling of the existing
`asset-pipeline` skill — see §5.3 on naming).

The runtime skill (`skill/SKILL.md`) gains a short "When to run
setup" section pointing at `asset-pipeline-setup`, so a user already
mid-workflow can discover the audit loop without having to remember
the setup skill's name.

### 5.1 Responsibilities

1. **First-machine bootstrap** (~6–7 prompts, one time, in this order):
   - Verify this repo is cloned locally; offer to clone if not. (1)
   - Ask tier (`laptop` / `studio`). (1)
   - Run `prereqs` check; surface hints as `brew install …` commands
     the user runs themselves. **Skill does not install brew packages
     itself.** (0–1, only if hints present)
   - Ask whether to include any optional feature_sets beyond the tier
     default (`hunyuan3d-paint`, `comfyui`, `multiview`). (1)
   - If any in-scope model declares `requires_hf_auth: true`, walk
     the user through `huggingface-cli login`, then call
     `huggingface_hub.HfApi().model_info(repo)` for each gated repo.
     If any 401, surface "request access at
     `https://huggingface.co/<repo>`" before continuing. (1)
   - Confirm disk + total download volume. (1)
   - Run `--apply` end-to-end, streaming engine output. On any stage
     failure, surface the precise repair command + suspected cause.

   The bootstrap flow is acknowledged as long; it's a one-time event
   per machine, and the audit loop (much more common) is bounded to
   ≤8 prompts per §5.2.

2. **Audit loop** (rerun on any deployed machine):
   - `git -C <repo> fetch`. If `HEAD..origin/<branch>` has any
     commits, show the commit-range summary (`git log
     HEAD..origin/<branch> --oneline`) and ask before
     fast-forwarding. **Never silent-pull**, even when working tree
     is clean — this is the §7 trust-model mitigation.
   - `pipeline_doctor.py --check installed --json` against the
     freshly pulled catalog.
   - Render the drift report as a punch list with stage grouping
     (see §5.2).
   - User picks per-stage action; engine reapplies.

### 5.2 Multi-select UX

Drift items are presented grouped by stage. For each stage with
drift, one prompt:

```
scripts/ — 4 items drifted
  [1] generate.sh
  [2] print.sh
  [3] turntable_render.py
  [4] mesh_quality_check.py

Apply: (a) all  (b) selected (e.g. "1,3-4")  (s) skip
>
```

Worst case is one prompt per stage (≤8 prompts), independent of
how many items drifted. "Selected" accepts comma-separated ranges
(`1-5,8,11`). Choosing `(s) skip` on one stage proceeds cleanly to
the next stage — the audit loop never aborts on a per-stage skip
(AC9b).

The bootstrap flow (§5.1.1) is the exception: it has its own
fixed sequence (~6–7 prompts) for one-time first-install and is not
bounded by the ≤8 rule.

### 5.3 Skill naming and tracked technical debt

The existing skill at repo `skill/` (singular) is the *runtime*
skill, hot-loaded by Claude Code during pipeline work. The setup
skill is one-shot; sharing the directory would conflate two
lifecycles.

CONVENTIONS.md will be updated to document the soft exception:
`skill/` hosts the runtime skill; `setup-skill/` hosts the setup
skill.

**Tracked debt:** v0.5 includes renaming `skill/` → `skills/runtime/`
and `setup-skill/` → `skills/setup/`, updating EMBEDS, GUIDE_PATHS,
and all install docs. This is recorded explicitly so the exception
doesn't quietly become a new precedent.

### 5.4 What the skill is NOT

- Not a substitute for `huggingface-cli login`. That stays manual.
- Not a brew installer. Reports hints, never `brew install`s.
- Not a SMB mounter. Verifies the mount; user wires it.
- Not a release manager.

---

## 6. Multi-machine studio specifics

The original problem statement (§Problem item 1) names "Mac Studios
(potentially two)" as a stated target — heartbeat-based liveness
earns its place against that target.

| Concern                | Approach |
| ---------------------- | -------- |
| Two studios, same repo | Each studio has its own clone at a known path. `git pull` is per-machine. |
| Shared workspace       | User mounts SMB / NAS at `~/3d-pipeline/workspace`. Skill verifies the mount before queue ops. |
| Tier declaration       | `~/3d-pipeline/.config` records `hardware_tier=studio`. Scripts already read this — no runtime change. |
| Worker autostart       | `studio_extras` stage offers (does not force) a launchd plist; templated from `scripts/launchd/queue-worker.plist.tmpl`. |

### 6.1 Queue write-safety

The skill never modifies `queue/running/` on a machine where the
worker is not the local machine — uses the existing `machine` field
in queue JSONs (`UPGRADES-studio.md` already requires it).

### 6.2 Worker liveness via heartbeat

`mtime` on `queue/running/<job>.json` is **not** a liveness probe; it
is the existing stuck-job reclaim heuristic. The setup skill must
not conflate the two.

This design adds a real heartbeat: when the worker is running, it
writes `queue/.heartbeat-<machine>` every 30s with an ISO timestamp.

**Heartbeat write protocol** (handles slow SMB):

1. Write to a local temp file (`/tmp/heartbeat-<machine>.tmp`).
2. Atomically rename onto the shared path.
3. Wrap step 2 in a watchdog with `heartbeat_write_timeout_seconds`
   (default 25s, declared in the manifest — strictly less than
   `heartbeat_max_age_seconds / 3` to avoid races).
4. On timeout, log and re-try next cycle. Multiple consecutive
   timeouts mark the worker `degraded` in its own log; the skill
   prints this as a warning during `--check installed`.

The skill's "is a foreign worker alive?" check is:
`now() - parse(read(queue/.heartbeat-<machine>)) < heartbeat_max_age_seconds`.

**`queue_worker.py` changes (no longer "small"):**

- Add a per-poll heartbeat write inserted at every continue-point in
  the main loop (currently `scripts/queue_worker.py:300-364`, three
  insertion sites: pending-empty sleep, job-claimed continue, job-failed
  continue).
- Wrap each heartbeat write in the temp-file + rename + timeout
  protocol above.
- Honour `--dry-run` for the heartbeat (skip writes when set).

The heartbeat does not replace the mtime-based reclaim in
`queue_worker.py`'s job recovery — those serve different purposes
(stuck-job recovery vs. cross-machine safety).

---

## 7. Security / trust model

The catalog repo is trusted. The setup skill must **not** silently
fast-forward `git pull` — instead it shows `git log
HEAD..origin/<branch> --oneline` and asks before pulling (§5.1.2).
This is a cheap, useful guard against the realistic threat
(compromised GitHub token, account takeover) without adding real
process burden.

The design assumes single-author use. If the repo is ever shared with
contributors, revisit (require signed commits, gate `--apply` behind
manual commit-range review, etc.).

---

## 8. What changes in this repo

| Change | File / location |
| ------ | --------------- |
| Schema bump + new fields (`tier_defaults`, `prereqs`, `studio_extras`, `mutable_embed_paths`, per-model `requires_hf_auth`/`hf_repo`/`storage_layout`/`warm_target`/`comfyui_kind`, per-venv `lockfile`/`python_version`) | `scripts/model_manifest.json` |
| Per-venv lockfiles | new `scripts/lockfiles/<name>.txt` (one per venv) |
| `--apply`, `--only`, `--yes`, `--tier`, `--check installed`, `--reconsider-optionals`, HF preflight, JSON-based pip failure parsing, lock + reentrancy, resumable HF + Range downloads, exit codes | `scripts/pipeline_doctor.py` |
| Smoke-warming recipes per `managed_by` (and `comfyui_kind`) | new `scripts/_install_lib.py` |
| **Added to EMBEDS** (needed by HTML fallback) | `scripts/_install_lib.py` → `~/3d-pipeline/workspace/_install_lib.py` (entry in `tools/_embed_lib.py`) |
| `EMBEDS_SCRIPTS` / `EMBEDS_SKILL` partition constants | `tools/_embed_lib.py` |
| Launchd plist template | new `scripts/launchd/queue-worker.plist.tmpl` (not in EMBEDS) |
| Heartbeat write on poll cycle (temp + rename + timeout) | `scripts/queue_worker.py` |
| Setup skill | new `setup-skill/SKILL.md` + scripts (not in EMBEDS) |
| Runtime skill — add "When to run setup" section | `skill/SKILL.md` (HTML embed regenerates via `make regenerate`) |
| `--check structure` extended for v2 schema rules (individually `schema_version >= 2`-gated) | `scripts/pipeline_doctor.py` |
| CI workflow — **no change required**; v2 rules ride the existing `--check structure --json` invocation | (none) |
| Install-via-Claude doc — **single file**, with a studio-extras subsection (tier handled at runtime by the skill) | new `docs/setup-via-claude.md` |
| v0.4 delta entry in tier change logs | `docs/UPGRADES-laptop.md`, `docs/UPGRADES-studio.md` |
| Naming-exception note + tracked v0.5 plural rename | `CONVENTIONS.md` |
| Stale `--fix` references → `--apply` | `docs/improvement-spec.md` (lines 986, 1013, 1099, 1129) |

Note: the dual-docs rule (CONVENTIONS.md) exists where tier content
genuinely differs. The Claude-driven flow is identical across tiers
(the skill reads `.config`); a single `setup-via-claude.md` respects
the spirit better than blind duplication. The tier-specific section
inside it covers studio_extras.

---

## 9. Out of scope (explicit)

- Replacing the HTML guide.
- Auto-installing brew, Python, or Xcode CLT.
- Mounting SMB shares or configuring NAS.
- Managing HuggingFace tokens or auth flows beyond verification.
- Cross-machine state synchronization (each clone is independent).
- Sandboxing scripts pulled from the repo (see §7).
- A web UI or status dashboard.
- Plural-`skills/` repo refactor (tracked for v0.5, §5.3).
- Custom resume logic for non-HF, non-Range-capable servers (the
  fallback to restart-from-zero is documented behaviour, §4.7).
- Detecting byte corruption in lazy-managed model files (§2 limitation).

---

## 10. Open questions — closed

| # | Question | Resolution |
| - | -------- | ---------- |
| 1 | Schema v1→v2 — required or optional new fields? | **Optional with sensible defaults.** §3 freezes preservation rules. Schema bump + CI activation in same commit. |
| 2 | Skill location — sibling vs sub-skill? | **Sibling.** §5.3. Tracked v0.5 plural rename. |
| 3 | Lock on `--apply`? | **Yes, local-only `flock`.** Scope explicitly excludes SMB; engine refuses to lock on network FS. Cross-machine safety is via §6.2 heartbeat. |
| 4 | Two-studio drift coordination | **Closed by §6.1 + §6.2.** The shared SMB workspace is the only cross-machine surface; the heartbeat-based liveness check + `machine`-field write guard make `--apply` safe to run on either studio without coordination. |

---

## 11. Acceptance criteria

- [ ] **AC1 — scripts idempotency.** `pipeline_doctor.py --apply --only scripts`
      on a fresh `~/3d-pipeline` installs every `EMBEDS_SCRIPTS` file
      and exits 0. A second run is a no-op (no mtime changes).
- [ ] **AC2 — bytes-exact drift.** Mutating one byte in a deployed
      script causes `--check installed --json` to flag it with a
      `fix_command` whose execution restores byte equality.
- [ ] **AC3 — venv lockfile drift, cross-Python-patch.** `--apply
      --only venvs` against a committed lockfile on the pinned
      Python patch produces a venv whose
      `pip freeze --exclude pip --exclude setuptools --exclude wheel`
      equals the lockfile bytes. A Python patch bump on the same
      machine surfaces a clear "regenerate lockfile" diagnostic
      rather than silently passing or failing T2.
- [ ] **AC4 — HF-auth preflight catches per-repo access denial.**
      With a token that has no access to `<gated_repo>`,
      `--apply --only models` (in-scope including that repo) exits 1
      **before any download starts**, names the repo, and points at
      "request access at `https://huggingface.co/<repo>`". No `.part`
      / `.incomplete` files left behind.
- [ ] **AC5 — stage prerequisite enforcement.** `--apply --only models`
      with no venvs present exits 1 with the message
      `requires stages ['venvs']`.
- [ ] **AC6 — smoke-warm verification.** A mocked host tool that
      exits 0 without producing the declared file causes the model's
      warm result to be `failed`, not `downloaded`. Test runs in CI
      with a stubbed `_install_lib.py` recipe.
- [ ] **AC7 — partial venv handling.** A `pip install` failure
      midway through a lockfile's packages produces a structured
      report parsing the pip JSON output (not stderr); state file
      records `ok: false`; next `--check installed` reports T2
      drift; next `--apply --only venvs` resumes cleanly via the
      pip-setuptools-wheel auto-retry.
- [ ] **AC8 — studio extras opt-out is sticky.** Declining the
      launchd plist records the decline in state; subsequent
      `--check installed` runs do not flag it as drift. Running
      `--apply --reconsider-optionals` re-offers it.
- [ ] **AC9 — multi-select UX prompt count.** With 30 drift items
      across 4 stages, the audit-loop flow asks at most 4 prompts.
- [ ] **AC9b — per-stage skip doesn't abort.** Choosing skip on any
      one stage advances the audit loop to the next stage without
      exiting.
- [ ] **AC10 — heartbeat liveness, unit-tested.** A unit test with
      mocked `time.time()` and a tmpdir queue verifies:
      (a) heartbeat written within `heartbeat_max_age_seconds` →
      reported alive; (b) heartbeat older than max age → reported
      dead; (c) heartbeat write timeout (file ops mocked to block
      past `heartbeat_write_timeout_seconds`) → degraded warning
      logged, worker proceeds.
- [ ] **AC11 — CI v2 schema validation.** `pipeline_doctor.py
      --check structure` against a malformed v2 manifest (missing
      `lockfile` field, lockfile has `pip` entry, unknown
      `tier_defaults` key, unknown `comfyui_kind`, etc.) exits 1
      with a specific finding per violation. v1 manifests still
      pass cleanly.
- [ ] **AC12 — zero-engine-code-for-new-model (scoped).** Adding a
      new model entry under an existing `(managed_by, comfyui_kind)`
      combination where the model uses the same `cache_dir`,
      `env_var`, and `storage_layout` as siblings requires only
      `model_manifest.json` and (if `requires_hf_auth: true`)
      lockfile/cache prep. No changes to `pipeline_doctor.py` or
      `_install_lib.py`. New `managed_by` tools or new
      `comfyui_kind` values are out of scope of this AC.
- [ ] **AC13 — cold-start contract.** `--apply` on a machine with no
      `~/3d-pipeline/.config` and no `--tier` exits 1 with the
      required-flag message. `--apply --tier laptop --only prereqs,dirs,config`
      then succeeds and writes `.config`.
- [ ] **AC14 — concurrent-apply lock + network-FS refusal.** Two
      `--apply` invocations on the same machine: the second exits 1
      with "already running". Running `--apply` with the lock file
      on a network-mounted path (`statvfs` detection) exits 1 with
      a diagnostic naming the FS type.
- [ ] **AC15 — EMBEDS partition invariant.** `--check structure`
      fails if any file under `setup-skill/` appears in EMBEDS, or
      if any EMBED's destination doesn't fall under `EMBEDS_SCRIPTS`
      or `EMBEDS_SKILL`'s declared prefixes.
- [ ] **AC16 — resumable HF download.** Killing `--apply --only
      models` mid-download (HF-hosted model) leaves an `.incomplete`
      file; re-running resumes from the byte offset (`hf_hub_download`
      behaviour). For a direct-URL model on a server that supports
      `Range:`, same behaviour via `.part` + Range. For a server that
      doesn't, the engine restarts from zero with a notice.
- [ ] **AC17 — git-pull commit-range gate.** With local clone behind
      origin by N commits, the skill shows `git log HEAD..origin
      --oneline` output and waits for confirmation before
      fast-forwarding. With local clone in sync, no prompt.

**Removed from rev 2:** the `under 30 minutes` wall-clock AC
(unmeasurable without fixed bench).
**Re-added from rev 1 (re-scoped):** resume-mid-download is in scope
via library functions (`huggingface_hub.hf_hub_download`, `requests`
+ `Range:`). The rev-2 future-work cut was reversed after review
showed the 7 GB SDXL / 5 GB Hunyuan3D-Paint cases make restart-from-zero
a real UX problem and the library functions make resume cheap.
