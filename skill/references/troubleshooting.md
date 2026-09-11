## Common issues

**"Project not detected" but I'm in one.** Make sure the project root has
the right markers: Unity needs both `Assets/` and `ProjectSettings/`;
Unreal needs `Content/` and a `*.uproject` file at the root. If neither
applies, add an empty `.asset-pipeline.json` to mark it as a project.

**Wrong project detected.** User is in a nested git checkout that
contains a Unity project at its root. Solutions: (a) `--project
/correct/path` override, (b) `PROJECT_ROOT=/correct/path` env var, (c)
add `.asset-pipeline.json` to the actual intended project root (closer
matches win).

**STL output has visible artifacts.** Run Snapmaker Orca's Auto Repair as
a second pass. The Blender print prep handles 90% of cases.

**STL was rejected as oversize (exit 3).** Re-run with a smaller `-s`
value. If the user insists, pass `--allow-oversize` AFTER they
acknowledge they'll print in pieces.

**Build volume warning on a non-longest axis.** Asset is wider than tall;
suggest a smaller `-s` value or reorientation.

**Non-commercial model warning fired.** flux-dev or trellis was selected.
Confirm the user has accepted the licence restriction for THIS asset
before proceeding. Add a note to the manifest if they want to track it.

**Queue worker says malformed JSON.** A wrapper printed something to
stdout that wasn't a valid JSON object. Re-run the wrapper directly with
`--json` to debug.

