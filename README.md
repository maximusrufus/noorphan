<p align="center">
  <img src="assets/logo.svg" alt="noorphan logo" width="96" height="96">
</p>

<h1 align="center">noorphan</h1>

<p align="center"><b>When your command dies, its children die with it.</b></p>

<p align="center">
  <a href="https://github.com/maximusrufus/noorphan/actions/workflows/ci.yml"><img src="https://github.com/maximusrufus/noorphan/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/license-Apache--2.0-green" alt="License: Apache-2.0">
</p>

Run a command and guarantee that every descendant dies when the command exits,
the wrapper exits, or the wrapper is killed. Pure standard library
(`psutil` is an optional extra used by `scan` when present).

## Quick start

    pip install .
    noorphan -- python my_server.py   # children die with it; exit code is forwarded
    noorphan scan                     # list orphaned processes (pid, name, age, command line)
    make demo                         # or: python demo.py

## Before / after

`python demo.py` starts a parent that spawns three sleeper grandchildren, then
kills the parent. Output of a real run on Windows:

    orphans without wrapper: 3
    orphans with wrapper:    0

## Why

- Dev servers that spawn workers which keep running after the server is stopped.
- Test runners that leave helper processes behind when interrupted or killed.
- AI coding agents that start background processes and leave them behind.

## Mechanisms

| Platform | Mechanism |
|----------|-----------|
| Windows  | Starts the child paused (not yet running), assigns it to a Job Object (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, via ctypes), then resumes it |
| Linux    | `PR_SET_PDEATHSIG` on the child, `PR_SET_CHILD_SUBREAPER` on the wrapper, own session with process-group kill, watcher process for forced wrapper death |
| macOS    | `start_new_session`, process-group kill on exit, watcher using kqueue `NOTE_EXIT` on the wrapper plus pipe EOF |

## Limits

- On POSIX a descendant that moves itself into a new session escapes the
  group kill (Linux still catches it on a normal wrapper exit via the subreaper).
- Interactive commands lose their controlling terminal on POSIX (the child runs
  in its own session), so full-screen programs and shells are not supported.
- Signals (interrupt, terminate, hangup) are forwarded to the child group; after a
  3 s grace period the group is killed, and the exit code is then 137 on POSIX.
- The watcher kills by process-group id; if the whole group is gone and the id is
  reused before the watcher fires, an unrelated group could be hit (narrow window).
- Not for multithreaded host processes: the Linux path uses a pre-exec hook, which
  is unsafe when other threads exist at fork time.

## Platform status

| Platform | Status |
|----------|--------|
| Windows  | tested |
| Linux    | tested |
| macOS    | pending CI |

## License

Apache-2.0, see `LICENSE`.
