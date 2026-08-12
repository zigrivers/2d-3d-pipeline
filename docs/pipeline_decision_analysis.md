# 2D-to-3D Asset Pipeline Decision Analysis Report

This document records the structured analysis and debate concerning the nine key decision points for the v0.3+ asset pipeline revision. These decisions balance technical architecture, performance, licensing risk, and game-development utility.

---

## The Panel of Experts

- **Dr. Evelyn Thorne (Lead Pipeline Architect)**: Focuses on architectural integrity, API contracts, race conditions, schema standardisation, and system maintainability.
- **Ken Allred (Lead Game Developer / User Representative)**: Represents the developer experience (DX) and user requirements for the target indie games *Grithkin* and *GripCraft*. Prioritises asset quality, execution predictability, and iteration speed.
- **Clara Vance (Legal & Compliance Counsel)**: Evaluates intellectual property risks, licensing terms (MIT, Apache 2.0, GPL, Tencent Community License), redistribution compliance, and usage thresholds.
- **Jax Mercer (Performance & Systems Engineer)**: Protects resources on hardware boundaries (Laptop vs. Studio tiers). Focuses on execution time, dependencies, virtual environment size, and cache hygiene.

---

## Debates and Verdicts

### 1. Metadata Consolidation: Single `meta.json` vs. Multiple Sidecars

* **The Core Tension**: Architectural cleanliness and concurrency safety vs. simple, independent text files.
* **The Debate**:
  * **Dr. Evelyn Thorne**: "In the v1 pipeline, we had a chaotic 'seven sidecars' approach. `clean_meta.json`, `print_meta.json`, etc., were scattered. If the cleanup and quality stages ran in parallel or near-simultaneously, we ran head-first into write conflicts. Consolidating into a single `<output>.meta.json` with a dedicated helper (`scripts/meta_helper.py`) that uses advisory file locks (`fcntl.flock` on macOS) is the only way to ensure concurrency safety. Namespacing the schema into `input`, `preprocessing`, `generation`, `cleanup`, `quality`, etc. gives us a predictable, single source of truth."
  * **Ken Allred**: "I agree that one file is cleaner for us to parse inside the game engine editor scripts. However, my worry is failure propagation. If a quality check crashes, does it wipe out the generation metadata already written? Or does the write fail entirely, leaving a corrupt JSON?"
  * **Dr. Evelyn Thorne**: "The merge helper is designed to perform field-level merges, not full-block overrides. If a stage fails or runs partially, it only merges the fields it successfully completed. The remaining sections of the JSON remain untouched. We also validate the end result against a strict JSON schema (`scripts/meta_schema.json`)."
  * **Jax Mercer**: "This is a big win for disk cleanliness. I don't want the assets directory cluttered with dozens of tiny JSON files per mesh. A single metadata file is easy to clean, archive, and parse. Let's make sure the file-locking doesn't introduce massive wait times on the laptop tier, though."
  * **Dr. Evelyn Thorne**: "It's an advisory lock using `fcntl.flock`. It holds for milliseconds during write-cycles. The performance overhead is negligible."
* **The Verdict**: **Consolidated single `<output>.meta.json` approved.** All scripts must use the `scripts/meta_helper.py` tool to write their sections under strict schemas.

---

### 2. Conditional Background Removal: Auto vs. Unconditional Default-on/off

* **The Core Tension**: Auto-processing convenience vs. processing overhead and the risk of destructive failures on complex inputs.
* **The Debate**:
  * **Ken Allred**: "Background removal is the single most important pre-processing step for image-to-3D. Without it, background gradients or shadows bleed into the mesh, causing ugly artifacts and distorted geometry. I want it on by default."
  * **Jax Mercer**: "Wait a minute, Ken. Running `rembg` takes 2 to 3 seconds on a laptop. If the user feeds in a clean studio shot that already has a uniform white background, we're wasting CPU cycles and thermal headroom. Furthermore, `rembg` is notorious for destroying thin geometries, hair, transparency, or fine details. If we run it unconditionally, we will silently ruin legitimate inputs."
  * **Dr. Evelyn Thorne**: "Jax is correct. We cannot make it a blind default-on. We must make it **conditional auto**. The pipeline should analyze the image quality first (Item 4). If the background uniformity is above 0.85, or if the input is already an RGBA image with low alpha coverage, we skip background removal entirely. If we do run it and the resulting alpha coverage falls below 5%, we flag a failure, discard the mask, and fall back to the original image."
  * **Ken Allred**: "As long as I can override it with `--bg-removal on` when the auto-detection gets it wrong, or `--bg-removal off` for sketches, I can accept a conditional default."
