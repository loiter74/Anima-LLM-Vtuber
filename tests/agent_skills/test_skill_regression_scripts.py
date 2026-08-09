from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGRESSION_SKILL = ROOT / ".agents/skills/test-skill-regression"
SNAPSHOT = REGRESSION_SKILL / "scripts/snapshot_tree.py"
COMPARE = REGRESSION_SKILL / "scripts/compare_runs.py"
PREPARE = REGRESSION_SKILL / "scripts/prepare_case.py"


def run_script(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


def snapshot(workspace: Path, output: Path) -> None:
    run_script(str(SNAPSHOT), str(workspace), str(output))


def write_case(
    path: Path,
    *,
    run_count: int = 2,
    allowed_paths: list[str] | None = None,
    not_contains: list[str] | None = None,
) -> None:
    invariant = {"path": "result.txt", "contains": ["after"]}
    if not_contains:
        invariant["not_contains"] = not_contains
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "fixed-test-case",
                "skill": "simplify",
                "task": "固定任务",
                "baseline": "baseline",
                "run_count": run_count,
                "allowed_paths": allowed_paths or ["result.txt"],
                "require_content_identical": True,
                "invariants": [invariant],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_snapshot_is_repeatable_when_output_is_inside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "result.txt").write_text("stable\n", encoding="utf-8")
    manifest = workspace / "manifest.json"

    snapshot(workspace, manifest)
    first = manifest.read_bytes()
    snapshot(workspace, manifest)

    assert manifest.read_bytes() == first
    assert "manifest.json" not in json.loads(first)["files"]


