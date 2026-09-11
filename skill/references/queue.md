## Flow 8: Queue-based batch generation (studio-tier, experimental)

Studio-tier feature. **Mention "experimental" in the conversation.**

Submit:

```bash
python3 ~/3d-pipeline/workspace/queue_submit.py \
    --assets-root <root> \
    --stage image_to_3d \
    --input <image> \
    --generator sf3d \
    --polycount 3000 \
    --json
```

Worker (run on the other Studio, or as a background process):

```bash
python3 ~/3d-pipeline/workspace/queue_worker.py \
    --assets-root <root> \
    --script-dir ~/3d-pipeline/workspace \
    [--once | --max-jobs N]
```

Each job moves `pending/ → running/ → done/` (or `failed/`). The job
file is the canonical record — `cat queue/done/<uuid>.json` for the full
result including the wrapper's `--json` output.

Only suggest the queue when both Studios are available and the user has
a batch of work. For one-off generations, run the wrappers directly.

