import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import pipeline_doctor  # noqa: E402


def test_download_direct_url_writes_to_part_then_rename(tmp_path):
    dest = tmp_path / "out.bin"
    chunks = [b"hello ", b"world", b""]
    mock_resp = MagicMock()
    mock_resp.iter_content = lambda chunk_size: iter([c for c in chunks if c])
    mock_resp.status_code = 200
    mock_resp.headers = {"content-length": "11"}
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = lambda s, *a: None
    with patch("requests.get", return_value=mock_resp):
        result = pipeline_doctor._download_with_range(
            "https://example/out.bin", dest, expected_size=11)
    assert dest.exists()
    assert dest.read_bytes() == b"hello world"
    assert not (dest.with_suffix(".bin.part")).exists()
    assert result["status"] == "ok"


def test_download_direct_url_resumes_from_part(tmp_path):
    dest = tmp_path / "out.bin"
    part = dest.with_suffix(".bin.part")
    part.write_bytes(b"hello ")  # 6 bytes already on disk
    chunks = [b"world", b""]
    captured_headers = {}

    def fake_get(url, headers=None, stream=False, timeout=None):
        captured_headers.update(headers or {})
        m = MagicMock()
        m.iter_content = lambda chunk_size: iter([c for c in chunks if c])
        m.status_code = 206
        m.headers = {"content-length": "5"}
        m.__enter__ = lambda s: s
        m.__exit__ = lambda s, *a: None
        return m

    with patch("requests.get", side_effect=fake_get):
        result = pipeline_doctor._download_with_range(
            "https://example/out.bin", dest, expected_size=11)
    assert dest.read_bytes() == b"hello world"
    assert "Range" in captured_headers
    assert captured_headers["Range"] == "bytes=6-"
    assert result["status"] == "ok"


def test_download_direct_url_restarts_when_server_ignores_range(tmp_path):
    dest = tmp_path / "out.bin"
    part = dest.with_suffix(".bin.part")
    part.write_bytes(b"stale-bytes")  # 11 bytes of stale data

    def fake_get(url, headers=None, stream=False, timeout=None):
        m = MagicMock()
        m.iter_content = lambda chunk_size: iter([b"abcdefghij", b""])
        m.status_code = 200  # server ignored Range
        m.headers = {"content-length": "10"}
        m.__enter__ = lambda s: s
        m.__exit__ = lambda s, *a: None
        return m

    with patch("requests.get", side_effect=fake_get):
        result = pipeline_doctor._download_with_range(
            "https://example/out.bin", dest, expected_size=10)
    assert dest.read_bytes() == b"abcdefghij"
    assert result.get("restarted") is True


def test_download_hf_uses_hf_hub_download(tmp_path):
    """hf_hub_download has always-on resume in current huggingface_hub."""
    with patch("huggingface_hub.hf_hub_download") as mock_dl:
        mock_dl.return_value = str(tmp_path / "snapshot" / "file.bin")
        (tmp_path / "snapshot").mkdir()
        (tmp_path / "snapshot" / "file.bin").write_bytes(b"x" * 100)
        result = pipeline_doctor._download_hf(
            "tencent/Hunyuan3D-2", "hunyuan3d-paint.safetensors",
            cache_dir=tmp_path)
    assert result["status"] == "ok"
    mock_dl.assert_called_once()
    assert "resume_download" not in mock_dl.call_args.kwargs, \
        "resume_download is deprecated/removed; rely on library default"


def test_download_with_range_appends_in_binary_mode_when_offset_nonzero(tmp_path):
    """Verify write mode is 'ab' (not 'wb') when we have a partial file and
    the server returned 206."""
    dest = tmp_path / "out.bin"
    part = dest.with_suffix(".bin.part")
    part.write_bytes(b"hello ")

    real_open = open
    captured_mode = {"mode": None}

    def capturing_open(path, mode="r", *args, **kwargs):
        if str(path).endswith(".part") and "b" in mode:
            captured_mode["mode"] = mode
        return real_open(path, mode, *args, **kwargs)

    def fake_get(url, headers=None, stream=False, timeout=None):
        m = MagicMock()
        m.iter_content = lambda chunk_size: iter([b"world"])
        m.status_code = 206
        m.headers = {"content-length": "5"}
        m.__enter__ = lambda s: s
        m.__exit__ = lambda s, *a: None
        return m

    with patch("requests.get", side_effect=fake_get), \
         patch("builtins.open", side_effect=capturing_open):
        pipeline_doctor._download_with_range(
            "https://example/out.bin", dest, expected_size=11)
    assert captured_mode["mode"] == "ab", \
        f"expected append-binary mode for resume, got {captured_mode['mode']!r}"
