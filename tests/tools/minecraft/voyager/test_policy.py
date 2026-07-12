"""Fail-closed policy tests for cheat-free Voyager execution."""

from __future__ import annotations

import importlib

import pytest

from animetta.tools.gamebot.contracts import (
    CapabilityManifest,
    CapabilityRisk,
    GameBotCapability,
)

SAFE_CAPABILITIES = {
    "observe",
    "status",
    "goto",
    "collect",
    "mine",
    "craft",
    "smelt",
    "place",
    "equip",
    "attack",
    "eat",
    "waitFor",
}


def _policy():
    module = importlib.import_module("animetta.tools.minecraft.voyager.policy")
    return module.VoyagerPolicy(
        supported_protocol="1.0",
        allowed_capabilities=SAFE_CAPABILITIES,
    )


def _manifest(*capabilities: tuple[str, CapabilityRisk], protocol: str = "1.0"):
    return CapabilityManifest(
        protocol_version=protocol,
        runtime_id="runtime-1",
        capabilities=[
            GameBotCapability(name=name, risk=risk, parameters={})
            for name, risk in capabilities
        ],
    )


def test_known_survival_manifest_is_accepted() -> None:
    report = _policy().validate_manifest(
        _manifest(
            ("collect", CapabilityRisk.SURVIVAL_SAFE),
            ("craft", CapabilityRisk.SURVIVAL_SAFE),
        )
    )

    assert report.allowed is True
    assert report.violations == []
    assert report.authorized_capabilities == {"collect", "craft"}


def test_unknown_manifest_capability_fails_closed() -> None:
    report = _policy().validate_manifest(
        _manifest(("fly", CapabilityRisk.SURVIVAL_SAFE))
    )

    assert report.allowed is False
    assert {violation.code for violation in report.violations} == {"UNKNOWN_CAPABILITY"}


def test_incompatible_manifest_version_fails_closed() -> None:
    report = _policy().validate_manifest(
        _manifest(("collect", CapabilityRisk.SURVIVAL_SAFE), protocol="2.0")
    )

    assert report.allowed is False
    assert report.violations[0].code == "INCOMPATIBLE_PROTOCOL"


@pytest.mark.parametrize(
    "capability",
    ["give", "teleport", "creative", "set_inventory", "set_block", "rcon", "reset_world"],
)
def test_admin_or_forbidden_capability_cannot_be_authorized(capability: str) -> None:
    risk = CapabilityRisk.TEST_ADMIN if capability == "reset_world" else CapabilityRisk.FORBIDDEN
    manifest = _manifest((capability, risk))

    report = _policy().authorize_capabilities([capability], manifest)

    assert report.allowed is False
    assert "CAPABILITY_NOT_SURVIVAL_SAFE" in {v.code for v in report.violations}


@pytest.mark.parametrize(
    ("code", "forbidden_fragment"),
    [
        ("process.exit(0)", "process"),
        ("require('fs').readFileSync('x')", "require"),
        ("await import('node:fs')", "import"),
        ("eval('collect()')", "eval"),
        ("Function('return process')()", "Function"),
        ("({}).constructor.constructor('return process')()", "constructor"),
        ("Object.getPrototypeOf({})", "getPrototypeOf"),
        ("globalThis.fetch('https://example.com')", "globalThis"),
        ("fetch('https://example.com')", "fetch"),
        ("new WebSocket('ws://example.com')", "WebSocket"),
        ("await give('iron_pickaxe', 1)", "give"),
        ("await teleport(0, 64, 0)", "teleport"),
        ("await rcon('/give @s diamond')", "rcon"),
    ],
)
def test_generated_code_rejects_escape_and_cheat_surfaces(
    code: str, forbidden_fragment: str
) -> None:
    manifest = _manifest(
        ("collect", CapabilityRisk.SURVIVAL_SAFE),
        ("craft", CapabilityRisk.SURVIVAL_SAFE),
    )

    report = _policy().validate_code(code, manifest)

    assert report.allowed is False
    assert any(forbidden_fragment in violation.subject for violation in report.violations)


def test_generated_code_rejects_capability_not_authorized_by_manifest() -> None:
    manifest = _manifest(("collect", CapabilityRisk.SURVIVAL_SAFE))

    report = _policy().validate_code("await craft('wooden_pickaxe', 1)", manifest)

    assert report.allowed is False
    assert report.violations[0].code == "CAPABILITY_NOT_AUTHORIZED"


def test_survival_code_returns_exact_authorized_capability_set() -> None:
    manifest = _manifest(
        ("collect", CapabilityRisk.SURVIVAL_SAFE),
        ("craft", CapabilityRisk.SURVIVAL_SAFE),
        ("status", CapabilityRisk.SURVIVAL_SAFE),
    )
    code = """
const before = await status();
await collect('oak_log', 1);
if (before.health > 5) await craft('oak_planks', 4);
"""

    report = _policy().validate_code(code, manifest)

    assert report.allowed is True
    assert report.authorized_capabilities == {"status", "collect", "craft"}
    assert report.violations == []
