"""【离线实验工具，未应用于实际生产逻辑链路】提交可复算的 Planner/InterGen 对照。

脚本默认只做 dry-run；只有显式传入 --submit 才创建真实任务。结果保存任务 ID 和
API 快照，大型产物留在 task_runs，不参与生产前端请求。
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES = REPO_ROOT / "InterGen_api" / "experiments" / "motion_r1_phase0_prompts.json"
DEFAULT_RECORD_DATA = (
    REPO_ROOT
    / "docs"
    / "project-growth"
    / "architecture-upgrades"
    / "motion-r1-intergen"
    / "records"
    / "2026-07-27-phase0-planner-foundation"
    / "data"
)
TERMINAL_STATUSES = {"succeeded", "failed"}


def _write_json_atomic(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def _json_request(url: str, method: str = "GET", payload: Optional[Dict[str, object]] = None):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _variant_payload(case: Dict[str, object], variant: str) -> Dict[str, object]:
    if variant == "baseline":
        return {"planner_enabled": False}
    if variant == "flat-baseline":
        flat_prompt = case.get("flat_prompt")
        if not flat_prompt:
            raise ValueError(f"Case {case['id']} does not define flat_prompt")
        return {
            "text": flat_prompt,
            "translation_required": False,
            "planner_enabled": False,
        }
    if variant == "manual-plan":
        manual_plan = case.get("manual_plan")
        if not manual_plan:
            raise ValueError(f"Case {case['id']} does not define manual_plan")
        return {"planner_enabled": False, "motion_plan": manual_plan}
    if variant == "planner-api":
        return {"planner_enabled": True, "planner_required": True}
    raise ValueError(f"Unsupported variant: {variant}")


def build_jobs(
    suite: Dict[str, object],
    variants: Iterable[str],
    seeds: Iterable[int],
    case_ids: Iterable[str],
) -> List[Dict[str, object]]:
    selected_ids = set(case_ids)
    jobs: List[Dict[str, object]] = []
    group = f"{suite['name']}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    for case in suite["cases"]:
        if selected_ids and case["id"] not in selected_ids:
            continue
        for variant in variants:
            if variant == "manual-plan" and not case.get("manual_plan"):
                continue
            if variant == "flat-baseline" and not case.get("flat_prompt"):
                continue
            for seed in seeds:
                payload: Dict[str, object] = {
                    "text": case["text"],
                    "skin_ids": ["smpl"],
                    "num_samples": int(suite.get("default_num_samples", 5)),
                    "seed": int(seed),
                    "experiment_group": group,
                    "experiment_variant": f"{case['id']}-{variant}",
                    "translation_required": True,
                }
                payload.update(_variant_payload(case, variant))
                jobs.append(
                    {
                        "case_id": case["id"],
                        "bucket": case["bucket"],
                        "variant": variant,
                        "seed": int(seed),
                        "expected": case.get("expected", []),
                        "payload": payload,
                    }
                )
    return jobs


def run_jobs(
    api_base: str,
    jobs: List[Dict[str, object]],
    poll_seconds: float,
    output: Path,
    run_manifest: Dict[str, object],
) -> List[Dict[str, object]]:
    results: List[Dict[str, object]] = []
    api_base = api_base.rstrip("/")

    def checkpoint() -> None:
        terminal_jobs = sum(
            1
            for item in results
            if item.get("error")
            or (item.get("task") or {}).get("status") in TERMINAL_STATUSES
        )
        _write_json_atomic(
            output,
            {
                **run_manifest,
                "run_status": "running",
                "submitted_jobs": len(results),
                "completed_jobs": terminal_jobs,
                "results": results,
            },
        )

    for index, job in enumerate(jobs, start=1):
        print(
            f"[{index}/{len(jobs)}] submit case={job['case_id']} "
            f"variant={job['variant']} seed={job['seed']}"
        )
        current: Dict[str, object] = {**job}
        try:
            task = _json_request(
                f"{api_base}/v1/intergen/tasks/generate",
                method="POST",
                payload=job["payload"],
            )
            current["task"] = task
            results.append(current)
            checkpoint()
            task_id = task["task_id"]
            while task.get("status") not in TERMINAL_STATUSES:
                time.sleep(poll_seconds)
                task = _json_request(f"{api_base}/v1/intergen/tasks/{task_id}")
                current["task"] = task
                checkpoint()
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
            current["error"] = str(exc)
            if current not in results:
                results.append(current)
        checkpoint()
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--api-base", default="http://127.0.0.1:8001")
    parser.add_argument(
        "--variant",
        action="append",
        choices=["baseline", "flat-baseline", "manual-plan", "planner-api"],
        help="Repeat to select variants; default is baseline only.",
    )
    parser.add_argument("--seed", type=int, action="append", help="Repeat to override suite seeds.")
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--poll-seconds", type=float, default=3.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--submit", action="store_true", help="Create real tasks; otherwise print a dry run.")
    args = parser.parse_args()

    suite = json.loads(args.cases.read_text(encoding="utf-8"))
    variants = args.variant or ["baseline"]
    seeds = args.seed or suite["default_seeds"]
    jobs = build_jobs(suite, variants, seeds, args.case_id)
    if not jobs:
        raise SystemExit("No experiment jobs matched the requested filters")

    run_manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "submit": args.submit,
        "suite_path": str(args.cases.resolve()),
        "job_count": len(jobs),
        "jobs": jobs,
    }
    print(json.dumps(run_manifest, ensure_ascii=False, indent=2))
    if not args.submit:
        if args.output:
            _write_json_atomic(args.output, run_manifest)
            print(f"Saved dry-run manifest: {args.output.resolve()}")
        return

    output = args.output or (
        DEFAULT_RECORD_DATA
        / f"phase0_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    _write_json_atomic(
        output,
        {
            **run_manifest,
            "run_status": "running",
            "submitted_jobs": 0,
            "completed_jobs": 0,
            "results": [],
        },
    )
    results = run_jobs(
        args.api_base,
        jobs,
        max(1.0, args.poll_seconds),
        output,
        run_manifest,
    )
    _write_json_atomic(
        output,
        {
            **run_manifest,
            "run_status": "completed",
            "submitted_jobs": len(results),
            "completed_jobs": len(results),
            "results": results,
        },
    )
    print(f"Saved experiment summary: {output}")


if __name__ == "__main__":
    main()
