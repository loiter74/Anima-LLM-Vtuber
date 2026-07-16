from __future__ import annotations

"""Tests for inspection data models."""

import pytest

from animetta.inspection.models import CheckResult, InspectionReport


class TestCheckResult:
    """CheckResult model tests."""

    def test_passed_creates_ok_result(self):
        result = CheckResult.passed("test_check", duration_ms=1.5, foo="bar")
        assert result.name == "test_check"
        assert result.ok is True
        assert result.duration_ms == 1.5
        assert result.detail == {"foo": "bar"}
        assert result.error is None

    def test_failed_creates_error_result(self):
        result = CheckResult.failed("bad_check", duration_ms=0.0, error="timeout", code=500)
        assert result.name == "bad_check"
        assert result.ok is False
        assert result.error == "timeout"
        assert result.detail == {"code": 500}

    def test_model_is_frozen(self):
        result = CheckResult.passed("x")
        with pytest.raises(Exception):
            result.ok = False  # type: ignore[misc]

    def test_failed_defaults(self):
        result = CheckResult.failed("x")
        assert result.ok is False
        assert result.error == ""
        assert result.detail == {}


class TestInspectionReport:
    """InspectionReport model tests."""

    def test_overall_ok_all_pass(self):
        report = InspectionReport(
            checks={
                "a": CheckResult.passed("a"),
                "b": CheckResult.passed("b"),
            }
        )
        assert report.overall_ok is True

    def test_overall_ok_one_fails(self):
        report = InspectionReport(
            checks={
                "a": CheckResult.passed("a"),
                "b": CheckResult.failed("b", error="boom"),
            }
        )
        assert report.overall_ok is False

    def test_overall_ok_empty_checks(self):
        report = InspectionReport()
        assert report.overall_ok is False

    def test_summary_all_pass(self):
        report = InspectionReport(
            checks={
                "a": CheckResult.passed("a"),
                "b": CheckResult.passed("b"),
            }
        )
        assert "All" in report.summary
        assert "passed" in report.summary

    def test_summary_with_failures(self):
        report = InspectionReport(
            checks={
                "a": CheckResult.passed("a"),
                "b": CheckResult.failed("b", error="boom"),
            }
        )
        assert "Failed" in report.summary
        assert "b" in report.summary

    def test_run_id_auto_generated(self):
        report = InspectionReport()
        assert len(report.run_id) == 36  # UUID format

    def test_model_is_frozen(self):
        report = InspectionReport()
        with pytest.raises(Exception):
            report.run_id = "new"  # type: ignore[misc]
