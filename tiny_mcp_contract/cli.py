"""Command-line interface for tiny-mcp-contract.

Usage:
    tiny-mcp-contract digest <snapshot.json>
    tiny-mcp-contract diff <old.json> <new.json>
    tiny-mcp-contract check <baseline.json> <current.json>
    tiny-mcp-contract gate <baseline.json> <current.json>

The "check" and "gate" commands exit non-zero when a BREAKING change is
found, which is what makes them usable as a CI step.
"""

import argparse
import json
import sys

from tiny_mcp_contract.core import (
    ChangeKind,
    ContractSnapshot,
    classify,
    diff_snapshots,
    is_breaking,
)


def _load(path):
    return ContractSnapshot.load(path)


def cmd_digest(args):
    snap = _load(args.snapshot)
    if args.json:
        print(json.dumps(snap.per_tool_digests(), indent=2, sort_keys=True))
    else:
        print(snap.digest)
    return 0


def cmd_diff(args):
    changes = diff_snapshots(_load(args.old), _load(args.new))
    if args.json:
        print(json.dumps([c.to_dict() for c in changes], indent=2))
        return 0

    if not changes:
        print("no contract changes")
        return 0

    grouped = classify(changes)
    for kind in ChangeKind.ALL:
        for change in grouped.get(kind, []):
            print("%-9s %s" % (kind, change))
    print("")
    breaking_count = len(grouped.get(ChangeKind.BREAKING, []))
    print("%d change(s), %d breaking" % (len(changes), breaking_count))
    return 0


def _report(changes, as_json):
    if as_json:
        print(json.dumps([c.to_dict() for c in changes], indent=2))
        return
    grouped = classify(changes)
    if not changes:
        print("contract unchanged")
        return
    for kind in ChangeKind.ALL:
        for change in grouped.get(kind, []):
            print("%-9s %s" % (kind, change))


def cmd_check(args):
    changes = diff_snapshots(_load(args.baseline), _load(args.current))
    _report(changes, args.json)
    return 1 if is_breaking(changes) else 0


def cmd_gate(args):
    """Fail on BREAKING, and optionally on any change at all."""
    changes = diff_snapshots(_load(args.baseline), _load(args.current))
    _report(changes, args.json)
    if is_breaking(changes):
        print("")
        print("contract gate FAILED: %d breaking change(s)" % len(
            [c for c in changes if c.breaking]))
        return 1
    if args.strict and changes:
        print("")
        print("contract gate FAILED: %d change(s) (strict mode)" % len(changes))
        return 1
    print("")
    print("contract gate passed")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="tiny-mcp-contract",
        description="Snapshot and diff MCP tool contracts. Zero dependencies.",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    sub = parser.add_subparsers(dest="cmd")

    p_digest = sub.add_parser("digest", help="print the contract digest")
    p_digest.add_argument("snapshot")
    p_digest.set_defaults(func=cmd_digest)

    p_diff = sub.add_parser("diff", help="diff two snapshots")
    p_diff.add_argument("old")
    p_diff.add_argument("new")
    p_diff.set_defaults(func=cmd_diff)

    p_check = sub.add_parser("check", help="exit non-zero on a breaking change")
    p_check.add_argument("baseline")
    p_check.add_argument("current")
    p_check.set_defaults(func=cmd_check)

    p_gate = sub.add_parser("gate", help="CI gate: fail on breaking changes")
    p_gate.add_argument("baseline")
    p_gate.add_argument("current")
    p_gate.add_argument(
        "--strict", action="store_true", help="fail on any change, not just breaking"
    )
    p_gate.set_defaults(func=cmd_gate)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    except (ValueError, TypeError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
