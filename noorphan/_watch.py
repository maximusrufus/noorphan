"""Watcher: kills a process group when the wrapper dies (pipe EOF / kqueue exit)."""

import os
import select
import signal
import sys


def main() -> None:
    pgid, wrapper = int(sys.argv[1]), int(sys.argv[2])
    fd = sys.stdin.fileno()
    if hasattr(select, "kqueue"):
        kq = select.kqueue()
        evs = [
            select.kevent(fd, select.KQ_FILTER_READ, select.KQ_EV_ADD),
            select.kevent(
                wrapper, select.KQ_FILTER_PROC, select.KQ_EV_ADD, select.KQ_NOTE_EXIT
            ),
        ]
        try:
            kq.control(evs, 0, 0)
        except OSError:
            pass
        while True:
            got = kq.control(None, 4, None)
            if any(e.filter == select.KQ_FILTER_PROC for e in got):
                break
            if any(e.filter == select.KQ_FILTER_READ for e in got):
                if os.read(fd, 1) != b"x":
                    break
                return
    else:
        if os.read(fd, 1) == b"x":
            return
    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        pass


if __name__ == "__main__":
    main()
