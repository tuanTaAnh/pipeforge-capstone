from __future__ import annotations

from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = APP_DIR / "contracts"
SEMANTIC_CONTRACTS_DIR = CONTRACTS_DIR / "semantic"
PROMPTS_DIR = APP_DIR / "prompts"
DATA_DIR = APP_DIR / "data"
