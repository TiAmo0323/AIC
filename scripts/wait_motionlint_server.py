"""Wait for the actual workbench response instead of assuming startup speed."""
import argparse
import time
import urllib.request

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('url')
parser.add_argument('--timeout',type=float,default=30)
args=parser.parse_args();deadline=time.monotonic()+args.timeout
while time.monotonic()<deadline:
    try:
        with urllib.request.urlopen(args.url,timeout=2) as response:
            if response.status==200:
                print('MotionLint workbench ready');raise SystemExit(0)
    except OSError:
        time.sleep(.2)
raise SystemExit('MotionLint server did not become ready within the startup budget')
