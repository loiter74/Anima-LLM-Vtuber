from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from .models import Catalog


@dataclass(frozen=True)
class LoadedCatalog:
    catalog: Catalog
    manifest_hash: str
    path: Path


def _catalog_hash(catalog: Catalog) -> str:
    payload = json.dumps(
        catalog.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_catalog(path: str | Path) -> LoadedCatalog:
    resolved = Path(path).resolve()
    raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    catalog = Catalog.model_validate(raw)
    return LoadedCatalog(catalog=catalog, manifest_hash=_catalog_hash(catalog), path=resolved)
