"""Typed expression-effect runtime for Anima responses."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from animetta.services.meme.styles import MemeRouter, MemeState, ZhouliTool

EffectMode = Literal["ending_quip", "inline_quip", "rewrite", "full_reply"]
EffectPosition = Literal["after_main_reply", "inline", "replace"]

FORBIDDEN_MEME_SCENES = {
    "medical",
    "mental_health",
    "grief",
    "legal",
    "finance_decision",
    "serious_work_report",
    "inspection_ping",
    "user_angry_at_bot",
    "user_requests_direct_answer",
}


@dataclass(frozen=True)
class EffectEvent:
    """Non-text performance metadata produced by an effect."""

    type: str
    name: str
    strength: float | None = None
    duration_ms: int | None = None
    text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": self.type, "name": self.name}
        if self.strength is not None:
            payload["strength"] = self.strength
        if self.duration_ms is not None:
            payload["duration_ms"] = self.duration_ms
        if self.text is not None:
            payload["text"] = self.text
        if self.metadata:
            payload["metadata"] = self.metadata
        return payload


@dataclass(frozen=True)
class EffectPlan:
    """A typed request for one expression effect."""

    id: str
    target_text: str
    mode: EffectMode = "ending_quip"
    position: EffectPosition = "after_main_reply"
    intensity: int = 2
    max_chars: int = 120
    explicit: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "target_text": self.target_text,
            "mode": self.mode,
            "position": self.position,
            "intensity": self.intensity,
            "max_chars": self.max_chars,
            "explicit": self.explicit,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class ResponsePlan:
    """The workflow-level plan for one response turn."""

    input_text: str
    main_text: str = ""
    scene: str = "chat"
    user_mood: str = "neutral"
    reply_goal: str = ""
    effects: list[EffectPlan] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_text": self.input_text,
            "main_text": self.main_text,
            "scene": self.scene,
            "user_mood": self.user_mood,
            "reply_goal": self.reply_goal,
            "effects": [effect.to_dict() for effect in self.effects],
            "forbidden": self.forbidden,
        }


@dataclass
class EffectResult:
    """Rendered effect output plus safety and performance events."""

    id: str
    text: str = ""
    position: EffectPosition = "after_main_reply"
    success: bool = True
    mode: EffectMode = "ending_quip"
    intensity: int = 2
    events: list[EffectEvent] = field(default_factory=list)
    safety: dict[str, Any] = field(default_factory=lambda: {"allowed": True})
    format_id: str = ""
    format_slots: dict[str, str] = field(default_factory=dict)
    rendered_text: str = ""
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "position": self.position,
            "success": self.success,
            "mode": self.mode,
            "intensity": self.intensity,
            "events": [event.to_dict() for event in self.events],
            "safety": self.safety,
            "format_id": self.format_id,
            "format_slots": self.format_slots,
            "rendered_text": self.rendered_text,
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass
class EffectResponse:
    """Final text after composition plus all effect execution evidence."""

    text: str
    response_plan: ResponsePlan
    effects: list[EffectResult] = field(default_factory=list)

    def to_metadata(self) -> dict[str, Any]:
        effect_payloads = [effect.to_dict() for effect in self.effects]
        return {
            "response_plan": self.response_plan.to_dict(),
            "effects": effect_payloads,
            "effect_events": [
                event for effect in effect_payloads for event in effect.get("events", [])
            ],
        }


class EffectRenderer(Protocol):
    async def render(self, plan: EffectPlan, response_plan: ResponsePlan) -> EffectResult:
        """Render one effect plan into an effect result."""


RendererFactory = Callable[[], EffectRenderer]
RendererLike = EffectRenderer | Callable[[EffectPlan, ResponsePlan], Awaitable[EffectResult]]


class EffectGuard:
    """Rule-first guard for expression effects."""

    def evaluate(self, plan: EffectPlan, response_plan: ResponsePlan) -> dict[str, Any]:
        if plan.explicit:
            return {"allowed": True, "reason": "explicit"}

        if response_plan.scene in FORBIDDEN_MEME_SCENES:
            return {
                "allowed": False,
                "reason": "blocked_scene",
                "scene": response_plan.scene,
            }

        if plan.id in response_plan.forbidden:
            return {"allowed": False, "reason": "forbidden_by_plan"}

        return {"allowed": True, "reason": "allowed"}


class EffectPlanner:
    """Rule-first planner that converts a turn into a response/effect plan."""

    def __init__(
        self,
        router: MemeRouter | None = None,
        state: MemeState | None = None,
    ) -> None:
        self.router = router or MemeRouter()
        self.state = state or MemeState()

    def plan(
        self,
        *,
        user_text: str,
        main_text: str = "",
        scene: str = "chat",
        mood: str = "neutral",
        semi_active_enabled: bool = False,
        turn_index: int = 0,
    ) -> ResponsePlan:
        decision = self.router.route(
            user_text,
            mood=mood,
            scene=scene,
            state=self.state,
            turn_index=turn_index,
            semi_active_enabled=semi_active_enabled,
        )

        if decision.action == "explicit" and decision.style_id:
            return plan_explicit_meme_effect(decision.style_id, decision.intent)

        effects: list[EffectPlan] = []
        forbidden: list[str] = []
        if scene in FORBIDDEN_MEME_SCENES or decision.reason == "blocked_scene":
            forbidden.append("meme:zhouli")

        if decision.action == "semi_active" and decision.style_id:
            effects.append(
                EffectPlan(
                    id=f"meme:{decision.style_id}",
                    target_text=decision.intent,
                    mode="ending_quip",
                    position="after_main_reply",
                    intensity=2,
                    max_chars=120,
                    explicit=False,
                )
            )

        return ResponsePlan(
            input_text=user_text,
            main_text=main_text,
            scene=scene,
            user_mood=mood,
            reply_goal=("respond_with_optional_effects" if effects else "respond_normally"),
            effects=effects,
            forbidden=forbidden,
        )


class EffectRegistry:
    """Registry of small typed effect renderers."""

    def __init__(self) -> None:
        self._renderers: dict[str, RendererLike] = {}

    def register(self, effect_id: str, renderer: RendererLike) -> None:
        self._renderers[effect_id] = renderer

    def get(self, effect_id: str) -> RendererLike | None:
        return self._renderers.get(effect_id)


class EffectRuntime:
    """Execute effect plans, compose text, and expose metadata."""

    def __init__(
        self,
        registry: EffectRegistry | None = None,
        guard: EffectGuard | None = None,
    ) -> None:
        self.registry = registry or EffectRegistry()
        self.guard = guard or EffectGuard()

    def register(self, effect_id: str, renderer: RendererLike) -> None:
        self.registry.register(effect_id, renderer)

    async def run(self, response_plan: ResponsePlan) -> EffectResponse:
        effects: list[EffectResult] = []
        for plan in response_plan.effects:
            renderer = self.registry.get(plan.id)
            if renderer is None:
                effects.append(
                    EffectResult(
                        id=plan.id,
                        position=plan.position,
                        success=False,
                        mode=plan.mode,
                        intensity=plan.intensity,
                        safety={"allowed": False, "reason": "unknown_effect"},
                        error="unknown_effect",
                    )
                )
                continue

            safety = self.guard.evaluate(plan, response_plan)
            if not safety.get("allowed", False):
                effects.append(
                    EffectResult(
                        id=plan.id,
                        position=plan.position,
                        success=False,
                        mode=plan.mode,
                        intensity=plan.intensity,
                        safety=safety,
                    )
                )
                continue

            try:
                if hasattr(renderer, "render"):
                    result = await renderer.render(plan, response_plan)  # type: ignore[union-attr]
                else:
                    result = await renderer(plan, response_plan)  # type: ignore[operator]
                result.safety = {**safety, **result.safety}
                effects.append(result)
            except Exception as exc:
                effects.append(
                    EffectResult(
                        id=plan.id,
                        position=plan.position,
                        success=False,
                        mode=plan.mode,
                        intensity=plan.intensity,
                        safety={"allowed": False, "reason": "render_failed"},
                        error=str(exc),
                    )
                )

        return EffectResponse(
            text=compose_effects(response_plan.main_text, effects),
            response_plan=response_plan,
            effects=effects,
        )


class ZhouliEffectRenderer:
    """Adapter that turns the zhouli meme renderer into a performance effect."""

    def __init__(self, llm_client: Any | None = None, tool: ZhouliTool | None = None) -> None:
        self.tool = tool or ZhouliTool(llm_client=llm_client)

    async def render(self, plan: EffectPlan, response_plan: ResponsePlan) -> EffectResult:
        result = await self.tool.run(
            plan.target_text,
            mode=_to_meme_mode(plan.mode),
            intensity=plan.intensity,
            max_chars=plan.max_chars,
        )
        events = _zhouli_events(plan)
        return EffectResult(
            id=plan.id,
            text=result.text,
            position=plan.position,
            success=True,
            mode=plan.mode,
            intensity=plan.intensity,
            events=events,
            safety={"allowed": True, "reason": "rendered"},
            format_id=result.format_id,
            format_slots=result.format_slots,
            rendered_text=result.rendered_text or result.text,
            metadata={
                "style": result.style,
                "source_scene": response_plan.scene,
            },
        )


def compose_effects(main_text: str, effects: list[EffectResult]) -> str:
    text = main_text
    for effect in effects:
        if not effect.success or not effect.text:
            continue
        if effect.position == "replace":
            text = effect.text
        elif effect.position == "inline":
            text = f"{text}{effect.text}" if text else effect.text
        else:
            text = f"{text}\n\n{effect.text}" if text else effect.text
    return text


def create_default_effect_runtime(llm_client: Any | None = None) -> EffectRuntime:
    runtime = EffectRuntime()
    runtime.register("meme:zhouli", ZhouliEffectRenderer(llm_client=llm_client))
    return runtime


def plan_explicit_meme_effect(style_id: str, intent: str) -> ResponsePlan:
    return ResponsePlan(
        input_text=f"meme:{style_id} {intent}".strip(),
        main_text="",
        scene="explicit_meme",
        user_mood="meme",
        reply_goal="render_requested_meme_style",
        effects=[
            EffectPlan(
                id=f"meme:{style_id}",
                target_text=intent,
                mode="full_reply",
                position="replace",
                intensity=2,
                max_chars=180,
                explicit=True,
            )
        ],
    )


def _to_meme_mode(mode: EffectMode) -> Literal["rewrite", "quip", "reply"]:
    if mode == "rewrite":
        return "rewrite"
    if mode == "full_reply":
        return "reply"
    return "quip"


def _zhouli_events(plan: EffectPlan) -> list[EffectEvent]:
    strength = min(1.0, max(0.2, 0.35 + plan.intensity * 0.12))
    return [
        EffectEvent(type="voice", name="mock_serious", strength=round(strength, 2)),
        EffectEvent(type="face", name="deadpan", duration_ms=1200),
        EffectEvent(type="overlay", name="zhouli_stamp", text="合乎周礼"),
    ]
