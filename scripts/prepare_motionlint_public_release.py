"""Prepare an allowlisted, checksummed standalone release; never upload it."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from motionlint_050_privacy import CREDENTIAL, private_path_fields

VERSION = "0.5.0"
ROOT_FILES = {"pyproject.toml", "LICENSE", "LICENSE_SCOPE.md", "THIRD_PARTY_NOTICES.md",
              "THIRD_PARTY_LICENSES.txt", "MODEL_LICENSES.md", "ASSET_LICENSES.md"}
DOC_FILES = {"docs/MOTIONLINT_QUICKSTART.md", "docs/MOTIONLINT_MIGRATION_V5.md",
             "docs/MOTIONLINT_050_RESULTS.md", "docs/MOTIONLINT_RELEASE_REVIEW.md"}
SCRIPT_FILES = {"scripts/prepare_motionlint_public_release.py", "scripts/publish_motionlint_github.py",
                "scripts/motionlint_050_privacy.py"}
FORBIDDEN_SUFFIXES = {".npy", ".npz", ".bvh", ".fbx", ".blend", ".ckpt", ".pth", ".pt", ".wav", ".mp3", ".mp4"}


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_allowed(name):
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
        return False
    if path.suffix.lower() in FORBIDDEN_SUFFIXES or any(p in {"__pycache__", "node_modules", ".env"} for p in path.parts):
        return False
    return (name in ROOT_FILES | DOC_FILES | SCRIPT_FILES
            or name.startswith(("motionlint/", "locks/", "resources/"))
            or name in {"tests/test_motionlint_portable.py", "tests/test_motionlint_public_release.py"})


def verify_archive(path):
    with ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError("Archive CRC failure")
        manifest = json.loads(archive.read("CONTENT_MANIFEST.json"))
        names = archive.namelist()
        expected = {r["path"] for r in manifest["files"]} | {"CONTENT_MANIFEST.json"}
        if len(names) != len(set(names)) or set(names) != expected:
            raise ValueError("Archive inventory mismatch")
        for row in manifest["files"]:
            if row["path"] != "README.md" and not source_allowed(row["path"]):
                raise ValueError("Non-allowlisted archive entry")
            if hashlib.sha256(archive.read(row["path"])).hexdigest() != row["sha256"]:
                raise ValueError("Archive content hash mismatch")
    return len(manifest["files"])


def verify_checksums(folder):
    rows = (folder / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    seen = set()
    for row in rows:
        expected, name = row.split("  ", 1)
        target = (folder / name).resolve()
        if target.parent != folder.resolve() or name in seen or sha(target) != expected:
            raise ValueError("Unsafe, duplicate or mismatched release checksum")
        seen.add(name)
    actual = {p.name for p in folder.iterdir() if p.is_file()} - {"SHA256SUMS.txt"}
    if seen != actual:
        raise ValueError("Release checksum inventory mismatch")
    return len(seen)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--wheel-validation", type=Path, required=True)
    parser.add_argument("--test-results", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    # Refuse replacement of a previous release or candidate.
    out.mkdir(parents=True, exist_ok=False)
    wheel = args.wheel.resolve()
    validation_rows = []
    for version in ("3.10", "3.11"):
        for extra in ("core", "optimize"):
            row = json.loads((args.wheel_validation / f"results-b-{version}-{extra}" / "verification.json").read_text())
            if row["status"] != "PASS" or row["wheel_sha256"] != sha(wheel) or not row["source_imports_excluded"]:
                raise ValueError("Release wheel installation not verified")
            if row["optimize"] != (extra == "optimize") or not row["python"].startswith(version + "."):
                raise ValueError("Installation configuration mismatch")
            validation_rows.append({"python": version, "extra": extra, "status": row["status"],
                "wheel_sha256": row["wheel_sha256"], "source_imports_excluded": True,
                "receipt_sha256": sha(args.wheel_validation / f"results-b-{version}-{extra}" / "verification.json")})
    suites = list(ET.parse(args.test_results).getroot().iter("testsuite"))
    totals = {key: sum(int(s.get(key, 0)) for s in suites) for key in ("tests", "failures", "errors", "skipped")}
    if not suites or totals["failures"] or totals["errors"]:
        raise ValueError("Full test suite has not passed")
    totals["passed"] = totals["tests"] - totals["skipped"]
    publication_validation = {"status": "PASS", "tests": totals, "windows_fresh_wheel_installs": validation_rows,
        "test_receipt_sha256": sha(args.test_results), "scope": "Machine checks; no human validation claim"}
    (out / "PUBLICATION_VALIDATION.json").write_text(json.dumps(publication_validation, indent=2) + "\n", encoding="utf-8")
    with ZipFile(wheel) as archive:
        for name in ("LICENSE", "LICENSE_SCOPE.md", "THIRD_PARTY_LICENSES.txt"):
            if not any(p.endswith("/licenses/" + name) for p in archive.namelist()):
                raise ValueError("Wheel lacks license: " + name)
        metadata = archive.read("motionlint-0.5.0.dist-info/METADATA").decode()
        if not {"License: MIT", "License-Expression: MIT"}.intersection(metadata.splitlines()):
            raise ValueError("Wheel does not identify MIT")
        if any(Path(p).suffix.lower() in FORBIDDEN_SUFFIXES for p in archive.namelist()):
            raise ValueError("Restricted resource in wheel")
    tracked = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT
    ).decode("utf-8").split("\0")
    source_rows = []
    source = out / "MotionLint-0.5.0-source.zip"
    with ZipFile(source, "w", ZIP_DEFLATED) as archive:
        for name in sorted(set(filter(source_allowed, tracked))):
            path = ROOT / name
            if not path.is_file():
                continue
            data = path.read_bytes()
            if CREDENTIAL.search(data):
                raise ValueError("Credential-like content in source")
            archive.writestr(name, data)
            source_rows.append({"path": name, "sha256": hashlib.sha256(data).hexdigest()})
        readme = ("# MotionLint 0.5.0 standalone source\n\n"
                  "Install: python -m pip install -c locks/competition.txt '.[competition]'\n\n"
                  "Start with docs/MOTIONLINT_QUICKSTART.md. The standalone component is MIT; "
                  "see LICENSE_SCOPE.md and THIRD_PARTY_LICENSES.txt. The original platform, "
                  "models, weights, datasets and characters are not included.\n\n"
                  "Reports, video and evidence: https://github.com/TiAmo0323/AIC/releases/tag/v0.5.0\n").encode()
        archive.writestr("README.md", readme)
        source_rows.append({"path": "README.md", "sha256": hashlib.sha256(readme).hexdigest()})
        archive.writestr("CONTENT_MANIFEST.json", json.dumps({"version": VERSION,
            "scope": "MIT standalone component with separately licensed bundled dependencies",
            "files": source_rows}, indent=2))
    count = verify_archive(source)
    evidence = args.evidence.resolve()
    with ZipFile(evidence) as archive:
        if archive.testzip() is not None:
            raise ValueError("Evidence CRC failure")
        for item in archive.infolist():
            data = archive.read(item)
            if Path(item.filename).suffix.lower() in FORBIDDEN_SUFFIXES or CREDENTIAL.search(data):
                raise ValueError("Restricted or credential-like evidence content")
            if item.filename.endswith(".json") and private_path_fields(json.loads(data)):
                raise ValueError("Private path in evidence")
    copies = [(wheel, wheel.name), (evidence, "MotionLint-0.5.0-evidence.zip"),
              (ROOT / "submission/MotionLint-050-report.pdf", "MotionLint-050-report.pdf"),
              (ROOT / "submission/MotionLint-050-demo.mp4", "MotionLint-050-demo.mp4"),
              (ROOT / "LICENSE", "LICENSE"), (ROOT / "LICENSE_SCOPE.md", "LICENSE_SCOPE.md"),
              (ROOT / "submission/RELEASE_NOTES_0.5.0.md", "RELEASE_NOTES.md")]
    for src, name in copies:
        shutil.copyfile(src, out / name)
    artifacts = [{"file": p.name, "sha256": sha(p), "bytes": p.stat().st_size}
                 for p in sorted(out.iterdir()) if p.is_file()]
    manifest = {"schema_version": 1, "version": VERSION, "tag": "v0.5.0",
        "status": "PREPARED_FOR_PUBLICATION", "license": "MIT; scope in LICENSE_SCOPE.md",
        "source_files": count, "artifacts": artifacts,
        "algorithm_freeze_unchanged": True,
        "historical_evidence": {"sha256": sha(evidence), "immutable_snapshot": True,
            "scope": "Original 0.5 experiments and original wheel installations, not the rebuilt release wheel"},
        "ci_scope": "Existing source-install matrix and frontend checks; optimize cross-platform wheel matrix not verified",
        "no_human_validation_claim": True}
    (out / "RELEASE_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (out / "SHA256SUMS.txt").write_text("".join(
        f"{sha(p)}  {p.name}\n" for p in sorted(out.iterdir()) if p.is_file()), encoding="utf-8")
    print(json.dumps({"status": "PASS", "source_files": count, "checksummed_files": verify_checksums(out)}))


if __name__ == "__main__":
    main()
