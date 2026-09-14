"""The wrappers must record their own runs, and accept every generator.

Two bugs motivated this:

1. The manifest depended on the calling agent remembering to run
   update_manifest.py by hand. In practice that was skipped, and
   asset_manifest.json was never written at all — the pipeline kept no run
   history despite every wrapper reporting a manifest_path.
2. update_manifest.py's generator enum went stale. trellis2, flux2-klein and
   ernie-image shipped in the wrappers but were rejected here, so recording a
   TRELLIS.2 run would have failed even once step 1 was fixed.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
UPDATER = REPO / "skill" / "scripts" / "update_manifest.py"

_spec = importlib.util.spec_from_file_location("update_manifest", UPDATER)
um = importlib.util.module_from_spec(_spec)
sys.modules["update_manifest"] = um
_spec.loader.exec_module(um)


# Every generator the wrappers can actually emit.
WRAPPER_GENERATORS_2D = ["z-image-turbo", "flux-schnell", "flux-dev",
                         "qwen-image", "flux2-klein", "ernie-image"]
WRAPPER_GENERATORS_3D = ["sf3d", "spar3d", "trellis", "trellis2"]


@pytest.mark.parametrize("generator", WRAPPER_GENERATORS_2D)
def test_2d_generators_are_known(generator):
    assert generator in um.GENERATOR_2D
    assert generator in um.GENERATORS


@pytest.mark.parametrize("generator", WRAPPER_GENERATORS_3D)
def test_3d_generators_are_known(generator):
    assert generator in um.GENERATOR_3D
    assert generator in um.GENERATORS


def test_generator_sets_do_not_overlap():
    assert um.GENERATOR_2D & um.GENERATOR_3D == set()


@pytest.mark.parametrize("generator", WRAPPER_GENERATORS_2D + WRAPPER_GENERATORS_3D)
def test_updater_accepts_every_wrapper_generator(generator, tmp_path):
    """The stale enum made this fail for trellis2 specifically."""
    manifest = tmp_path / "asset_manifest.json"
    result = subprocess.run(
        [sys.executable, str(UPDATER), "--manifest", str(manifest),
         "--name", "probe", "--concept", "/tmp/probe.png",
         "--generator", generator, "--category", "prop"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert manifest.exists()


# --- wrappers must call the recorder -----------------------------------
# Running a wrapper needs Blender and the model venvs, which CI has not got,
# so these assert on the source.

LIB = (REPO / "scripts" / "_pipeline_lib.sh").read_text()


@pytest.mark.parametrize("wrapper", ["concept.sh", "generate.sh"])
def test_wrapper_records_its_run(wrapper):
    source = (REPO / "scripts" / wrapper).read_text()
    assert "record_manifest \\" in source, f"{wrapper} does not record its run"


@pytest.mark.parametrize("wrapper", ["concept.sh", "generate.sh"])
def test_recording_is_not_gated_on_json_mode(wrapper):
    """A run without --json is still a run; it used to leave no trace."""
    source = (REPO / "scripts" / wrapper).read_text()
    call = source.index("record_manifest \\")
    # Both wrappers test JSON_MODE several times; the one that matters is the
    # last, which gates the final result emit.
    emit_gate = source.rindex('if [[ "$JSON_MODE" == "1" ]]')
    assert call < emit_gate, \
        f"{wrapper} records inside the --json emit branch, so plain runs go unrecorded"


def test_helper_is_defined_in_the_shared_library():
    assert "record_manifest()" in LIB
    assert "find_manifest_updater()" in LIB


def test_helper_never_fails_the_run():
    """A manifest problem must not lose an asset that was produced."""
    helper = LIB[LIB.index("record_manifest()"):]
    assert "return 0" in helper


def test_helper_keeps_stdout_clean_for_json_mode():
    """Under --json the last stdout line must stay the wrapper's result."""
    helper = LIB[LIB.index("record_manifest()"):]
    assert '>&2' in helper
