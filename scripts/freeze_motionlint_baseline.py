"""Archive the pre-change implementation and evidence without exporting assets."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ROOT / "reports" / "first_prize" / "baseline_v3"
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / "snapshot.json"
    if manifest.exists():
        raise SystemExit("Baseline already exists; refusing to overwrite")
    folders = ("motionlint", "shared", "InterGen_api", "LODGE_api", "project/src", "tests", "scripts", "docs", "experiments", "config")
    suffixes = {".py", ".js", ".mjs", ".vue", ".json", ".yaml", ".md", ".ps1", ".bat", ".txt"}
    files = {p for folder in folders for p in (ROOT / folder).rglob("*")
             if p.is_file() and p.suffix in suffixes and not any(part in {"task_runs", "__pycache__", "node_modules", "project-growth"} for part in p.parts)}
    files.update(p for p in ROOT.iterdir() if p.is_file() and (p.suffix in suffixes or p.name == ".gitignore"))
    for folder in ("reports/system_experiments_20261002", "reports/character_feet_20261002"):
        files.update(p for p in (ROOT / folder).rglob("*") if p.is_file() and p.suffix in {".json", ".csv", ".yaml"})
    hashes = {}
    with zipfile.ZipFile(output / "source_and_evidence.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            name = path.relative_to(ROOT).as_posix()
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
            archive.write(path, name)
    packages = {d.metadata["Name"]: d.version for d in importlib.metadata.distributions() if d.metadata.get("Name")}
    payload = {"created_utc": datetime.now(timezone.utc).isoformat(), "purpose": "Development baseline; all previously inspected samples are development data, not fresh holdout",
               "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
               "git_status": subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True),
               "files": hashes, "packages": packages, "archive_sha256": hashlib.sha256((output / "source_and_evidence.zip").read_bytes()).hexdigest()}
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Frozen {len(files)} files: {manifest}")


if __name__ == "__main__":
    main()
