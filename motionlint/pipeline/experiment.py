"""Batch evaluation for repeatable MotionLint experiments.

The batch runner consumes already generated NPY/BVH files.  It never loads an
InterGen or LODGE checkpoint, so a competition demo can evaluate many outputs
without competing for GPU memory with a generator.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

from motionlint.cli.main import _json_safe, _write_json, _write_report, load_motion
from motionlint.core.quality_gate import evaluate_gate
from motionlint.pipeline.inspector import inspect


def _entry_name(entry: dict, index: int) -> str:
    value = str(entry.get("name") or entry.get("id") or f"motion_{index + 1:03d}")
    name = "".join(char if char.isalnum() or char in "-_ ." else "_" for char in value).strip().rstrip(" .")
    if not name:
        raise ValueError("Batch entry name must identify a report folder, not '.' or '..'")
    return name


def run_batch(
    entries: Iterable[dict],
    output_dir: str | Path,
    *,
    base_dir: str | Path | None = None,
    default_fps: float = 30,
    config_path=None, unit_scale=1., up_axis=1, joint_mapping=None,
) -> dict:
    """Inspect each manifest entry and export per-motion and summary reports."""

    entries = list(entries)
    if not entries or any(not isinstance(entry, dict) or not entry.get("input") for entry in entries):
        raise ValueError("Batch requires a non-empty list of objects with input paths")
    names = [_entry_name(entry, index) for index, entry in enumerate(entries)]
    if len({name.casefold() for name in names}) != len(names):
        raise ValueError("Batch entry names resolve to duplicate report folders")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    root = Path(base_dir or ".").resolve()
    rows: list[dict] = []
    details: list[dict] = []
    for index, raw_entry in enumerate(entries):
        entry = dict(raw_entry)
        name = _entry_name(entry, index)
        input_path = Path(str(entry.get("input") or "")).expanduser()
        if not input_path.is_absolute():
            input_path = root / input_path
        fps = float(entry.get("fps", default_fps))
        actor2 = entry.get("actor2")
        if actor2 and not Path(str(actor2)).is_absolute():
            actor2 = str(root / str(actor2))
        row = {
            "name": name,
            "input": str(input_path),
            "source": "",
            "frames": "",
            "fps": fps,
            "overall_score": "",
            "gate_status": "ERROR",
            "issue_count": "",
            "error": "",
        }
        try:
            motion = load_motion(input_path, actor2, fps, unit_scale=float(entry.get("unit_scale", unit_scale)), up_axis=int(entry.get("up_axis", up_axis)), joint_mapping=entry.get("joint_mapping", joint_mapping))
            report = inspect(motion, config_path=config_path)
            gate = evaluate_gate(report, config_path=config_path)
            item_dir = output / name
            _write_report(item_dir, report)
            _write_json(item_dir / "quality_gate.json", gate.to_dict())
            row.update(
                source=report.metadata.get("source", motion.source),
                frames=report.metadata.get("frame_count", motion.frame_count),
                fps=report.metadata.get("fps", motion.fps),
                overall_score=report.overall_score,
                gate_status=gate.status,
                issue_count=report.issue_count,
            )
            row.update({f"{test.test_name}_score": test.score for test in report.tests})
            row.update({f"{test.test_name}_issues": len(test.issues) for test in report.tests})
            details.append({"name": name, "entry": entry, "report": report.to_dict(), "gate": gate.to_dict()})
        except (OSError, ValueError, TypeError, ImportError, KeyError, RuntimeError) as exc:
            row["error"] = str(exc)
            details.append({"name": name, "entry": entry, "error": str(exc)})
        rows.append(row)

    columns = ["name", "input", "source", "frames", "fps", "overall_score", "gate_status", "issue_count", "error"]
    test_names = sorted({key[:-6] for row in rows for key in row if key.endswith("_score") and key != "overall_score"})
    for test_name in test_names:
        columns.extend([f"{test_name}_score", f"{test_name}_issues"])
    with (output / "summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "count": len(rows),
        "success_count": sum(1 for row in rows if not row["error"]),
        "gate_pass_count": sum(1 for row in rows if row["gate_status"] == "PASS"),
        "rows": rows,
        "details": details,
    }
    _write_json(output / "summary.json", _json_safe(summary))
    return summary


def run_manifest(manifest_path: str | Path, output_dir: str | Path, **options) -> dict:
    path = Path(manifest_path).expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        entries = payload
    elif isinstance(payload, dict) and isinstance(payload.get("motions"), list):
        entries = payload["motions"]
    else:
        raise ValueError("Manifest must be a list or an object with a 'motions' list")
    return run_batch(entries, output_dir, base_dir=path.parent, default_fps=float(payload.get("fps", 30)) if isinstance(payload, dict) else 30, **options)
