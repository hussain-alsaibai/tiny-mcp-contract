"""tiny-mcp-contract -- snapshot and diff MCP tool contracts.

Zero dependencies. Answers a real, open, unanswered problem: MCP servers
change their tool contracts between releases without announcing it.
"""

from tiny_mcp_contract.core import (
    Change,
    ChangeKind,
    ContractSnapshot,
    ToolSpec,
    classify,
    diff_snapshots,
    is_breaking,
    snapshot_from_client,
)

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

__version__ = "0.1.0"
