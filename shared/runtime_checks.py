"""Cheap file checks before queuing model inference or character rendering."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys

from shared.skin_catalog import load_skin_catalog, resolve_skin_resource, skin_requires_retarget


def _path(raw, base=None):
    if not raw:
        return None
    path = Path(str(raw)).expanduser()
    return (base / path if base is not None and not path.is_absolute() else path).resolve()


def discover_ffmpeg():
    configured = os.getenv("LODGE_FFMPEG_EXE") or os.getenv("INTERGEN_FFMPEG_EXE")
    if configured:
        return configured
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError, OSError):
        return None


def runtime_report(project_root, backend, profiles, options=None, *, operation="generate"):
    """Honor request overrides; rendering existing motion needs no checkpoints."""
    options = options or {}
    project_root = Path(project_root).resolve()
    prefix = backend.upper()
    checks = []

    def check(key, label, raw, *, directory=False, json_file=False):
        path = _path(raw)
        try:
            ready = bool(path and (path.is_dir() if directory else path.is_file() and path.stat().st_size > 0))
            if ready and json_file:
                value = json.loads(path.read_text(encoding="utf-8"))
                ready = isinstance(value, (dict, list)) and bool(value)
        except (OSError, ValueError):
            ready = False
        checks.append({"id": key, "label": label, "ready": ready,
                       "message": "已就绪" if ready else f"{label}缺失或不可读取，请检查本地配置。"})

    python = options.get("python_executable") or os.getenv(f"{prefix}_PYTHON") or sys.executable
    check("python", "运行环境", shutil.which(str(python)) or python)
    root_raw = options.get("lodge_root") if backend == "lodge" else options.get("source_root")
    root_raw = root_raw or os.getenv("LODGE_ROOT" if backend == "lodge" else "INTERGEN_SOURCE_ROOT")
    root = _path(root_raw)
    if operation != "retarget":
        check("source", "动作模型代码", root, directory=True)
    if operation == "generate":
        if backend == "intergen":
            configs = _path(os.getenv("INTERGEN_CONFIG_DIR")) or (root / "configs" if root else None)
            check("model_config", "动作模型配置", configs / "model.yaml" if configs else None)
            check("infer_config", "动作推理配置", configs / "infer.yaml" if configs else None)
            checkpoint = options.get("checkpoint") or os.getenv("INTERGEN_FIXED_CHECKPOINT")
            fixed_checkpoint = bool(checkpoint)
            if not checkpoint and configs and (configs / "model.yaml").is_file():
                try:
                    import yaml
                    try:
                        checkpoint = yaml.safe_load((configs / "model.yaml").read_text(encoding="utf-8")).get("CHECKPOINT")
                    except yaml.YAMLError:
                        next(row for row in checks if row["id"] == "model_config").update(
                            ready=False, message="动作模型配置无法解析，请检查本地配置。")
                except (ImportError, OSError, ValueError, AttributeError):
                    pass
                checkpoint = _path(checkpoint, root)
            candidates = [checkpoint] if fixed_checkpoint else [checkpoint, root.parent / "checkpoints/intergen.ckpt" if root else None,
                project_root.parent / "InterGen/checkpoints/intergen.ckpt"]
            check("checkpoint", "动作模型权重", next((p for p in candidates if p and _path(p).is_file()), checkpoint))
        else:
            check("inference", "舞蹈推理程序", root / "infer_lodge.py" if root else None)
            for key, label, relative in (
                ("global_checkpoint", "舞蹈全局模型权重", "Global_Module/FineDance_Global/checkpoints/epoch=2999.ckpt"),
                ("local_checkpoint", "舞蹈局部模型权重", "Local_Module/FineDance_FineTuneV2_Local/checkpoints/epoch=299.ckpt"),
                ("global_config", "舞蹈全局模型配置", "Global_Module/FineDance_Global/global_train.yaml"),
                ("local_config", "舞蹈局部模型配置", "Local_Module/FineDance_FineTuneV2_Local/local_train.yaml"),
            ):
                candidates = [root / prefix_dir / relative for prefix_dir in ("exp", "exp/exp")] if root else []
                check(key, label, next((p for p in candidates if p.is_file()), None))
            check("assets_config", "舞蹈资源配置", root / "configs/data/assets.yaml" if root else None)

    retargets = [profile for profile in profiles if skin_requires_retarget(profile)]
    if retargets:
        check("blender", "角色渲染器", options.get("blender_executable") or os.getenv(f"{prefix}_BLENDER_EXE"))
        script = options.get("retarget_script") or os.getenv(f"{prefix}_RETARGET_SCRIPT") or project_root / "LODGE_api/blender_rokoko_retarget.py"
        check("retarget_script", "角色渲染脚本", script)
        if backend == "intergen":
            momask = _path(os.getenv("INTERGEN_MOMASK_ROOT")) or project_root.parent / "momask-main"
            check("bvh_converter", "骨骼转换程序", momask / "visualization/joints2bvh.py" if momask else None)
        for profile in retargets:
            for field, label in (("target_fbx", "角色模型"), ("mapping_file", "骨骼映射")):
                # Person A/B always use their catalog profiles in the renderer.
                override = None if options.get("person_a_skin_id") else options.get(field)
                check(f"{profile['id']}:{field}", f"{profile.get('label', profile['id'])}的{label}",
                      override or resolve_skin_resource(project_root, profile, field), json_file=field == "mapping_file")
    if any(profile.get("output_kind") == "smpl" for profile in profiles):
        if backend == "lodge":
            model = options.get("model_path") or os.getenv("LODGE_SMPLX_MODEL")
            check("human_model", "标准人体模型", model)
        elif os.getenv("INTERGEN_RENDER_MODE") != "skeleton":
            from_root = _path(os.getenv("INTERGEN_HUMAN_MODELS_ROOT")) or (root / "human_models" if root else project_root / "human_models")
            candidates = list(from_root.rglob("SMPLX_NEUTRAL.npz")) + list(from_root.rglob("SMPL_NEUTRAL.pkl")) if from_root and from_root.is_dir() else []
            check("human_model", "标准人体模型", candidates[0] if candidates else None)
    check("ffmpeg", "视频处理工具", options.get("ffmpeg_executable") or discover_ffmpeg())
    return {"backend": backend, "ready": all(row["ready"] for row in checks), "checks": checks}


def checked_catalog(project_root, backend, catalog, options=None):
    _, profiles = load_skin_catalog(Path(project_root))
    for skin in catalog["skins"]:
        report = runtime_report(project_root, backend, [profiles[skin["id"]]], options, operation="retarget")
        skin["available"] = report["ready"]
        skin["unavailable_reasons"] = [row["message"] for row in report["checks"] if not row["ready"]]
    return catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("intergen", "lodge"), required=True)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    _, profiles = load_skin_catalog(args.project_root)
    reports = {key: runtime_report(args.project_root, args.backend, [profile]) for key, profile in profiles.items()}
    for key, report in reports.items():
        missing = [row["message"] for row in report["checks"] if not row["ready"]]
        print(f"{key}: {'READY' if report['ready'] else 'UNAVAILABLE'}" + (" — " + "；".join(missing) if missing else ""))
    # Missing optional roles do not prevent other roles or the CPU workbench from starting.
    return 0 if any(report["ready"] for report in reports.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
