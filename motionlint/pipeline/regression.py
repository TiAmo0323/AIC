"""Compare synchronized motions using the shared physical audit."""
from __future__ import annotations
from pathlib import Path
from motionlint.core.config import load_config
from motionlint.core.provenance import rule_hash
from motionlint.pipeline.safety import audit


def compare(baseline, candidate, *, config_path: str | Path | None = None,
            baseline_motion=None, candidate_motion=None) -> dict:
    config = load_config(config_path) if config_path is not None else load_config()
    for field, expected in {"config_version": config["version"], "config_sha256": rule_hash(config)}.items():
        old, new = baseline.metadata.get(field), candidate.metadata.get(field)
        if old is None or new is None or old != new:
            raise ValueError(f"Cannot compare different or missing {field}; re-inspect both inputs with the same policy")
        if old != expected:
            raise ValueError(f"Cannot compare reports with a different comparison policy ({field}); use the original policy or re-inspect both inputs")
    guard = audit(baseline, candidate, config, baseline_motion=baseline_motion, candidate_motion=candidate_motion)
    old = {t.test_name: t for t in baseline.tests}
    new = {t.test_name: t for t in candidate.tests}
    rows = []
    for name in config["tests"]:
        if name not in old or name not in new:
            continue
        unavailable = old[name].metrics.get("evaluation_status") == "unavailable"
        delta = None if unavailable else round(new[name].score - old[name].score, 2)
        reasons = [r for r in guard["regression_reasons"] if r.startswith(name + " ")]
        if unavailable:
            reasons = [r for r in guard["incomplete_reasons"] if r.startswith(name + " ")]
        rows.append({"test": name, "baseline": old[name].score, "candidate": new[name].score,
                     "change": delta, "status": "INCOMPARABLE" if unavailable else "REGRESSION" if reasons else "IMPROVED" if delta > 0 else "UNCHANGED",
                     "reasons": reasons})
    incomplete, regressions = guard["incomplete_reasons"], guard["regression_reasons"]
    return {"schema_version": 3, "status": "REGRESSION DETECTED" if regressions else "COMPARISON INCOMPLETE" if incomplete else "PASS",
            "overall_change": None if incomplete else round(candidate.overall_score - baseline.overall_score, 2),
            "tests": rows, "reasons": regressions + incomplete, "audit": guard,
            "evidence_type": "synchronized_arrays" if baseline_motion is not None and candidate_motion is not None else "reports_only"}
