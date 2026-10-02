# 前后端蒙皮输出契约的无模型回归测试。
# 通过替身推理与渲染覆盖 SMPL、五个 FBX 角色、双人角色绑定和重定向分流；
# 测试不会加载真实生成模型或 Blender，因此不证明最终动作与画面质量。
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.skin_catalog import public_skin_catalog, resolve_skin_resource, resolve_skins


RETARGET_SKINS = {
    "nailong": ("nailong.fbx", "mapping.json"),
    "robot": ("X Bot.fbx", "mapping.json"),
    "aj": ("Aj (1).fbx", "mapping.json"),
    "ch09_nonpbr": ("Ch09_nonPBR (1).fbx", "mapping6.json"),
    "ch46_nonpbr": ("Ch46_nonPBR (1).fbx", "mapping.json"),
    "y_bot": ("Y Bot.fbx", "mapping.json"),
}


def load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_lodge_plans(lodge):
    cases = {
        "smpl_only": (["smpl"], False, True),
        "multi": (["smpl", "robot"], True, True),
    }
    cases.update(
        {
            f"{skin_id}_only": ([skin_id], True, False)
            for skin_id in RETARGET_SKINS
        }
    )
    results = {}
    for name, (skin_ids, expected_retarget, expected_smpl) in cases.items():
        req = lodge.InferFromAudioRequest(
            lodge_root=".",
            audio_path="input.wav",
            song_id=name,
            skin_ids=skin_ids,
        )
        options = lodge._retarget_options_from_req(req)
        assert options["enabled"] is expected_retarget
        assert options["render_smpl"] is expected_smpl
        if expected_retarget:
            retarget_skin_id = next(
                skin_id for skin_id in skin_ids if skin_id in RETARGET_SKINS
            )
            expected_fbx, expected_mapping = RETARGET_SKINS[retarget_skin_id]
            assert Path(options["target_fbx"]).name == expected_fbx
            assert Path(options["mapping_file"]).name == expected_mapping
        results[name] = {
            "retarget": options["enabled"],
            "smpl": options["render_smpl"],
            "skin_id": options["skin_id"],
        }
    return results


def test_catalog_resources():
    requested_ids = ["smpl", *RETARGET_SKINS]
    profiles = {
        str(profile["id"]): profile
        for profile in resolve_skins(REPO_ROOT, requested_ids)
    }
    assert list(profiles) == requested_ids

    public_ids = [
        str(profile["id"])
        for profile in public_skin_catalog(REPO_ROOT)["skins"]
    ]
    assert public_ids == ["smpl", "kenney_cc0", *RETARGET_SKINS]

    kenney = resolve_skins(REPO_ROOT, ["kenney_cc0"])[0]
    assert Path(resolve_skin_resource(REPO_ROOT, kenney, "target_fbx")).is_file()
    assert Path(resolve_skin_resource(REPO_ROOT, kenney, "mapping_file")).is_file()

    results = {}
    for skin_id, (expected_fbx, expected_mapping) in RETARGET_SKINS.items():
        profile = profiles[skin_id]
        target_fbx = Path(resolve_skin_resource(REPO_ROOT, profile, "target_fbx"))
        mapping_file = Path(
            resolve_skin_resource(REPO_ROOT, profile, "mapping_file")
        )
        assert target_fbx.name == expected_fbx
        assert mapping_file.name == expected_mapping
        results[skin_id] = {
            "target_fbx": target_fbx.name,
            "mapping_file": mapping_file.name,
            "installed": target_fbx.is_file() and mapping_file.is_file(),
        }
    return results


