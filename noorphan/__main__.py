import sys


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["scan"]:
        from .scan import main as scan_main

        return scan_main()
    if argv[:1] == ["--"]:
        argv = argv[1:]
    elif not argv or argv[0] in ("-h", "--help"):
        print("usage: noorphan -- <cmd> [args]\n       noorphan scan")
        return 2
    if not argv:
        print("noorphan: no command given", file=sys.stderr)
        return 2
    from .core import run

    try:
        return run(argv)
    except FileNotFoundError as e:
        print(f"noorphan: {e}", file=sys.stderr)
        return 127


if __name__ == "__main__":
    sys.exit(main())
