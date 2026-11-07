import os
import signal
import subprocess
import sys
import time

from noorphan._util import pid_alive

PARENT = (
    "import os,subprocess,sys,time\n"
    "kids=[subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'])"
    " for _ in range(2)]\n"
    "open(sys.argv[1]+'.tmp','w').write(' '.join(str(k.pid) for k in kids))\n"
    "os.replace(sys.argv[1]+'.tmp',sys.argv[1])\n"
    "time.sleep(SLEEP)\n"
)


def _wait_file(path, t=20):
    end = time.time() + t
    while time.time() < end:
        try:
            txt = open(path).read().split()
            if len(txt) == 2:
                return [int(x) for x in txt]
        except OSError:
            pass
        time.sleep(0.05)
    raise AssertionError("grandchildren never started")


def _wrap(code, f):
    return [sys.executable, "-m", "noorphan", "--", sys.executable, "-c", code, f]


def test_exit_code_forwarded():
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "noorphan",
            "--",
            sys.executable,
            "-c",
            "raise SystemExit(7)",
        ]
    )
    assert r.returncode == 7


def test_forced_kill_leaves_no_grandchildren(tmp_path):
    f = str(tmp_path / "pids")
    w = subprocess.Popen(_wrap(PARENT.replace("SLEEP", "120"), f))
    pids = _wait_file(f)
    try:
        assert all(pid_alive(p) for p in pids)
        w.kill()
        w.wait()
        end = time.time() + 10
        while time.time() < end and any(pid_alive(p) for p in pids):
            time.sleep(0.1)
        assert [p for p in pids if pid_alive(p)] == []
    finally:
        for p in pids:
            if pid_alive(p):
                try:
                    os.kill(p, getattr(signal, "SIGKILL", signal.SIGTERM))
                except OSError:
                    pass


def test_normal_exit_kills_grandchildren(tmp_path):
    f = str(tmp_path / "pids")
    r = subprocess.run(_wrap(PARENT.replace("SLEEP", "1.5"), f))
    pids = [int(x) for x in open(f).read().split()]
    time.sleep(0.5)
    assert r.returncode == 0
    assert not any(pid_alive(p) for p in pids)


def test_scan_runs():
    r = subprocess.run(
        [sys.executable, "-m", "noorphan", "scan"], capture_output=True, text=True
    )
    assert r.returncode == 0
