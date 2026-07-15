#!/usr/bin/env python3
"""
Wrapper entrypoint for survey pipeline workflows.

Forwards arguments to the repository-level unified CLI:
    python survey_tool_cli.py pipeline ...
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    parent_dir = script_dir.parent
    repo_root = parent_dir.parent

    # Support both source-tree execution and nested pipelines layouts where
    # survey_tool_cli.py is one or two levels above this wrapper.
    for root in (script_dir, parent_dir, repo_root):
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

    try:
        from survey_tool_cli import main as unified_main
    except Exception as exc:
        print(f"Failed to import unified CLI from '{repo_root}': {exc}", file=sys.stderr)
        return 1

    old_argv = sys.argv[:]
    try:
        sys.argv = ["survey_tool_cli.py", "pipeline", *old_argv[1:]]
        return int(unified_main())
    finally:
        sys.argv = old_argv


if __name__ == "__main__":
    raise SystemExit(main())
