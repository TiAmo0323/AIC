"""Read historical repaired-character evidence; no rendering or publication."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def repaired_inputs(task: Path) -> list[Path]:
    return [task / "motionlint" / f"repaired_actor{actor}.npy" for actor in (1, 2)]


def fingerprint(paths: list[Path]) -> list[dict]:
    return [{"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in paths]


def read_export(task: Path) -> dict:
    path = task / "motionlint/character_export.json"
    if not path.is_file():
        return {"status": "unavailable"}
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("status") == "ready":
        inputs = repaired_inputs(task)
        if not all(path.is_file() for path in inputs) or fingerprint(inputs) != state.get("input_fingerprints"):
            return {**state, "status": "stale"}
    return state
