"""Versioned, linear program-script contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScriptModel(BaseModel):
    """Strict base model shared by persisted and API script DTOs."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProgramPhase(StrEnum):
    QI = "qi"
    CHENG = "cheng"
    ZHUAN = "zhuan"
    HE = "he"


class InputType(StrEnum):
    CHOICE = "choice"
    FIXED = "fixed"


class MemoryMode(StrEnum):
    WRITE = "write"
    PROBE = "probe"
    NONE = "none"


class ThreadMode(StrEnum):
    SHARED = "shared"
    ISOLATED = "isolated"


class TransitionStyle(StrEnum):
    DIRECT = "direct"
    SOFT = "soft"


class EvaluatorType(StrEnum):
    RECALL_SLOTS = "recall_slots"
    LATEST_SLOT = "latest_slot"
    REJECT_FALSE_PREMISE = "reject_false_premise"
    COMPOSITE_SLOTS = "composite_slots"


class ScriptOption(ScriptModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    label: str = Field(min_length=1, max_length=40)
    danmaku: str = Field(min_length=1, max_length=240)
    aliases: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=list,
        max_length=12,
    )

    @model_validator(mode="after")
    def include_label_alias(self) -> ScriptOption:
        if self.label not in self.aliases:
            self.aliases.insert(0, self.label)
        self.aliases = list(dict.fromkeys(alias for alias in self.aliases if alias))
        return self


class ScriptInput(ScriptModel):
    type: InputType
    options: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    save_as: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    text: str | None = Field(default=None, max_length=240)
    exclude_slot: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{0,63}$")

    @model_validator(mode="after")
    def validate_shape(self) -> ScriptInput:
        if self.type is InputType.CHOICE:
            if not self.options or not self.save_as:
                raise ValueError("choice input requires options and save_as")
            if self.text:
                raise ValueError("choice input cannot define fixed text")
        elif not self.text:
            raise ValueError("fixed input requires text")
        elif self.options or self.save_as or self.exclude_slot:
            raise ValueError("fixed input cannot reference choice options or save a slot")
        return self


class ScriptReply(ScriptModel):
    objective: str = Field(min_length=1, max_length=300)
    max_sentences: int = Field(default=2, ge=1, le=5)
    max_chars: int = Field(default=80, ge=20, le=500)


class ScriptTransition(ScriptModel):
    style: TransitionStyle = TransitionStyle.DIRECT
    text: str | None = Field(default=None, max_length=240)

    @model_validator(mode="after")
    def validate_text(self) -> ScriptTransition:
        if self.style is TransitionStyle.SOFT and not self.text:
            raise ValueError("soft transition requires text")
        if self.style is TransitionStyle.DIRECT and self.text:
            raise ValueError("direct transition cannot define text")
        return self


class ScriptEvaluator(ScriptModel):
    type: EvaluatorType
    slots: list[str] = Field(default_factory=list, max_length=8)
    false_values: list[str] = Field(default_factory=list, max_length=8)
    rejection_markers: list[str] = Field(
        default_factory=lambda: ["不是", "不对", "没有", "记错"],
        max_length=8,
    )

    @model_validator(mode="after")
    def validate_requirements(self) -> ScriptEvaluator:
        if not self.slots:
            raise ValueError("evaluator requires at least one slot")
        if self.type is EvaluatorType.REJECT_FALSE_PREMISE and not self.false_values:
            raise ValueError("reject_false_premise requires false_values")
        return self


