"""CLI boundary for credential-safe audition startup."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TextIO

from animetta.acceptance.tts_audition.clients import AuditionClientError

AuditionExecutor = Callable[[str, Path], object]


def run_cli(
    *,
    environ: Mapping[str, str] | None = None,
    output_root: Path = Path("artifacts/tts-audition"),
    execute: AuditionExecutor | None = None,
    runtime_version: tuple[int, int] | None = None,
    stderr: TextIO | None = None,
    stdout: TextIO | None = None,
) -> int:
    """Validate startup inputs before allowing network or artifact side effects."""

    environment = os.environ if environ is None else environ
    error_stream = sys.stderr if stderr is None else stderr
    output_stream = sys.stdout if stdout is None else stdout
    version = sys.version_info[:2] if runtime_version is None else runtime_version
    if version < (3, 13):
        print(
            "Python 3.13 or newer is required. Run this command with py -3.13.", file=error_stream
        )
        return 2
    api_key = environment.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        print(
            "Missing DASHSCOPE_API_KEY. Set it in the current process environment, then retry.",
            file=error_stream,
        )
        return 2
    if execute is None:
        from animetta.acceptance.tts_audition.runner import execute_live_audition

        execute = execute_live_audition
    try:
        result = execute(api_key, output_root)
    except AuditionClientError as exc:
        print(f"Audition failed: {exc}", file=error_stream)
        return 1
    except (FileExistsError, ValueError) as exc:
        print(f"Audition failed: {exc}", file=error_stream)
        return 1
    except KeyboardInterrupt:
        print("Audition cancelled; no evidence bundle was published.", file=error_stream)
        return 130
    except Exception:
        print("Audition failed unexpectedly; no evidence bundle was published.", file=error_stream)
        return 1
    if isinstance(result, Path):
        print(f"Audition bundle: {result}", file=output_stream)
    return 0


def main() -> int:
    """Run the live audition with process environment defaults."""

    return run_cli()