* **The Verdict**: **Conditional auto background removal approved.** Implement `--bg-removal {auto,on,off}` with fallback triggers when foreground coverage is lost (<5%) or unchanged (>95%).

---

### 3. Hunyuan3D-Paint Licensing: Commercial Approval vs. Risk Mitigation

* **The Core Tension**: The quality benefits of a state-of-the-art PBR texture generator vs. compliance risks under the Tencent Hunyuan Community License.
* **The Debate**:
  * **Ken Allred**: "Our games, *Grithkin* and *GripCraft*, have commercial intent. The existing texturing pipeline uses a basic upscale path. We need Hunyuan3D-Paint to generate realistic albedo, roughness, metallic, and normal maps to make these assets look premium. The quality gap is night and day."
  * **Clara Vance**: "I've reviewed the Tencent Hunyuan Community License (version 2024-11). It allows commercial use of outputs, and output ownership rests with the user. However, there is a hard threshold: if a product using the model's outputs exceeds **100 million Monthly Active Users (MAU)**, we must negotiate a separate commercial agreement with Tencent. We must also warrant that the outputs are not used for illegal content, military applications, or surveillance."
  * **Ken Allred**: "Honestly, if *Grithkin* or *GripCraft* hits 100 million MAU, that is a multi-million dollar 'problem' we will gladly pay Tencent to resolve. For an indie game, that limit is functionally infinite."
  * **Clara Vance**: "Agreed. The risk is low for our current scale. We also do not distribute the model weights ourselves; we fetch them directly from Tencent's official channels during setup, meaning we don't trigger redistribution terms. I approve this model under the `commercial_threshold` license bucket."
  * **Dr. Evelyn Thorne**: "We must ensure the wrappers reflect this. The script `scripts/texture.sh` will ungate the `--mode paint` stub and log the model's license bucket as `commercial_threshold` in the output metadata so we maintain an audit trail."
* **The Verdict**: **Hunyuan3D-Paint approved for integration.** Model classified under the `commercial_threshold` license bucket. Wrapper restrictions removed; audit trails maintained in the manifest.

---

### 4. ComfyUI 2D Backend Integration: Option A (Direct Backend) vs. Alternates

* **The Core Tension**: Multi-character visual consistency vs. complex installation footprints and environment pollution.
* **The Debate**:
  * **Ken Allred**: "Creating single assets is fine, but in game development, we need families of assets. If I generate a warrior character, I need the same character in five different poses. If I use `mflux` for each pose, the face and armor change completely. We need ComfyUI's LoRA + IP-Adapter + ControlNet setups to enforce character identity consistency."
  * **Jax Mercer**: "ComfyUI requires a massive dependency stack. It expects a different PyTorch build and version of CUDA/MPS than our standard tools. If we install it in our main environment, we will brick the pipeline. The disk footprint is also huge."
  * **Dr. Evelyn Thorne**: "That's why Option A is the correct architectural choice. We will add ComfyUI as a separate 2D backend, isolated in its own virtual environment (`comfyui-env/`). The default backend will remain `mflux`. ComfyUI will only launch if the user explicitly requests `--backend comfyui` or provides a `--consistency-pack`. We've also defined the consistency pack format in `docs/consistency-pack-format.md` first, so our parser has a clean contract to validate against."
  * **Clara Vance**: "Let's clarify ComfyUI's license. The tool itself is GPL-3.0. This restricts us if we redistribute ComfyUI source code, but the image *outputs* generated by it are not GPL-encumbered. They retain the license bucket of the model used (SDXL = `commercial_threshold`). This is legally safe for *GripCraft*."
