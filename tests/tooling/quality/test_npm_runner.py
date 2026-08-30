from __future__ import annotations

import subprocess

import pytest

from tooling.quality.npm_runner import parse_commands, run_commands


def test_parse_commands_splits_npm_sequence() -> None:
    commands = parse_commands(("ci", "::", "run", "test:contract"))

    assert commands == (
        ("ci",),
        ("run", "test:contract"),
    )


@pytest.mark.parametrize(
    "arguments",
    [(), ("::", "test"), ("ci", "::")],
)
def test_parse_commands_rejects_empty_commands(arguments: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="command"):
        parse_commands(arguments)


def test_run_commands_stops_after_first_failure() -> None:
    calls: list[list[str]] = []

    def run(argv: list[str], *, check: bool) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 7 if len(calls) == 2 else 0)

    result = run_commands(
        "npm",
        (("ci",), ("run", "check"), ("test",)),
        command_runner=run,
    )

    assert result == 7
    assert calls == [["npm", "ci"], ["npm", "run", "check"]]