def test_intergen_outputs(intergen):
    original_generate = intergen.service.generate
    original_retarget = intergen._run_intergen_retarget_if_requested
    render_plans = {}

    def fake_generate(_prompt, output_path, render_preview=True, **_kwargs):
        render_plans[output_path.stem] = bool(render_preview)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        candidate_dir = output_path.parent / "candidates"
        candidate_dir.mkdir(parents=True, exist_ok=True)
        if render_preview:
            output_path.write_bytes(b"temporary-smpl-preview")
            (candidate_dir / "candidate.mp4").write_bytes(b"candidate")
        return {
            "message": (
                "Mock motion and SMPL completed"
                if render_preview
                else "Mock motion completed without SMPL"
            ),
            "generated_frames": 180,
            "fps": 30,
            "raw_joints_files": [],
        }

    def fake_retarget(task_id, task_root, output_path, raw_joints_files, req, motion_prompt=""):
        del output_path, raw_joints_files, motion_prompt
        profiles = intergen._resolve_request_skins(req)
        retarget_profile = next(
            (profile for profile in profiles if intergen.skin_requires_retarget(profile)),
            None,
        )
        if retarget_profile is None:
            intergen._update_task(
                task_id,
                retarget_status="skipped",
                retarget_message="Retarget disabled",
            )
            return
        output = task_root / "retarget" / f"{task_id}_retarget.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"robot-video")
        intergen._update_task(
            task_id,
            output_retarget_path=str(output.resolve()),
            retarget_status="succeeded",
            retarget_message="Mock retarget completed",
        )

    intergen.service.generate = fake_generate
    intergen._run_intergen_retarget_if_requested = fake_retarget

    results = {}
    full_badminton_translation = (
        "Two people are playing badminton: Player A serves with a sideways motion and follows through, "
        "while Player B, on the opposite side, remains in a ready stance and steps toward the incoming shuttlecock."
    )
    assert intergen._optimize_prompt_for_intergen(full_badminton_translation) == full_badminton_translation
    cases = {
        "smpl_only": ["smpl"],
        "multi": ["smpl", "robot"],
    }
    cases.update(
        {
            f"{skin_id}_only": [skin_id]
            for skin_id in RETARGET_SKINS
        }
    )
    for name, skin_ids in cases.items():
        task_id = name
        now = "2026-07-24T00:00:00Z"
        intergen._tasks[task_id] = intergen.TaskInfo(
            task_id=task_id,
            status="queued",
            created_at=now,
            updated_at=now,
            skin_id=skin_ids[0],
            requested_skin_ids=skin_ids,
        )
        req = intergen.GenerateMotionRequest(
            text="Two people dance.",
            skin_ids=skin_ids,
        )
        intergen._run_generate_task(task_id, req)
        task = intergen._tasks[task_id]
        assert task.status == "succeeded"
        assert task.original_prompt == "Two people dance."
        assert task.translated_prompt == "Two people dance."
        assert task.translation_status == "not-needed"
        assert task.translation_error == ""
        assert task.baseline_prompt == "Two people are dancing together face to face with synchronized body movements."
        assert task.seed is not None
        assert task.experiment_variant == "baseline"
        assert task.planner_status == "disabled"
        assert task.experiment_manifest_path
        assert Path(task.experiment_manifest_path).is_file()
        assert task.available_skin_ids == skin_ids
        assert render_plans[task_id] is ("smpl" in skin_ids)
        if "smpl" in skin_ids:
            assert task.output_mp4_path and Path(task.output_mp4_path).is_file()
        else:
            assert task.output_mp4_path is None
            assert not list((intergen.DEFAULT_TASK_ROOT / task_id / "output" / "candidates").glob("*.mp4"))
        has_retarget = any(skin_id in RETARGET_SKINS for skin_id in skin_ids)
        if has_retarget:
            assert task.output_retarget_path and Path(task.output_retarget_path).is_file()
        else:
            assert task.output_retarget_path is None
        results[name] = {
            "available_skin_ids": task.available_skin_ids,
            "smpl_video": bool(task.output_mp4_path),
            "smpl_render_requested": render_plans[task_id],
            "retarget_video": bool(task.output_retarget_path),
        }

    pair_task_id = "person-pair-retarget-only"
    pair_skin_ids = ["aj", "ch09_nonpbr"]
    now = "2026-07-26T00:00:00Z"
    intergen._tasks[pair_task_id] = intergen.TaskInfo(
        task_id=pair_task_id,
        status="queued",
        created_at=now,
        updated_at=now,
        skin_id=pair_skin_ids[0],
        requested_skin_ids=pair_skin_ids,
        person_skin_ids=pair_skin_ids,
    )
    pair_req = intergen.GenerateMotionRequest(
        text="Two people dance.",
        person_a_skin_id=pair_skin_ids[0],
        person_b_skin_id=pair_skin_ids[1],
    )
    intergen._run_generate_task(pair_task_id, pair_req)
    pair_task = intergen._tasks[pair_task_id]
    assert pair_task.status == "succeeded"
    assert render_plans[pair_task_id] is False
    assert pair_task.output_mp4_path is None
    assert pair_task.output_retarget_path and Path(pair_task.output_retarget_path).is_file()
    results[pair_task_id] = {
        "person_skin_ids": pair_task.person_skin_ids,
        "smpl_render_requested": render_plans[pair_task_id],
        "smpl_video": bool(pair_task.output_mp4_path),
        "retarget_video": bool(pair_task.output_retarget_path),
    }

    smpl_pair_task_id = "person-pair-smpl-only"
    smpl_pair_skin_ids = ["smpl", "smpl"]
    intergen._tasks[smpl_pair_task_id] = intergen.TaskInfo(
        task_id=smpl_pair_task_id,
        status="queued",
        created_at=now,
        updated_at=now,
        skin_id="smpl",
        requested_skin_ids=["smpl"],
        person_skin_ids=smpl_pair_skin_ids,
    )
    smpl_pair_req = intergen.GenerateMotionRequest(
        text="Two people dance.",
        person_a_skin_id="smpl",
        person_b_skin_id="smpl",
    )
    intergen._run_generate_task(smpl_pair_task_id, smpl_pair_req)
    smpl_pair_task = intergen._tasks[smpl_pair_task_id]
    assert smpl_pair_task.status == "succeeded"
    assert render_plans[smpl_pair_task_id] is True
    assert smpl_pair_task.output_mp4_path
    assert Path(smpl_pair_task.output_mp4_path).is_file()
    assert smpl_pair_task.output_retarget_path is None
    assert smpl_pair_task.available_skin_ids == ["smpl"]
    results[smpl_pair_task_id] = {
        "person_skin_ids": smpl_pair_task.person_skin_ids,
        "smpl_render_requested": render_plans[smpl_pair_task_id],
        "smpl_video": bool(smpl_pair_task.output_mp4_path),
        "retarget_video": bool(smpl_pair_task.output_retarget_path),
    }

    translation_task_id = "translation-required-failure"
    intergen._tasks[translation_task_id] = intergen.TaskInfo(
        task_id=translation_task_id,
        status="queued",
        created_at=now,
        updated_at=now,
        skin_id="smpl",
        requested_skin_ids=["smpl"],
    )
    previous_dashscope_key = os.environ.pop("DASHSCOPE_API_KEY", None)
    try:
        translation_req = intergen.GenerateMotionRequest(
            text="两个人正在打羽毛球。",
            skin_ids=["smpl"],
            translation_required=True,
        )
        intergen._run_generate_task(translation_task_id, translation_req)
    finally:
        if previous_dashscope_key is not None:
            os.environ["DASHSCOPE_API_KEY"] = previous_dashscope_key
    translation_task = intergen._tasks[translation_task_id]
    assert translation_task.status == "failed"
    assert translation_task.translation_status == "skipped"
    assert "DASHSCOPE_API_KEY" in translation_task.translation_error
    assert translation_task_id not in render_plans
    results[translation_task_id] = {
        "status": translation_task.status,
        "translation_status": translation_task.translation_status,
        "generation_called": translation_task_id in render_plans,
    }

    intergen.service.generate = original_generate
    intergen._run_intergen_retarget_if_requested = original_retarget
    return results


