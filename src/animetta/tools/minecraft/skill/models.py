"""Skill domain models and step parameter definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Includes both Python-side step types and Node.js-side actions from AVAILABLE_TOOLS.
STEP_TYPES: set[str] = {
    "goto",
    "smart_goto",
    "collect",
    "mine",
    "place",
    "smart_build",
    "craft",
    "chat",
    "check",
    "wait",
    "attack",
    "smelt",
    "water_bucket_clutch",
}

# Required parameters per step type: name -> (type, default).
_STEP_PARAM_DEFS: dict[str, dict[str, tuple[type, Any]]] = {
    "goto": {"x": (int, None), "y": (int, None), "z": (int, None)},
    "smart_goto": {"target": (str, None)},
    "collect": {"block_type": (str, None), "count": (int, 1)},
    "mine": {"block_type": (str, None), "count": (int, 1)},
    "place": {"block_type": (str, None), "x": (int, None), "y": (int, None), "z": (int, None)},
    "smart_build": {
        "block_type": (str, None),
        "x": (int, None),
        "y": (int, None),
        "z": (int, None),
        "blueprint": (str, None),
    },
    "craft": {"recipe": (str, None), "count": (int, 1)},
    "chat": {"message": (str, None)},
    "check": {"condition": (str, None)},
    "wait": {"seconds": (float, None)},
    "attack": {"target": (str, None)},
    "smelt": {"item": (str, None), "fuel": (str, None), "count": (int, 1)},
    "water_bucket_clutch": {},
}


@dataclass
class SkillStep:
    """A single executable step within a Skill."""

    name: str
    params: dict[str, Any] = field(default_factory=dict)
    preconditions: list[str] = field(default_factory=list)
    timeout: float = 60.0
    retry: int = 0

    def validate_params(self) -> list[str]:
        """Validate params against the step type definition."""
        errors: list[str] = []

        if self.name not in STEP_TYPES:
            errors.append(f"Unknown step type '{self.name}', expected one of: {sorted(STEP_TYPES)}")
            return errors

        defs = _STEP_PARAM_DEFS.get(self.name, {})
        for param_name, (param_type, default) in defs.items():
            if param_name not in self.params:
                if default is None:
                    errors.append(
                        f"Missing required param '{param_name}' for step type '{self.name}'"
                    )
            else:
                value = self.params[param_name]
                if not isinstance(value, param_type):
                    errors.append(
                        f"Param '{param_name}' for '{self.name}' must be {param_type.__name__}, "
                        f"got {type(value).__name__}: {value!r}"
                    )

        return errors

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "name": self.name,
            "params": self.params,
            "preconditions": self.preconditions,
            "timeout": self.timeout,
            "retry": self.retry,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillStep:
        """Deserialize from a dict."""
        return cls(
            name=data["name"],
            params=data.get("params", {}),
            preconditions=data.get("preconditions", []),
            timeout=data.get("timeout", 60.0),
            retry=data.get("retry", 0),
        )


@dataclass
class Skill:
    """A reusable, composable Minecraft action skill."""

    id: str
    name: str
    description: str
    parameters: dict[str, str] = field(default_factory=dict)
    preconditions: list[str] = field(default_factory=list)
    body: dict[str, Any] = field(default_factory=dict)
    steps: list[SkillStep] = field(default_factory=list)
    category: str = ""
    postconditions: list[str] = field(default_factory=list)
    success_count: int = 0
    fail_count: int = 0
    avg_duration: float = 0.0
    last_used: str = ""
    tags: list[str] = field(default_factory=list)
    is_learned: bool = False
    validated: bool = True

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        return self.success_count / total if total > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "preconditions": self.preconditions,
            "body": self.body,
            "steps": [s.to_dict() for s in self.steps],
            "category": self.category,
            "postconditions": self.postconditions,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "avg_duration": self.avg_duration,
            "last_used": self.last_used,
            "tags": self.tags,
            "is_learned": self.is_learned,
            "validated": self.validated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Skill:
        data = dict(data)
        steps_data = data.pop("steps", [])
        steps = [SkillStep.from_dict(s) for s in steps_data]
        return cls(steps=steps, **data)


@dataclass
class SkillResult:
    """Result of executing a Skill."""

    success: bool
    skill_id: str
    failed_at: int | None = None
    reason: str | None = None
    duration: float = 0.0
    context_updates: dict[str, Any] = field(default_factory=dict)
