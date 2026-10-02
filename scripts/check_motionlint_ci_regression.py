"""A negative control must fail; do not make CI succeed by ignoring exits."""
import sys
from pathlib import Path
from motionlint.cli.main import main

root=Path(sys.argv[1])
code=main(["compare",str(root/"clean_00.npy"),str(root/"foot_sliding_00.npy"),"--output-dir","reports/ci-regression"])
raise SystemExit(0 if code==1 else 1)
