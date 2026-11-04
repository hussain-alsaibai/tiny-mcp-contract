"""CLI and packaging tests.

The "gate" command is the point of this package: it has to exit non-zero
when a caller would break, and exit zero when nothing breaks. A gate that
always returns zero is worse than no gate, because it teaches people to
ignore it.
"""

import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from tiny_mcp_contract.cli import main  # noqa: E402
from tiny_mcp_contract.core import ContractSnapshot  # noqa: E402


def _write(tmp_path, name, tools):
    path = str(tmp_path / name)
    ContractSnapshot.from_dicts(tools).save(path)
    return path


def _tool(name, schema=None, description="does a thing"):
    entry = {"name": name, "description": description}
    if schema is not None:
        entry["inputSchema"] = schema
    return entry


def test_digest_command(tmp_path, capsys):
    path = _write(tmp_path, "a.json", [_tool("x")])
    assert main(["digest", path]) == 0
    out = capsys.readouterr().out.strip()
    assert len(out) == 64


def test_digest_json_command(tmp_path, capsys):
    path = _write(tmp_path, "a.json", [_tool("x"), _tool("y")])
    assert main(["--json", "digest", path]) == 0
    data = json.loads(capsys.readouterr().out)
    assert set(data) == {"x", "y"}


def test_diff_command_reports_changes(tmp_path, capsys):
    old = _write(tmp_path, "old.json", [_tool("x")])
    new = _write(tmp_path, "new.json", [_tool("x"), _tool("y")])
    assert main(["diff", old, new]) == 0
    out = capsys.readouterr().out
    assert "NEW" in out
    assert "y" in out


def test_diff_command_on_identical_snapshots(tmp_path, capsys):
    old = _write(tmp_path, "old.json", [_tool("x")])
    new = _write(tmp_path, "new.json", [_tool("x")])
    assert main(["diff", old, new]) == 0
    assert "no contract changes" in capsys.readouterr().out


def test_check_exits_nonzero_on_breaking(tmp_path):
    old = _write(tmp_path, "old.json", [
        _tool("x", schema={"type": "object", "properties": {"a": {"type": "string"}}})
    ])
    new = _write(tmp_path, "new.json", [
        _tool("x", schema={
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "required": ["a"],
        })
    ])
    assert main(["check", old, new]) == 1


def test_check_exits_zero_when_safe(tmp_path):
    old = _write(tmp_path, "old.json", [_tool("x")])
    new = _write(tmp_path, "new.json", [_tool("x"), _tool("y")])
    assert main(["check", old, new]) == 0


def test_gate_fails_on_removed_tool(tmp_path, capsys):
    old = _write(tmp_path, "old.json", [_tool("x")])
    new = _write(tmp_path, "new.json", [])
    assert main(["gate", old, new]) == 1
    assert "FAILED" in capsys.readouterr().out


def test_gate_passes_on_unchanged(tmp_path, capsys):
    old = _write(tmp_path, "old.json", [_tool("x")])
    new = _write(tmp_path, "new.json", [_tool("x")])
    assert main(["gate", old, new]) == 0
    assert "passed" in capsys.readouterr().out


def test_gate_strict_fails_on_any_change(tmp_path):
    old = _write(tmp_path, "old.json", [_tool("x")])
    new = _write(tmp_path, "new.json", [_tool("x", description="reworded")])
    assert main(["gate", "--strict", old, new]) == 1


def test_gate_non_strict_passes_on_notation_change(tmp_path):
    old = _write(tmp_path, "old.json", [_tool("x")])
    new = _write(tmp_path, "new.json", [_tool("x", description="reworded")])
    assert main(["gate", old, new]) == 0


def test_missing_file_exits_two(tmp_path):
    assert main(["digest", str(tmp_path / "nope.json")]) == 2


def test_no_command_prints_help(capsys):
    assert main([]) == 1


def test_module_entry_point_runs():
    proc = subprocess.run(
        [sys.executable, "-m", "tiny_mcp_contract.cli", "--help"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "tiny-mcp-contract" in proc.stdout


def test_pyproject_declares_a_package():
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib

    with open(os.path.join(REPO, "pyproject.toml"), "rb") as fh:
        config = tomllib.load(fh)

    setuptools_cfg = config.get("tool", {}).get("setuptools", {})
    assert setuptools_cfg.get("packages") == ["tiny_mcp_contract"]
    assert "py-modules" not in setuptools_cfg
