#!/usr/bin/env bash
set -euo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

if [[ -n "${OS_AGENT_PYTHON:-}" && -x "${OS_AGENT_PYTHON}" ]]; then
  exec "${OS_AGENT_PYTHON}" "${ROOT}/mcp_server.py"
fi

for python_bin in \
  "${ROOT}/.venv/bin/python" \
  "${ROOT}/venv/bin/python"; do
  if [[ -x "${python_bin}" ]]; then
    exec "${python_bin}" "${ROOT}/mcp_server.py"
  fi
done

for python_bin in \
  "${HOME}/miniconda3/envs/os_agent/bin/python" \
  "${HOME}/anaconda3/envs/os_agent/bin/python" \
  "${HOME}/mambaforge/envs/os_agent/bin/python"; do
  if [[ -x "${python_bin}" ]]; then
    exec "${python_bin}" "${ROOT}/mcp_server.py"
  fi
done

if command -v conda >/dev/null 2>&1; then
  exec conda run --no-capture-output -n os_agent python "${ROOT}/mcp_server.py"
fi

echo "OS-Agent MCP: cannot find a Python environment with requirements installed. Create conda env os_agent, create .venv, or set OS_AGENT_PYTHON to its Python executable. See README.md Quick Start." >&2
exit 1