def test_prepare_case_preflights_and_copies_isolated_runs(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    (baseline / "result.txt").write_text("after\n", encoding="utf-8")
    case = tmp_path / "case.json"
    write_case(case, run_count=3, not_contains=["forbidden"])
    prepared = tmp_path / "prepared"

    result = run_script(
        str(PREPARE),
        "--case",
        str(case),
        "--output-root",
        str(prepared),
    )

    payload = json.loads(result.stdout)
    run_roots = [Path(path) for path in payload["run_roots"]]
    assert payload["preflight_passed"] is True
    assert len(run_roots) == 3
    assert all((root / "result.txt").read_text(encoding="utf-8") == "after\n" for root in run_roots)
    (run_roots[0] / "result.txt").write_text("changed\n", encoding="utf-8")
    assert (run_roots[1] / "result.txt").read_text(encoding="utf-8") == "after\n"


def test_prepare_case_rejects_contradictory_constraints_before_creating_runs(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    (baseline / "result.txt").write_text("after\n", encoding="utf-8")
    case = tmp_path / "case.json"
    write_case(case, not_contains=["after"])
    prepared = tmp_path / "prepared"

    result = run_script(
        str(PREPARE),
        "--case",
        str(case),
        "--output-root",
        str(prepared),
        check=False,
    )

    assert result.returncode == 1
    assert "语义预检失败" in result.stderr
    assert not prepared.exists()


def test_bundled_cases_reference_fixed_skill_and_baseline_paths() -> None:
    cases = sorted((REGRESSION_SKILL / "fixtures/cases").glob("*.json"))

    assert cases
    for case_path in cases:
        case = json.loads(case_path.read_text(encoding="utf-8"))
        skill_path = ROOT / ".agents/skills" / case["skill"] / "SKILL.md"
        baseline_path = (case_path.parent / case["baseline"]).resolve(strict=True)
        baselines_root = (REGRESSION_SKILL / "fixtures/baselines").resolve(strict=True)

        assert case_path.stem == case["skill"] or case_path.stem.startswith(f"{case['skill']}-")
        assert skill_path.is_file()
        assert baseline_path.is_dir()
        assert baseline_path.is_relative_to(baselines_root)
        assert case["run_count"] >= 2
        assert case["allowed_paths"]
        assert case["invariants"]
        for invariant in case["invariants"]:
            target = baseline_path / invariant["path"]
            baseline_text = target.read_text(encoding="utf-8")
            assert invariant.get("contains") or invariant.get("not_contains")
            assert all(fragment in baseline_text for fragment in invariant.get("contains", []))
            assert all(
                fragment not in required
                for fragment in invariant.get("not_contains", [])
                for required in invariant.get("contains", [])
            )
            assert all(
                fragment not in case["task"] for fragment in invariant.get("not_contains", [])
            )


def test_compare_detects_repeatability_and_path_drift(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    run_one = tmp_path / "run-one"
    run_two = tmp_path / "run-two"
    run_drift = tmp_path / "run-drift"
    for workspace in (baseline, run_one, run_two, run_drift):
        workspace.mkdir()
        (workspace / "result.txt").write_text("before\n", encoding="utf-8")
    for workspace in (run_one, run_two, run_drift):
        (workspace / "result.txt").write_text("after\n", encoding="utf-8")
    (run_drift / "escaped.txt").write_text("outside boundary\n", encoding="utf-8")

    manifests = {
        name: tmp_path / f"{name}.json" for name in ("baseline", "run-one", "run-two", "run-drift")
    }
    for name, workspace in (
        ("baseline", baseline),
        ("run-one", run_one),
        ("run-two", run_two),
        ("run-drift", run_drift),
    ):
        snapshot(workspace, manifests[name])
    case = tmp_path / "case.json"
    write_case(case)

    passed = run_script(
        str(COMPARE),
        "--case",
        str(case),
        "--baseline",
        str(manifests["baseline"]),
        str(manifests["run-one"]),
        str(manifests["run-two"]),
    )
    passed_result = json.loads(passed.stdout)
    assert passed_result["path_consistent"] is True
    assert passed_result["content_identical_on_affected_paths"] is True
    assert passed_result["boundary_consistent"] is True

    failed = run_script(
        str(COMPARE),
        "--case",
        str(case),
        "--baseline",
        str(manifests["baseline"]),
        str(manifests["run-one"]),
        str(manifests["run-drift"]),
        check=False,
    )
    failed_result = json.loads(failed.stdout)
    assert failed.returncode == 1
    assert failed_result["path_consistent"] is False
    assert failed_result["boundary_consistent"] is False


def test_compare_prepared_runs_enforces_positive_and_negative_invariants(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    (baseline / "result.txt").write_text("after\n", encoding="utf-8")
    case = tmp_path / "case.json"
    write_case(case, not_contains=["forbidden"])
    prepared = tmp_path / "prepared"
    preparation = run_script(
        str(PREPARE),
        "--case",
        str(case),
        "--output-root",
        str(prepared),
    )
    run_roots = [Path(path) for path in json.loads(preparation.stdout)["run_roots"]]

    no_op = run_script(
        str(COMPARE),
        "--case",
        str(case),
        "--prepared-root",
        str(prepared),
        check=False,
    )
    assert no_op.returncode == 1
    assert json.loads(no_op.stdout)["changes_observed"] is False

    for run_root in run_roots:
        (run_root / "result.txt").write_text("after changed\n", encoding="utf-8")

    passed = run_script(
        str(COMPARE),
        "--case",
        str(case),
        "--prepared-root",
        str(prepared),
    )
    passed_result = json.loads(passed.stdout)
    assert passed_result["semantic_invariants_passed"] is True
    assert passed_result["semantic_invariants_require_manual_check"] is False

    (run_roots[1] / "result.txt").write_text("after forbidden\n", encoding="utf-8")
    failed = run_script(
        str(COMPARE),
        "--case",
        str(case),
        "--prepared-root",
        str(prepared),
        check=False,
    )
    failed_result = json.loads(failed.stdout)
    assert failed.returncode == 1
    assert failed_result["semantic_invariants_passed"] is False
    assert failed_result["invariant_results"][1]["passed"] is False


def test_compare_enforces_fixed_case_run_count(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "result.txt").write_text("after\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    snapshot(workspace, manifest)
    case = tmp_path / "case.json"
    write_case(case, run_count=3)

    result = run_script(
        str(COMPARE),
        "--case",
        str(case),
        "--baseline",
        str(manifest),
        str(manifest),
        str(manifest),
        check=False,
    )

    assert result.returncode == 1
    assert "固定用例要求 3 次运行" in result.stderr
