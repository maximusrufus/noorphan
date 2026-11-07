"""Demo: orphans after killing a parent, without and with noorphan."""

import os
import signal
import subprocess
import sys
import tempfile
import time

from noorphan._util import pid_alive

PARENT = (
    "import os,subprocess,sys,time\n"
    "kids=[subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'])"
    " for _ in range(3)]\n"
    "ids=[os.getpid()]+[k.pid for k in kids]\n"
    "open(sys.argv[1]+'.tmp','w').write(' '.join(map(str,ids)))\n"
    "os.replace(sys.argv[1]+'.tmp',sys.argv[1])\n"
    "time.sleep(120)\n"
)
KILL = getattr(signal, "SIGKILL", signal.SIGTERM)


def trial(wrapped: bool) -> int:
    f = os.path.join(tempfile.mkdtemp(), "pids")
    cmd = [sys.executable, "-c", PARENT, f]
    if wrapped:
        cmd = [sys.executable, "-m", "noorphan", "--"] + cmd
    top = subprocess.Popen(cmd)
    end = time.time() + 20
    while not os.path.exists(f) and time.time() < end:
        time.sleep(0.05)
    ids = [int(x) for x in open(f).read().split()]
    parent, sleepers = ids[0], ids[1:]
    os.kill(parent, KILL)  # kill the parent only
    time.sleep(2)
    survivors = [p for p in sleepers if pid_alive(p)]
    for p in survivors:  # clean up leftovers
        try:
            os.kill(p, KILL)
        except OSError:
            pass
    if top.poll() is None:
        top.kill()
    top.wait()
    return len(survivors)


if __name__ == "__main__":
    a = trial(False)
    b = trial(True)
    print(f"orphans without wrapper: {a}")
    print(f"orphans with wrapper:    {b}")
    sys.exit(0 if a > 0 and b == 0 else 1)
