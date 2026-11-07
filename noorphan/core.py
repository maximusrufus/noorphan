import os
import signal
import subprocess
import sys
import time

GRACE = 3.0


def run(cmd: list[str]) -> int:
    if sys.platform == "win32":
        return _run_windows(cmd)
    return _run_posix(cmd)


# ---------------------------------------------------------------- Windows
def _run_windows(cmd):
    import ctypes
    from ctypes import wintypes as w

    k = ctypes.WinDLL("kernel32", use_last_error=True)

    class IOC(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("a", "b", "c", "d", "e", "f")]

    class BASIC(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", w.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", w.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", w.DWORD),
            ("SchedulingClass", w.DWORD),
        ]

    class EXT(ctypes.Structure):
        _fields_ = [
            ("Basic", BASIC),
            ("Io", IOC),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    k.CreateJobObjectW.restype = w.HANDLE
    k.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
    k.SetInformationJobObject.argtypes = [
        w.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        w.DWORD,
    ]
    k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    k.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
    k.CloseHandle.argtypes = [w.HANDLE]

    job = k.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    info = EXT()
    info.Basic.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
    if not k.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    # Start paused (creation flag 0x4) so no descendant can exist before the child is in the job.
    p = subprocess.Popen(cmd, creationflags=0x4)
    try:
        if not k.AssignProcessToJobObject(job, int(p._handle)):
            err = ctypes.get_last_error()
            p.kill()
            raise ctypes.WinError(err)
        nt = ctypes.WinDLL("ntdll")
        nt.NtResumeProcess.argtypes = [w.HANDLE]
        if nt.NtResumeProcess(int(p._handle)) != 0:
            p.kill()
            raise OSError("NtResumeProcess failed")
        while True:
            try:
                return p.wait()
            except KeyboardInterrupt:
                pass  # console delivers Ctrl-C to the child too; keep waiting
    finally:
        k.TerminateJobObject(job, 1)
        k.CloseHandle(job)


# ------------------------------------------------------------------ POSIX
def _children_of(me):
    out = []
    try:
        names = os.listdir("/proc")
    except OSError:
        return out
    for n in names:
        if n.isdigit():
            try:
                with open(f"/proc/{n}/stat") as f:
                    if int(f.read().rsplit(")", 1)[1].split()[1]) == me:
                        out.append(int(n))
            except (OSError, ValueError, IndexError):
                pass
    return out


def _reap_all():
    me = os.getpid()
    for _ in range(20):
        kids = _children_of(me)
        if not kids:
            break
        for c in kids:
            try:
                os.kill(c, signal.SIGKILL)
            except OSError:
                pass
        try:
            while os.waitpid(-1, os.WNOHANG)[0]:
                pass
        except ChildProcessError:
            pass


def _run_posix(cmd):
    linux = sys.platform.startswith("linux")
    libc = None
    if linux:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl(36, 1, 0, 0, 0)  # PR_SET_CHILD_SUBREAPER

    expected_ppid = os.getpid()

    def pre():
        if libc is not None:
            libc.prctl(1, signal.SIGKILL, 0, 0, 0)  # PR_SET_PDEATHSIG
            if os.getppid() != expected_ppid:  # wrapper died before prctl took effect
                os._exit(1)

    p = subprocess.Popen(cmd, start_new_session=True, preexec_fn=pre if linux else None)
    pgid = p.pid
    watcher = subprocess.Popen(
        [sys.executable, "-m", "noorphan._watch", str(pgid), str(os.getpid())],
        stdin=subprocess.PIPE,
        start_new_session=True,
    )

    deadline = [None]

    def forward(signum, _frame):
        try:
            os.killpg(pgid, signum)
        except OSError:
            pass
        if deadline[0] is None:
            deadline[0] = time.monotonic() + GRACE

    for sg in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sg, forward)
    try:
        while True:
            try:
                rc = p.wait(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                if deadline[0] is not None and time.monotonic() > deadline[0]:
                    try:
                        os.killpg(pgid, signal.SIGKILL)
                    except OSError:
                        pass
        if rc < 0:
            rc = 128 - rc
        return rc
    finally:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except OSError:
            pass
        try:
            watcher.stdin.write(b"x")
            watcher.stdin.close()
            watcher.wait(timeout=5)
        except Exception:
            pass
        if linux:
            _reap_all()
