from __future__ import annotations

from pathlib import Path

FORBIDDEN_PATTERNS = (
    "import training_lab",
    "from training_lab",
    "import persona_lab",
    "from persona_lab",
)


def test_animetta_runtime_does_not_import_training_lab_modules() -> None:
    violations: list[str] = []
    for path in Path("src/animetta").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(FORBIDDEN_PATTERNS):
                violations.append(f"{path}:{line_number}:{stripped}")

    assert violations == []
