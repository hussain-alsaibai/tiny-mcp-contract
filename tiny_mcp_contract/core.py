"""MCP tool-contract snapshots and diffs.

The problem this solves: an MCP server can change its tool contract
between versions and nothing tells you. A tool disappears, a required
parameter is added, a description is reworded -- and the change is not in
the changelog. Clients keep passing the old shape and fail at runtime,
with an error that points at the call site rather than the release.

This module takes a snapshot of a server's tool surface, digests it, and
diffs two snapshots into a classified list of changes.

Zero dependencies: hashing is hashlib, JSON is json.
"""

import hashlib
import json

__all__ = [
    "Change",
    "ChangeKind",
    "ContractSnapshot",
    "ToolSpec",
    "classify",
    "diff_snapshots",
    "is_breaking",
    "snapshot_from_client",
]

# Canonical JSON: sorted keys, no insignificant whitespace. Two schemas
# that differ only in key order must produce the same digest, or every
# server that reformats its JSON would look like a contract change.
_CANONICAL = {"sort_keys": True, "separators": (",", ":"), "ensure_ascii": False}


class ChangeKind:
    """The kinds of change a contract diff can report.

    These names follow the taxonomy used in the MCP contract-drift
    discussion (modelcontextprotocol/servers#5414), so a diff produced
    here can be compared against theirs directly.
    """

    BREAKING = "BREAKING"
    NEW = "NEW"
    GONE = "GONE"
    NOTATION = "NOTATION"
    RELAXED = "RELAXED"

    ALL = (BREAKING, NEW, GONE, NOTATION, RELAXED)


class Change:
    """One difference between two contract snapshots."""

    __slots__ = ("kind", "subject", "detail")

    def __init__(self, kind, subject, detail=""):
        self.kind = kind
        self.subject = subject
        self.detail = detail

    @property
    def breaking(self):
        """True if this change would break an existing caller.

        GONE counts: a caller of a removed tool fails at runtime.
        """
        return self.kind in (ChangeKind.BREAKING, ChangeKind.GONE)

    def to_dict(self):
        return {"kind": self.kind, "subject": self.subject, "detail": self.detail}

    def __repr__(self):
        return "Change(%s, %r)" % (self.kind, self.subject)

    def __eq__(self, other):
        if not isinstance(other, Change):
            return NotImplemented
        return (self.kind, self.subject, self.detail) == (
            other.kind,
            other.subject,
            other.detail,
        )

    def __hash__(self):
        return hash((self.kind, self.subject, self.detail))

    def __str__(self):
        if self.detail:
            return "%s %s: %s" % (self.kind, self.subject, self.detail)
        return "%s %s" % (self.kind, self.subject)


class ToolSpec:
    """The contract of a single MCP tool."""

    __slots__ = ("name", "description", "input_schema", "output_schema")

    def __init__(self, name, description="", input_schema=None, output_schema=None):
        self.name = name
        self.description = description
        self.input_schema = input_schema or {}
        self.output_schema = output_schema

    @classmethod
    def from_dict(cls, d):
        """Build a ToolSpec from an MCP tools/list entry.

        Accepts the raw wire shape. Missing keys are tolerated because a
        server that omits "description" is still a server whose contract
        we need to track.
        """
        if not isinstance(d, dict):
            raise TypeError("tool entry must be a dict, got %r" % type(d).__name__)
        name = d.get("name")
        if not name:
            raise ValueError("tool entry has no name")
        return cls(
            name=name,
            description=d.get("description") or "",
            input_schema=d.get("inputSchema") or {},
            output_schema=d.get("outputSchema"),
        )

    def to_dict(self):
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
            "outputSchema": self.output_schema,
        }

    def canonical(self):
        """The canonical form used for hashing and comparison."""
        return json.dumps(self.to_dict(), **_CANONICAL)

    @property
    def input_digest(self):
        """Digest of the input schema alone."""
        return hashlib.sha256(
            json.dumps(self.input_schema, **_CANONICAL).encode("utf-8")
        ).hexdigest()

    @property
    def output_digest(self):
        """Digest of the output schema alone, or None if there is none.

        The output schema is hashed separately from the input schema on
        purpose: a server that starts declaring an outputSchema has
        changed what it promises to return, which is a different kind of
        change from tightening what it accepts.
        """
        if self.output_schema is None:
            return None
        return hashlib.sha256(
            json.dumps(self.output_schema, **_CANONICAL).encode("utf-8")
        ).hexdigest()

    def __repr__(self):
        return "ToolSpec(%r)" % self.name


