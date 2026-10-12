"""Verify local candidate artifacts and disclose outstanding remote delivery gates.

This reads frozen results; it never recalibrates rules or runs the held-out set.
Exit codes: 0 all required gates verified, 1 outstanding/failed gates, 2 input error.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile

from motionlint_050_privacy import CREDENTIAL, private_path_fields

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def pointer(value, path):
    for part in path.split("/")[1:]:
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def verify(out):
    result = load(ROOT / "evidence/iteration-050-results.json")
    audit = load(ROOT / "evidence/iteration-050-release-audit.json")
    video = load(ROOT / "evidence/iteration-050-video-validation.json")
    pdf = load(ROOT / "output/pdf/report-validation.json")
    release = load(out / "RELEASE_MANIFEST.json")
    checks = []

    def check(name, condition, actual, target):
        checks.append({"name": name, "status": "PASS" if condition else "FAIL",
                       "actual": actual, "target": target})

    controlled = result["controlled"]
    per_class = {key: value["f1"] for key, value in controlled["per_class"].items()}
    check("known_defect_detection", controlled["macro_f1"] >= .95 and len(per_class) == 6
          and min(per_class.values()) >= .90,
          {"macro_f1": controlled["macro_f1"], "per_class_f1": per_class},
          {"macro_f1_min": .95, "per_class_min": .90, "scope": "analytic injected defects only"})
    check("normal_high_severity_false_positives",
          controlled["normal_high_severity_false_positive_fraction"] <= .02,
          controlled["normal_high_severity_false_positive_fraction"], {"maximum_fraction": .02})
    check("event_and_joint_localization_policy", "IoU >= 0.5" in controlled["event_policy"]
          and "one-to-one" in controlled["event_policy"],
          {"policy": controlled["event_policy"], "joint_recall": controlled["joint_localization_recall"]},
          "Same type/actor, IoU >= 0.5, one-to-one matching; joint localization separately disclosed")
    before, after = result["baseline"], result["candidate_baseline"]
    delta = after["median_support_distance_reduction_ratio"] - before["median_support_distance_reduction_ratio"]
    check("same_v4_baseline_preservation", after["injected_gate_pass_count"] >= before["injected_gate_pass_count"]
          and delta >= -result["baseline_float_comparison_tolerance"],
          {"old_passes": before["injected_gate_pass_count"], "new_passes": after["injected_gate_pass_count"],
           "old_median": before["median_support_distance_reduction_ratio"],
           "new_median": after["median_support_distance_reduction_ratio"], "floating_point_delta": delta},
          {"strict_pass_min": before["injected_gate_pass_count"],
           "numerical_equivalence_tolerance": result["baseline_float_comparison_tolerance"],
           "quality_thresholds_relaxed": False})
    repair = result["repairable_holdout"]
    check("predeclared_repairable_subset", repair["count"] == 54
          and repair["median_original_support_distance_reduction_ratio"] >= .5
          and repair["all_attempts_in_denominator"], repair,
          {"median_reduction_min": .5, "all_predeclared_attempts_counted": True})
    check("safety_counterexamples", result["safety"]["passed_count"] == result["safety"]["count"] == 60,
          result["safety"], "All 60 predeclared adverse checks pass")
    check("input_and_normal_control_protection", audit["protected_sample_count"] == audit["unchanged_sample_count"] == 720
          and repair["input_hashes_unchanged"] and repair["normal_controls_unchanged_count"] == 36
          and after["clean_unchanged_count"] == 30,
          {"protected": audit["protected_sample_count"], "unchanged": audit["unchanged_sample_count"],
           "development_normal_unchanged": after["clean_unchanged_count"],
           "holdout_normal_unchanged": repair["normal_controls_unchanged_count"]},
          "720 unchanged inputs; 30 development and 36 holdout normal repairs unchanged")
    bvh_rows = audit["bvh_roundtrips"]
    bvh_error = max(row["max_coordinate_error_m"] for row in bvh_rows)
    check("written_bvh_roundtrip", len(bvh_rows) == 24 and bvh_error <= .0001
          and all(row["hierarchy_channels_rotation_order_fps_preserved"] for row in bvh_rows),
          {"count": len(bvh_rows), "max_error_m": bvh_error}, "24 files, <= 0.1mm, hierarchy/order/FPS preserved")
    flows = result["flows"]
    check("six_actual_flows", len(flows) == result["complete_flow_ready_count"] == 6
          and all(row["status"] == "ready" and len(row["gates"]) == 4
                  and row["video_verification"]["fully_decoded"] for row in flows),
          {"ready": result["complete_flow_ready_count"],
           "cross_stage_skeleton_pass": result["complete_flow_quality_pass_count"],
           "mesh_metrics_reported_separately": True},
          "6 predeclared actual four-stage flows; quality FAIL is allowed and retained")
    check("performance", result["performance"]["same_rule_v4_detection_cost_ratio"] <= 1.25,
          result["performance"]["same_rule_v4_detection_cost_ratio"], {"maximum_ratio": 1.25})

    wheel = out / "motionlint-0.5.0-py3-none-any.whl"
    wheel_hash = digest(wheel)
    local_rows = result["local_wheel"]["rows"]
    local_combinations = {(row["python"].split()[0].rsplit(".", 1)[0], row["optimize"]) for row in local_rows}
    expected_combinations = {("3.10", False), ("3.10", True), ("3.11", False), ("3.11", True)}
    check("windows_external_wheel_installations", local_combinations == expected_combinations
          and all(row["status"] == "PASS" and row["source_imports_excluded"]
                  and row["wheel_sha256"] == wheel_hash for row in local_rows),
          {"platform": "Windows", "configurations": len(local_rows), "wheel_sha256": wheel_hash},
          "Python 3.10/3.11 x core/optimize, outside checkout; does not claim Linux")
    check("actual_browser_flows", result["browser"]["status"] == "PASS"
          and len(result["browser"]["checks"]) == 6
          and all(row["status"] == "PASS" for row in result["browser"]["checks"]),
          {"status": result["browser"]["status"], "checks": len(result["browser"]["checks"])},
          "6 actual browser scenarios on the current packaged workbench")
    check("dependency_audit", result["dependency_audit"]["known_vulnerabilities"] == 0
          and result["frontend_dependency_audit"]["vulnerabilities"]["total"] == 0,
          {"python": result["dependency_audit"]["known_vulnerabilities"],
           "frontend": result["frontend_dependency_audit"]["vulnerabilities"]["total"]},
          "No known advisories in this recorded audit snapshot")
    check("formal_pdf", pdf["pages"] <= 15 and pdf["report_bytes"] <= 10 * 1024 * 1024
          and not pdf["private_path_or_identity_hits"],
          {"pages": pdf["pages"], "bytes": pdf["report_bytes"]}, "<=15 pages, <=10MB; identity/path scan")
    check("actual_video", video["status"] == "PASS" and video["fully_decoded"]
          and video["has_fully_decoded_audio"] and 180 <= video["duration_seconds"] <= 300
          and video["bytes"] <= 300 * 1024 * 1024,
          {"duration_seconds": video["duration_seconds"], "bytes": video["bytes"],
           "captured_frames": video["captured_browser_frame_count"], "recorded_frontend_commit": video["recorded_frontend_commit"]},
          "3-5 minutes, <=300MB, actual screen recording, full audio/video decode")

    bad_sources = [key for key, source in result["source_results"].items()
                   if digest(ROOT / source["relative_path"]) != source["sha256"]]
    check("frozen_result_source_hashes", not bad_sources, {"checked": len(result["source_results"]),
          "mismatched": bad_sources}, "Every source result matches the generated result index")
    claims = load(ROOT / "evidence/iteration-050-claims.json")
    claim_checks = {}
    for name, item in claims.items():
        value = pointer(load(ROOT / item["json_file"]), item["json_pointer"])
        claim_checks[name] = {"resolved": value is not None,
                             "rules_match": item["rules_sha256"] == result["rules_sha256"],
                             "freeze_matches": item["code_freeze_sha256"] == result["freeze_sha256"]}
    check("claim_field_links", len(claim_checks) == 7
          and all(all(row.values()) for row in claim_checks.values()), claim_checks,
          "All 7 published conclusion links resolve to this rule and frozen code")

    archive_checks = []
    for artifact in release["artifacts"]:
        path = out / artifact["file"]
        if digest(path) != artifact["sha256"]:
            raise ValueError("Artifact manifest hash mismatch: " + path.name)
        if path.suffix not in {".zip", ".whl"}:
            continue
        is_evidence = path.name.endswith("evidence.zip")
        with ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise ValueError("Archive CRC failed: " + path.name)
            entries = archive.namelist()
            if len(entries) != len(set(entries)):
                raise ValueError("Duplicate archive entries: " + path.name)
            content_index = load_archive(archive, "CONTENT_MANIFEST.json") if path.suffix == ".zip" else None
            expected = {row["path"]: row for row in content_index["files"]} if content_index else {}
            for name in entries:
                if name.startswith("/") or ".." in Path(name).parts:
                    raise ValueError("Unsafe archive path")
                content = archive.read(name)
                if CREDENTIAL.search(content):
                    raise ValueError("Credential-like content in archive entry: " + name)
                if name in expected and hashlib.sha256(content).hexdigest() != expected[name]["sha256"]:
                    raise ValueError("Archive entry hash mismatch: " + name)
                if is_evidence and name.endswith(".json") and private_path_fields(json.loads(content)):
                    raise ValueError("Private local path in public evidence entry: " + name)
                if is_evidence and Path(name).suffix.lower() in {".npy", ".npz", ".bvh", ".fbx", ".blend", ".ckpt", ".pth", ".pt"}:
                    raise ValueError("Restricted raw resource in public evidence")
                if path.name.endswith("source-candidate.zip") and name in expected and (ROOT / name).is_file():
                    if digest(ROOT / name) != expected[name]["sha256"]:
                        raise ValueError("Source archive differs from candidate worktree: " + name)
            if expected and not set(expected).issubset(entries):
                raise ValueError("Missing content-manifest entry")
            archive_checks.append({"file": path.name, "entries": len(entries), "status": "PASS"})
    check("archive_contents_and_privacy", True, archive_checks,
          "CRC/SHA, credentials, all dictionary keys/values, no raw restricted evidence, current source")

    hashes = []
    for line in (out / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        expected, name = line.split("  ", 1)
        if digest(out / name) != expected:
            raise ValueError("Outer checksum mismatch: " + name)
        hashes.append(name)
    check("delivery_checksum_list", True, {"checked_files": len(hashes)}, "All listed files verified")

    local_ok = all(item["status"] == "PASS" for item in checks)
    # A previous commit's green status cannot satisfy this gate. No remote result
    # is invented when the candidate has not been pushed with sufficient rights.
    pending = [{"name": "current_commit_remote_windows_linux_matrix", "status": "NOT_VERIFIED",
                "reason": result["remote_ci"]["reason"]},
               {"name": "team_and_inherited_code_rights", "status": "REVIEW_PENDING",
                "reason": "No automatic team signature or project-wide MIT license claim"}]
    receipt = {"schema_version": 3,
               "status": "LOCAL_PASS_REMOTE_DELIVERY_PENDING" if local_ok else "LOCAL_ACCEPTANCE_FAILED",
               "version": "0.5.0", "local_checks": checks, "pending": pending,
               "source_results_sha256": digest(ROOT / "evidence/iteration-050-results.json"),
               "release_manifest_sha256": digest(out / "RELEASE_MANIFEST.json"),
               "quality_limits": result["limitations"],
               "contact_hash_timing": "Contact-file SHA separately recorded at release, not a pre-test receipt"}
    target = out / "ACCEPTANCE.json"
    target.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sums = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "SHA256SUMS.txt")
    (out / "SHA256SUMS.txt").write_text("".join(digest(p) + "  " + p.relative_to(out).as_posix() + "\n" for p in sums), encoding="utf-8")
    print(receipt["status"], "-", sum(row["status"] == "PASS" for row in checks), "/", len(checks), "local checks")
    return 1


def load_archive(archive, name):
    return json.loads(archive.read(name))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    try:
        return verify(args.candidate.resolve())
    except (ValueError, KeyError, OSError, AssertionError) as error:
        print("Delivery verification error:", error, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
