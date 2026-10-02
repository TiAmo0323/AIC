"""Content hashes for rules and input files."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import numpy as np


def rule_hash(config: dict) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def input_hashes(metadata: dict) -> dict:
    paths = metadata.get("source_paths") or [metadata.get("source_path")]
    return {str(path): hashlib.sha256(Path(path).read_bytes()).hexdigest()
            for path in paths if path and Path(path).is_file()}


def evaluated_array_hashes(motion) -> dict:
    """Identify the actual candidate, even if its source file is the original."""
    result = {}
    for name in ('positions','rotation_matrices','root_translation','contacts'):
        value = getattr(motion, name)
        if value is not None:
            array = np.ascontiguousarray(value)
            header = json.dumps({'shape':array.shape,'dtype':array.dtype.str},sort_keys=True).encode()
            result[name] = hashlib.sha256(header + array.tobytes()).hexdigest()
    return result