class ContractSnapshot:
    """A point-in-time snapshot of a server's tool surface."""

    __slots__ = ("tools", "server_name", "server_version", "source")

    def __init__(self, tools=None, server_name=None, server_version=None, source=None):
        self.tools = {}
        for tool in tools or []:
            self.tools[tool.name] = tool
        self.server_name = server_name
        self.server_version = server_version
        self.source = source

    # -- construction ----------------------------------------------------

    @classmethod
    def from_dicts(cls, entries, server_name=None, server_version=None, source=None):
        """Build a snapshot from raw MCP tools/list entries."""
        tools = [ToolSpec.from_dict(e) for e in entries]
        return cls(tools, server_name, server_version, source)

    @classmethod
    def from_json(cls, text, **kwargs):
        """Build a snapshot from a JSON document.

        Accepts either a bare list of tools or an object with a "tools"
        key, which is the shape tools/list returns.
        """
        data = json.loads(text)
        if isinstance(data, dict):
            entries = data.get("tools") or []
            kwargs.setdefault("server_name", data.get("serverName"))
            kwargs.setdefault("server_version", data.get("serverVersion"))
        elif isinstance(data, list):
            entries = data
        else:
            raise TypeError(
                "expected a list or an object, got %r" % type(data).__name__
            )
        return cls.from_dicts(entries, **kwargs)

    # -- queries ---------------------------------------------------------

    def tool_names(self):
        return sorted(self.tools)

    def get(self, name):
        return self.tools.get(name)

    def __len__(self):
        return len(self.tools)

    def __contains__(self, name):
        return name in self.tools

    def __iter__(self):
        return iter(self.tool_names())

    # -- digests ---------------------------------------------------------

    @property
    def digest(self):
        """Digest of the whole contract.

        This is the value you pin in CI and compare against the next
        release. It changes if and only if something in the contract
        changed.
        """
        payload = json.dumps(
            [self.tools[name].canonical() for name in self.tool_names()],
            **_CANONICAL
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def per_tool_digests(self):
        """Map of tool name to that tool's own digest."""
        return {
            name: hashlib.sha256(
                self.tools[name].canonical().encode("utf-8")
            ).hexdigest()
            for name in self.tool_names()
        }

    def to_dict(self):
        return {
            "serverName": self.server_name,
            "serverVersion": self.server_version,
            "source": self.source,
            "digest": self.digest,
            "tools": [self.tools[n].to_dict() for n in self.tool_names()],
        }

    def to_json(self, indent=2):
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    def save(self, path):
        """Write the snapshot to a file as JSON."""
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.to_json())
        return path

    @classmethod
    def load(cls, path):
        """Read a snapshot written by save()."""
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        entries = data.get("tools") or []
        return cls.from_dicts(
            entries,
            server_name=data.get("serverName"),
            server_version=data.get("serverVersion"),
            source=data.get("source"),
        )

    def __eq__(self, other):
        if not isinstance(other, ContractSnapshot):
            return NotImplemented
        return self.digest == other.digest

    def __hash__(self):
        return hash(self.digest)

    def __repr__(self):
        return "ContractSnapshot(%r, %d tools)" % (self.server_name, len(self.tools))


# ---------------------------------------------------------------------------
# Diffing
# ---------------------------------------------------------------------------


def _required(schema):
    """The set of required property names in a JSON schema."""
    if not isinstance(schema, dict):
        return set()
    required = schema.get("required")
    if isinstance(required, list):
        return set(x for x in required if isinstance(x, str))
    return set()


def _properties(schema):
    if not isinstance(schema, dict):
        return {}
    props = schema.get("properties")
    return props if isinstance(props, dict) else {}


def _type_of(prop):
    if not isinstance(prop, dict):
        return None
    t = prop.get("type")
    if isinstance(t, str):
        return t
    if isinstance(t, list):
        return ",".join(sorted(x for x in t if isinstance(x, str)))
    return None


