from __future__ import annotations

from types import SimpleNamespace

import pytest

from evaluations.rag.runner import EvalConfig, EvalRunner, main


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


def test_rag_cli_returns_nonzero_when_every_experiment_fails(tmp_path) -> None:
    config = tmp_path / "configs.yaml"
    config.write_text(
        "experiments:\n  baseline:\n    broken: {}\n",
        encoding="utf-8",
    )
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text("", encoding="utf-8")

    def failing_factory(workspace, eval_config):
        raise RuntimeError("backend unavailable")

    exit_code = main(
        [
            "--config",
            str(config),
            "--dataset",
            str(dataset),
            "--output",
            str(tmp_path / "results"),
        ],
        manager_factory=failing_factory,
    )

    assert exit_code == 1


def test_rag_cli_requires_an_explicit_backend_factory(tmp_path) -> None:
    config = tmp_path / "configs.yaml"
    config.write_text("experiments:\n  baseline:\n    one: {}\n", encoding="utf-8")
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text("", encoding="utf-8")

    exit_code = main(
        ["--config", str(config), "--dataset", str(dataset)],
        manager_factory=None,
    )

    assert exit_code == 2


def test_rag_cli_rejects_an_empty_experiment_group(tmp_path) -> None:
    config = tmp_path / "configs.yaml"
    config.write_text("experiments:\n  baseline: {}\n", encoding="utf-8")
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text("", encoding="utf-8")

    exit_code = main(
        ["--config", str(config), "--dataset", str(dataset)],
        manager_factory=lambda workspace, eval_config: FakeSearchBackend(),
    )

    assert exit_code == 1


def test_eval_config_defaults_match_production_weights() -> None:
    """Harness defaults MUST match production (store.py 0.55/0.25)."""
    config = EvalConfig(name="defaults")
    assert config.vector_weight == 0.55
    assert config.keyword_weight == 0.25


def test_rag_cli_weight_flags_override_yaml(tmp_path) -> None:
    """--vector-weight / --keyword-weight override both defaults and YAML."""
    captured: list[EvalConfig] = []

    def recording_factory(workspace, eval_config: EvalConfig):
        captured.append(eval_config)
        return FakeSearchBackend()

    config = tmp_path / "configs.yaml"
    config.write_text(
        "experiments:\n  baseline:\n    one:\n      vector_weight: 0.7\n      keyword_weight: 0.3\n",
        encoding="utf-8",
    )
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text("", encoding="utf-8")

    exit_code = main(
        [
            "--config",
            str(config),
            "--dataset",
            str(dataset),
            "--vector-weight",
            "0.9",
            "--keyword-weight",
            "0.1",
        ],
        manager_factory=recording_factory,
    )

    assert exit_code == 0
    assert captured
    assert captured[0].vector_weight == 0.9
    assert captured[0].keyword_weight == 0.1
