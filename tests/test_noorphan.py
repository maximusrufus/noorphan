import os
import signal
import subprocess
import sys
import time

import pytest
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


def test_fast_grandchild_spawn_killed_with_wrapper(tmp_path):
    f = str(tmp_path / "pid")
    code = (
        "import subprocess,sys,os;"
        "k=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)']);"
        "open(sys.argv[1]+'.t','w').write(str(k.pid));os.replace(sys.argv[1]+'.t',sys.argv[1])"
    )
    w = subprocess.Popen(_wrap(code, f))
    end = time.time() + 20
    while not os.path.exists(f) and time.time() < end:
        time.sleep(0.05)
    pid = int(open(f).read())
    try:
        w.kill()
        w.wait()
        end = time.time() + 10
        while time.time() < end and pid_alive(pid):
            time.sleep(0.1)
        assert not pid_alive(pid)
    finally:
        if pid_alive(pid):
            os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal forwarding")
def test_sigint_forwarded_tree_gone_exit_code(tmp_path):
    f = str(tmp_path / "pids")
    code = (
        "import signal,sys;signal.signal(signal.SIGINT,lambda *a:sys.exit(5));"
        + PARENT.replace("SLEEP", "120")
    )
    w = subprocess.Popen(_wrap(code, f))
    pids = _wait_file(f)
    time.sleep(0.5)
    w.send_signal(signal.SIGINT)
    assert w.wait(timeout=15) == 5
    end = time.time() + 10
    while time.time() < end and any(pid_alive(p) for p in pids):
        time.sleep(0.1)
    assert not any(pid_alive(p) for p in pids)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal forwarding")
def test_grace_period_kill_exit_code_137():
    code = "import signal,time;signal.signal(signal.SIGINT,signal.SIG_IGN);time.sleep(60)"
    w = subprocess.Popen([sys.executable, "-m", "noorphan", "--", sys.executable, "-c", code])
    time.sleep(1.5)
    w.send_signal(signal.SIGINT)
    assert w.wait(timeout=15) == 137


def test_filter_orphans_since_baseline_allow():
    from noorphan.scan import _split_allow, filter_orphans

    o = [
        {"pid": 1, "ppid": 1, "name": "a", "start": 100.0, "cmd": "a --x"},
        {"pid": 2, "ppid": 1, "name": "b", "start": 200.0, "cmd": "b --y"},
        {"pid": 3, "ppid": 1, "name": "c", "start": 300.0, "cmd": "c --z"},
    ]
    assert [p["pid"] for p in filter_orphans(o, since=150)] == [2, 3]
    assert [p["pid"] for p in filter_orphans(o, baseline=[o[0]])] == [2, 3]
    assert [p["pid"] for p in filter_orphans(o, allow=["^b$", "--z"])] == [1]
    assert _split_allow(["x, y\nz"]) == ["x", "y", "z"]


def test_scan_json_and_fail_flag(tmp_path):
    r = subprocess.run(
        [sys.executable, "-m", "noorphan", "scan", "--json", "--since", str(time.time() + 3600)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    import json

    assert json.loads(r.stdout) == []
    r = subprocess.run(
        [sys.executable, "-m", "noorphan", "scan", "--since", str(time.time() + 3600), "--fail"]
    )
    assert r.returncode == 0