def test_intergen_service_retarget_only_skips_candidate_mp4(intergen, task_root):
    service = intergen.InterGenService()
    render_flags = []

    class FakeMotionModel:
        def generate_one_sample(
            self,
            _prompt,
            output_path,
            motion_frames=None,
            cfg_weight=None,
            render_preview=True,
        ):
            del motion_frames, cfg_weight
            render_flags.append(bool(render_preview))
            raw_dir = Path(output_path).parent / "raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_paths = []
            for person_index in (1, 2):
                raw_path = raw_dir / f"sample_person{person_index}.npy"
                np.save(raw_path, np.zeros((12, 22, 3), dtype=np.float32))
                raw_paths.append(str(raw_path))
            return {
                "render_mode": "skipped",
                "message": "Motion generated without preview",
                "fallback_used": "0",
                "raw_joints_files": raw_paths,
                "generated_frames": 12,
                "fps": 30,
            }

    service._model = FakeMotionModel()
    output_path = task_root / "service-retarget-only" / "output" / "result.mp4"
    original_metrics = intergen._raw_hand_head_collision_metrics
    try:
        intergen._raw_hand_head_collision_metrics = lambda _paths: {}
        result = service.generate(
            "Two people dance.",
            output_path,
            num_samples=2,
            render_preview=False,
            seed=12345,
        )
    finally:
        intergen._raw_hand_head_collision_metrics = original_metrics

    assert render_flags == [False, False]
    assert result["render_mode"] == "skipped"
    assert result["seed"] == 12345
    assert result["selected_sample"] == 1
    assert result["num_samples"] == 2
    assert [item["seed"] for item in result["candidate_summaries"]] == [12345, 12346]
    assert len(result["raw_joints_files"]) == 2
    assert all(Path(path).is_file() for path in result["raw_joints_files"])
    assert not output_path.exists()
    assert not list(output_path.parent.rglob("*.mp4"))
    return {
        "render_preview_flags": render_flags,
        "stable_raw_joint_files": len(result["raw_joints_files"]),
        "candidate_mp4_files": 0,
    }


