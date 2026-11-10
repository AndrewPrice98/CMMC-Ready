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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cmmcready")
    sub = parser.add_subparsers(dest="command", required=True)

    catalog = sub.add_parser("catalog", help="inspect the NIST SP 800-171 Rev 2 catalog")
    catalog.add_argument("--check", action="store_true", help="validate the catalog data")
    catalog.set_defaults(func=_catalog)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
