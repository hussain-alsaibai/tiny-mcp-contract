"""Tests for tiny-mcp-contract.

The classification rules are the whole point of this package, so the tests
focus on them: a change that breaks a caller must be reported as
BREAKING, and a cosmetic change must NOT be.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tiny_mcp_contract.core import (  # noqa: E402
    Change,
    ChangeKind,
    ContractSnapshot,
    ToolSpec,
    classify,
    diff_snapshots,
    is_breaking,
)


def snap(tools, **kwargs):
    return ContractSnapshot.from_dicts(tools, **kwargs)


def tool(name, description="does a thing", schema=None, output=None):
    entry = {"name": name, "description": description}
    if schema is not None:
        entry["inputSchema"] = schema
    if output is not None:
        entry["outputSchema"] = output
    return entry



def obj(properties=None, required=None):
    """Build a JSON schema object with the given properties."""
    schema = {"type": "object", "properties": properties or {}}
    if required:
        schema["required"] = required
    return schema


def kinds(changes):
    return sorted(c.kind for c in changes)


def subjects(changes, kind):
    return sorted(c.subject for c in changes if c.kind == kind)


# --- snapshots -------------------------------------------------------------

def test_snapshot_from_dicts():
    s = snap([tool("a"), tool("b")])
    assert len(s) == 2
    assert s.tool_names() == ["a", "b"]


def test_snapshot_from_json_list():
    s = ContractSnapshot.from_json(json.dumps([tool("a")]))
    assert len(s) == 1


def test_snapshot_from_json_object():
    payload = json.dumps({"tools": [tool("a")], "serverName": "srv"})
    s = ContractSnapshot.from_json(payload)
    assert len(s) == 1
    assert s.server_name == "srv"


def test_snapshot_from_json_rejects_garbage():
    with pytest.raises(TypeError):
        ContractSnapshot.from_json(json.dumps("not a contract"))


def test_tool_requires_a_name():
    with pytest.raises(ValueError):
        ToolSpec.from_dict({"description": "no name here"})


def test_tool_rejects_non_dict():
    with pytest.raises(TypeError):
        ToolSpec.from_dict(["not", "a", "dict"])


def test_snapshot_missing_description_is_tolerated():
    s = snap([{"name": "a"}])
    assert s.get("a").description == ""


# --- digests ---------------------------------------------------------------

def test_digest_is_stable():
    a = snap([tool("x"), tool("y")])
    b = snap([tool("y"), tool("x")])
    assert a.digest == b.digest


def test_digest_ignores_key_order_in_schema():
    schema_a = {"type": "object", "properties": {"p": {"type": "string"}}}
    schema_b = {"properties": {"p": {"type": "string"}}, "type": "object"}
    a = snap([tool("x", schema=schema_a)])
    b = snap([tool("x", schema=schema_b)])
    assert a.digest == b.digest


def test_digest_changes_when_schema_changes():
    a = snap([tool("x", schema=obj())])
    b = snap([tool("x", schema=obj({"p": {}}))])
    assert a.digest != b.digest


def test_digest_changes_when_tool_added():
    a = snap([tool("x")])
    b = snap([tool("x"), tool("y")])
    assert a.digest != b.digest


def test_output_schema_digest_is_separate():
    t = ToolSpec("x", output_schema={"type": "object"})
    assert t.output_digest is not None
    assert t.output_digest != t.input_digest
    assert ToolSpec("x").output_digest is None


def test_per_tool_digests():
    s = snap([tool("a"), tool("b")])
    d = s.per_tool_digests()
    assert set(d) == {"a", "b"}
    assert len(d["a"]) == 64


def test_snapshots_compare_by_digest():
    assert snap([tool("a")]) == snap([tool("a")])
    assert snap([tool("a")]) != snap([tool("b")])


# --- save / load -----------------------------------------------------------

def test_save_and_load_roundtrip(tmp_path):
    s = snap([tool("a", schema={"type": "object"})], server_name="srv")
    path = str(tmp_path / "snap.json")
    s.save(path)
    loaded = ContractSnapshot.load(path)
    assert loaded.digest == s.digest
    assert loaded.server_name == "srv"


# --- diffing: no change ----------------------------------------------------

def test_identical_snapshots_produce_no_changes():
    a = snap([tool("a")])
    b = snap([tool("a")])
    assert diff_snapshots(a, b) == []


# --- diffing: tools --------------------------------------------------------

def test_added_tool_is_new():
    changes = diff_snapshots(snap([tool("a")]), snap([tool("a"), tool("b")]))
    assert kinds(changes) == [ChangeKind.NEW]
    assert subjects(changes, ChangeKind.NEW) == ["b"]


def test_removed_tool_is_gone():
    changes = diff_snapshots(snap([tool("a"), tool("b")]), snap([tool("a")]))
    assert kinds(changes) == [ChangeKind.GONE]
    assert subjects(changes, ChangeKind.GONE) == ["b"]


def test_removed_tool_is_breaking():
    """A caller of a removed tool fails at runtime."""
    changes = diff_snapshots(snap([tool("a")]), snap([]))
    assert is_breaking(changes)


# --- diffing: parameters ---------------------------------------------------

def test_newly_required_parameter_is_breaking():
    old = snap([tool("t", schema=obj({"a": {"type": "string"}}))])
    new = snap([tool("t", schema=obj({"a": {"type": "string"}}, ["a"]))])
    changes = diff_snapshots(old, new)
    assert ChangeKind.BREAKING in kinds(changes)
    assert is_breaking(changes)


def test_no_longer_required_parameter_is_relaxed():
    old = snap([tool("t", schema=obj({"a": {"type": "string"}}, ["a"]))])
    new = snap([tool("t", schema=obj({"a": {"type": "string"}}))])
    changes = diff_snapshots(old, new)
    assert ChangeKind.RELAXED in kinds(changes)
    assert not is_breaking(changes)


def test_new_optional_parameter_is_new_not_breaking():
    old = snap([tool("t", schema=obj())])
    new = snap([tool("t", schema=obj({"a": {"type": "string"}}))])
    changes = diff_snapshots(old, new)
    assert kinds(changes) == [ChangeKind.NEW]
    assert not is_breaking(changes)


def test_new_required_parameter_is_breaking_not_also_new():
    old = snap([tool("t", schema=obj())])
    new = snap([tool("t", schema=obj({"a": {"type": "string"}}, ["a"]))])
    changes = diff_snapshots(old, new)
    assert kinds(changes) == [ChangeKind.BREAKING]


def test_removed_required_parameter_is_breaking():
    old = snap([tool("t", schema=obj({"a": {"type": "string"}}, ["a"]))])
    new = snap([tool("t", schema=obj())])
    changes = diff_snapshots(old, new)
    assert ChangeKind.BREAKING in kinds(changes)


def test_removed_optional_parameter_is_notation():
    old = snap([tool("t", schema=obj({"a": {"type": "string"}}))])
    new = snap([tool("t", schema=obj())])
    changes = diff_snapshots(old, new)
    assert kinds(changes) == [ChangeKind.NOTATION]
    assert not is_breaking(changes)


def test_type_change_is_breaking():
    old = snap([tool("t", schema=obj({"a": {"type": "string"}}))])
    new = snap([tool("t", schema=obj({"a": {"type": "integer"}}))])
    changes = diff_snapshots(old, new)
    assert ChangeKind.BREAKING in kinds(changes)
    assert is_breaking(changes)


# --- diffing: descriptions and output schemas -------------------------------

def test_description_change_is_notation():
    old = snap([tool("t", description="old text")])
    new = snap([tool("t", description="new text")])
    changes = diff_snapshots(old, new)
    assert kinds(changes) == [ChangeKind.NOTATION]
    assert not is_breaking(changes)


def test_new_output_schema_is_new():
    old = snap([tool("t")])
    new = snap([tool("t", output={"type": "object"})])
    changes = diff_snapshots(old, new)
    assert ChangeKind.NEW in kinds(changes)


def test_changed_output_schema_is_breaking():
    old = snap([tool("t", output={"type": "object", "properties": {"a": {}}})])
    new = snap([tool("t", output={"type": "object", "properties": {"b": {}}})])
    changes = diff_snapshots(old, new)
    assert ChangeKind.BREAKING in kinds(changes)


def test_removed_output_schema_is_breaking():
    old = snap([tool("t", output={"type": "object"})])
    new = snap([tool("t")])
    changes = diff_snapshots(old, new)
    assert ChangeKind.BREAKING in kinds(changes)


# --- the real case from servers#5414 ---------------------------------------

def test_server_filesystem_0_2_0_to_1_0_0_shape():
    """Model the server-filesystem 0.2.0 -> 1.0.0 change.

    From the measured drift data in modelcontextprotocol/servers#5414:
    the release added a required parameter to an existing tool while
    keeping the tool itself. That is a BREAKING change and it is exactly
    the kind that does not appear in a changelog.
    """
    old = snap([
        tool("read_file", schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }),
    ], server_name="server-filesystem", server_version="0.2.0")

    new = snap([
        tool("read_file", schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "encoding": {"type": "string"},
            },
            "required": ["path", "encoding"],
        }),
        tool("read_directory", schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
        }),
    ], server_name="server-filesystem", server_version="1.0.0")

    changes = diff_snapshots(old, new)
    assert is_breaking(changes)
    assert subjects(changes, ChangeKind.NEW) == ["read_directory"]
    breaking = [c for c in changes if c.breaking]
    assert any("encoding" in c.detail for c in breaking)


def test_a_pure_release_with_no_contract_change_produces_nothing():
    """A version bump alone must not look like drift."""
    old = snap([tool("a")], server_version="1.0.0")
    new = snap([tool("a")], server_version="1.0.1")
    assert diff_snapshots(old, new) == []


# --- helpers ---------------------------------------------------------------

def test_classify_groups_by_kind():
    changes = diff_snapshots(snap([tool("a")]), snap([tool("b")]))
    grouped = classify(changes)
    assert set(grouped) == {ChangeKind.GONE, ChangeKind.NEW}


def test_change_str_includes_detail():
    c = Change(ChangeKind.BREAKING, "tool", "because")
    assert "BREAKING" in str(c)
    assert "because" in str(c)


def test_change_to_dict():
    c = Change(ChangeKind.NEW, "tool", "added")
    assert c.to_dict() == {"kind": "NEW", "subject": "tool", "detail": "added"}
