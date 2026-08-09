from __future__ import annotations

import fnmatch

_GLOB_MARKERS = "*?["


def matches_repository_path(path: str, pattern: str) -> bool:
    """Match a repository-relative path without suffix-matching nested paths."""
    normalized_path = path.replace("\\", "/")
    normalized_pattern = pattern.replace("\\", "/")
    if not any(marker in normalized_pattern for marker in _GLOB_MARKERS):
        return normalized_path == normalized_pattern or normalized_path.startswith(
            normalized_pattern.rstrip("/") + "/"
        )
    if normalized_pattern.endswith("/**") and normalized_path.startswith(
        normalized_pattern[:-3].rstrip("/") + "/"
    ):
        return True
    return any(
        fnmatch.fnmatchcase(normalized_path, candidate)
        for candidate in _zero_directory_globstar_variants(normalized_pattern)
    )


def _zero_directory_globstar_variants(pattern: str) -> tuple[str, ...]:
    variants = {pattern}
    pending = [pattern]
    while pending:
        candidate = pending.pop()
        if candidate.startswith("**/"):
            reduced = candidate[3:]
            if reduced not in variants:
                variants.add(reduced)
                pending.append(reduced)
        marker = "/**/"
        start = 0
        while (index := candidate.find(marker, start)) >= 0:
            reduced = candidate[: index + 1] + candidate[index + len(marker) :]
            if reduced not in variants:
                variants.add(reduced)
                pending.append(reduced)
            start = index + 1
    return tuple(sorted(variants))
