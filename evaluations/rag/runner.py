#!/usr/bin/env python3
"""RAG Evaluation Runner — Core engine for running retrieval experiments.

Usage:
    python evaluations/rag/runner.py \\
        --config evaluations/rag/configs.yaml \\
        --group baseline \\
        --dataset evaluations/rag/dataset.jsonl \\
        --k 5 \\
        --output evaluations/rag/results/
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import tempfile
import time
import traceback
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import yaml

# Ensure project root + src/ are on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC_ROOT = _PROJECT_ROOT / "src"
for _p in (str(_PROJECT_ROOT), str(_SRC_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


from evaluations.rag.metrics import (
    chunk_diversity,
    latency_percentiles,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)

logger = logging.getLogger(__name__)

# ── ChunkId type alias (matches metrics.py) ────────────────────────────
ChunkId = tuple[str, int, int]  # (path, start_line, end_line)


# ═══════════════════════════════════════════════════════════════════════
# EvalConfig
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class EvalConfig:
    """Single experiment configuration — mirrors MemoryConfig parameters."""

    name: str
    vector_weight: float = 0.7
    keyword_weight: float = 0.3
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    target_tokens: int = 400
    overlap_tokens: int = 80
    chars_per_token: float = 2.0
    fuzzy_enabled: bool = False
    max_results: int = 5
    candidate_multiplier: int = 4
    description: str = ""


class SearchResult(Protocol):
    path: str
    start_line: int
    end_line: int
    score: float
    text: str


class SearchBackend(Protocol):
    def sync(self) -> None: ...

    def search(self, query: str, max_results: int) -> list[SearchResult]: ...

    def close(self) -> None: ...


SearchBackendFactory = Callable[[Path, EvalConfig], SearchBackend]


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════


def _search_result_to_chunk_id(sr: SearchResult) -> ChunkId:
    """Convert a SearchResult to a ChunkId tuple for metrics.

    Normalizes path separators to forward slash for cross-platform matching.
    """
    normalized_path = sr.path.replace("\\", "/")
    return (normalized_path, sr.start_line, sr.end_line)


def _expected_to_chunk_ids(expected_chunks: list[dict]) -> list[ChunkId]:
    """Convert dataset expected_chunks to ChunkId tuples.

    Normalizes path separators to forward slash for cross-platform matching.
    """
    return [(c["path"].replace("\\", "/"), c["start_line"], c["end_line"]) for c in expected_chunks]


def _normalize_expected(expected: list[ChunkId], retrieved: list[ChunkId]) -> list[ChunkId]:
    """Remap expected chunk IDs to match actual retrieved chunk boundaries.

    The dataset annotates specific line ranges (e.g., L19-L21), but the
    chunker produces larger chunks (e.g., L1-L22). This function uses
    "contains" matching: if a retrieved chunk covers the expected line
    range, remap the expected ID to the retrieved chunk's exact boundaries
    so that set-intersection metrics work correctly.
    """
    normalized: list[ChunkId] = []
    for exp_path, exp_start, exp_end in expected:
        found = False
        for r_path, r_start, r_end in retrieved:
            if r_path == exp_path and r_start <= exp_start and r_end >= exp_end:
                normalized.append((r_path, r_start, r_end))
                found = True
                break
        if not found:
            # Keep original — metrics will correctly report 0 for this
            normalized.append((exp_path, exp_start, exp_end))
    return normalized


def load_jsonl(path: str | Path) -> list[dict]:
    """Load a JSONL dataset file."""
    path = Path(path)
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def get_git_commit() -> str:
    """Get current git commit (short hash), or 'unknown'."""
    import subprocess

    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            text=True,
        ).strip()
    except Exception:
        return "unknown"


def _copy_corpus(project_root: Path, workspace: Path) -> int:
    """Copy eval corpus from memory_db/ into workspace.

    Returns number of files copied.
    """
    copied = 0
    for src_name in ("wiki", "raw"):
        src = project_root / "memory_db" / src_name
        if not src.exists():
            logger.warning("Corpus source missing: %s", src)
            continue
        dst = workspace / src_name
        dst.mkdir(parents=True, exist_ok=True)
        for item in src.rglob("*"):
            if item.is_file():
                rel = item.relative_to(src)
                target = dst / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
                copied += 1
    return copied


# ═══════════════════════════════════════════════════════════════════════
# EvalRunner
# ═══════════════════════════════════════════════════════════════════════


class EvalRunner:
    """Runs a single experiment configuration against a dataset."""

    def __init__(
        self,
        workspace_dir: Path,
        config: EvalConfig,
        manager_factory: SearchBackendFactory | None = None,
    ):
        self.workspace_dir = workspace_dir
        self.config = config
        self._manager_factory = manager_factory
        self._manager: SearchBackend | None = None

    @property
    def manager(self) -> SearchBackend:
        if self._manager is None:
            raise RuntimeError("MemoryManager not initialized. Call setup() first.")
        return self._manager

    def setup(self) -> None:
        """Initialize the configured search backend."""
        if self._manager_factory is None:
            raise RuntimeError(
                "RAG evaluation requires a search backend factory; "
                "the legacy MemoryManager was removed by the Memory V2 migration"
            )
        self._manager = self._manager_factory(self.workspace_dir, self.config)

    def sync(self) -> None:
        """Index all files in the workspace."""
        self.manager.sync()

    def run(self, dataset: list[dict], k: int = 5) -> dict[str, Any]:
        """Run evaluation: search each query, measure latency, compute metrics.

        Returns a result dict suitable for the reporter.
        """
        timings_ms: list[float] = []
        per_query: list[dict] = []

        # Group metrics accumulators per category
        cat_recall: dict[str, list[float]] = {}
        cat_precision: dict[str, list[float]] = {}
        cat_mrr: dict[str, list[float]] = {}
        cat_ndcg: dict[str, list[float]] = {}
        cat_latency: dict[str, list[float]] = {}

        for item in dataset:
            query = item["query"]
            expected = _expected_to_chunk_ids(item.get("expected_chunks", []))

            # ── Search + latency ──
            t0 = time.perf_counter()
            search_results = self.manager.search(query, max_results=k)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            timings_ms.append(elapsed_ms)

            # ── Convert to metric format ──
            retrieved_chunk_ids = [_search_result_to_chunk_id(sr) for sr in search_results]

            # ── Normalize expected chunks to match actual chunk boundaries ──
            # The dataset annotates specific line ranges, but the chunker may
            # produce larger chunks. Use "contains" matching: if a retrieved
            # chunk covers the expected line range, remap the expected ID to
            # the retrieved chunk's actual boundaries.
            normalized_expected = _normalize_expected(expected, retrieved_chunk_ids)

            # ── Compute per-query metrics ──
            rec = recall_at_k(retrieved_chunk_ids, normalized_expected, k)
            prec = precision_at_k(retrieved_chunk_ids, normalized_expected, k)
            mrr_val = mrr(retrieved_chunk_ids, normalized_expected)
            ndcg_val = ndcg_at_k(retrieved_chunk_ids, normalized_expected, k)

            # ── Chunk diversity ──
            retrieved_chunks_for_diversity = [{"path": sr.path} for sr in search_results[:k]]
            div = chunk_diversity(retrieved_chunks_for_diversity)

            # ── Store per-query result ──
            retrieved_summary = [
                {
                    "path": sr.path,
                    "start_line": sr.start_line,
                    "end_line": sr.end_line,
                    "score": round(sr.score, 4),
                    "text_preview": sr.text[:120] if sr.text else "",
                }
                for sr in search_results[:k]
            ]

            per_query.append(
                {
                    "id": item["id"],
                    "query": query,
                    "category": item.get("category", "unknown"),
                    "difficulty": item.get("difficulty", "unknown"),
                    "retrieved_chunks": retrieved_summary,
                    "expected_chunks": item.get("expected_chunks", []),
                    "expected_docs": item.get("expected_docs", []),
                    "recall_at_k": round(rec, 4),
                    "precision_at_k": round(prec, 4),
                    "mrr": round(mrr_val, 4),
                    "ndcg_at_k": round(ndcg_val, 4),
                    "latency_ms": round(elapsed_ms, 2),
                    "chunk_diversity": round(div, 4),
                }
            )

            # ── Accumulate per category ──
            cat = item.get("category", "unknown")
            cat_recall.setdefault(cat, []).append(rec)
            cat_precision.setdefault(cat, []).append(prec)
            cat_mrr.setdefault(cat, []).append(mrr_val)
            cat_ndcg.setdefault(cat, []).append(ndcg_val)
            cat_latency.setdefault(cat, []).append(elapsed_ms)

        # ── Aggregate overall summary ──
        all_recall = [q["recall_at_k"] for q in per_query]
        all_precision = [q["precision_at_k"] for q in per_query]
        all_mrr = [q["mrr"] for q in per_query]
        all_ndcg = [q["ndcg_at_k"] for q in per_query]
        all_diversity = [q["chunk_diversity"] for q in per_query]

        lpc = latency_percentiles(timings_ms)

        summary = {
            "recall_at_k": round(sum(all_recall) / len(all_recall), 4) if all_recall else 0.0,
            "precision_at_k": round(sum(all_precision) / len(all_precision), 4)
            if all_precision
            else 0.0,
            "mrr": round(sum(all_mrr) / len(all_mrr), 4) if all_mrr else 0.0,
            "ndcg_at_k": round(sum(all_ndcg) / len(all_ndcg), 4) if all_ndcg else 0.0,
            "chunk_diversity": round(sum(all_diversity) / len(all_diversity), 4)
            if all_diversity
            else 0.0,
            "latency_p50_ms": round(lpc["p50"], 2),
            "latency_p95_ms": round(lpc["p95"], 2),
            "latency_p99_ms": round(lpc["p99"], 2),
            "latency_mean_ms": round(lpc["mean"], 2),
            "total_queries": len(per_query),
            "k": k,
        }

        # ── Per-category summary ──
        per_category: dict[str, dict] = {}
        for cat in sorted(cat_recall.keys()):
            vals = cat_recall[cat]
            if not vals:
                continue
            per_category[cat] = {
                "recall_at_k": round(sum(vals) / len(vals), 4),
                "precision_at_k": round(sum(cat_precision.get(cat, [])) / len(vals), 4),
                "mrr": round(sum(cat_mrr.get(cat, [])) / len(vals), 4),
                "ndcg_at_k": round(sum(cat_ndcg.get(cat, [])) / len(vals), 4),
                "latency_mean_ms": round(sum(cat_latency.get(cat, [])) / len(vals), 2),
                "count": len(vals),
            }

        return {
            "config": asdict(self.config),
            "timestamp": datetime.now(UTC).isoformat(),
            "git_commit": get_git_commit(),
            "summary": summary,
            "per_category": per_category,
            "per_query": per_query,
            "latency_percentiles": lpc,
        }

    def teardown(self) -> None:
        """Clean up the MemoryManager."""
        if self._manager is not None:
            self._manager.close()
            self._manager = None


# ═══════════════════════════════════════════════════════════════════════
# Main / CLI
# ═══════════════════════════════════════════════════════════════════════


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RAG Evaluation Runner — run retrieval experiments against a dataset.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to configs.yaml (experiment matrix)",
    )
    parser.add_argument(
        "--group",
        default="baseline",
        help="Experiment group name from configs.yaml (default: baseline)",
    )
    parser.add_argument(
        "--dataset",
        required=True,
        help="Path to dataset.jsonl",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=5,
        help="Top-k for retrieval metrics (default: 5)",
    )
    parser.add_argument(
        "--output",
        default="evaluations/rag/results/",
        help="Output directory for result files (default: evaluations/rag/results/)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    # ── Logging ──
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    # ── Load configs YAML ──
    config_path = Path(args.config).resolve()
    if not config_path.exists():
        logger.error("Config file not found: %s", config_path)
        sys.exit(1)

    with open(config_path, encoding="utf-8") as f:
        all_configs = yaml.safe_load(f)

    experiments = all_configs.get("experiments", {})
    if args.group not in experiments:
        logger.error(
            "Experiment group '%s' not found in %s. Available: %s",
            args.group,
            config_path,
            list(experiments.keys()),
        )
        sys.exit(1)

    group_configs = experiments[args.group]
    defaults = all_configs.get("defaults", {})
    logger.info("Experiment group: %s (%d configs)", args.group, len(group_configs))

    # ── Load dataset ──
    dataset_path = Path(args.dataset).resolve()
    if not dataset_path.exists():
        logger.error("Dataset file not found: %s", dataset_path)
        sys.exit(1)

    dataset = load_jsonl(dataset_path)
    logger.info("Loaded %d queries from dataset", len(dataset))

    # ── Locate corpus ──
    project_root = config_path.parent.parent.parent
    corpus_wiki = project_root / "memory_db" / "wiki"
    corpus_raw = project_root / "memory_db" / "raw"
    has_corpus = corpus_wiki.exists() or corpus_raw.exists()
    if not has_corpus:
        logger.warning(
            "memory_db/ corpus not found at %s — search will return empty results",
            project_root / "memory_db",
        )

    # ── Output directory ──
    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Run experiments ──
    all_results: list[dict] = []
    total_configs = len(group_configs)

    for idx, (exp_name, exp_params) in enumerate(group_configs.items(), 1):
        logger.info("── [%d/%d] Running: %s ──", idx, total_configs, exp_name)

        # Merge defaults + experiment params
        merged = {**defaults, **exp_params}
        eval_config = EvalConfig(name=exp_name, **merged)

        # Create isolated workspace
        with tempfile.TemporaryDirectory(
            prefix=f"rag_eval_{exp_name}_", ignore_cleanup_errors=True
        ) as tmpdir:
            ws = Path(tmpdir)
            logger.debug("Workspace: %s", ws)

            # Copy corpus
            if has_corpus:
                copied = _copy_corpus(project_root, ws)
                logger.info("Copied %d corpus files to workspace", copied)
            else:
                # Create empty dirs so sync() doesn't error
                (ws / "wiki").mkdir(parents=True, exist_ok=True)
                (ws / "raw").mkdir(parents=True, exist_ok=True)

            # Run evaluation
            try:
                runner = EvalRunner(ws, eval_config)
                runner.setup()
                runner.sync()

                t_start = time.perf_counter()
                result = runner.run(dataset, k=args.k)
                elapsed = time.perf_counter() - t_start

                runner.teardown()

                logger.info(
                    "  recall@%d=%.3f  mrr=%.3f  p50_latency=%.1fms  total=%.1fs",
                    args.k,
                    result["summary"]["recall_at_k"],
                    result["summary"]["mrr"],
                    result["summary"]["latency_p50_ms"],
                    elapsed,
                )
                all_results.append(result)

            except Exception:
                logger.exception("Failed to run experiment: %s", exp_name)
                traceback.print_exc()

    # ── Generate reports ──
    if all_results:
        from evaluations.rag.reporter import (
            save_charts,
            save_json_results,
            save_json_summary,
            save_markdown_report,
        )

        for result in all_results:
            exp_out_dir = output_dir / result["config"]["name"]
            exp_out_dir.mkdir(parents=True, exist_ok=True)
            save_json_results(result, exp_out_dir)
            save_json_summary(result, exp_out_dir)
            save_markdown_report(result, exp_out_dir)

        # Aggregated charts (compare all configs)
        save_charts(all_results, output_dir / "charts")
        logger.info("Charts saved to %s", output_dir / "charts")

        logger.info("All results saved to %s", output_dir)
    else:
        logger.warning("No results generated.")


if __name__ == "__main__":
    main()
