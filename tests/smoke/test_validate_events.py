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


def test_frontend_event_validation_scans_standalone_html(tmp_path, monkeypatch):
    module = _load_validate_events_module()
    frontend_dir = tmp_path / "frontend" / "src"
    frontend_dir.mkdir(parents=True)
    standalone = tmp_path / "frontend" / "live.html"
    invalid_event = "dan" + "maku"
    standalone.write_text(
        f'<script>socket.on("{invalid_event}", () => {{}})</script>\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "FRONTEND_SRC_DIR", frontend_dir)
    monkeypatch.setattr(module, "FRONTEND_ENTRY_FILES", [standalone])

    errors = module.validate_frontend_event_literals(
        {"bilibili.danmaku": "bilibili:danmaku"}
    )

    assert errors == [
        f"frontend/live.html: on('{invalid_event}') not in socket-events.json"
    ]


def test_legacy_alias_is_rejected_outside_adapter_boundary(tmp_path, monkeypatch):
    module = _load_validate_events_module()
    source_dir = tmp_path / "src" / "animetta"
    source_dir.mkdir(parents=True)
    (source_dir / "probe.py").write_text(
        'await sio.' + 'emit("sentence", {"text": "stale"})\n', encoding="utf-8"
    )
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "SRC_DIR", source_dir)
    monkeypatch.setattr(module, "FRONTEND_SRC_DIR", tmp_path / "frontend" / "src")
    monkeypatch.setattr(module, "LEGACY_ADAPTER_FILES", set())

    assert module.validate_legacy_alias_boundaries({"sentence"}) == [
        "src/animetta/probe.py: legacy event 'sentence' is outside the adapter boundary"
    ]


def test_legacy_alias_is_legal_inside_declared_adapter(tmp_path, monkeypatch):
    module = _load_validate_events_module()
    source_dir = tmp_path / "src" / "animetta"
    adapter = source_dir / "adapter.py"
    source_dir.mkdir(parents=True)
    adapter.write_text('sio.' + 'on("text_input", handler)\n', encoding="utf-8")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "SRC_DIR", source_dir)
    monkeypatch.setattr(module, "FRONTEND_SRC_DIR", tmp_path / "frontend" / "src")
    monkeypatch.setattr(module, "LEGACY_ADAPTER_FILES", {adapter})

    assert module.validate_legacy_alias_boundaries({"text_input"}) == []
