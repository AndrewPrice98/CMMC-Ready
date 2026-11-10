"""Command line entry point: ``python -m cmmcready <command>``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_DEMO_DB = Path(__file__).resolve().parent.parent / "data" / "demo.db"


def _coverage(args: argparse.Namespace) -> int:
    from cmmcready import coverage

    if args.check:
        stale = coverage.stale_files()
        if stale:
            print(f"collector coverage is out of date in {', '.join(stale)}; "
                  "run: python -m cmmcready catalog --coverage-md --write", file=sys.stderr)
            return 1
        print("collector coverage tables are current")
    elif args.write:
        try:
            coverage.write()
        except ValueError as exc:
            print(f"coverage error: {exc}", file=sys.stderr)
            return 1
        print(f"wrote {coverage.COVERAGE_DOC} and the coverage section of {coverage.README}")
    else:
        sys.stdout.write(coverage.coverage_markdown())
    return 0


def _catalog(args: argparse.Namespace) -> int:
    from cmmcready.catalog import load_catalog, validate

    if args.coverage_md:
        return _coverage(args)
    if args.write:
        print("--write is only used with --coverage-md", file=sys.stderr)
        return 2
    catalog = load_catalog()
    if args.check:
        problems = validate(catalog)
        if problems:
            for problem in problems:
                print(f"catalog error: {problem}", file=sys.stderr)
            return 1
    print(
        f"{len(catalog.requirements)} requirements, "
        f"{catalog.objective_count} objectives, "
        f"total weight {catalog.total_weight}"
    )
    return 0


def _collect_parse(args: argparse.Namespace) -> int:
    import json
    from collections import Counter

    from cmmcready.evidence import m365, windows
    from cmmcready.evidence.engine import DEFAULT_ODP, combine, evaluate

    module = {"windows": windows, "m365": m365}[args.collector]
    try:
        with open(args.file, encoding="utf-8-sig") as handle:
            data = json.load(handle)
        module.validate(data)
        ok_count = sum(1 for c in data["checks"].values() if c["status"] == "ok")
        if ok_count < args.min_ok:
            raise ValueError(f"only {ok_count} checks were readable; at least {args.min_ok} required")
        findings = combine(evaluate(data, DEFAULT_ODP))
    except (OSError, ValueError) as exc:  # json.JSONDecodeError is a ValueError
        print(f"collect-parse error: {exc}", file=sys.stderr)
        return 1
    info = module.summarize(data)
    if module is windows:
        print(f"windows collector v{data['version']}: {info['os']} build {info['build']}, "
              f"elevated={info['elevated']}")
    else:
        print(f"m365 collector v{data['version']}: tenant {info['tenant_id']}, "
              f"names redacted={info['redacted']}")
    print(f"checks: {len(info['ok'])} ok, {len(info['unavailable'])} unavailable")
    for check_id, reason in info["unavailable"].items():
        print(f"  unavailable {check_id}: {reason}")
    if info["missing"]:
        print(f"  not reported: {', '.join(info['missing'])}")
    counts = Counter(f.result for f in findings.values())
    print(f"objectives: {counts['met']} met, {counts['not_met']} not met, "
          f"{counts['not_assessed']} not assessed")
    return 0


def _read_password(args: argparse.Namespace) -> str:
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        import getpass

        password = getpass.getpass("Admin password: ")
        if password != getpass.getpass("Repeat password: "):
            sys.exit("Passwords do not match.")
    if len(password) < 12:
        sys.exit("Use at least 12 characters.")
    return password


def _update_env_file(path: Path, values: dict[str, str]) -> None:
    """Set keys in a .env file, keeping any other lines as they are."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(values)
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in remaining:
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in remaining.items()]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _create_admin(args: argparse.Namespace) -> int:
    import secrets

    from cmmcready import config
    from cmmcready.auth import hash_password

    password = _read_password(args)
    values = {
        "CMMCREADY_ADMIN_USER": args.username,
        "CMMCREADY_ADMIN_PASSWORD_HASH": hash_password(password),
        # Reuse an existing secret so current sessions stay valid, unless asked to rotate.
        "CMMCREADY_SECRET_KEY": (config.secret_key() if config.secret_key() and not args.rotate_secret
                                 else secrets.token_urlsafe(48)),
    }
    if args.print:
        print("Set these environment variables on your host. Keep them secret.\n")
        for key, value in values.items():
            print(f"{key}={value}")
        print("CMMCREADY_TRUST_PROXY=true")
        return 0
    _update_env_file(config.ENV_FILE, {**values, "CMMCREADY_COOKIE_SECURE": "false"})
    print(f"Admin '{args.username}' saved to {config.ENV_FILE} (git-ignored).")
    print("Restart the API to pick it up. For a hosted deployment, run again with --print.")
    return 0