def _classify_schema_change(old_spec, new_spec):
    """Classify how a tool's input schema changed.

    Returns a list of (kind, detail) pairs. The classification is
    deliberately conservative: anything that could break an existing
    caller is reported as BREAKING, because a false BREAKING costs a
    human thirty seconds and a missed BREAKING costs a production
    incident.
    """
    changes = []
    old_schema = old_spec.input_schema or {}
    new_schema = new_spec.input_schema or {}

    old_req = _required(old_schema)
    new_req = _required(new_schema)
    old_props = _properties(old_schema)
    new_props = _properties(new_schema)

    # A newly required parameter breaks every caller that omits it.
    added_required = sorted(new_req - old_req)
    if added_required:
        changes.append(
            (
                ChangeKind.BREAKING,
                "parameter(s) %s are now required" % ", ".join(added_required),
            )
        )

    # A parameter that stopped being required is a relaxation.
    removed_required = sorted(old_req - new_req)
    if removed_required:
        changes.append(
            (
                ChangeKind.RELAXED,
                "parameter(s) %s are no longer required" % ", ".join(removed_required),
            )
        )

    # A removed property breaks a caller that sends it, if it was required.
    removed_props = sorted(set(old_props) - set(new_props))
    required_removals = [p for p in removed_props if p in old_req]
    if required_removals:
        changes.append(
            (
                ChangeKind.BREAKING,
                "required parameter(s) %s removed" % ", ".join(required_removals),
            )
        )
    optional_removals = [p for p in removed_props if p not in old_req]
    if optional_removals:
        changes.append(
            (
                ChangeKind.NOTATION,
                "optional parameter(s) %s removed" % ", ".join(optional_removals),
            )
        )

    # A new parameter is additive. If it is required, it is already
    # reported above as BREAKING, so do not double-report it.
    added_props = sorted(set(new_props) - set(old_props))
    optional_additions = [p for p in added_props if p not in new_req]
    if optional_additions:
        changes.append(
            (
                ChangeKind.NEW,
                "optional parameter(s) %s added" % ", ".join(optional_additions),
            )
        )

    # A property whose type changed breaks callers that send the old type.
    for name in sorted(set(old_props) & set(new_props)):
        old_type = _type_of(old_props[name])
        new_type = _type_of(new_props[name])
        if old_type and new_type and old_type != new_type:
            changes.append(
                (
                    ChangeKind.BREAKING,
                    "parameter %r type changed from %s to %s"
                    % (name, old_type, new_type),
                )
            )

    return changes


def diff_snapshots(old, new):
    """Diff two contract snapshots into a classified list of changes.

    The classification:

    - NEW       a tool or optional parameter was added
    - GONE      a tool was removed -- always breaking for its callers
    - BREAKING  an existing caller would now fail
    - RELAXED   the server accepts strictly more than before
    - NOTATION  a cosmetic change: wording, descriptions, optional
                 parameters, metadata
    """
    changes = []

    old_names = set(old.tool_names())
    new_names = set(new.tool_names())

    for name in sorted(new_names - old_names):
        changes.append(Change(ChangeKind.NEW, name, "tool added"))

    for name in sorted(old_names - new_names):
        # A removed tool breaks every caller of that tool, so GONE is a
        # breaking kind even though it is reported separately from
        # BREAKING. is_breaking() treats it as breaking; a strict gate can
        # still filter on kind == BREAKING alone.
        changes.append(Change(ChangeKind.GONE, name, "tool removed"))

    for name in sorted(old_names & new_names):
        old_spec = old.tools[name]
        new_spec = new.tools[name]

        for kind, detail in _classify_schema_change(old_spec, new_spec):
            changes.append(Change(kind, name, detail))

        if old_spec.description != new_spec.description:
            changes.append(
                Change(ChangeKind.NOTATION, name, "description changed")
            )

        old_out = old_spec.output_digest
        new_out = new_spec.output_digest
        if old_out != new_out:
            if old_out is None:
                changes.append(
                    Change(ChangeKind.NEW, name, "outputSchema declared")
                )
            elif new_out is None:
                changes.append(
                    Change(ChangeKind.BREAKING, name, "outputSchema removed")
                )
            else:
                changes.append(
                    Change(ChangeKind.BREAKING, name, "outputSchema changed")
                )

    return changes


def snapshot_from_client(client, server_name=None):
    """Take a snapshot from a live MCP client.

    Works with any object exposing an awaitable list_tools() that
    returns objects with a name, description and inputSchema -- which
    includes tiny_mcp_client.MCPClient. The client is duck-typed on
    purpose: this package must not depend on the client package.
    """
    import asyncio

    async def _take():
        tools = await client.list_tools()
        specs = []
        for tool in tools:
            if isinstance(tool, dict):
                specs.append(ToolSpec.from_dict(tool))
            else:
                specs.append(
                    ToolSpec(
                        name=getattr(tool, "name", None),
                        description=getattr(tool, "description", "") or "",
                        input_schema=getattr(tool, "input_schema", None)
                        or getattr(tool, "inputSchema", None)
                        or {},
                        output_schema=getattr(tool, "output_schema", None)
                        or getattr(tool, "outputSchema", None),
                    )
                )
        return specs

    specs = asyncio.get_event_loop().run_until_complete(_take())
    return ContractSnapshot(
        specs,
        server_name=server_name or getattr(client, "server_name", None),
    )


def classify(changes):
    """Group changes by kind. Returns a dict of kind -> list of changes."""
    out = {}
    for change in changes:
        out.setdefault(change.kind, []).append(change)
    return out


def is_breaking(changes):
    """True if any change in the list would break an existing caller.

    A removed tool (GONE) counts as breaking: every caller of that tool
    fails at runtime. It is reported under its own kind so a report can
    distinguish "this tool disappeared" from "this tool changed shape",
    but it must still fail the gate.
    """
    return any(c.breaking or c.kind == ChangeKind.GONE for c in changes)
