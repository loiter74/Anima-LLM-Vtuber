from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .hashing import canonical_json_hash
from .models import Catalog


@dataclass(frozen=True)
class LoadedCatalog:
    catalog: Catalog
    manifest_hash: str
    path: Path


def _catalog_hash(catalog: Catalog) -> str:
    return canonical_json_hash(catalog)


def load_catalog(path: str | Path) -> LoadedCatalog:
    resolved = Path(path).resolve()
    raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    catalog = Catalog.model_validate(raw)
    return LoadedCatalog(catalog=catalog, manifest_hash=_catalog_hash(catalog), path=resolved)
