"""Meme style tools for controlled post-response styling."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from loguru import logger

MemeMode = Literal["rewrite", "quip", "reply"]


class MemeStyleValidationError(ValueError):
    """Raised when a meme style cannot be rendered from the provided slots."""

    def __init__(self, message: str, missing_slots: list[str] | None = None) -> None:
        super().__init__(message)
        self.missing_slots = missing_slots or []


@dataclass(frozen=True)
class MemeStyleSlot:
    name: str
    description: str
    required: bool = True


@dataclass(frozen=True)
class MemeStyleExample:
    title: str
    source_text: str
    slots: dict[str, str]
    rendered_text: str


@dataclass(frozen=True)
class MemeStyle:
    id: str
    aliases: tuple[str, ...]
    description: str
    explanation: str
    slots: tuple[MemeStyleSlot, ...]
    template: str
    few_shots: tuple[MemeStyleExample, ...]
    style_rules: tuple[str, ...]
    negative_rules: tuple[str, ...]
    triggers_explicit: tuple[str, ...]
    triggers_implicit: tuple[str, ...]
    avoid_scenes: tuple[str, ...]
    cooldown_turns: int = 3
    window_turns: int = 10
    max_per_window: int = 2
    default_intensity: int = 2
    default_max_chars: int = 180

    @property
    def required_slot_names(self) -> list[str]:
        return [slot.name for slot in self.slots if slot.required]


@dataclass
class MemeStyleResult:
    text: str
    style: str = "zhouli"
    success: bool = True
    mode: MemeMode = "quip"
    intensity: int = 2
    format_id: str = "zhouli"
    format_slots: dict[str, str] = field(default_factory=dict)
    format_confidence: float | None = None
    rendered_text: str = ""
    error: str = ""


@dataclass(frozen=True)
class MemeInvocation:
    style_id: str
    intent: str
    is_explicit: bool = True


@dataclass
class MemeRouteDecision:
    action: Literal["none", "explicit", "semi_active"]
    style_id: str | None = None
    intent: str = ""
    reason: str = ""
    bypass_cooldown: bool = False


@dataclass
class MemeState:
    last_used_turns: dict[str, int] = field(default_factory=dict)
    recent_uses: dict[str, list[int]] = field(default_factory=dict)
    cooldown_turns: int = 3
    window_turns: int = 10
    max_per_window: int = 2

    def record_use(self, style_id: str, turn_index: int) -> None:
        self.last_used_turns[style_id] = turn_index
        self.recent_uses.setdefault(style_id, []).append(turn_index)
        cutoff = turn_index - self.window_turns
        self.recent_uses[style_id] = [
            turn for turn in self.recent_uses[style_id] if turn >= cutoff
        ]

    def cooldown_reason(self, style: MemeStyle, turn_index: int) -> str | None:
        last_turn = self.last_used_turns.get(style.id)
        cooldown_turns = style.cooldown_turns or self.cooldown_turns
        if last_turn is not None and turn_index - last_turn < cooldown_turns:
            return "cooldown"

        window_turns = style.window_turns or self.window_turns
        max_per_window = style.max_per_window or self.max_per_window
        cutoff = turn_index - window_turns
        recent = [
            turn for turn in self.recent_uses.get(style.id, []) if turn >= cutoff
        ]
        self.recent_uses[style.id] = recent
        if len(recent) >= max_per_window:
            return "window_cap"
        return None


def _zhouli_style() -> MemeStyle:
    slots = (
        MemeStyleSlot("modern_event", "现代事件或诉求"),
        MemeStyleSlot("surface_behavior", "表面看起来像什么普通行为"),
        MemeStyleSlot("elevated_interpretation", "被拔高成礼法/名分/情义/职分的解释"),
        MemeStyleSlot("other_action", "对方或自己照做的动作"),
        MemeStyleSlot("ordinary_behavior", "这个动作原本看起来像什么普通行为"),
        MemeStyleSlot("noble_interpretation", "这个动作被解释成什么高尚行为"),
    )
    template = (
        "吾闻古人制礼，并非只为拘束人情，乃是使万事各归其位。"
        "今{modern_event}，看似{surface_behavior}，实则{elevated_interpretation}。"
        "若{other_action}，便不是{ordinary_behavior}，而是{noble_interpretation}。"
        "此岂不合乎周礼？"
    )
    examples = (
        MemeStyleExample(
            title="疯狂星期四",
            source_text="想让别人请疯狂星期四",
            slots={
                "modern_event": "正逢星期四，我请诸君助我一食",
                "surface_behavior": "贪嘴",
                "elevated_interpretation": "给诸位修仁义、结善缘的机会",
                "other_action": "有人愿以鸡相赠",
                "ordinary_behavior": "破费",
                "noble_interpretation": "以食通礼、以礼会友",
            },
            rendered_text=(
                "吾闻古人设宴，并非只为一餐之饱，乃是借饭食以观朋友情义。"
                "今正逢星期四，我请诸君助我一食，看似贪嘴，"
                "实则是在给诸位修仁义、结善缘的机会。若有人愿以鸡相赠，"
                "便不是破费，而是以食通礼、以礼会友。此岂不合乎周礼？"
            ),
        ),
        MemeStyleExample(
            title="不想上班",
            source_text="不想上班",
            slots={
                "modern_event": "身心俱疲而不欲赴工",
                "surface_behavior": "懒散",
                "elevated_interpretation": "养其精神以全职守",
                "other_action": "暂得休养",
                "ordinary_behavior": "偷闲",
                "noble_interpretation": "使明日复能尽职守分",
            },
            rendered_text=(
                "吾闻先王设官分职，并非使百工昼夜殉于案牍，"
                "乃是使职有所司、劳有所息。今身心俱疲，若强行赴工，"
                "看似勤勉，实则神思散乱，反损公事。若暂得休养，"
                "使明日复能尽职守分，便不是懒散，而是养其精神，以全其职。"
                "此岂不合乎周礼？"
            ),
        ),
    )
    return MemeStyle(
        id="zhouli",
        aliases=("meme:zhouli", "吾闻", "古人云", "先王制礼", "周礼体", "合乎周礼"),
        description="大周礼时代风格，把现代小事解释成礼制、名分、职掌、秩序、情义问题。",
        explanation=(
            "周礼体用一本正经的礼法语气，把现代小事、请求或借口拔高为"
            "秩序、名分、职守、情义或修身问题，形成庄重解释与日常事件的反差。"
        ),
        slots=slots,
        template=template,
        few_shots=examples,
        style_rules=(
            "使用现代中文为骨架，不要写成纯文言",
            "使用“吾闻”“古人制礼”“并非……乃是……”",
            "使用“看似……实则……”",
            "结尾可以用“此岂不合乎周礼？”",
            "不要堆砌生僻字",
            "不要超过 180 字",
            "不要连续多轮主动触发",
        ),
        negative_rules=(
            "不要假装这是真实周礼解释",
            "不要在用户痛苦、求助、工作汇报时强行玩梗",
            "不要每句话都周礼化",
        ),
        triggers_explicit=("meme:zhouli", "周礼一下", "合乎周礼"),
        triggers_implicit=(
            "上班好累",
            "不想上班",
            "不想开会",
            "想放假",
            "想点外卖",
            "疯狂星期四",
            "游戏输了",
            "代码又炸",
            "这合理吗",
            "给我圆一下",
        ),
        avoid_scenes=(
            "medical",
            "mental_health",
            "grief",
            "serious_work_report",
            "legal",
            "finance_decision",
            "inspection",
            "work_report",
        ),
    )


_BUILTIN_STYLES: dict[str, MemeStyle] = {"zhouli": _zhouli_style()}


def get_builtin_meme_styles() -> list[MemeStyle]:
    return list(_BUILTIN_STYLES.values())


def get_meme_style(style_id: str) -> MemeStyle | None:
    return _BUILTIN_STYLES.get(style_id)


def build_style_prompt_section(styles: list[MemeStyle] | None = None) -> str:
    active_styles = styles or get_builtin_meme_styles()
    sections: list[str] = ["=== Meme style tools ==="]
    for style in active_styles:
        sections.append(f"style_id: {style.id}")
        sections.append(f"name: {style.aliases[-2] if len(style.aliases) >= 2 else style.id}")
        sections.append(f"explanation: {style.explanation}")
        sections.append("style_rules:")
        for rule in style.style_rules:
            sections.append(f"- {rule}")
        sections.append("slots:")
        for slot in style.slots:
            sections.append(f"- {slot.name}: {slot.description}")
        sections.append("few_shots:")
        for example in style.few_shots:
            sections.append(f"- {example.title}: {example.source_text}")
            sections.append(f"  format_slots: {json.dumps(example.slots, ensure_ascii=False)}")
            sections.append(f"  rendered_text: {example.rendered_text}")
    sections.append(
        "When a candidate matches a style, include format_id, format_slots, "
        "format_confidence, rendered_text, and optional mode. Generic memes may omit them."
    )
    return "\n".join(sections)


_INVOCATION_RE = re.compile(r"^\s*meme:(?P<style>[a-zA-Z0-9_-]+)(?:\s+(?P<intent>.*))?$")


def parse_meme_invocation(text: str) -> MemeInvocation | None:
    match = _INVOCATION_RE.match(text or "")
    if not match:
        return None
    return MemeInvocation(
        style_id=match.group("style").strip(),
        intent=(match.group("intent") or "").strip(),
        is_explicit=True,
    )


class ZhouliTool:
    """Render or generate short zhouli-style quips."""

    def __init__(self, llm_client: Any | None = None, style: MemeStyle | None = None) -> None:
        self.llm_client = llm_client
        self.style = style or _BUILTIN_STYLES["zhouli"]

    def validate_slots(self, slots: dict[str, str]) -> None:
        missing = [
            name for name in self.style.required_slot_names
            if not str(slots.get(name, "")).strip()
        ]
        if missing:
            raise MemeStyleValidationError(
                f"Missing required zhouli slots: {', '.join(missing)}",
                missing_slots=missing,
            )

    def render(
        self,
        slots: dict[str, str],
        *,
        mode: MemeMode = "quip",
        intensity: int = 2,
        max_chars: int | None = None,
    ) -> MemeStyleResult:
        normalized = {key: str(value).strip() for key, value in slots.items()}
        self.validate_slots(normalized)
        text = self.style.template.format(**normalized)
        max_len = max_chars or self.style.default_max_chars
        if len(text) > max_len:
            text = text[: max(0, max_len - 1)].rstrip("，。；、 ") + "…"
        return MemeStyleResult(
            text=text,
            style=self.style.id,
            success=True,
            mode=mode,
            intensity=intensity,
            format_id=self.style.id,
            format_slots=normalized,
            rendered_text=text,
        )

    async def run(
        self,
        source_text: str = "",
        *,
        slots: dict[str, str] | None = None,
        mode: MemeMode = "quip",
        intensity: int = 2,
        max_chars: int | None = None,
    ) -> MemeStyleResult:
        if slots is not None:
            return self.render(
                slots,
                mode=mode,
                intensity=intensity,
                max_chars=max_chars,
            )

        intent = source_text.strip()
        if not intent:
            raise MemeStyleValidationError(
                "meme:zhouli requires text or complete slots",
                missing_slots=self.style.required_slot_names,
            )

        if self.llm_client is not None:
            filled = await self._fill_slots_with_llm(intent)
            if filled:
                return self.render(
                    filled,
                    mode=mode,
                    intensity=intensity,
                    max_chars=max_chars,
                )

        return self.render(
            self._heuristic_slots(intent),
            mode=mode,
            intensity=intensity,
            max_chars=max_chars,
        )

    async def _fill_slots_with_llm(self, intent: str) -> dict[str, str] | None:
        prompt = (
            f"{build_style_prompt_section([self.style])}\n\n"
            "Fill only the JSON object for the zhouli slots. "
            f"Intent: {intent}"
        )
        try:
            if hasattr(self.llm_client, "chat_messages"):
                result = await self.llm_client.chat_messages(
                    messages=[
                        {"role": "system", "content": "你是梗风格槽位抽取器，只输出 JSON。"},
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                )
            elif hasattr(self.llm_client, "chat"):
                result = await self.llm_client.chat(
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                )
            else:
                return None
            raw = result.get("content", "") if isinstance(result, dict) else str(result)
            data = _parse_json_object(raw)
            slots = {
                name: str(data.get(name, "")).strip()
                for name in self.style.required_slot_names
            }
            self.validate_slots(slots)
            return slots
        except Exception as exc:
            logger.debug("[ZhouliTool] LLM slot filling failed: {}", exc)
            return None

    def _heuristic_slots(self, intent: str) -> dict[str, str]:
        if "疯狂星期四" in intent or "肯德基" in intent or "鸡" in intent:
            return {
                "modern_event": intent,
                "surface_behavior": "贪嘴",
                "elevated_interpretation": "给诸友修仁义、结善缘的机会",
                "other_action": "有人愿以鸡相赠",
                "ordinary_behavior": "破费",
                "noble_interpretation": "以食通礼、以礼会友",
            }
        if "上班" in intent or "开会" in intent or "工" in intent:
            return {
                "modern_event": intent,
                "surface_behavior": "懒散",
                "elevated_interpretation": "身心求养以全后日之功",
                "other_action": "暂得休养",
                "ordinary_behavior": "偷闲",
                "noble_interpretation": "养其精神以全其职",
            }
        return {
            "modern_event": intent,
            "surface_behavior": "寻常小事",
            "elevated_interpretation": "名分已明、情理自洽",
            "other_action": "顺势而行",
            "ordinary_behavior": "任性",
            "noble_interpretation": "各安其职",
        }


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Expected JSON object")
    return data


class MemeRouter:
    """Rule-first router for explicit and semi-active meme style use."""

    def route(
        self,
        text: str,
        *,
        mood: str = "neutral",
        scene: str = "chat",
        state: MemeState | None = None,
        turn_index: int = 0,
        semi_active_enabled: bool = False,
    ) -> MemeRouteDecision:
        invocation = parse_meme_invocation(text)
        if invocation:
            return MemeRouteDecision(
                action="explicit",
                style_id=invocation.style_id,
                intent=invocation.intent,
                bypass_cooldown=True,
            )

        if not semi_active_enabled:
            return MemeRouteDecision(action="none", reason="disabled")

        style = get_meme_style("zhouli")
        if style is None:
            return MemeRouteDecision(action="none", reason="unknown_style")

        if scene in style.avoid_scenes:
            return MemeRouteDecision(action="none", reason="blocked_scene")

        state = state or MemeState()
        cooldown_reason = state.cooldown_reason(style, turn_index)
        if cooldown_reason:
            return MemeRouteDecision(action="none", reason=cooldown_reason)

        text_hit = any(trigger in text for trigger in style.triggers_implicit)
        alias_hit = any(alias in text for alias in ("周礼", "合乎周礼"))
        mood_hit = mood in {"banter", "meme", "light_complaint"}
        if text_hit or alias_hit or mood_hit:
            return MemeRouteDecision(
                action="semi_active",
                style_id=style.id,
                intent=text,
            )

        return MemeRouteDecision(action="none", reason="no_trigger")


@dataclass
class DecoratedResponse:
    text: str
    used_style: str | None = None
    style_result: MemeStyleResult | None = None


async def decorate_response(
    *,
    user_text: str,
    response_text: str,
    mood: str = "neutral",
    scene: str = "chat",
    state: MemeState | None = None,
    turn_index: int = 0,
    semi_active_enabled: bool = False,
    tool: ZhouliTool | None = None,
) -> DecoratedResponse:
    state = state or MemeState()
    decision = MemeRouter().route(
        user_text,
        mood=mood,
        scene=scene,
        state=state,
        turn_index=turn_index,
        semi_active_enabled=semi_active_enabled,
    )
    if decision.action != "semi_active" or decision.style_id != "zhouli":
        return DecoratedResponse(text=response_text)

    style_tool = tool or ZhouliTool()
    result = await style_tool.run(user_text, mode="quip", max_chars=160)
    state.record_use("zhouli", turn_index)
    return DecoratedResponse(
        text=f"{response_text}\n\n{result.text}",
        used_style="zhouli",
        style_result=result,
    )
