# tiny-mcp-contract

[![CI](https://github.com/hussain-alsaibai/tiny-mcp-contract/actions/workflows/ci.yml/badge.svg)](https://github.com/hussain-alsaibai/tiny-mcp-contract/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Deps](https://img.shields.io/badge/dependencies-0-orange.svg)](pyproject.toml)

**Zero-dependency MCP tool-contract snapshots and diffs.**

Catch silent breaking changes between MCP server releases — before your
clients find out at runtime.

---

## The problem

An MCP server can change its tool contract between versions and nothing
tells you.

- a required parameter is added
- a tool disappears
- a parameter's type changes
- an `outputSchema` is dropped

None of it appears in the changelog. Your client keeps sending the old
shape and fails at runtime, with an error that points at the call site
rather than the release that caused it.

This is not hypothetical. In
[modelcontextprotocol/servers#5414](https://github.com/modelcontextprotocol/servers/issues/5414)
the reporter measured **140 silent contract changes across 66 version
pairs** of the reference servers — none announced in the changelogs. The
most-installed server, `server-filesystem`, went from 0.2.0 to 1.0.0
with 14 findings.

The reference servers are the template the ecosystem copies. Silent
breakage there propagates as accepted practice.

## What this does

```python
from tiny_mcp_contract import ContractSnapshot, diff_snapshots, is_breaking

old = ContractSnapshot.from_json(open("v1.json").read())
new = ContractSnapshot.from_json(open("v2.json").read())

changes = diff_snapshots(old, new)

for c in changes:
    print(c.kind, c.subject, c.detail)

if is_breaking(changes):
    raise SystemExit("contract broke")
```

Output:

```
BREAKING  read_file: parameter(s) encoding are now required
NEW       read_directory: tool added
NOTATION  write_file: description changed
```

## Change kinds

| kind | meaning | breaks a caller? |
|---|---|---|
| `BREAKING` | an existing caller would now fail | yes |
| `GONE` | a tool was removed | yes |
| `NEW` | a tool or optional parameter was added | no |
| `RELAXED` | the server now accepts strictly more | no |
| `NOTATION` | cosmetic: wording, descriptions, optional params | no |

The classification is deliberately conservative. Anything that could
break an existing caller is reported as breaking, because a false
`BREAKING` costs a human thirty seconds and a missed `BREAKING` costs a
production incident.

The kind names match the taxonomy used in
[the MCP contract-drift discussion](https://github.com/modelcontextprotocol/servers/issues/5414),
so a diff produced here can be compared against theirs directly.

## CLI

```bash
# Print the contract digest -- this is what you pin in CI.
tiny-mcp-contract digest contract.json

# Diff two snapshots.
tiny-mcp-contract diff old.json new.json

# Exit non-zero if a caller would break.
tiny-mcp-contract check baseline.json current.json

# The CI gate. Exits 1 on a breaking change.
tiny-mcp-contract gate baseline.json current.json

# Fail on ANY change, not just breaking ones.
tiny-mcp-contract gate --strict baseline.json current.json
```

Add `--json` to any command for machine-readable output.

## API reference

| name | what it is |
|---|---|
| `ContractSnapshot` | the snapshot: `from_dicts`, `from_json`, `load`, `save`, `digest`, `per_tool_digests` |
| `ToolSpec` | one tool: `from_dict`, `input_digest`, `output_digest` |
| `Change` | one difference: `kind`, `subject`, `detail`, `breaking` |
| `ChangeKind` | the kinds: `BREAKING`, `NEW`, `GONE`, `NOTATION`, `RELAXED` |
| `diff_snapshots` | diff two snapshots into a list of `Change` |
| `classify` | group changes by kind into a dict |
| `is_breaking` | True if any change would break an existing caller |
| `snapshot_from_client` | take a snapshot from a live MCP client |

## The CI gate

The whole point of the package. Pin a baseline, diff against it, fail the
build:

```yaml
- name: Check the MCP tool contract
  run: |
    tiny-mcp-contract gate contract/baseline.json contract/current.json \
      --json > contract-diff.json
```

The gate exits **1** when a breaking change is present and **0** when
there is none. That is the contract: a gate that always returns zero is
worse than no gate, because it teaches people to ignore it.

## Digests

```python
old.digest          # sha256 of the whole contract
old.per_tool_digests()   # {"read_file": "a1b2...", ...}
tool.input_digest   # sha256 of the input schema alone
tool.output_digest  # sha256 of the output schema alone, or None
```

The digest is computed over **canonical JSON** — sorted keys, no
insignificant whitespace — so a server that reformats its output does
not look like a contract change.

The output schema is hashed **separately** from the input schema, because
a server that starts declaring an `outputSchema` has changed what it
promises to return. That is a different kind of change from tightening
what it accepts.

## Taking a snapshot from a live client

```python
from tiny_mcp_client import MCPClient
from tiny_mcp_contract import snapshot_from_client

client = MCPClient(...)
await client.initialize()
snap = snapshot_from_client(client)
snap.save("contract.json")
```

The client is duck-typed on purpose: any object with an awaitable
`list_tools()` works, so this package does not depend on the client
package.

## Tests

```bash
python -m pytest tests/ -v
```

49 tests. The suite includes a test that models the real
`server-filesystem` 0.2.0 to 1.0.0 change from issue #5414, and a test
that a version bump **alone** produces no changes — a release that only
changes the version number is not contract drift.

## Requirements

- Python 3.8+
- No runtime dependencies

## Part of the tiny-* ecosystem

- [`tiny-mcp-client`](https://github.com/hussain-alsaibai/tiny-mcp-client) — a zero-dependency MCP client
- [`tiny-router`](https://github.com/hussain-alsaibai/tiny-router) — HTTP router
- [`tiny-worktree`](https://github.com/hussain-alsaibai/tiny-worktree) — git worktrees for parallel agents
- [`tiny-validator`](https://github.com/hussain-alsaibai/tiny-validator) — input validation
- [`tiny-log`](https://github.com/hussain-alsaibai/tiny-log) — structured logging
- [`fast-cache`](https://github.com/hussain-alsaibai/fast-cache) — LRU + TTL cache

## License

MIT
