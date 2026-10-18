#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${REPO_DIR}/.venv"

echo "============================================================"
echo "  Bedtime Book Studio — Environment & Onboarding Setup"
echo "============================================================"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is required." >&2
  exit 1
fi

if [ ! -d "${VENV_DIR}" ]; then
  echo "-> Creating Python virtual environment in ${VENV_DIR}..."
  python3 -m venv "${VENV_DIR}"
fi

echo "-> Installing Python dependencies (Pillow, MCP SDK)..."
"${VENV_DIR}/bin/pip" install --upgrade pip -q
"${VENV_DIR}/bin/pip" install -r "${REPO_DIR}/requirements.txt" -q

chmod +x "${REPO_DIR}/scripts/book_studio.py" "${REPO_DIR}/scripts/mcp_server.py"

if [[ "${1:-}" != "--skip-onboard" ]]; then
  "${VENV_DIR}/bin/python" "${REPO_DIR}/scripts/book_studio.py" onboard
fi

cat <<EOF

============================================================
  Agent Integration Snippets
============================================================

1. MCP Server Config (Claude Code / Antigravity / Cursor / Windsurf):
Add to your MCP config JSON:

{
  "mcpServers": {
    "bedtime-book-studio": {
      "command": "${VENV_DIR}/bin/python",
      "args": ["${REPO_DIR}/scripts/mcp_server.py"]
    }
  }
}

2. Agent Skill Symlink (Antigravity / Claude / OpenClaw):
  mkdir -p ~/.agents/skills
  ln -sfn "${REPO_DIR}" ~/.agents/skills/bedtime-book-studio

3. Re-run onboarding anytime:
  ${VENV_DIR}/bin/python ${REPO_DIR}/scripts/book_studio.py onboard
============================================================
EOF