def test_intergen_candidate_audit_retains_all_samples(intergen, task_root):
    service = intergen.InterGenService()

    class FakeMotionModel:
        def generate_one_sample(
            self,
            _prompt,
            output_path,
            motion_frames=None,
            cfg_weight=None,
            render_preview=True,
        ):
            del motion_frames, cfg_weight
            path = Path(output_path)
            raw_dir = path.parent / "raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_paths = []
            for person_index in (1, 2):
                raw_path = raw_dir / f"{path.stem}_person{person_index}.npy"
                np.save(raw_path, np.zeros((12, 22, 3), dtype=np.float32))
                raw_paths.append(str(raw_path))
            if render_preview:
                path.write_bytes(f"video-{path.stem}".encode("utf-8"))
            return {
                "render_mode": "mock",
                "message": "Mock candidate generated",
                "fallback_used": "0",
                "raw_joints_files": raw_paths,
                "generated_frames": 12,
                "fps": 30,
            }

    service._model = FakeMotionModel()
    original_metrics = intergen._raw_hand_head_collision_metrics
    original_keep_all = os.environ.pop("INTERGEN_KEEP_ALL_SAMPLES", None)
    original_audit_samples = os.environ.pop("INTERGEN_AUDIT_NUM_SAMPLES", None)
    try:
        intergen._raw_hand_head_collision_metrics = lambda _paths: {}
        audit_output = task_root / "candidate-audit" / "result.mp4"
        audit_result = service.generate(
            "Two people play badminton.",
            audit_output,
            render_preview=True,
            seed=100,
            candidate_audit=True,
        )
        default_output = task_root / "candidate-default" / "result.mp4"
        default_result = service.generate(
            "Two people play badminton.",
            default_output,
            num_samples=3,
            render_preview=True,
            seed=200,
        )
    finally:
        intergen._raw_hand_head_collision_metrics = original_metrics
        if original_keep_all is not None:
            os.environ["INTERGEN_KEEP_ALL_SAMPLES"] = original_keep_all
        if original_audit_samples is not None:
            os.environ["INTERGEN_AUDIT_NUM_SAMPLES"] = original_audit_samples

    audit_candidates = list((audit_output.parent / "candidates").glob("*.mp4"))
    default_candidates = list((default_output.parent / "candidates").glob("*.mp4"))
    assert len(audit_candidates) == 8
    assert all(item["retained"] is True for item in audit_result["candidate_summaries"])
    assert audit_result["candidate_audit"] is True
    assert len(default_candidates) == 1
    assert sum(item["retained"] is True for item in default_result["candidate_summaries"]) == 1
    assert default_result["candidate_audit"] is False
    return {
        "audit_candidate_videos": len(audit_candidates),
        "default_candidate_videos": len(default_candidates),
        "audit_retained_flags": [
            item["retained"] for item in audit_result["candidate_summaries"]
        ],
    }


