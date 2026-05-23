"""
OpenHands integration placeholder.

The current demo uses mock_pipeforge_runner.py to guarantee that the event stream,
trace tree, ask_user flow, parallel agents, and artifacts work end-to-end.

Final integration idea:
- Run OpenHands in a workspace.
- Capture raw OpenHands actions/tool calls/file edits.
- Normalize them into the same AgentEvent schema.
- Reuse the frontend unchanged.
"""

import os
from pathlib import Path


def get_openhands_config() -> dict:
    return {
        "api_key_present": bool(os.getenv("LLM_API_KEY")),
        "model": os.getenv("LLM_MODEL", ""),
        "base_url": os.getenv("LLM_BASE_URL", ""),
    }


def get_workspace(run_id: str) -> Path:
    workspace_root = Path(os.getenv("OPENHANDS_WORKSPACE_DIR", "/app/workspace"))
    workspace = workspace_root / run_id
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace