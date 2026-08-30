"""Run a lockfile-backed sequence of npm commands without a command shell."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from collections.abc import Callable, Sequence

from .models import parse_npm_commands as parse_commands


def run_commands(
    npm_executable: str,
    commands: Sequence[Sequence[str]],
    *,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> int:
    """Run commands in order and stop at the first non-zero exit status."""

    for command in commands:
        argv = [npm_executable, *command]
        print(f"$ npm {shlex.join(command)}", flush=True)
        try:
            completed = command_runner(argv, check=False)
        except OSError as exc:
            print(f"npm launch failed: {exc}", file=sys.stderr)
            return 127
        if completed.returncode != 0:
            return completed.returncode
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--npm", required=True, help="resolved npm executable")
    parser.add_argument("commands", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    arguments = args.commands[1:] if args.commands[:1] == ["--"] else args.commands
    try:
        commands = parse_commands(arguments)
    except ValueError as exc:
        parser.error(str(exc))
    return run_commands(args.npm, commands)


if __name__ == "__main__":
    raise SystemExit(main())
