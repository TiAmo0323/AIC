"""Install a user-downloaded official SMPL-X model archive into local runtime.

Usage: python scripts/install_smplx_model.py C:\\Users\\you\\Downloads\\models_smplx.zip
The model files remain outside the Git repository.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path


MODEL_NAMES = {
    "SMPLX_NEUTRAL.npz",
    "SMPLX_MALE.npz",
    "SMPLX_FEMALE.npz",
}
RUNTIME_MODEL_DIR = (
    Path(__file__).resolve().parents[2]
    / "HumanAction-runtime"
    / "InterGen"
    / "InterGen_master"
    / "human_models"
    / "smplx"
)


def _validate_npz(path: Path) -> None:
    if not zipfile.is_zipfile(path):
        raise ValueError(f"Not a valid NPZ file: {path}")
    with zipfile.ZipFile(path) as model:
        names = {Path(name).name for name in model.namelist()}
        required = {"v_template.npy", "shapedirs.npy", "posedirs.npy", "J_regressor.npy", "weights.npy", "f.npy"}
        missing = required - names
        if missing:
            raise ValueError(f"Incomplete SMPL-X model {path.name}: missing {sorted(missing)}")


def install(source: Path, destination: Path) -> list[Path]:
    if not source.exists():
        raise FileNotFoundError(source)

    if source.is_dir():
        candidates = [(path.name, path.open) for path in source.rglob("SMPLX_*.npz") if path.name in MODEL_NAMES]
        if not candidates:
            raise ValueError(f"No SMPL-X NPZ model files found in {source}")
        if not any(name == "SMPLX_NEUTRAL.npz" for name, _ in candidates):
            raise ValueError("SMPLX_NEUTRAL.npz is required")
        destination.mkdir(parents=True, exist_ok=True)
        installed = []
        for name, opener in candidates:
            target = destination / name
            with opener("rb") as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            _validate_npz(target)
            installed.append(target)
        return installed

    if source.suffix.lower() == ".npz":
        if source.name not in MODEL_NAMES:
            raise ValueError(f"Expected one of {sorted(MODEL_NAMES)}")
        _validate_npz(source)
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / source.name
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        return [target]

    if source.suffix.lower() != ".zip":
        raise ValueError("Provide the official ZIP, extracted directory, or SMPLX_NEUTRAL.npz")
    with zipfile.ZipFile(source) as archive:
        members = [info for info in archive.infolist() if Path(info.filename).name in MODEL_NAMES]
        if not members:
            raise ValueError(f"No SMPL-X NPZ model files found in {source}")
        if not any(Path(info.filename).name == "SMPLX_NEUTRAL.npz" for info in members):
            raise ValueError("SMPLX_NEUTRAL.npz is required")
        destination.mkdir(parents=True, exist_ok=True)
        installed = []
        for info in members:
            target = destination / Path(info.filename).name
            with archive.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            _validate_npz(target)
            installed.append(target)
        return installed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Official SMPL-X model ZIP, extracted directory, or neutral NPZ")
    args = parser.parse_args()
    try:
        installed = install(args.source.expanduser().resolve(), RUNTIME_MODEL_DIR)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"SMPL-X installation failed: {exc}", file=sys.stderr)
        return 1
    for path in installed:
        print(f"Installed: {path} ({path.stat().st_size:,} bytes)")
    print("Model files installed. Mesh rendering still requires renderer integration and verification.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
