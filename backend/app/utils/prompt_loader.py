from pathlib import Path
from string import Template
from typing import Any


PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


def load_prompt_template(filename: str) -> Template:
    path = PROMPTS_DIR / filename

    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")

    content = path.read_text(encoding="utf-8")
    return Template(content)


def render_prompt(filename: str, **values: Any) -> str:
    template = load_prompt_template(filename)
    safe_values = {key: str(value) for key, value in values.items()}
    return template.substitute(**safe_values)


def load_prompt_text(filename: str) -> str:
    path = PROMPTS_DIR / filename

    if not path.exists():
        raise FileNotFoundError(f"Prompt text not found: {path}")

    return path.read_text(encoding="utf-8")