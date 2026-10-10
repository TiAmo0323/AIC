"""Resource checks honor real selections, overrides, and inference boundaries."""
import json
import sys

from shared.runtime_checks import runtime_report, checked_catalog
from shared.skin_catalog import public_skin_catalog


def write(path, contents="resource"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    return path


def runtime_fixture(tmp_path, monkeypatch):
    project = tmp_path / "project"
    root = tmp_path / "lodge"
    write(project / "LODGE_api/blender_rokoko_retarget.py")
    blender = write(tmp_path / "blender.exe")
    ffmpeg = write(tmp_path / "ffmpeg.exe")
    model = write(tmp_path / "SMPLX_NEUTRAL.npz")
    fbx = write(project / "config/robot.fbx")
    mapping = write(project / "config/mapping.json", '{"Hips": "mixamorig:Hips"}')
    write(project / "config/skin_catalog.json", json.dumps({"default_skin_id": "smpl", "skins": [
        {"id": "smpl", "label": "Human", "output_kind": "smpl"},
        {"id": "robot", "label": "Robot", "output_kind": "retarget", "target_fbx": "robot.fbx", "mapping_file": "mapping.json"},
        {"id": "missing", "label": "Missing", "output_kind": "retarget", "target_fbx": "missing.fbx", "mapping_file": "mapping.json"},
    ]}))
    for relative in ("infer_lodge.py", "configs/data/assets.yaml",
        "exp/Global_Module/FineDance_Global/checkpoints/epoch=2999.ckpt",
        "exp/Global_Module/FineDance_Global/global_train.yaml",
        "exp/Local_Module/FineDance_FineTuneV2_Local/checkpoints/epoch=299.ckpt",
        "exp/Local_Module/FineDance_FineTuneV2_Local/local_train.yaml"):
        write(root / relative)
    monkeypatch.setenv("HUMAN_ACTION_SKIN_CATALOG", str(project / "config/skin_catalog.json"))
    monkeypatch.setenv("LODGE_PYTHON", sys.executable)
    monkeypatch.setenv("LODGE_BLENDER_EXE", str(blender))
    monkeypatch.setenv("LODGE_FFMPEG_EXE", str(ffmpeg))
    monkeypatch.setenv("LODGE_SMPLX_MODEL", str(model))
    monkeypatch.delenv("LODGE_RETARGET_SCRIPT", raising=False)
    monkeypatch.delenv("INTERGEN_PYTHON", raising=False)
    return project, root, fbx, mapping


def test_missing_role_does_not_disable_installed_role(tmp_path, monkeypatch):
    project, _, _, _ = runtime_fixture(tmp_path, monkeypatch)
    result = checked_catalog(project, "lodge", public_skin_catalog(project))
    skins = {skin["id"]: skin for skin in result["skins"]}
    assert skins["robot"]["available"]
    assert not skins["missing"]["available"]
    assert skins["missing"]["unavailable_reasons"]
    assert "target_fbx" not in skins["robot"]


def test_render_existing_motion_does_not_require_inference_weights(tmp_path, monkeypatch):
    from shared.skin_catalog import resolve_skins
    project, root, _, _ = runtime_fixture(tmp_path, monkeypatch)
    profiles = resolve_skins(project, ["robot"])
    options = {"lodge_root": str(root)}
    checkpoint = root / "exp/Global_Module/FineDance_Global/checkpoints/epoch=2999.ckpt"
    checkpoint.unlink()
    assert not runtime_report(project, "lodge", profiles, options)["ready"]
    assert runtime_report(project, "lodge", profiles, options, operation="render")["ready"]


def test_request_overrides_and_corrupt_mapping_are_checked(tmp_path, monkeypatch):
    from shared.skin_catalog import resolve_skins
    project, root, fbx, mapping = runtime_fixture(tmp_path, monkeypatch)
    profiles = resolve_skins(project, ["missing"])
    options = {"lodge_root": str(root), "target_fbx": str(fbx), "mapping_file": str(mapping)}
    assert runtime_report(project, "lodge", profiles, options)["ready"]
    mapping.write_text("invalid JSON", encoding="utf-8")
    result = runtime_report(project, "lodge", profiles, options)
    assert not result["ready"]
    assert not next(row for row in result["checks"] if row["id"] == "missing:mapping_file")["ready"]


def test_person_pair_cannot_override_missing_second_person_asset(tmp_path, monkeypatch):
    from shared.skin_catalog import resolve_skins
    project, _, fbx, mapping = runtime_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("INTERGEN_BLENDER_EXE", str(tmp_path / "blender.exe"))
    monkeypatch.setenv("INTERGEN_MOMASK_ROOT", str(tmp_path / "momask"))
    write(tmp_path / "momask/visualization/joints2bvh.py")
    profiles = resolve_skins(project, ["robot", "missing"])
    result = runtime_report(project, "intergen", profiles,
        {"person_a_skin_id": "robot", "person_b_skin_id": "missing", "target_fbx": str(fbx), "mapping_file": str(mapping)}, operation="retarget")
    assert not result["ready"]
    assert not next(row for row in result["checks"] if row["id"] == "missing:target_fbx")["ready"]


def test_corrupt_model_config_reports_unavailable_instead_of_server_error(tmp_path, monkeypatch):
    from shared.skin_catalog import resolve_skins
    project, _, _, _ = runtime_fixture(tmp_path, monkeypatch)
    source = tmp_path / "intergen"
    write(source / "configs/model.yaml", 'CHECKPOINT: [unterminated')
    write(source / "configs/infer.yaml")
    monkeypatch.delenv("INTERGEN_CONFIG_DIR", raising=False)
    monkeypatch.delenv("INTERGEN_FIXED_CHECKPOINT", raising=False)
    result = runtime_report(project, "intergen", resolve_skins(project, ["smpl"]), {"source_root": str(source)})
    assert not result["ready"]
    assert not next(row for row in result["checks"] if row["id"] == "model_config")["ready"]


def test_missing_fixed_checkpoint_does_not_use_automatic_fallback(tmp_path, monkeypatch):
    from shared.skin_catalog import resolve_skins
    project, _, _, _ = runtime_fixture(tmp_path, monkeypatch)
    source = tmp_path / "intergen"
    write(source / "configs/model.yaml", 'CHECKPOINT: ../checkpoints/intergen.ckpt')
    write(source / "configs/infer.yaml")
    write(source.parent / "checkpoints/intergen.ckpt")
    monkeypatch.delenv("INTERGEN_CONFIG_DIR", raising=False)
    monkeypatch.setenv("INTERGEN_FIXED_CHECKPOINT", str(tmp_path / "missing.ckpt"))
    result = runtime_report(project, "intergen", resolve_skins(project, ["smpl"]), {"source_root": str(source)})
    assert not next(row for row in result["checks"] if row["id"] == "checkpoint")["ready"]
