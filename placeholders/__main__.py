import argparse
import json
import sys
from collections import OrderedDict

from . import check, load_data


def main(argv=None):
    ap = argparse.ArgumentParser(prog="placeholders", description="Find template placeholders in text before you send it.")
    ap.add_argument("file", help="the template or the final email text/HTML (- for standard input)")
    ap.add_argument("--data", help="a JSON file, a CSV (its header row) or a .env file naming the fields that will fill the template")
    ap.add_argument("--rendered", action="store_true", help="the text is the FINAL email: any placeholder left is an error")
    ap.add_argument("--allow", default="", help="placeholders to ignore, comma-separated (the whole text or just the name)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        text = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8", errors="replace").read()
        data = load_data(open(args.data, encoding="utf-8", errors="replace").read()) if args.data else None
    except OSError as exc:
        print("placeholders: cannot read %s: %s" % (exc.filename, exc.strerror), file=sys.stderr)
        return 2
    except (ValueError, StopIteration) as exc:
        print("placeholders: cannot read the data file: %s" % exc, file=sys.stderr)
        return 2
    allow = {a.strip() for a in args.allow.split(",") if a.strip()}
    findings, found = check(text, data, args.rendered, allow)
    unique = OrderedDict()
    for f in found:
        unique.setdefault((f["syntax"], f["text"]), []).append(f["line"])
    if args.json:
        print(json.dumps({"placeholders": [{"syntax": s, "text": t, "lines": ls} for (s, t), ls in unique.items()],
                          "findings": [{"level": f.level, "line": f.line, "rule": f.rule, "message": f.message} for f in findings]}, indent=2))
    else:
        if unique and not args.rendered:
            print("%d placeholder%s (%d distinct):" % (len(found), "" if len(found) == 1 else "s", len(unique)))
            for (s, t), ls in unique.items():
                print("  %-22s %-28s line%s %s" % (s, t[:28], "" if len(ls) == 1 else "s", ", ".join(map(str, ls[:6])) + ("..." if len(ls) > 6 else "")))
        elif not unique and not findings:
            print("no placeholders found")
        for f in findings:
            print("%-5s%s [%s] %s" % (f.level, " line %d" % f.line if f.line else "", f.rule, f.message))
    return 1 if any(f.level == "error" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
