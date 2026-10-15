"""Release boundaries, archive integrity and complete checksum inventory."""
import hashlib
import importlib.util
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("public_release", ROOT / "scripts/prepare_motionlint_public_release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


@pytest.mark.parametrize("name", ["motionlint/core/skeleton.py", "motionlint/static/assets/app.js",
                                  "LICENSE", "LICENSE_SCOPE.md", "locks/core.txt"])
def test_release_allowlist_accepts_standalone(name):
    assert release.source_allowed(name)


@pytest.mark.parametrize("name", ["../LICENSE", "/LICENSE", "motionlint/../private.txt", "C:/LICENSE",
    "motionlint\\secret.py", "InterGen_api/server.py", "LODGE_api/lodge2bvh.py", "shared/task_manifest.py",
    "motionlint/model.npz", "motionlint/clip.bvh", "motionlint/.env", "motionlint/__pycache__/code.pyc"])
def test_release_allowlist_excludes_runtime_and_platform(name):
    assert not release.source_allowed(name)


def test_checksum_inventory_rejects_extra_and_modified_files(tmp_path):
    file = tmp_path / "LICENSE"
    file.write_text("content")
    sums = tmp_path / "SHA256SUMS.txt"
    sums.write_text(release.sha(file) + "  LICENSE\n")
    assert release.verify_checksums(tmp_path) == 1
    (tmp_path / "unlisted.txt").write_text("extra")
    with pytest.raises(ValueError):
        release.verify_checksums(tmp_path)
    (tmp_path / "unlisted.txt").unlink()
    file.write_text("changed")
    with pytest.raises(ValueError):
        release.verify_checksums(tmp_path)


def test_archive_checks_actual_content_hashes(tmp_path):
    archive = tmp_path / "source.zip"
    with ZipFile(archive, "w") as out:
        out.writestr("LICENSE", b"actual")
        out.writestr("CONTENT_MANIFEST.json", json.dumps({"files": [{"path": "LICENSE",
            "sha256": hashlib.sha256(b"different").hexdigest()}]}))
    with pytest.raises(ValueError, match="hash mismatch"):
        release.verify_archive(archive)


def test_package_license_scope_is_explicit():
    assert (ROOT / "LICENSE").read_text().startswith("MIT License")
    scope = (ROOT / "LICENSE_SCOPE.md").read_text(encoding="utf-8")
    for name in ("legacy_arm_clearance.py", "continuity.py", "skeleton.py", "第三方",
                 "不因根目录出现 LICENSE 而自动改为 MIT"):
        assert name in scope