def _server_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default="127.0.0.1", help="address to listen on (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="port (default 8000)")
    parser.add_argument("--reload", action="store_true", help="restart when the code changes (development)")


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("cmmcready.api:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def _remove_db(path: Path) -> None:
    for candidate in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        candidate.unlink(missing_ok=True)


def _demo(args: argparse.Namespace) -> int:
    import os

    path = Path(args.db or DEFAULT_DEMO_DB).resolve()
    # The demo always runs on its own database file, never on CMMCREADY_DB from backend/.env.
    os.environ["CMMCREADY_DB"] = str(path)
    if args.reset:
        _remove_db(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    from cmmcready import db, demo

    conn = db.connect(path)
    try:
        if demo.seed(conn):
            print(f"Loaded the fictional demo organization into {path}")
        else:
            print(f"{path} already holds an organization; left it as it is (use --reset to reload)")
        org = db.get_organization(conn)
        print(f"Organization: {org['name'] if org else '(none)'}")
        for a in sorted(db.list_assessments(conn), key=lambda a: a["id"]):
            result = db.current_score(conn, a["id"])
            print(f"  assessment {a['id']}: {a['title']}: SPRS score {result.score}"
                  f"{' (provisional)' if result.provisional else ''}")
    finally:
        conn.close()
    if args.serve:
        # Demo mode: read-only guests unless an admin signs in (see create-admin).
        os.environ["CMMCREADY_DEMO"] = "true"
        return _serve(args)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cmmcready")
    sub = parser.add_subparsers(dest="command", required=True)

    catalog = sub.add_parser("catalog", help="inspect the NIST SP 800-171 Rev 2 catalog")
    catalog.add_argument("--check", action="store_true",
                         help="validate the catalog data (with --coverage-md: fail if the "
                              "committed coverage tables are out of date)")
    catalog.add_argument("--coverage-md", action="store_true",
                         help="print the collector coverage table generated from rules.yml")
    catalog.add_argument("--write", action="store_true",
                         help="with --coverage-md: update docs/COLLECTOR_COVERAGE.md and the README section")
    catalog.set_defaults(func=_catalog)

    demo = sub.add_parser("demo", help="load the fictional demo organization into a separate database")
    demo.add_argument("--db", type=Path, default=None, metavar="PATH",
                      help=f"demo database file (default: {DEFAULT_DEMO_DB})")
    demo.add_argument("--reset", action="store_true", help="delete the demo database first and reload it")
    demo.add_argument("--serve", action="store_true", help="start the API on it afterwards (demo mode)")
    _server_args(demo)
    demo.set_defaults(func=_demo)

    serve = sub.add_parser("serve", help="run the API server")
    _server_args(serve)
    serve.set_defaults(func=_serve)

    parse = sub.add_parser("collect-parse", help="validate collector output and summarise the findings")
    parse.add_argument("collector", choices=["windows", "m365"])
    parse.add_argument("file")
    parse.add_argument("--min-ok", type=int, default=0, metavar="N",
                       help="fail unless at least N checks have status ok")
    parse.set_defaults(func=_collect_parse)

    admin = sub.add_parser("create-admin", help="set the dashboard login (writes backend/.env)")
    admin.add_argument("--username", default="admin")
    admin.add_argument("--password-stdin", action="store_true", help="read the password from stdin")
    admin.add_argument("--print", action="store_true",
                       help="print the variables for a hosting provider instead of writing .env")
    admin.add_argument("--rotate-secret", action="store_true", help="new signing secret (logs everyone out)")
    admin.set_defaults(func=_create_admin)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
