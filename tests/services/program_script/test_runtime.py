from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from animetta.services.program_script import (
    ProgramRuntimeError,
    ProgramScriptRepository,
    ProgramScriptRunner,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class FakeMemoryRuntime:
    def __init__(self) -> None:
        self.callback = None
        self.system = SimpleNamespace(forget_memory=AsyncMock())

    def subscribe_revision(self, callback):
        self.callback = callback
        return lambda: None

    def commit(self, turn_id: str, atom_id: str) -> None:
        assert self.callback is not None
        self.callback({"revision": 7, "reason": "ingested", "atom_id": atom_id, "turn_id": turn_id})


async def wait_until(predicate, timeout: float = 1.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0)


async def test_runner_waits_for_commit_and_uses_isolated_probe_thread(tmp_path: Path) -> None:
    repository = ProgramScriptRepository(
        tmp_path,
        builtin_dir=PROJECT_ROOT / "config" / "program_scripts",
    )
    memory = FakeMemoryRuntime()
    runner = ProgramScriptRunner(repository, memory_runtime=memory)
    contexts: list[dict] = []

    async def dispatch(text: str, context: dict):
        contexts.append(context)
        if not context["is_probe"]:
            asyncio.get_running_loop().call_soon(
                memory.commit,
                context["turn_id"],
                f"atom-{len(contexts)}",
            )
        return {
            "response_text": "小岚，记得。",
            "memory_recall": {"degraded": False, "atom_count": 1},
        }

    runner.set_dispatcher(dispatch)
    runner.set_room_state_provider(lambda _room_id: {"state": "stopped"})
    started = await runner.start(
        "aura-debut-memory",
        1,
        room_id=1,
        creator_id="creator",
    )
    run_id = started["run_id"]
    await runner.submit_choice(run_id, "q01", "xiaolan", creator_id="creator")
    await wait_until(
        lambda: runner.get_run(run_id)["current_index"] == 1 and run_id not in runner._tasks
    )

    assert runner.get_run(run_id)["slots"] == {"nickname": "xiaolan"}
    assert started["current_beat"]["lead_in"] == started["opening"]
    assert runner.get_run(run_id)["current_beat"]["lead_in"]
    assert contexts[0]["checkpoint_thread_id"] == f"program:{run_id}"
    assert contexts[0]["memory_mode"] == "write"
    assert contexts[0]["scene_guidance"]["response_objective"]

    await runner.control(run_id, "pause", creator_id="creator")
    retried = await runner.control(run_id, "retry", creator_id="creator")
    assert retried["waiting_for"] == "choice"
    assert len(contexts) == 1

    run = runner._runs[run_id]
    run.current_index = 8
    run.slots.update(
        {
            "color": "night_blue",
            "weekend": "tidy_desk",
            "secret": "moon_off",
            "camp": "dog",
        }
    )
    runner._prepare_current(run)
    await wait_until(lambda: runner.get_run(run_id)["current_index"] == 9)

    assert contexts[-1]["is_probe"] is True
    assert contexts[-1]["memory_mode"] == "probe"
    assert contexts[-1]["checkpoint_thread_id"] == f"program:{run_id}:q09"
    assert runner.get_run(run_id)["records"][-1]["probe_result"] == "matched"
    await runner.control(run_id, "stop", creator_id="creator")


async def test_running_snapshot_is_frozen_when_a_new_version_is_published(tmp_path: Path) -> None:
    repository = ProgramScriptRepository(
        tmp_path,
        builtin_dir=PROJECT_ROOT / "config" / "program_scripts",
    )
    runner = ProgramScriptRunner(repository)
    runner.set_dispatcher(AsyncMock(return_value={"response_text": "好"}))
    runner.set_room_state_provider(lambda _room_id: {"state": "stopped"})

    started = await runner.start("aura-debut-memory", 1, room_id=1, creator_id="creator")
    draft = repository.duplicate_version(
        "aura-debut-memory", 1, new_id="separate-script", title="后来发布"
    )
    repository.publish("separate-script", expected_revision=draft.revision)

    current = runner.get_run(started["run_id"])
    assert current["script_title"] == "Aura 首播记忆游戏"
    assert current["script_version"] == 1
    await runner.control(started["run_id"], "stop", creator_id="creator")


async def test_archived_script_cannot_start_a_new_run(tmp_path: Path) -> None:
    repository = ProgramScriptRepository(
        tmp_path,
        builtin_dir=PROJECT_ROOT / "config" / "program_scripts",
    )
    draft = repository.duplicate_version(
        "aura-debut-memory",
        1,
        new_id="archived-script",
    )
    repository.publish("archived-script", expected_revision=draft.revision)
    repository.archive("archived-script")
    runner = ProgramScriptRunner(repository)
    runner.set_dispatcher(AsyncMock(return_value={"response_text": "好"}))
    runner.set_room_state_provider(lambda _room_id: {"state": "stopped"})

    with pytest.raises(ProgramRuntimeError) as exc_info:
        await runner.start("archived-script", 1, room_id=1, creator_id="creator")

    assert exc_info.value.code == "script_archived"