def test_intergen_candidate_audit_review_contract(intergen, task_root):
    task_id = "candidate-audit-review"
    task_dir = task_root / task_id
    candidate_video = task_dir / "output" / "candidates" / "sample1.mp4"
    candidate_video.parent.mkdir(parents=True, exist_ok=True)
    candidate_video.write_bytes(b"candidate-video")
    audit_path = task_dir / "output" / "candidate_audit.json"
    audit_payload = {
        "status": "awaiting-human-review",
        "summary": {
            "candidate_count": 1,
            "human_reviewed_count": 0,
            "semantic_pass_count": 0,
            "gate_decision": "pending-human-review",
        },
        "candidates": [
            {
                "candidate_index": 1,
                "human_review": {"review_status": "pending", "semantic_pass": None},
            }
        ],
    }
    audit_path.write_text(json.dumps(audit_payload), encoding="utf-8")
    now = "2026-07-27T00:00:00Z"
    intergen._tasks[task_id] = intergen.TaskInfo(
        task_id=task_id,
        status="succeeded",
        created_at=now,
        updated_at=now,
        candidate_audit=True,
        candidate_audit_manifest_path=str(audit_path),
        candidate_summaries=[
            {"candidate_index": 1, "file_path": str(candidate_video), "retained": True}
        ],
    )
    assert intergen.get_candidate_audit(task_id)["status"] == "awaiting-human-review"
    result = intergen.review_candidate(
        task_id,
        1,
        intergen.CandidateReviewRequest(
            mutual_facing=True,
            racket_swing_proxy=False,
            receiver_ready_and_reacts=False,
            role_consistency=True,
            badminton_semantic_match=False,
            reviewer="test",
            notes="Generic arm movement only.",
        ),
    )
    assert result["human_review"]["semantic_pass"] is False
    assert result["summary"]["gate_decision"] == (
        "no-qualifying-candidate-refine-planner-or-structured-prompt"
    )
    response = intergen.download_task_candidate(task_id, 1)
    assert Path(response.path) == candidate_video
    saved = json.loads(audit_path.read_text(encoding="utf-8"))
    assert saved["status"] == "no-qualifying-candidate"
    return {
        "review_status": result["human_review"]["review_status"],
        "semantic_pass": result["human_review"]["semantic_pass"],
        "gate_decision": result["summary"]["gate_decision"],
        "candidate_download_file": Path(response.path).name,
    }


