<!--
Pull request template for Animetta.
Lines in HTML comments are guidance — they won't render in the posted PR.
-->

## Summary

<!-- 1-3 sentences: what does this PR change and why? Reference the openspec
change if there is one (e.g. "implements add-livestream-scene-director"). -->

## Verification

<!-- Check what you actually ran. Don't tick boxes you didn't run. -->

- [ ] `make install-hooks` then `pre-commit run --all-files` (or the hook passed on commit)
- [ ] `make lint` (ruff check)
- [ ] `make format-check` (ruff format --check)
- [ ] `make typecheck` (mypy src/animetta)
- [ ] `make test-quick` OR `make test-affected` (impact-selected, per tooling/quality.yml)
- [ ] `make test-full` (if the change touches a release-critical path / core loop)

## Impact checklist

<!-- Tick anything this PR touches. Reviewers focus on these. -->

- [ ] Adds or renames a Socket.IO event (if so: update `config/socket-events.json` + `frontend/src/constants/socket-events.ts` + run `python scripts/validate-events.py`)
- [ ] Changes a config schema (`config/animetta.yaml`, a persona, `tools.yaml`, or a Pydantic config model)
- [ ] Changes a CLI flag or public class/function signature
- [ ] Changes the LLM/TTS/ASR provider contract or the dialogue graph topology
- [ ] Changes the probe ingress filter (`core/message_filter.py`) or any `orchestrator.process_text` caller
- [ ] Needs a golden-soak run (release-critical behavior change)

## Notes for reviewer

<!-- Anything non-obvious: trade-offs taken, follow-ups deferred, tests you
couldn't run locally (e.g. GPU/Docker). -->
