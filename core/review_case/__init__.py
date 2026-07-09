"""OS-Agent review case system.

Agent-authored artifacts are Markdown contracts; JSON is produced only by
deterministic compilers for the frontend and batch index.
"""

from .contracts import ValidationIssue, ValidationReport

__all__ = ["ValidationIssue", "ValidationReport"]
