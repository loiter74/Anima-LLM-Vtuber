"""Fail-closed production policy for generated Minecraft skills."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from animetta.tools.gamebot.contracts import (
    CapabilityManifest,
    CapabilityRisk,
)


class PolicyViolation(BaseModel):
    code: str
    subject: str
    detail: str = ""


class PolicyReport(BaseModel):
    allowed: bool
    authorized_capabilities: set[str] = Field(default_factory=set)
    violations: list[PolicyViolation] = Field(default_factory=list)


_FORBIDDEN_TOKENS: tuple[str, ...] = (
    "process",
    "require",
    "import",
    "eval",
    "Function",
    "constructor",
    "__proto__",
    "prototype",
    "getPrototypeOf",
    "setPrototypeOf",
    "globalThis",
    "fetch",
    "WebSocket",
    "XMLHttpRequest",
    "child_process",
    "give",
    "teleport",
    "creative",
    "set_inventory",
    "set_block",
    "rcon",
    "reset_world",
)
_FORBIDDEN_PATTERN = re.compile("|".join(rf"\b{re.escape(token)}\b" for token in _FORBIDDEN_TOKENS))
_CALL_PATTERN = re.compile(r"(?<![\w.$])([A-Za-z_$][\w$]*)\s*\(")
_LANGUAGE_CALLS = frozenset(
    {
        "if",
        "for",
        "while",
        "switch",
        "catch",
        "String",
        "Number",
        "Boolean",
        "Array",
        "Object",
        "Math",
        "JSON",
    }
)


class VoyagerPolicy:
    """Validate runtime capabilities and generated code before execution."""

    def __init__(self, *, supported_protocol: str, allowed_capabilities: set[str]):
        self._supported_protocol = supported_protocol
        self._allowed_capabilities = frozenset(allowed_capabilities)

    def validate_manifest(self, manifest: CapabilityManifest) -> PolicyReport:
        violations: list[PolicyViolation] = []
        authorized: set[str] = set()

        if manifest.protocol_version != self._supported_protocol:
            violations.append(
                PolicyViolation(
                    code="INCOMPATIBLE_PROTOCOL",
                    subject=manifest.protocol_version,
                    detail=f"expected {self._supported_protocol}",
                )
            )

        seen: set[str] = set()
        for capability in manifest.capabilities:
            if capability.name in seen:
                violations.append(
                    PolicyViolation(
                        code="DUPLICATE_CAPABILITY",
                        subject=capability.name,
                    )
                )
                continue
            seen.add(capability.name)

            if capability.risk is CapabilityRisk.SURVIVAL_SAFE:
                if capability.name not in self._allowed_capabilities:
                    violations.append(
                        PolicyViolation(
                            code="UNKNOWN_CAPABILITY",
                            subject=capability.name,
                        )
                    )
                else:
                    authorized.add(capability.name)

        return PolicyReport(
            allowed=not violations,
            authorized_capabilities=authorized if not violations else set(),
            violations=violations,
        )

    def authorize_capabilities(
        self,
        requested: list[str],
        manifest: CapabilityManifest,
    ) -> PolicyReport:
        violations: list[PolicyViolation] = []
        authorized: set[str] = set()
        manifest_by_name = {capability.name: capability for capability in manifest.capabilities}

        if manifest.protocol_version != self._supported_protocol:
            violations.append(
                PolicyViolation(
                    code="INCOMPATIBLE_PROTOCOL",
                    subject=manifest.protocol_version,
                    detail=f"expected {self._supported_protocol}",
                )
            )

        for name in requested:
            capability = manifest_by_name.get(name)
            if capability is None:
                violations.append(PolicyViolation(code="CAPABILITY_NOT_AUTHORIZED", subject=name))
            elif capability.risk is not CapabilityRisk.SURVIVAL_SAFE:
                violations.append(
                    PolicyViolation(code="CAPABILITY_NOT_SURVIVAL_SAFE", subject=name)
                )
            elif name not in self._allowed_capabilities:
                violations.append(PolicyViolation(code="UNKNOWN_CAPABILITY", subject=name))
            else:
                authorized.add(name)

        return PolicyReport(
            allowed=not violations,
            authorized_capabilities=authorized if not violations else set(),
            violations=violations,
        )

    def validate_code(self, code: str, manifest: CapabilityManifest) -> PolicyReport:
        violations: list[PolicyViolation] = []

        for match in _FORBIDDEN_PATTERN.finditer(code):
            violations.append(
                PolicyViolation(
                    code="FORBIDDEN_CODE_TOKEN",
                    subject=match.group(0),
                )
            )

        referenced = {name for name in _CALL_PATTERN.findall(code) if name not in _LANGUAGE_CALLS}
        authorization = self.authorize_capabilities(sorted(referenced), manifest)
        violations.extend(authorization.violations)

        return PolicyReport(
            allowed=not violations,
            authorized_capabilities=(
                authorization.authorized_capabilities if not violations else set()
            ),
            violations=violations,
        )
