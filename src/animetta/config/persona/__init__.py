"""
Persona configuration module

Contains base persona configuration and enhanced persona builder
"""

from .base import (
    BehaviorRules,
    MBTIDimensionDelta,
    MBTIDimensions,
    MBTIProfile,
    PersonaConfig,
    PersonalityTraits,
    list_available_personas,
)
from .enhanced import (
    EnhancedPersonaBuilder,
    create_enhanced_system_prompt,
)

__all__ = [
    "PersonalityTraits",
    "BehaviorRules",
    "PersonaConfig",
    "MBTIProfile",
    "MBTIDimensions",
    "MBTIDimensionDelta",
    "EnhancedPersonaBuilder",
    "create_enhanced_system_prompt",
    "list_available_personas",
]
