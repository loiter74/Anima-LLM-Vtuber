from __future__ import annotations

from pathlib import Path

from animetta.services.program_script import (
    ProgramScript,
    ProgramScriptRepository,
    validate_program_script,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_aura_builtin_has_twelve_valid_linear_beats() -> None:
    repository = ProgramScriptRepository(
        PROJECT_ROOT / ".unused-program-scripts",
        builtin_dir=PROJECT_ROOT / "config" / "program_scripts",
    )

    script = repository.get_published("aura-debut-memory", 1).script

    assert [beat.id for beat in script.beats] == [f"q{index:02d}" for index in range(1, 13)]
    assert validate_program_script(script) == []
    assert script.beats[7].input.exclude_slot == "camp"
    assert all(beat.thread == "isolated" for beat in script.beats[8:12])


def test_generic_four_beat_script_is_not_bound_to_aura_rules() -> None:
    script = ProgramScript.model_validate(
        {
            "id": "four-beat-demo",
            "title": "四轮演示",
            "option_sets": {
                "answer": [{"id": "yes", "label": "愿意", "danmaku": "我愿意", "aliases": ["愿意"]}]
            },
            "beats": [
                {
                    "id": f"beat-{index}",
                    "phase": phase,
                    "input": (
                        {"type": "choice", "options": "answer", "save_as": "answer"}
                        if index == 1
                        else {"type": "fixed", "text": f"第 {index} 轮"}
                    ),
                    "memory": "write" if index == 1 else "none",
                    "reply": {"objective": "简短回应"},
                }
                for index, phase in enumerate(("qi", "cheng", "zhuan", "he"), start=1)
            ],
        }
    )

    assert len(script.beats) == 4
    assert validate_program_script(script) == []


def test_aura_probe_cannot_embed_a_real_option_alias() -> None:
    repository = ProgramScriptRepository(
        PROJECT_ROOT / ".unused-program-scripts",
        builtin_dir=PROJECT_ROOT / "config" / "program_scripts",
    )
    script = repository.get_published("aura-debut-memory", 1).script.model_copy(deep=True)
    script.beats[8].reply.objective = "直接回答小岚"

    issues = validate_program_script(script)

    assert any(issue.code == "probe_answer_leak" and issue.path == "beats.8" for issue in issues)
