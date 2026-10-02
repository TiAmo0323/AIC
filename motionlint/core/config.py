"""Load and validate MotionLint's versioned quality policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import math

import yaml


DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "configs" / "default_quality.yaml"


def load_config(path: str | Path = DEFAULT_CONFIG) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError("Quality config must be a mapping")
    def validate_numbers(value):
        if isinstance(value, dict):
            for item in value.values():
                validate_numbers(item)
        elif isinstance(value, list):
            for item in value:
                validate_numbers(item)
        elif isinstance(value, (int, float)) and not math.isfinite(value):
            raise ValueError("Quality config contains NaN or Inf")
    validate_numbers(config)
    tests = config.get("tests")
    if not isinstance(tests, dict) or not tests:
        raise ValueError("Quality config must define tests")
    weights = []
    for name, settings in tests.items():
        if not isinstance(settings, dict) or "weight" not in settings:
            raise ValueError(f"Test {name} must define a weight")
        weight = float(settings["weight"])
        if not math.isfinite(weight) or weight < 0:
            raise ValueError(f"Test {name} has a negative weight")
        weights.append(weight)
    if abs(sum(weights) - 1.0) > 1e-6:
        raise ValueError("Quality test weights must sum to 1")
    for section in ("version", "gate", "regression", "repairs"):
        if section not in config:
            raise ValueError(f"Quality config must define {section}")
    return config
