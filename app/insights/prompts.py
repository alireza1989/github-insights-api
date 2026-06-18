"""File-based versioned prompt registry.

Prompts live in prompts/ as Markdown files named {name}_{role}_v{version}.md.
Every LLM call logs the name + version so changes are auditable.
Bumping a version requires re-running evals before merging.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


@dataclass(frozen=True)
class Prompt:
    name: str
    role: str
    version: int
    text: str

    def render(self, **kwargs: object) -> str:
        return self.text.format(**kwargs)


class PromptRegistry:
    def __init__(self, prompts_dir: Path = _PROMPTS_DIR) -> None:
        self._dir = prompts_dir
        self._cache: dict[str, Prompt] = {}

    def get(self, name: str, role: str, version: int = 1) -> Prompt:
        key = f"{name}_{role}_v{version}"
        if key not in self._cache:
            path = self._dir / f"{key}.md"
            if not path.exists():
                raise FileNotFoundError(f"Prompt file not found: {path}")
            self._cache[key] = Prompt(
                name=name, role=role, version=version, text=path.read_text()
            )
        return self._cache[key]

    def version_string(self, name: str, role: str, version: int = 1) -> str:
        return f"{name}_v{version}"


_registry = PromptRegistry()


def get_prompt(name: str, role: str, version: int = 1) -> Prompt:
    return _registry.get(name, role, version)
