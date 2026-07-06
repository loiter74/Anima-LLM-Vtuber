from __future__ import annotations

"""Safe temporary file helpers."""

from pathlib import Path
from tempfile import NamedTemporaryFile


def write_temp_bytes(data: bytes, *, suffix: str) -> str:
    """Write bytes to a safely-created temp file and return its path."""
    with NamedTemporaryFile("wb", suffix=suffix, delete=False) as temp_file:
        temp_file.write(data)
        return temp_file.name


def reserve_temp_path(*, suffix: str) -> Path:
    """Return a safely-created temp path for another writer to fill later."""
    with NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
        return Path(temp_file.name)
