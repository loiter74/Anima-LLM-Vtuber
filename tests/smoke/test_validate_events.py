from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_validate_events_module():
    script = Path(__file__).resolve().parents[2] / "scripts" / "validate-events.py"
    spec = importlib.util.spec_from_file_location("validate_events", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_python_event_validation_rejects_stale_listener_names(tmp_path, monkeypatch):
    module = _load_validate_events_module()
    source_dir = tmp_path / "src" / "animetta"
    source_dir.mkdir(parents=True)
    event_name = "sentence"
    (source_dir / "probe.py").write_text(
        f'sio.on("{event_name}", lambda data: None)\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "SRC_DIR", source_dir)
    monkeypatch.setattr(module, "PYTHON_EVENT_DIRS", [source_dir])

    errors = module.validate_python_emits({"chat.sentence": "chat:sentence"})

    assert errors == [
        "src/animetta/probe.py: on('sentence') not in socket-events.json"
    ]


def test_frontend_event_validation_rejects_stale_emit_names(tmp_path, monkeypatch):
    module = _load_validate_events_module()
    frontend_dir = tmp_path / "frontend" / "src"
    frontend_dir.mkdir(parents=True)
    stale_event_name = "text_input"
    (frontend_dir / "Probe.vue").write_text(
        f'<script setup lang="ts">\nsocket.emit("{stale_event_name}", {{ text: "hi" }})\n</script>\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "FRONTEND_SRC_DIR", frontend_dir)

    errors = module.validate_frontend_event_literals({"chat.text": "chat:text"})

    assert errors == [
        "frontend/src/Probe.vue: emit('text_input') not in socket-events.json"
    ]
