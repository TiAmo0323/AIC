# 【实验测试，非生产链路验收】只验证规划 schema、提示词编译和实验清单等工程约束，
# 不证明规划器已被生产前端调用，也不证明生成动作的语义质量得到提升。
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from pydantic import ValidationError


REPO_ROOT = Path(__file__).resolve().parents[1]
INTERGEN_API_ROOT = REPO_ROOT / "InterGen_api"
if str(INTERGEN_API_ROOT) not in sys.path:
    sys.path.insert(0, str(INTERGEN_API_ROOT))

from motion_planner import (  # noqa: E402
    MotionPlan,
    MotionPlannerError,
    PlannerSettings,
    _clip_body_token_count,
    compile_intergen_prompt,
    parse_motion_plan,
)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from scripts.motion_r1 import run_phase0_baseline as phase0_runner  # noqa: E402


VALID_PLAN = {
    "action": "badminton serve",
    "duration_seconds": 6.5,
    "actor_a": [
        {
            "phase": "prepare",
            "time": [0.0, 0.25],
            "motion": "stand sideways and raise the serving arm",
            "body_parts": ["torso", "arm"],
        },
        {
            "phase": "serve",
            "time": [0.25, 0.75],
            "motion": "shift weight forward and swing one arm overhead",
            "body_parts": ["legs", "torso", "arm"],
        },
    ],
    "actor_b": [
        {
            "phase": "ready",
            "time": [0.0, 0.7],
            "motion": "face person A in a ready stance",
            "body_parts": ["legs", "arms"],
        },
        {
            "phase": "react",
            "time": [0.7, 1.0],
            "motion": "take a small step toward the incoming direction",
            "body_parts": ["legs"],
        },
    ],
    "interaction": {
        "facing": True,
        "physical_contact": False,
        "relative_distance": "far",
        "relation": "serve and receive",
    },
}


FOUR_PHASE_BADMINTON_PLAN = {
    "action": "Two people playing badminton",
    "duration_seconds": 6.0,
    "actor_a": [
        {
            "phase": "serve",
            "time": [0.0, 0.3],
            "motion": "right hand swings racket forward and upward to strike shuttlecock; left foot steps forward, weight shifts forward",
            "body_parts": ["right arm", "right wrist", "left leg", "torso"],
        },
        {
            "phase": "recover",
            "time": [0.3, 0.6],
            "motion": "returns to ready stance: knees bent, racket held in front, weight balanced on balls of feet",
            "body_parts": ["arms", "knees", "feet", "torso"],
        },
    ],
    "actor_b": [
        {
            "phase": "receive",
            "time": [0.2, 0.5],
            "motion": "tracks shuttlecock with eyes, steps sideways with right foot, extends racket arm to intercept shuttlecock",
            "body_parts": ["eyes", "right leg", "right arm", "shoulders"],
        },
        {
            "phase": "return",
            "time": [0.5, 0.8],
            "motion": "swings racket upward and backward to lift shuttlecock deep into opponent's court",
            "body_parts": ["right arm", "wrist", "torso", "left leg"],
        },
    ],
    "interaction": {
        "facing": True,
        "physical_contact": False,
        "relative_distance": "medium",
        "relation": "opponents across net; shuttlecock trajectory defines temporal coordination",
    },
}


@contextmanager
def expect_exception(exception_type, message_fragment=""):
    try:
        yield
    except exception_type as exc:
        if message_fragment:
            assert message_fragment in str(exc)
    else:
        raise AssertionError(f"Expected {exception_type.__name__}")


def test_motion_plan_and_compiler_are_role_aware():
    plan = MotionPlan.parse_obj(VALID_PLAN)
    for max_words in (24, 48):
        prompt = compile_intergen_prompt(plan, max_words=max_words)
        assert prompt.startswith("Two people")
        assert "Person A" in prompt
        assert "Person B" in prompt
        assert "maintain spacing" in prompt
        assert "without physical contact" in prompt
        assert _clip_body_token_count(prompt) <= 75
        for phase in ("prepare", "serve", "ready", "react"):
            assert f"{phase}:" in prompt


def test_compiler_covers_every_phase_before_expanding_details():
    plan = MotionPlan.parse_obj(FOUR_PHASE_BADMINTON_PLAN)
    prompt = compile_intergen_prompt(plan, max_words=48)

    for phase in ("serve", "recover", "receive", "return"):
        assert f"{phase}:" in prompt
    assert prompt.index("serve:") < prompt.index("recover:")
    assert prompt.index("receive:") < prompt.index("return:")
    assert "face each other" in prompt
    assert "without physical contact" in prompt
    assert _clip_body_token_count(prompt) <= 75


