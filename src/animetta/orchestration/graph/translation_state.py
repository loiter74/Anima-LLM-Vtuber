"""Shared translation state for runtime configuration.

Both output_node.py and routes.py import this module to read/write
the current translation settings. This avoids circular imports and
allows real-time updates via socket events.
"""


class TranslationState:
    """Runtime translation configuration state.

    Updated by routes.py when receiving `translation.core.configure` events.
    Read by output_node.py before emitting sentence events.
    """

    def __init__(self):
        self._enabled: bool = True  # Default on; user can toggle via 📝 字幕 settings panel
        self._target_language: str = "English"
        self._source_language: str = "Chinese"

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    @property
    def target_language(self) -> str:
        return self._target_language

    @target_language.setter
    def target_language(self, value: str) -> None:
        self._target_language = value

    @property
    def source_language(self) -> str:
        return self._source_language

    def to_dict(self) -> dict:
        return {
            "enabled": self._enabled,
            "target_language": self._target_language,
            "source_language": self._source_language,
        }


# Module-level singleton — shared across the process
translation_state = TranslationState()
