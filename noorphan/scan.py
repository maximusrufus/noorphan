import json
import os
import re
import subprocess
import sys
import time


def _list_procs():
    """Yield dicts: pid, ppid, name, start (epoch), cmd."""
    try:
        import psutil

        for pr in psutil.process_iter(
            ["pid", "ppid", "name", "create_time", "cmdline"]
        ):
            i = pr.info
            yield {
                "pid": i["pid"],
                "ppid": i["ppid"] or 0,
                "name": i["name"] or "",
                "start": i["create_time"] or 0,
                "cmd": " ".join(i["cmdline"] or []),
            }
        return
    except ImportError:
        pass
    if sys.platform == "win32":
        ps = (
            "Get-CimInstance Win32_Process | Select-Object ProcessId,"
            "ParentProcessId,Name,CommandLine,@{n='S';e={[double]("
            "([DateTimeOffset]$_.CreationDate).ToUnixTimeSeconds())}} "
            "| ConvertTo-Json -Compress"
        )
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True
        ).stdout
        data = json.loads(out or "[]")
        if isinstance(data, dict):
            data = [data]
        for d in data:
            yield {
                "pid": d["ProcessId"],
                "ppid": d["ParentProcessId"],
                "name": d["Name"] or "",
                "start": d["S"] or 0,
                "cmd": d["CommandLine"] or "",
            }
        return
    out = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,etime=,command="], capture_output=True, text=True
    ).stdout
    now = time.time()
    for line in out.splitlines():
        m = re.match(r"\s*(\d+)\s+(\d+)\s+(\S+)\s+(.*)", line)
        if not m:
            continue
        pid, ppid, et, cmd = m.groups()
        days = 0
        if "-" in et:
            d, et = et.split("-")
            days = int(d)
        parts = [int(x) for x in et.split(":")]
        while len(parts) < 3:
            parts.insert(0, 0)
        age = days * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2]
        yield {
            "pid": int(pid),
            "ppid": int(ppid),
            "name": os.path.basename(cmd.split()[0]) if cmd else "",
            "start": now - age,
            "cmd": cmd,
        }


def _boot_time():
    try:
        with open("/proc/uptime") as f:
            return time.time() - float(f.read().split()[0])
    except OSError:
        pass
    try:
        import psutil

        return psutil.boot_time()
    except ImportError:
        pass
    if sys.platform == "darwin":
        m = re.search(
            r"sec = (\d+)",
            subprocess.run(
                ["sysctl", "-n", "kern.boottime"], capture_output=True, text=True
            ).stdout,
        )
        if m:
            return float(m.group(1))
    return 0.0


def find_orphans():
    procs = {p["pid"]: p for p in _list_procs()}
    boot = _boot_time()
    me = os.getpid()
    res = []
    for p in procs.values():
        pid, ppid = p["pid"], p["ppid"]
        if pid in (0, 1, 2, 4, me) or ppid == 2 or not p["cmd"]:
            continue
        par = procs.get(ppid)
        if sys.platform == "win32":
            orphan = par is None or par["start"] > p["start"] > 0
        else:
            orphan = ppid == 1 or par is None
        if orphan and p["start"] >= boot:
            res.append(p)
    return sorted(res, key=lambda p: p["start"])


def _fmt_age(s):
    s = int(max(s, 0))
    return f"{s // 3600}h{s % 3600 // 60:02d}m{s % 60:02d}s"


def _split_allow(items):
    out = []
    for it in items or []:
        out += [x.strip() for x in re.split(r"[\n,]", it) if x.strip()]
    return out


MAC_DEFAULT_IGNORE = ("/System/", "/usr/libexec/", "/usr/sbin/")


def default_ignored(p, platform=None):
    """macOS only: system daemons launched by the init process are not leaks."""
    if (platform or sys.platform) != "darwin":
        return False
    return p["cmd"].startswith(MAC_DEFAULT_IGNORE)


def filter_orphans(
    orphans, since=None, baseline=None, allow=(), default_ignore=True, platform=None
):
    """Drop orphans older than `since`, present in `baseline`, matching `allow`, or default-ignored."""
    base = [(b["pid"], b["start"]) for b in baseline or []]
    pats = [re.compile(a) for a in allow]
    res = []
    for p in orphans:
        if default_ignore and default_ignored(p, platform):
            continue
        if since is not None and p["start"] < since:
            continue
        if any(bp == p["pid"] and abs(bs - p["start"]) <= 2.0 for bp, bs in base):
            continue
        if any(r.search(p["name"]) or r.search(p["cmd"]) for r in pats):
            continue
        res.append(p)
    return res


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="noorphan scan")
    ap.add_argument("--json", action="store_true", help="print a JSON list")
    ap.add_argument(
        "--since", type=float, help="only processes started at/after this epoch"
    )
    ap.add_argument(
        "--baseline", help="JSON file from an earlier --json scan to ignore"
    )
    ap.add_argument(
        "--allow",
        action="append",
        default=[],
        help="regexes (newline/comma separated) on name or command line to ignore",
    )
    ap.add_argument(
        "--fail",
        nargs="?",
        const=1,
        type=int,
        metavar="CODE",
        help="exit CODE (default 1) if any orphans remain",
    )
    ap.add_argument(
        "--no-default-ignore",
        action="store_true",
        help="macOS: also report processes whose executable is under /System/, /usr/libexec/ or /usr/sbin/",
    )
    a = ap.parse_args(argv)
    base = None
    if a.baseline:
        try:
            with open(a.baseline, encoding="utf-8") as f:
                base = json.load(f)
            [(b["pid"], b["start"]) for b in base]
        except OSError:
            base = []
        except (ValueError, KeyError, TypeError):
            print(f"noorphan: invalid baseline file: {a.baseline}", file=sys.stderr)
            return 2
    try:
        found = filter_orphans(
            find_orphans(),
            a.since,
            base,
            _split_allow(a.allow),
            default_ignore=not a.no_default_ignore,
        )
    except re.error as e:
        print(f"noorphan: invalid --allow regex: {e}", file=sys.stderr)
        return 2
    now = time.time()
    if a.json:
        print(json.dumps(found))
    else:
        for p in found:
            print(f"{p['pid']}\t{p['name']}\t{_fmt_age(now - p['start'])}\t{p['cmd']}")
    return a.fail if (a.fail and found) else 0