* **The Verdict**: **Option A approved.** ComfyUI is integrated as an opt-in second backend, isolated in `~/3d-pipeline/comfyui-env/` with its own model validation.

---

### 5. Multi-View 3D Backend Selection: TRELLIS vs. OpenLRM vs. InstantMesh

* **The Core Tension**: High geometric reconstruction accuracy vs. commercial-use constraints.
* **The Debate**:
  * **Ken Allred**: "For assets with complex backsides or asymmetric features, single-image generators fail. Multi-view input is essential. I want the backend that gives the absolute best mesh quality."
  * **Clara Vance**: "Let's look at the legalities first. InstantMesh is distributed under a restrictive Tencent license, which requires separate review and carries high commercial risk. TRELLIS's code is released under a non-commercial license. OpenLRM is Apache 2.0, which is fully `commercial_safe`."
  * **Dr. Evelyn Thorne**: "We established an empirical benchmark harness in `scripts/multiview_benchmark.py` and a scoring rubric. InstantMesh was automatically disqualified (DQ) due to its license score falling below the 4.0 floor. TRELLIS scored high on geometry but is legally flagged as non-commercial (score 4.0). OpenLRM is fully commercial-safe (score 10.0) but historically has lower geometric fidelity."
  * **Ken Allred**: "If OpenLRM's quality falls below our 6.5 pass threshold, we can't use it for *Grithkin*, regardless of how safe it is. I'd rather use TRELLIS for prototyping and swap it out later, or wait for the InstantMesh review."
  * **Clara Vance**: "We cannot ship assets generated via a non-commercial backend in a paid game on Steam. We must run the benchmark. If OpenLRM fails, we must seek a commercial-safe alternative or run the InstantMesh license review parallel track if its quality is close."
* **The Verdict**: **Benchmark-driven selection.** InstantMesh is DQ'd on license. Run the benchmark harness using `multiview_benchmark.py`. If OpenLRM scores above the 6.5 threshold, it becomes the default commercial lane; if not, TRELLIS remains the non-commercial prototyping fallback while a license review is fast-tracked.

---

### 6. Turntable Preview Gating: Opt-in vs. Default-on

* **The Core Tension**: Immediate, visual quality feedback vs. processing time and thermal load.
* **The Debate**:
  * **Ken Allred**: "When I run a generation, I want to see the 3D model immediately without launching Blender or a web viewer. A turntable GIF is perfect. It lets me spot gaps, bad texturing, or holes instantly."
  * **Jax Mercer**: "Generating a 12-frame, 512x512 GIF at 8 FPS takes between 3 and 6 seconds on an Apple Silicon laptop. If we do this on every generation by default, we're adding 20-30% overhead to the total run time. The laptop heats up, and the battery drains."
  * **Dr. Evelyn Thorne**: "We have a strict cross-cutting principle: a feature can only be default-on if it is fast (<1s) and cannot degrade quality. Turntable GIF generation violates the speed rule on the laptop tier. However, generating a static, single-frame hero PNG is cheap (<0.2s)."
  * **Ken Allred**: "Can we make it tier-conditional? Keep it default-on for the Studio tier (which has the GPU/CPU headroom) and default-off (or hero-only) on the Laptop tier?"
  * **Jax Mercer**: "Yes, that works. We can use our `hardware_tier` helper in `_pipeline_lib.sh`. Laptop gets static hero PNG default with GIF as an opt-in flag; Studio gets the full GIF default-on."
* **The Verdict**: **Tier-conditional preview approved.** Laptop defaults to static hero PNG with opt-in `--preview-gif` flag. Studio defaults to full turntable GIF.

---

### 7. Watertight Mesh Verification: Warning vs. Blocking

