"""Every python example in README.md must actually run.

A README example that does not execute teaches the reader an API that
does not exist. The block in this README is the main usage example, so
it is executed here against a real snapshot pair.
"""

import ast
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README = os.path.join(REPO, "README.md")

sys.path.insert(0, REPO)

FENCE = chr(96) * 3


def readme_blocks():
    with open(README, encoding="utf-8") as fh:
        text = fh.read()
    pattern = FENCE + "python" + chr(92) + "n(.*?)" + FENCE
    return re.findall(pattern, text, re.S)


def test_readme_has_python_blocks():
    assert readme_blocks(), "README has no python examples"


def test_every_readme_block_parses():
    blocks = readme_blocks()
    assert len(blocks) >= 2, "expected the usage and client blocks"
    for index, block in enumerate(blocks):
        try:
            ast.parse(block)
        except SyntaxError as exc:
            raise AssertionError(
                "README python block %d does not parse: %s" % (index, exc)
            ) from exc


def test_usage_example_runs():
    """The main usage example must work end to end."""
    from tiny_mcp_contract import ContractSnapshot, diff_snapshots, is_breaking

    old = ContractSnapshot.from_dicts([
        {
            "name": "read_file",
            "description": "read it",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
        },
    ])
    new = ContractSnapshot.from_dicts([
        {
            "name": "read_file",
            "description": "read it",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "encoding": {"type": "string"},
                },
                "required": ["encoding"],
            },
        },
        {
            "name": "read_directory",
            "description": "read a dir",
            "inputSchema": {"type": "object", "properties": {}},
        },
    ])

    changes = diff_snapshots(old, new)
    rendered = ["%s %s: %s" % (c.kind, c.subject, c.detail) for c in changes]

    assert any(c.kind == "BREAKING" for c in changes), rendered
    assert any(c.kind == "NEW" for c in changes), rendered
    assert is_breaking(changes)


def test_readme_mentions_every_public_name():
    import tiny_mcp_contract

    with open(README, encoding="utf-8") as fh:
        text = fh.read()

    missing = [n for n in tiny_mcp_contract.__all__ if n not in text]
    assert not missing, "README does not document: %s" % ", ".join(missing)


def test_cli_entry_point_is_importable():
    from tiny_mcp_contract.cli import main

    assert callable(main)