def test_intergen_person_skin_manifest(intergen, task_root):
    task_id = "person-skin-pair"
    now = "2026-07-26T00:00:00Z"
    person_skin_ids = ["aj", "ch09_nonpbr"]
    intergen._tasks[task_id] = intergen.TaskInfo(
        task_id=task_id,
        status="running",
        created_at=now,
        updated_at=now,
        skin_id=person_skin_ids[0],
        requested_skin_ids=person_skin_ids,
        person_skin_ids=person_skin_ids,
    )

    output_path = task_root / task_id / "output" / f"{task_id}.mp4"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    raw_paths = []
    for person_index in (1, 2):
        raw_path = task_root / task_id / "raw" / f"person{person_index}.npy"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(raw_path, np.zeros((12, 22, 3), dtype=np.float32))
        raw_paths.append(str(raw_path))

    fake_blender = task_root / "blender.exe"
    fake_blender.write_bytes(b"fake")
    original_export = intergen._export_intergen_bvh
    original_run = intergen._run_subprocess
    original_resolve = intergen.resolve_skin_resource
    assets = {}
    for skin_id, (fbx_name, mapping_name) in RETARGET_SKINS.items():
        for key, name in (("target_fbx", fbx_name), ("mapping_file", mapping_name)):
            path = task_root / skin_id / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"mock")
            assets[(skin_id, key)] = str(path)

    def fake_resolve(root, profile, key):
        return assets.get((profile["id"], key)) or original_resolve(root, profile, key)

    def fake_export(_task_id, current_root, _raw_path, person_idx=1):
        bvh_path = current_root / "retarget" / f"{task_id}_person{person_idx}.bvh"
        bvh_path.parent.mkdir(parents=True, exist_ok=True)
        bvh_path.write_text("HIERARCHY", encoding="utf-8")
        return bvh_path

    def fake_run(command, cwd, timeout_sec=None):
        del cwd, timeout_sec
        manifest_path = Path(command[-1])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        Path(manifest["output_mp4"]).write_bytes(b"dual-person-video")
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    try:
        intergen._export_intergen_bvh = fake_export
        intergen._run_subprocess = fake_run
        intergen.resolve_skin_resource = fake_resolve
        req = intergen.GenerateMotionRequest(
            text="Two people dance.",
            person_a_skin_id=person_skin_ids[0],
            person_b_skin_id=person_skin_ids[1],
            blender_executable=str(fake_blender),
        )
        intergen._run_intergen_retarget_if_requested(
            task_id=task_id,
            task_root=task_root / task_id,
            output_path=output_path,
            raw_joints_files=raw_paths,
            req=req,
        )
    finally:
        intergen._export_intergen_bvh = original_export
        intergen._run_subprocess = original_run
        intergen.resolve_skin_resource = original_resolve

    manifest_path = task_root / task_id / "retarget" / "retarget_manifest.json"
    assert manifest_path.is_file(), intergen._tasks[task_id].retarget_message
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["person_skin_ids"] == person_skin_ids
    assert manifest["source_preview_mp4"] is None
    assert [Path(path).name for path in manifest["target_fbx_files"]] == [
        "Aj (1).fbx",
        "Ch09_nonPBR (1).fbx",
    ]
    assert [Path(path).name for path in manifest["mapping_files"]] == [
        "mapping.json",
        "mapping6.json",
    ]
    assert intergen._tasks[task_id].retarget_status == "succeeded"

    smpl_profiles = intergen._resolve_person_skin_profiles(
        intergen.GenerateMotionRequest(
            text="Two people dance.",
            person_a_skin_id="smpl",
            person_b_skin_id="smpl",
        )
    )
    assert [profile["id"] for profile in smpl_profiles] == ["smpl", "smpl"]

    mixed_person_request = intergen.GenerateMotionRequest(
        text="Two people dance.",
        person_a_skin_id="smpl",
        person_b_skin_id="robot",
    )
    try:
        intergen._resolve_person_skin_profiles(mixed_person_request)
    except intergen.SkinCatalogError:
        pass
    else:
        raise AssertionError("Mixed SMPL and FBX person skins must be rejected")

    try:
        intergen._validate_request_skins(mixed_person_request)
    except intergen.HTTPException as exc:
        assert exc.status_code == 422
    else:
        raise AssertionError("Mixed SMPL and FBX person skins must return HTTP 422")

    return {
        "person_skin_ids": manifest["person_skin_ids"],
        "target_fbx_files": [Path(path).name for path in manifest["target_fbx_files"]],
        "mapping_files": [Path(path).name for path in manifest["mapping_files"]],
        "smpl_pair_supported": True,
        "mixed_smpl_fbx_rejected": True,
        "mixed_smpl_fbx_http_status": 422,
        "retarget_status": intergen._tasks[task_id].retarget_status,
    }


