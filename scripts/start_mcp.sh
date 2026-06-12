#!/usr/bin/env bash
set -euo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

if [[ -n "${OS_AGENT_PYTHON:-}" && -x "${OS_AGENT_PYTHON}" ]]; then
  exec "${OS_AGENT_PYTHON}" "${ROOT}/mcp_server.py"
fi

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

echo "OS-Agent MCP: cannot find the os_agent Python environment. Set OS_AGENT_PYTHON to its Python executable." >&2
exit 1
