"""Command line entry point: ``python -m cmmcready <command>``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _catalog(args: argparse.Namespace) -> int:
    from cmmcready.catalog import load_catalog, validate

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cmmcready")
    sub = parser.add_subparsers(dest="command", required=True)

    catalog = sub.add_parser("catalog", help="inspect the NIST SP 800-171 Rev 2 catalog")
    catalog.add_argument("--check", action="store_true", help="validate the catalog data")
    catalog.set_defaults(func=_catalog)

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