def test_intergen_default_motion_frames(intergen):
    model = object.__new__(intergen.LitGenModel)
    env_keys = (
        "INTERGEN_DEFAULT_MOTION_FRAMES",
        "INTERGEN_MIN_MOTION_FRAMES",
        "INTERGEN_MAX_MOTION_FRAMES",
        "INTERGEN_MOTION_FRAMES",
    )
    original_env = {key: os.environ.get(key) for key in env_keys}
    try:
        os.environ["INTERGEN_MIN_MOTION_FRAMES"] = "180"
        os.environ["INTERGEN_MAX_MOTION_FRAMES"] = "210"
        os.environ["INTERGEN_MOTION_FRAMES"] = "180"

        resolved_defaults = {}
        for frames in (180, 300, 360):
            os.environ["INTERGEN_DEFAULT_MOTION_FRAMES"] = str(frames)
            resolved = model._resolve_window_size("identical prompt", None)
            assert resolved == frames
            resolved_defaults[str(frames)] = resolved

        os.environ["INTERGEN_DEFAULT_MOTION_FRAMES"] = "360"
        assert model._resolve_window_size("identical prompt", 180) == 180
        assert model._resolve_window_size("identical prompt", 200) == 200
        return {
            "resolved_defaults": resolved_defaults,
            "explicit_180_overrides_default_360": True,
            "explicit_200_overrides_default_360": True,
        }
    finally:
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_motionlint_candidate_ranking(intergen):
    candidates = [
        {"candidate_index": 1, "motionlint": {"overall_score": 70}, "self_collision": {"hard_violation_count": 0}},
        {"candidate_index": 2, "motionlint": {"overall_score": 85}, "self_collision": {"hard_violation_count": 0}},
        {"candidate_index": 3, "motionlint": {"overall_score": 99}, "self_collision": {"hard_violation_count": 1}},
    ]
    assert intergen._pick_best_candidate(candidates)["candidate_index"] == 2
    return {"higher_motionlint_score_selected": True, "hard_collision_still_rejected": True}


def main():
    compile(
        (REPO_ROOT / "LODGE_api" / "blender_rokoko_retarget.py").read_text(encoding="utf-8"),
        "LODGE_api/blender_rokoko_retarget.py",
        "exec",
    )
    lodge = load_module("lodge_api_skin_test", "LODGE_api/lodge_async_api.py")
    intergen = load_module("intergen_api_skin_test", "InterGen_api/intergen_async_api.py")
    with tempfile.TemporaryDirectory(prefix="human_action_skin_test_") as temp_dir:
        intergen.DEFAULT_TASK_ROOT = Path(temp_dir)
        results = {
            "contract_resolution": {
                "explicit_smpl_overrides_legacy_flag": [
                    profile["id"]
                    for profile in resolve_skins(
                        REPO_ROOT,
                        ["smpl"],
                        legacy_retarget_enabled=True,
                    )
                ],
                "legacy_retarget_requests_both": [
                    profile["id"]
                    for profile in resolve_skins(
                        REPO_ROOT,
                        None,
                        legacy_retarget_enabled=True,
                    )
                ],
            },
            "catalog_resources": test_catalog_resources(),
            "lodge_execution_plan": test_lodge_plans(lodge),
            "intergen_mock_outputs": test_intergen_outputs(intergen),
            "intergen_retarget_only_generation": (
                test_intergen_service_retarget_only_skips_candidate_mp4(
                    intergen,
                    Path(temp_dir),
                )
            ),
            "intergen_candidate_audit": test_intergen_candidate_audit_retains_all_samples(
                intergen,
                Path(temp_dir),
            ),
            "intergen_candidate_audit_review": test_intergen_candidate_audit_review_contract(
                intergen,
                Path(temp_dir),
            ),
            "intergen_person_skin_manifest": test_intergen_person_skin_manifest(
                intergen,
                Path(temp_dir),
            ),
            "intergen_default_motion_frames": test_intergen_default_motion_frames(intergen),
            "motionlint_candidate_ranking": test_motionlint_candidate_ranking(intergen),
        }
    assert results["contract_resolution"]["explicit_smpl_overrides_legacy_flag"] == ["smpl"]
    assert results["contract_resolution"]["legacy_retarget_requests_both"] == ["smpl", "robot"]
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
