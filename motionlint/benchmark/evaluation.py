"""One-to-one interval matching and sample-level bootstrap intervals."""
from __future__ import annotations
import numpy as np


def iou(first, second):
    overlap = max(0, min(first["end_frame"], second["end_frame"]) - max(first["start_frame"], second["start_frame"]) + 1)
    union = max(first["end_frame"], second["end_frame"]) - min(first["start_frame"], second["start_frame"]) + 1
    return overlap / union


def merge_events(events):
    result = []
    groups = {}
    for event in events:
        if event.get("uncertain"):
            continue
        groups.setdefault((event["test_name"], event.get("actor_id")), []).append(event)
    for values in groups.values():
        current = None
        for event in sorted(values, key=lambda e: (e["start_frame"], e["end_frame"])):
            if current is not None and event["start_frame"] <= current["end_frame"] + 1:
                current["end_frame"] = max(current["end_frame"], event["end_frame"])
            else:
                current = dict(event)
                result.append(current)
    return result


def match_events(truth, predictions, threshold=.5):
    """Maximum-cardinality bipartite matching, not a greedy overlap count."""
    truth, predictions = merge_events(truth), merge_events(predictions)
    edges = [[j for j,p in sorted(enumerate(predictions), key=lambda x: -iou(event,x[1]))
              if p["test_name"] == event["test_name"] and p.get("actor_id") == event.get("actor_id") and iou(event,p) >= threshold]
             for event in truth]
    matched = {}
    def augment(index, visited):
        for candidate in edges[index]:
            if candidate in visited:
                continue
            visited.add(candidate)
            if candidate not in matched or augment(matched[candidate], visited):
                matched[candidate] = index
                return True
        return False
    for index in range(len(truth)):
        augment(index, set())
    return {"tp": len(matched), "fp": len(predictions)-len(matched), "fn": len(truth)-len(matched)}


def metrics(rows):
    tp, fp, fn = (sum(row[key] for row in rows) for key in ("tp", "fp", "fn"))
    return {"tp": tp, "fp": fp, "fn": fn, "precision": tp/(tp+fp) if tp+fp else None,
            "recall": tp/(tp+fn) if tp+fn else None, "f1": 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None}


def bootstrap(rows, seed=42000, repeats=1000):
    if not rows:
        return {}
    rng = np.random.default_rng(seed)
    estimates = [metrics([rows[i] for i in rng.integers(0,len(rows),len(rows))]) for _ in range(repeats)]
    return {key: np.percentile([e[key] for e in estimates if e[key] is not None],[2.5,97.5]).tolist()
            for key in ("precision", "recall", "f1") if any(e[key] is not None for e in estimates)}
