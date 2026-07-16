from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

ARCHIVE_DOCS = [
    ROOT / ".claude" / "commands" / "opsx" / "archive.md",
    ROOT / ".agents" / "skills" / "source-command-opsx-archive" / "SKILL.md",
    ROOT / ".agents" / "skills" / "openspec-archive-change" / "SKILL.md",
]


def test_opsx_archive_docs_finalize_git_to_remote_and_main() -> None:
    required_phrases = [
        "**Finalize Git state**",
        "git add",
        'git commit -m "archive: <change-name>"',
        "git push -u origin",
        "git checkout main",
        "git pull --ff-only origin main",
        "git merge --no-ff",
        "git push origin main",
        "Do not stage unrelated worktree changes",
        "If the main branch has uncommitted changes",
        "If merge conflicts occur",
    ]

    for path in ARCHIVE_DOCS:
        text = path.read_text(encoding="utf-8")
        missing = [phrase for phrase in required_phrases if phrase not in text]
        assert not missing, (
            f"{path.relative_to(ROOT)} missing archive Git finalization phrases: {missing}"
        )
