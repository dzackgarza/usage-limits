import os
import subprocess
import sys

env = os.environ.copy()
env["BROWSER"] = "true"
proc = subprocess.Popen(
    [sys.executable, "-u", "-m", "usage_limits", "login"],
    env=env,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)
assert proc.stdout is not None
while True:
    line = proc.stdout.readline()
    if not line:
        break
    print("STDOUT:", repr(line))
