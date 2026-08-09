from __future__ import annotations

import pytest

from tooling.quality.path_matching import matches_repository_path


@pytest.mark.parametrize(
    ("path", "pattern", "expected"),
    [
        ("scripts/task.py", "scripts/**", True),
        (".agents/skills/demo/scripts/task.py", "scripts/**", False),
        ("src/module.py", "src/**/*.py", True),
        ("src/package/module.py", "src/**/*.py", True),
        ("AGENTS.md", "**/AGENTS.md", True),
        ("src/AGENTS.md", "**/AGENTS.md", True),
        ("frontend/src/view.ts", "frontend/src/**", True),
        ("frontend-test/src/view.ts", "frontend/src/**", False),
    ],
)
def test_repository_globs_are_root_anchored(path: str, pattern: str, expected: bool) -> None:
    assert matches_repository_path(path, pattern) is expected
