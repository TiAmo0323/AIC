"""Persist user supplied motion files and their explicit input conventions."""
from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import fields
import hashlib
import json
from pathlib import Path

import numpy as np

from motionlint.cli.main import load_motion, _write_json, _write_report
from motionlint.core.quality_gate import evaluate_gate
from motionlint.pipeline.inspector import inspect
from motionlint.core.motion_sequence import MotionSequence

MAX_IMPORT_BYTES = 32 * 1024 * 1024
MAX_IMPORT_FRAMES = 12000


def import_manifest(folder):
    folder = Path(folder).resolve()
    data = json.loads((folder / "import.json").read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("task_id") != folder.name:
        raise ValueError("导入记录不完整，请重新导入。")
    if not isinstance(data.get("options"), dict) or any(key not in data for key in (
            "title", "fps", "frame_count", "actor_count", "joint_count", "parents", "joint_names", "bounds", "up_axis")):
        raise ValueError("导入参数或骨架信息不完整，请重新导入。")
    files = data.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= 2:
        raise ValueError("导入文件记录不完整。")
    for entry in files:
        path = (folder / entry["path"]).resolve()
        if not path.is_relative_to(folder) or not path.is_file():
            raise ValueError("导入的原始文件已不可用，请重新导入。")
    return data


def imported_paths(folder):
    return [Path(folder) / entry["path"] for entry in import_manifest(folder)["files"]]


def load_imported_motion(folder):
    data = import_manifest(folder)
    paths = [Path(folder) / entry["path"] for entry in data["files"]]
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != entry.get("sha256") for path, entry in zip(paths, data["files"])):
        raise ValueError("导入的原始文件已变化，请重新导入。")
    # Freeze the evaluated geometry at import time. A later SMPL-X configuration
    # change must not make a new report disagree with the cached skeleton view.
    with np.load(Path(folder) / "normalized_motion.npz", allow_pickle=False) as archive:
        description = json.loads(str(archive["description"].item()))
        arrays = {key: archive[key] for key in ("positions", "rotations_6d", "rotation_matrices", "root_translation", "contacts") if key in archive}
    metadata = description["metadata"]
    if "source_paths" in metadata:
        metadata["source_paths"] = [str(path) for path in paths]
    else:
        metadata["source_path"] = str(paths[0])
    return MotionSequence(**{**description, **arrays})


def public_import(data):
    return {key: data[key] for key in ("task_id", "title", "files", "format", "imported_at", "fps", "frame_count",
        "actor_count", "joint_count", "up_axis", "unit_scale", "geometry_source", "warnings", "bounds") if key in data} | {
        "files": [entry["name"] for entry in data["files"]], "source": "import", "conventions": data["options"]}


def finish_import(folder, files, options):
    folder = Path(folder)
    paths = [folder / entry["path"] for entry in files]
    motion = load_motion(paths[0], paths[1] if len(paths) == 2 else None, max_frames=MAX_IMPORT_FRAMES, max_joints=128, **options)
    if motion.frame_count > MAX_IMPORT_FRAMES or motion.positions.shape[2] > 128:
        raise ValueError("当前导入支持最多 12000 帧、128 个关节，请裁剪文件后导入。")
    metadata = motion.metadata
    files = [{**entry, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for entry, path in zip(files, paths)]
    warnings = []
    if len(metadata.get("foot_joint_ids", [])) < 2:
        warnings.append("未识别到足部关节，脚滑和地面接触可能无法完整评估。请核对 BVH 关节映射。")
    if metadata.get("geometry_source") == "fixed_bvh_proxy":
        warnings.append("人体模型不可用，LODGE 使用固定骨架代理；评分仅适用于代理骨架。")
    data = {"task_id": folder.name, "title": " + ".join(entry["name"] for entry in files), "files": files,
        "format": "bvh" if paths[0].suffix == ".bvh" else ("lodge_npy" if motion.source == "lodge" else "joints22_npy"),
        "options": options, "imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fps": motion.fps, "frame_count": motion.frame_count, "actor_count": motion.actor_count,
        "joint_count": motion.positions.shape[2], "joint_names": motion.joint_names,
        "parents": metadata.get("parents", []), "up_axis": metadata.get("up_axis", 1),
        "unit_scale": options["unit_scale"], "geometry_source": metadata.get("geometry_source", "native_joint_positions"),
        "bounds": [motion.positions.min(axis=(0, 1, 2)).tolist(), motion.positions.max(axis=(0, 1, 2)).tolist()],
        "warnings": warnings}
    report = inspect(motion)
    report.metadata["inspection_stage"] = "raw"
    gate = evaluate_gate(report)
    output = folder / "motionlint/stages/raw"
    _write_report(output, report)
    _write_json(output / "quality_gate.json", gate.to_dict())
    description, arrays = {}, {}
    for field in fields(motion):
        value = getattr(motion, field.name)
        if isinstance(value, np.ndarray):
            arrays[field.name] = value
        else:
            description[field.name] = value
    np.savez_compressed(folder / "normalized_motion.npz", description=json.dumps(description, ensure_ascii=False), **arrays)
    np.save(folder / "preview_positions.npy", motion.positions.astype(np.float32), allow_pickle=False)
    # Completion marker is written last; task scans ignore interrupted uploads.
    _write_json(folder / "import.json", data)
    return {"task": {"source": "import", "task_id": folder.name}, "stage": "raw", "import": public_import(data),
        "report": report.to_dict(), "gate": gate.to_dict(), "video_url": None}


def preview_frames(folder, start, count):
    data = import_manifest(folder)
    positions = np.load(Path(folder) / "preview_positions.npy", mmap_mode="r", allow_pickle=False)
    try:
        if positions.shape != (data["frame_count"], data["actor_count"], data["joint_count"], 3):
            raise ValueError("骨架预览数据与导入记录不一致，请重新导入。")
        if start >= len(positions):
            raise ValueError("预览帧超出了动作范围。")
        return {"start": start, "positions": positions[start:start + count].tolist(),
            "fps": data["fps"], "frame_count": data["frame_count"], "joint_names": data["joint_names"],
            "parents": data["parents"], "up_axis": data["up_axis"], "bounds": data["bounds"]}
    finally:
        positions._mmap.close()
