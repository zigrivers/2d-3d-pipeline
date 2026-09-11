## Flow 10: Edit a concept / generate camera-angle views (v0.4+)

Use `edit.sh` when the user wants to **change an existing concept image**
in place, or wants **additional camera angles** of it to feed into
Flow 9's multi-view reconstruction. Both modes call
Qwen-Image-Edit-2511 (`commercial_safe`, Apache 2.0) and always run a
DreamSim drift check afterward so a no-op or over-aggressive edit is
caught automatically instead of silently shipped.

**Trigger phrases:** "make this darker/older/mossier", "edit this
concept", "I need a side view of this", "give me more angles of this
image", "tweak the color on this".

**Instruction-edit mode** — free-text change to a concept image:

```bash
edit.sh -i concept/chest.png "make the wood darker and more weathered"
# -> concept/chest_edit1.png (auto-numbered; re-running keeps prior edits)
```

**Angle-view mode** — parametric camera rotation via the official
Multiple-Angles LoRA:

```bash
edit.sh -i concept/chest.png --angle 90,0
# -> concept/chest_090deg.png
```

`--angle H,V` takes azimuth (0=front, 90=right, 180=back, 270=left)
and elevation (-30/0/30/60) in degrees, snapped to the LoRA's real
8×4 grid — read this off the tool's own "requested X,Y -> snapped
X,Y" line, don't assume the exact number you passed was used.

> **Known limitation — tell the user before they rely on `--angle`:**
> as of mflux 0.18.1, the Multiple-Angles LoRA's diffusers-style key
> names (`transformer_blocks.N.attn.*.lora_A/B`) don't match mflux's
> internal Qwen-Image-Edit-2511 layer names, so mflux applies **zero**
> LoRA weight (confirmed live: "Applied to 0 layers (0/1680 keys
> matched)", and the output image showed no rotation at all versus
> the source). This is tracked upstream at
> github.com/filipstrand/mflux/issues/298, not something fixable from
> this repo. `edit.sh` detects the 0-key-match case itself, prints a
> loud warning, and records `angle_lora_applied: false` in the
> output's meta.json — always check that field (or watch for the
> warning) before treating an `--angle` output as a real rotated view.
> Instruction-edit mode is unaffected and fully working.

Outputs from either mode land in the same `concept/` directory as
`concept.sh`, so angle-view outputs (once the upstream LoRA gap is
fixed) are ready to feed straight into `multiview.sh`.

**Drift check:** every run prints `[edit] edit drift: 0.NNN (band)`.
`too_similar` means the edit likely had no real effect (re-run with a
stronger instruction); `too_different` means the subject may have
changed rather than just the requested attribute. `similar_but_changed`
is the expected healthy result. These bootstrap thresholds
(0.03/0.45) are uncalibrated — treat the band as a hint, not a hard
gate.

---

