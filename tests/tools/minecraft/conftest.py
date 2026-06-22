"""Conftest for Minecraft tests.

Pre-populates sys.modules with the minecraft package to prevent
__init__.py from importing the full module tree (which may have
dependencies not available in the test environment).
"""

import sys
import types

# Create a lightweight package stub so that submodule imports
# like ``from animetta.tools.minecraft.survival_models import ...``
# don't trigger the full __init__.py import chain.
_PKG_NAME = "animetta.tools.minecraft"
_PKG_PATH = "src/animetta/tools/minecraft"

if _PKG_NAME not in sys.modules or not hasattr(sys.modules[_PKG_NAME], "__path__"):
    pkg = types.ModuleType(_PKG_NAME)
    pkg.__path__ = [_PKG_PATH]
    pkg.__package__ = _PKG_NAME
    sys.modules[_PKG_NAME] = pkg