def test_motion_plan_rejects_invalid_time_and_order():
    invalid = json.loads(json.dumps(VALID_PLAN))
    invalid["actor_a"][0]["time"] = [0.8, 0.2]
    with expect_exception(ValidationError):
        MotionPlan.parse_obj(invalid)

    invalid = json.loads(json.dumps(VALID_PLAN))
    invalid["actor_a"] = list(reversed(invalid["actor_a"]))
    with expect_exception(ValidationError):
        MotionPlan.parse_obj(invalid)


def test_parse_motion_plan_accepts_json_fence():
    content = "```json\n" + json.dumps(VALID_PLAN) + "\n```"
    plan = parse_motion_plan(content)
    assert plan.action == "badminton serve"


def test_planner_settings_require_key():
    keys = (
        "INTERGEN_MOTION_PLANNER_PROVIDER",
        "INTERGEN_MOTION_PLANNER_API_KEY",
        "DASHSCOPE_API_KEY",
    )
    original = {key: os.environ.get(key) for key in keys}
    try:
        os.environ["INTERGEN_MOTION_PLANNER_PROVIDER"] = "dashscope"
        os.environ.pop("INTERGEN_MOTION_PLANNER_API_KEY", None)
        os.environ.pop("DASHSCOPE_API_KEY", None)
        with expect_exception(MotionPlannerError, "API key"):
            PlannerSettings.from_env()
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_planner_settings_reject_invalid_numeric_env():
    keys = (
        "INTERGEN_MOTION_PLANNER_PROVIDER",
        "INTERGEN_MOTION_PLANNER_API_KEY",
        "INTERGEN_MOTION_PLANNER_TIMEOUT_SEC",
    )
    original = {key: os.environ.get(key) for key in keys}
    try:
        os.environ["INTERGEN_MOTION_PLANNER_PROVIDER"] = "dashscope"
        os.environ["INTERGEN_MOTION_PLANNER_API_KEY"] = "test-only"
        os.environ["INTERGEN_MOTION_PLANNER_TIMEOUT_SEC"] = "invalid"
        with expect_exception(MotionPlannerError, "must be numeric"):
            PlannerSettings.from_env()
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_phase0_suite_is_valid():
    suite_path = INTERGEN_API_ROOT / "experiments" / "motion_r1_phase0_prompts.json"
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    assert suite["schema_version"] == 1
    assert len(suite["default_seeds"]) >= 3
    ids = {case["id"] for case in suite["cases"]}
    assert {"id-tai-chi-control", "ood-badminton-serve"}.issubset(ids)
    badminton = next(case for case in suite["cases"] if case["id"] == "ood-badminton-serve")
    assert len(badminton["flat_prompt"].split()) <= 24
    plan = MotionPlan.parse_obj(badminton["manual_plan"])
    prompt = compile_intergen_prompt(plan, max_words=48)
    for phase in plan.actor_a + plan.actor_b:
        assert f"{phase.phase}:" in prompt
    assert _clip_body_token_count(prompt) <= 75


def test_experiment_runner_checkpoints_results():
    jobs = [
        {
            "case_id": "smoke",
            "bucket": "test",
            "variant": "baseline",
            "seed": seed,
            "expected": [],
            "payload": {"text": "Two people wave.", "seed": seed},
        }
        for seed in (1, 2)
    ]
    original_request = phase0_runner._json_request
    counter = {"value": 0}

    def fake_request(_url, method="GET", payload=None):
        del payload
        if method == "POST":
            counter["value"] += 1
            return {"task_id": f"task-{counter['value']}", "status": "succeeded"}
        raise AssertionError("A succeeded task must not be polled")

    try:
        phase0_runner._json_request = fake_request
        with tempfile.TemporaryDirectory(prefix="phase0_runner_test_") as temp_dir:
            output = Path(temp_dir) / "results.json"
            results = phase0_runner.run_jobs(
                "http://test.invalid",
                jobs,
                0.0,
                output,
                {"schema_version": 1, "job_count": len(jobs)},
            )
            saved = json.loads(output.read_text(encoding="utf-8"))
    finally:
        phase0_runner._json_request = original_request

    assert len(results) == 2
    assert saved["run_status"] == "running"
    assert saved["submitted_jobs"] == 2
    assert saved["completed_jobs"] == 2
    assert [item["task"]["task_id"] for item in saved["results"]] == ["task-1", "task-2"]


def main():
    tests = [
        test_motion_plan_and_compiler_are_role_aware,
        test_compiler_covers_every_phase_before_expanding_details,
        test_motion_plan_rejects_invalid_time_and_order,
        test_parse_motion_plan_accepts_json_fence,
        test_planner_settings_require_key,
        test_planner_settings_reject_invalid_numeric_env,
        test_phase0_suite_is_valid,
        test_experiment_runner_checkpoints_results,
    ]
    for test in tests:
        test()
    print(json.dumps({"status": "passed", "tests": [test.__name__ for test in tests]}, indent=2))


if __name__ == "__main__":
    main()
