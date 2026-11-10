"""Command line entry point: ``python -m cmmcready <command>``."""

from __future__ import annotations

import argparse
import sys


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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
