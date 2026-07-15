from __future__ import annotations

from types import SimpleNamespace

import pytest

from evaluations.rag.runner import EvalConfig, EvalRunner


class FakeSearchBackend:
    def __init__(self) -> None:
        self.synced = False
        self.closed = False

    def sync(self) -> None:
        self.synced = True

    def search(self, query: str, max_results: int) -> list[SimpleNamespace]:
        return []

    def close(self) -> None:
        self.closed = True


def test_eval_runner_requires_an_explicit_v2_search_backend(tmp_path) -> None:
    runner = EvalRunner(tmp_path, EvalConfig(name="contract"))

    with pytest.raises(RuntimeError, match="search backend factory"):
        runner.setup()


def test_eval_runner_owns_injected_search_backend_lifecycle(tmp_path) -> None:
    backend = FakeSearchBackend()
    runner = EvalRunner(
        tmp_path,
        EvalConfig(name="contract"),
        manager_factory=lambda workspace, config: backend,
    )

    runner.setup()
    runner.sync()
    result = runner.run([], k=5)
    runner.teardown()

    assert backend.synced is True
    assert backend.closed is True
    assert result["summary"]["total_queries"] == 0
