from __future__ import annotations

"""
Preset Loader
Loads Live2D action preset configuration (YAML format)
Based on open-yachiyo's live2d-presets.yaml
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from .action_queue import ActionFactory, ActionMessage


@dataclass
class EmotePreset:
    """Emotion preset"""
    name: str
    intensity: str  # low, medium, high
    expression: str
    params: list[dict[str, Any]]


@dataclass
class GesturePreset:
    """Gesture preset"""
    name: str
    expression: str | None
    motion_group: str | None
    motion_index: int | None


@dataclass
class ReactPreset:
    """Reaction preset"""
    name: str
    actions: list[dict[str, Any]]


class PresetLoader:
    """
    Live2D Preset Loader

    Loads expression, gesture, and reaction presets from YAML files
    """

    def __init__(self, config_path: str = None):
        """
        Initialize the preset loader

        Args:
            config_path: Preset configuration file path
        """
        if config_path is None:
            # Default path
            project_root = Path(__file__).parent.parent.parent.parent.parent
            config_path = project_root / "config" / "live2d-presets.yaml"

        self.config_path = Path(config_path)
        self.presets: dict[str, Any] = {}
        self._load_presets()

    def _load_presets(self):
        """Load preset file"""
        if not self.config_path.exists():
            logger.warning(f"[PresetLoader] Preset file does not exist: {self.config_path}")
            return

        try:
            with open(self.config_path, encoding='utf-8') as f:
                self.presets = yaml.safe_load(f)
            logger.info(f"[PresetLoader] Preset loaded successfully: {self.config_path}")
        except Exception as e:
            logger.error(f"[PresetLoader] Failed to load preset: {e}")

    def get_emote(self, emotion: str, intensity: str = "medium") -> dict | None:
        """
        Get emotion preset

        Args:
            emotion: Emotion name (e.g., "happy", "sad")
            intensity: Intensity ("low", "medium", "high")

        Returns:
            Preset data
        """
        emote_presets = self.presets.get('emote', {})
        emotion_data = emote_presets.get(emotion, {})
        intensity_data = emotion_data.get(intensity)

        if not intensity_data:
            # Try using medium as default
            intensity_data = emotion_data.get('medium')

        return intensity_data

    def get_gesture(self, gesture_name: str) -> dict | None:
        """
        Get gesture preset

        Args:
            gesture_name: Gesture name (e.g., "greet", "think")

        Returns:
            Preset data
        """
        gesture_presets = self.presets.get('gesture', {})
        return gesture_presets.get(gesture_name)

    def get_react(self, react_name: str) -> list[dict] | None:
        """
        Get reaction preset

        Args:
            react_name: Reaction name (e.g., "success", "error")

        Returns:
            Action list
        """
        react_presets = self.presets.get('react', {})
        return react_presets.get(react_name)

    def create_emote_action(self, emotion: str, intensity: str = "medium") -> ActionMessage | None:
        """
        Create an emotion action

        Args:
            emotion: Emotion name
            intensity: Intensity

        Returns:
            Action message
        """
        preset = self.get_emote(emotion, intensity)
        if not preset:
            return None

        # Create action
        actions = []

        # Expression
        expression = preset.get('expression')
        if expression:
            actions.append({
                "type": "expression",
                "name": expression
            })

        # Parameters
        params = preset.get('params', [])
        for param in params:
            actions.append({
                "type": "param",
                "name": param.get('name'),
                "value": param.get('value')
            })

        # If there are multiple actions, wrap as a sequence
        if len(actions) > 1:
            return ActionFactory.sequence(actions, 0.5)
        elif actions:
            return ActionMessage(
                action_id=f"emote_{emotion}_{intensity}",
                action=actions[0],
                duration_sec=0.3
            )

        return None

    def create_gesture_action(self, gesture_name: str) -> ActionMessage | None:
        """
        Create a gesture action

        Args:
            gesture_name: Gesture name

        Returns:
            Action message
        """
        preset = self.get_gesture(gesture_name)
        if not preset:
            return None

        actions = []

        # Expression
        expression = preset.get('expression')
        if expression:
            actions.append({
                "type": "expression",
                "name": expression
            })

        # Motion
        motion = preset.get('motion')
        if motion:
            actions.append({
                "type": "motion",
                "group": motion.get('group'),
                "index": motion.get('index')
            })

        if len(actions) > 1:
            return ActionFactory.sequence(actions, 1.0)
        elif actions:
            return ActionMessage(
                action_id=f"gesture_{gesture_name}",
                action=actions[0],
                duration_sec=0.8
            )

        return None

    def create_react_action(self, react_name: str) -> ActionMessage | None:
        """
        Create a reaction action

        Args:
            react_name: Reaction name

        Returns:
            Action message (sequence)
        """
        preset = self.get_react(react_name)
        if not preset:
            return None

        # Calculate total duration
        total_duration = 0
        for action in preset:
            if action.get('type') == 'wait':
                total_duration += action.get('ms', 0) / 1000
            else:
                total_duration += 0.3  # Default action duration

        return ActionMessage(
            action_id=f"react_{react_name}",
            action={
                "type": "sequence",
                "actions": preset
            },
            duration_sec=total_duration
        )

    def list_emotes(self) -> list[str]:
        """List all available emotions"""
        return list(self.presets.get('emote', {}).keys())

    def list_gestures(self) -> list[str]:
        """List all available gestures"""
        return list(self.presets.get('gesture', {}).keys())

    def list_reacts(self) -> list[str]:
        """List all available reactions"""
        return list(self.presets.get('react', {}).keys())


# Global instance
_preset_loader: PresetLoader | None = None


def get_preset_loader() -> PresetLoader:
    """Get the global preset loader instance"""
    global _preset_loader
    if _preset_loader is None:
        _preset_loader = PresetLoader()
    return _preset_loader
