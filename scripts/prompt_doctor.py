#!/usr/bin/env python3
"""v0.6.1 — prompt doctor: rewrite a failed concept prompt using judge scores.

When `concept.sh --best-of N --auto-retry` finds every variant rejected by the
VLM judge, this script sends the original prompt plus the judge's rubric scores
to an OpenAI-compatible chat endpoint (any local or remote LLM server) and
returns one rewritten prompt targeting the failures the judge named — most
commonly a missing 3/4 view (single visible face) or a cluttered background.

Opt-in and generic: requires $PIPELINE_PROMPT_DOCTOR_ENDPOINT (or --endpoint);
nothing in the pipeline assumes any particular server exists. stdlib-only.

Usage:
    prompt_doctor.py --prompt "TEXT" --scores-file judge_result.json
Prints the rewritten prompt on stdout; any failure exits non-zero with the
reason on stderr (callers treat that as "no retry").
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

ENDPOINT_ENV = "PIPELINE_PROMPT_DOCTOR_ENDPOINT"
MODEL_ENV = "PIPELINE_PROMPT_DOCTOR_MODEL"
TIMEOUT_SECONDS = int(os.environ.get("PIPELINE_PROMPT_DOCTOR_TIMEOUT", "120"))

SYSTEM = """You repair prompts for a text-to-image model that generates single-object
game-asset concept art used as input to an image-to-3D reconstruction pipeline.

The ideal image: exactly ONE subject, photographed from a 3/4 angle (two or more
faces of the object visible, meeting at a corner — never dead-on front view),
clean plain white background, even diffuse studio lighting, full subject centered.

You get the original prompt and a judge's 0-10 rubric scores for the failed
attempts. Rewrite the prompt to fix the LOWEST-scoring dimensions. Keep the
subject identical. Be concrete about camera angle when three_quarter_view was
low (e.g. "seen from a 3/4 angle showing the front and right side"). Do not
add new objects, characters, text, or scenery.

Return strict JSON, no other prose: {"prompt": "<the rewritten prompt>"}"""


def _first_served_model(endpoint: str) -> str:
    with urllib.request.urlopen(f"{endpoint}/models", timeout=10) as r:
        models = json.loads(r.read().decode()).get("data") or []
    if not models:
        raise ValueError("endpoint serves no models")
    # mlx_lm.server lists every HF-cache entry; the served model is the one
    # listed as a filesystem path. Fall back to the first entry otherwise.
    for m in models:
        if str(m.get("id", "")).startswith("/"):
            return m["id"]
    return models[0]["id"]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--prompt", required=True, help="The original (full) prompt that failed")
    p.add_argument("--scores-file", required=True,
                   help="vlm_judge.py --rank --json output file (or any JSON with judge scores)")
    p.add_argument("--endpoint", default=os.environ.get(ENDPOINT_ENV, ""),
                   help=f"OpenAI-compatible chat endpoint base URL. Default: ${ENDPOINT_ENV}")
    p.add_argument("--model", default=os.environ.get(MODEL_ENV, ""),
                   help=f"Model id to request. Default: ${MODEL_ENV}, else the endpoint's served model")
    args = p.parse_args()

    endpoint = args.endpoint.strip().rstrip("/")
    if not endpoint:
        print(f"ERROR: no endpoint (set {ENDPOINT_ENV} or --endpoint)", file=sys.stderr)
        return 2

    try:
        with open(args.scores_file) as f:
            scores = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: cannot read scores file: {e}", file=sys.stderr)
        return 2

    try:
        model = args.model or _first_served_model(endpoint)
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content":
                    f"Original prompt:\n{args.prompt}\n\n"
                    f"Judge results for the failed variants:\n{json.dumps(scores, indent=1)}"},
            ],
            "temperature": 0.4,
            "max_tokens": 300,
            # Local thinking models otherwise spend the budget in a hidden
            # reasoning channel and return no content.
            "chat_template_kwargs": {"enable_thinking": False},
        }
        req = urllib.request.Request(
            f"{endpoint}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as r:
            body = json.loads(r.read().decode("utf-8"))
        text = body["choices"][0]["message"]["content"].strip()
        data = json.loads(text[text.index("{"):text.rindex("}") + 1])
        new_prompt = str(data["prompt"]).strip()
    except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
        print(f"ERROR: prompt doctor failed against {endpoint}: {e}", file=sys.stderr)
        return 1

    if not new_prompt or new_prompt == args.prompt:
        print("ERROR: doctor returned an empty or unchanged prompt", file=sys.stderr)
        return 1

    print(new_prompt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