class ProgramBeat(ScriptModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    phase: ProgramPhase
    host_prompt: str | None = Field(default=None, max_length=240)
    input: ScriptInput
    memory: MemoryMode = MemoryMode.NONE
    thread: ThreadMode = ThreadMode.SHARED
    reply: ScriptReply
    transition: ScriptTransition = Field(default_factory=ScriptTransition)
    evaluator: ScriptEvaluator | None = None

    @model_validator(mode="after")
    def validate_memory_contract(self) -> ProgramBeat:
        if self.memory is MemoryMode.WRITE and not self.input.save_as:
            raise ValueError("memory write requires a saved choice slot")
        if self.thread is ThreadMode.ISOLATED and self.memory is not MemoryMode.PROBE:
            raise ValueError("isolated thread is only valid for probes")
        if self.memory is not MemoryMode.PROBE and self.evaluator is not None:
            raise ValueError("evaluators are only valid for probes")
        return self


class ProgramDefaults(ScriptModel):
    reply_timeout_ms: int = Field(default=30_000, ge=1_000, le=120_000)
    memory_commit_timeout_ms: int = Field(default=15_000, ge=500, le=60_000)


class ProgramScript(ScriptModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    template: Literal["aura_debut_memory"] | None = None
    disclosure: str = Field(default="", max_length=240)
    opening: str = Field(default="", max_length=240)
    closing: str = Field(default="", max_length=240)
    defaults: ProgramDefaults = Field(default_factory=ProgramDefaults)
    option_sets: dict[str, list[ScriptOption]] = Field(default_factory=dict)
    beats: list[ProgramBeat] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_references(self) -> ProgramScript:
        beat_ids = [beat.id for beat in self.beats]
        if len(beat_ids) != len(set(beat_ids)):
            raise ValueError("beat IDs must be unique")

        slot_names: set[str] = set()
        for set_id, options in self.option_sets.items():
            if not _valid_id(set_id):
                raise ValueError(f"invalid option-set ID: {set_id}")
            option_ids = [option.id for option in options]
            if not options or len(option_ids) != len(set(option_ids)):
                raise ValueError(f"option set {set_id} must contain unique options")
            aliases = [alias.casefold() for option in options for alias in option.aliases]
            if len(aliases) != len(set(aliases)):
                raise ValueError(f"option set {set_id} contains conflicting aliases")

        for beat in self.beats:
            if beat.input.type is InputType.CHOICE:
                if beat.input.options not in self.option_sets:
                    raise ValueError(f"beat {beat.id} references an unknown option set")
                if beat.input.exclude_slot and beat.input.exclude_slot not in slot_names:
                    raise ValueError(f"beat {beat.id} excludes an unknown prior slot")
                slot_names.add(str(beat.input.save_as))
            if beat.evaluator:
                missing = set(beat.evaluator.slots) - slot_names
                if missing:
                    raise ValueError(
                        f"beat {beat.id} evaluates unknown slots: {', '.join(sorted(missing))}"
                    )
        return self


class ValidationIssue(ScriptModel):
    path: str
    message: str
    code: str


class ProgramScriptDraft(ScriptModel):
    revision: int = Field(ge=1)
    script: ProgramScript


class PublishedProgramScript(ScriptModel):
    version: int = Field(ge=1)
    content_hash: str = Field(min_length=64, max_length=64)
    created_at: str
    builtin: bool = False
    script: ProgramScript


def validate_program_script(script: ProgramScript) -> list[ValidationIssue]:
    """Return semantic issues that require the complete script graph."""
    issues = _probe_leakage_issues(script)
    if script.template == "aura_debut_memory":
        issues.extend(_aura_template_issues(script))
    return issues


def _slot_option_sets(script: ProgramScript) -> dict[str, list[ScriptOption]]:
    result: dict[str, list[ScriptOption]] = {}
    for beat in script.beats:
        if beat.input.type is InputType.CHOICE and beat.input.save_as and beat.input.options:
            result[beat.input.save_as] = script.option_sets[beat.input.options]
    return result


def _probe_leakage_issues(script: ProgramScript) -> list[ValidationIssue]:
    slot_options = _slot_option_sets(script)
    issues: list[ValidationIssue] = []
    for index, beat in enumerate(script.beats):
        if beat.memory is not MemoryMode.PROBE or beat.evaluator is None:
            continue
        instruction = " ".join(
            value for value in (beat.host_prompt, beat.input.text, beat.reply.objective) if value
        ).casefold()
        leaked = sorted(
            {
                alias
                for slot in beat.evaluator.slots
                for option in slot_options.get(slot, [])
                for alias in option.aliases
                if alias.casefold() in instruction
            }
        )
        if leaked:
            issues.append(
                ValidationIssue(
                    path=f"beats.{index}",
                    code="probe_answer_leak",
                    message=f"探测指令包含答案别名：{'、'.join(leaked)}",
                )
            )
    return issues


def _aura_template_issues(script: ProgramScript) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if len(script.beats) != 12:
        issues.append(
            ValidationIssue(path="beats", code="aura_round_count", message="Aura 模板必须为 12 轮")
        )
        return issues

    expected_ids = [f"q{index:02d}" for index in range(1, 13)]
    if [beat.id for beat in script.beats] != expected_ids:
        issues.append(
            ValidationIssue(
                path="beats",
                code="aura_round_ids",
                message="Aura 模板轮次 ID 必须连续为 q01–q12",
            )
        )

    q8 = script.beats[7]
    q5 = script.beats[4]
    q8_options = script.option_sets.get(q8.input.options or "", [])
    if (
        q8.input.exclude_slot != q5.input.save_as
        or q8.input.save_as != q5.input.save_as
        or q8.input.options != q5.input.options
        or len(q8_options) != 2
        or q8.memory is not MemoryMode.WRITE
    ):
        issues.append(
            ValidationIssue(
                path="beats.7",
                code="aura_reverse_camp",
                message="Q8 必须从 Q5 的二选一阵营中排除当前值并写入同一槽位",
            )
        )

    for index in range(8, 12):
        beat = script.beats[index]
        if beat.memory is not MemoryMode.PROBE or beat.thread is not ThreadMode.ISOLATED:
            issues.append(
                ValidationIssue(
                    path=f"beats.{index}",
                    code="aura_strict_probe",
                    message=f"Q{index + 1} 必须是隔离线程记忆探测",
                )
            )

    q11 = script.beats[10]
    weekend_values = {
        value
        for option in _slot_option_sets(script).get("weekend", [])
        for value in [option.danmaku, *option.aliases]
    }
    if "爬山" not in (q11.input.text or "") or any("爬山" in value for value in weekend_values):
        issues.append(
            ValidationIssue(
                path="beats.10.input.text",
                code="aura_false_weekend",
                message="Q11 必须使用不属于真实周末选项的“爬山”干扰项",
            )
        )
    return issues


def _valid_id(value: str) -> bool:
    return (
        bool(value)
        and value[0].islower()
        and all(
            character.islower() or character.isdigit() or character in "_-" for character in value
        )
    )