* **The Core Tension**: Preventing printing failures and material waste vs. pipeline flexibility and slicer capabilities.
* **The Debate**:
  * **Ken Allred**: "If a mesh has holes (non-manifold edges), it is not watertight. In 3D printing, slicing a non-manifold mesh can cause the printer to fill interior spaces, print hollow walls, or crash. However, modern slicers (like Cura or Bambu Studio) are incredibly smart. They often auto-repair minor boundary edges. If the pipeline blocks export because of a 1-pixel hole, it will drive users crazy."
  * **Dr. Evelyn Thorne**: "We shouldn't block, but we must make the issue visible. If we write the watertight status to `quality.manifold.is_watertight` in the metadata, the user-facing skill can translate the jargon (e.g. '3 small gaps in the surface') and warn the user, rather than terminating the run."
  * **Jax Mercer**: "Agreed. The only thing that should block a print export is a physical dimension violation — like exceeding the Snapmaker U1's 270mm build plate. Bad geometry should just trigger a warning."
* **The Verdict**: **Warn-only policy approved.** Non-watertight meshes will proceed to print export with descriptive warnings and hole counts, rather than failing the execution.

---

### 8. CLIP Consistency Metric: Soft Signal vs. Hard Threshold

* **The Core Tension**: Objective quality gating vs. model limitations and subjective prompts.
* **The Debate**:
  * **Dr. Evelyn Thorne**: "We wanted a metric to prove the 3D model looks like the input image. Running an open_clip ViT-L/14 check comparison seemed ideal. In v1, we discussed setting a hard threshold, like CLIP similarity >= 0.80, and failing the run if it was below that."
  * **Ken Allred**: "A hard threshold is a bad idea. CLIP scores vary wildly depending on the art style, the length of the prompt, and the generator used. A stylized cartoon character might get a 0.72 but look perfect to the human eye, while a noisy, garbled mesh might get a 0.81. If the pipeline deletes my mesh because of an arbitrary score, I'll be forced to bypass the checks."
  * **Jax Mercer**: "It also adds a processing overhead to run the CLIP model. If we run it, it should be for ranking variations or suggesting improvements, not as a pass/fail gatekeeper."
  * **Dr. Evelyn Thorne**: "Agreed. We will position the CLIP score as a soft variant-ranking tool. If a user runs multiple variants, they can see the ranking. If a score is < 0.75, we output a suggestion in the skill: 'image matches your prompt: weak — consider re-generating', rather than failing the run."
* **The Verdict**: **CLIP designated as a soft signal.** Used for suggestion and variation ranking, never as a hard pass/fail barrier.

---

### 9. Environment Consolidation: Single Shared venv vs. Isolated venvs

* **The Core Tension**: Virtual environment size and disk footprint vs. dependency isolation and version conflict risks.
* **The Debate**:
  * **Jax Mercer**: "Installing separate virtual environments for rembg, CLIP, trimesh, and Pillow takes up over 15 GB of disk space on a developer's laptop due to duplicated PyTorch, Torchvision, and CUDA/MPS binaries. If we consolidate them into a single `pipeline-tools-env`, we reduce that footprint to 6 GB. That is a 9 GB savings!"
  * **Dr. Evelyn Thorne**: "Consolidation makes sense, but we must be careful with dependency hell. If `rembg` expects one version of numpy/Pillow and `open_clip_torch` expects another, they will conflict. We must lock the dependency versions in our setup guides."
  * **Jax Mercer**: "I've tested the matrix. `trimesh`, `numpy`, `scipy`, `Pillow`, `rembg[cpu]`, and `open_clip_torch` can successfully co-exist on the same PyTorch 2.x stack on both laptop (Apple Silicon MPS) and studio tiers. ComfyUI is the only exception; it is too unstable and must remain isolated."
  * **Ken Allred**: "As long as running `make verify` or `pipeline_doctor.py` checks that this shared venv is intact, this is a great change. It makes installation much easier."
* **The Verdict**: **Consolidated `pipeline-tools-env` approved.** ComfyUI remains in its own isolated `comfyui-env/`. Setup guides and CI updated accordingly.
