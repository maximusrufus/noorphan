# noorphan

Run a command and guarantee that every descendant dies when the command exits,
the wrapper exits, or the wrapper is killed. Python 3.10+, standard library only
(`psutil` is an optional extra used by `scan` when present).

## Install

    pip install .            # or: pip install .[psutil]

## Use

    noorphan -- <cmd> [args]   # run cmd; exit code is forwarded
    noorphan scan              # list orphaned processes (pid, name, age, command line)

## Demo

    make demo      # or: python demo.py

Starts a parent that spawns sleeper grandchildren, kills the parent, and reports
surviving sleepers without and with the wrapper.

## Mechanisms

| Platform | Mechanism |
|----------|-----------|
| Windows  | Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (ctypes); child assigned right after spawn |
| Linux    | `PR_SET_PDEATHSIG` on the child, `PR_SET_CHILD_SUBREAPER` on the wrapper, own session + process-group kill, watcher process for forced wrapper death |
| macOS    | `start_new_session`, process-group kill on exit, watcher using kqueue `NOTE_EXIT` on the wrapper plus pipe EOF |

Tested on Windows and Linux. macOS is untested until CI runs.

Limit: on POSIX a descendant that moves itself into a new session escapes the
group kill (Linux still catches it on a normal wrapper exit via the subreaper).

## Notes

- Interactive commands lose their controlling terminal on POSIX (the child runs
  in its own session), so full-screen programs and shells are not supported.
- Signals (interrupt, terminate, hangup) are forwarded to the child group; after a
  3 s grace period the group is killed.
- The watcher kills by process-group id; if the whole group is gone and the id is
  reused before the watcher fires, an unrelated group could be hit (narrow window).
- Not for multithreaded host processes: the Linux path uses a pre-exec hook, which
  is unsafe when other threads exist at fork time.
