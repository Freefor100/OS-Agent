#!/usr/bin/env python3
"""Run one OS-Agent tool from the command line.

This is a diagnostic/emergency entrypoint. Normal Claude Code workflow should call
the MCP tools directly. This script imports ``mcp_server.py`` and invokes the same
Python function by name, so it does not duplicate tool logic and does not speak
stdio JSON-RPC.

Usage:
  scripts/run_mcp_tool.py <tool_name> '<json_object_args>'
  scripts/run_mcp_tool.py --list
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import traceback
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONUNBUFFERED", "1")


def _candidate_pythons() -> list[Path]:
    candidates: list[Path] = []
    env_python = os.environ.get("OS_AGENT_PYTHON")
    if env_python:
        candidates.append(Path(env_python))
    candidates.extend([
        ROOT / ".venv" / "bin" / "python",
        ROOT / "venv" / "bin" / "python",
        Path.home() / "miniconda3" / "envs" / "os_agent" / "bin" / "python",
        Path.home() / "anaconda3" / "envs" / "os_agent" / "bin" / "python",
        Path.home() / "mambaforge" / "envs" / "os_agent" / "bin" / "python",
    ])
    return candidates


def _reexec_with_project_python() -> None:
    if os.environ.get("OS_AGENT_RUN_MCP_REEXEC") == "1":
        return
    env = dict(os.environ)
    env["OS_AGENT_RUN_MCP_REEXEC"] = "1"
    current = Path(sys.executable).resolve()
    for python in _candidate_pythons():
        if python.is_file() and os.access(python, os.X_OK) and python.resolve() != current:
            os.execve(str(python), [str(python), str(Path(__file__).resolve()), *sys.argv[1:]], env)
    for runner in ("conda", "mamba", "micromamba"):
        exe = shutil.which(runner)
        if exe:
            run_args = [exe, "run"]
            if runner in {"conda", "mamba"}:
                run_args.append("--no-capture-output")
            os.execve(exe, [*run_args, "-n", "os_agent", "python", str(Path(__file__).resolve()), *sys.argv[1:]], env)


def _load_tools() -> dict[str, Any]:
    try:
        import mcp_server
    except ModuleNotFoundError as exc:
        if exc.name == "mcp":
            _reexec_with_project_python()
            raise SystemExit(
                "Cannot import MCP dependencies from this Python, and no OS-Agent "
                "Python environment was found. Create .venv, create conda env "
                "os_agent, or set OS_AGENT_PYTHON to the environment's Python."
            ) from exc
        raise

    manager = getattr(mcp_server.mcp, "_tool_manager", None)
    registered = getattr(manager, "_tools", None)
    if not isinstance(registered, dict):
        raise SystemExit("Cannot inspect MCP tool registry from mcp_server.py.")
    return dict(sorted((name, tool.fn) for name, tool in registered.items()))


def _json_default(value: Any) -> str:
    return str(value)


def main(argv: list[str]) -> int:
    tools = _load_tools()
    if len(argv) == 2 and argv[1] in {"--list", "list"}:
        print(json.dumps({"tools": list(tools)}, ensure_ascii=False, indent=2))
        return 0

    if len(argv) < 2 or argv[1] in {"-h", "--help"}:
        print(__doc__.strip(), file=sys.stderr)
        return 2

    tool_name = argv[1]
    if tool_name not in tools:
        print(f"Unknown tool: {tool_name}", file=sys.stderr)
        print("Use --list to show available tools.", file=sys.stderr)
        return 2

    if len(argv) > 2:
        try:
            args = json.loads(argv[2])
        except json.JSONDecodeError as exc:
            print(f"Invalid JSON args: {exc}", file=sys.stderr)
            return 2
    else:
        args = {}
    if not isinstance(args, dict):
        print("JSON args must be an object, for example '{\"target\":\"repo\"}'.", file=sys.stderr)
        return 2

    try:
        result = tools[tool_name](**args)
    except Exception:
        traceback.print_exc()
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
