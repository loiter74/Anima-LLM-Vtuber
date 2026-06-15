from __future__ import annotations

"""Tests for LoggerManager configuration and singleton behavior."""

from unittest.mock import patch

from animetta.utils.logger_manager import LoggerManager, logger_manager


class TestLoggerManagerBasic:
    """LoggerManager basic operations."""

    def test_singleton_behavior(self):
        instance1 = LoggerManager.get_instance()
        instance2 = LoggerManager.get_instance()
        assert instance1 is instance2

    def test_initial_level_is_info(self):
        mgr = LoggerManager.get_instance()
        assert mgr.get_level() is not None

    def test_set_level_valid(self):
        mgr = LoggerManager.get_instance()
        # Save current level and restore
        original_level = mgr.get_level()
        result = mgr.set_level("DEBUG")
        assert result is True
        assert mgr.get_level() == "DEBUG"
        # Restore
        mgr.set_level(original_level)

    def test_set_level_invalid(self):
        mgr = LoggerManager.get_instance()
        original_level = mgr.get_level()
        result = mgr.set_level("INVALID")
        assert result is False
        # Level should remain unchanged
        mgr.set_level(original_level)

    def test_set_level_case_insensitive(self):
        mgr = LoggerManager.get_instance()
        original_level = mgr.get_level()
        result = mgr.set_level("debug")
        assert result is True
        assert mgr.get_level() == "DEBUG"
        mgr.set_level(original_level)

    def test_set_level_all_valid_values(self):
        mgr = LoggerManager.get_instance()
        original_level = mgr.get_level()
        for level in ["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            result = mgr.set_level(level)
            assert result is True
            assert mgr.get_level() == level
        mgr.set_level(original_level)


class TestLoggerManagerSingleton:
    """Global logger_manager singleton."""

    def test_global_singleton_exists(self):
        assert logger_manager is not None
        assert hasattr(logger_manager, "set_level")
        assert hasattr(logger_manager, "get_level")

    def test_global_is_same_instance(self):
        assert logger_manager is LoggerManager.get_instance()

    def test_set_level_on_global(self):
        original = logger_manager.get_level()
        logger_manager.set_level("WARNING")
        assert logger_manager.get_level() == "WARNING"
        logger_manager.set_level(original)


class TestLoggerManagerInstantiation:
    """LoggerManager __init__ behavior."""

    def test_init_sets_up_handler(self):
        with patch("animetta.utils.logger_manager.logger.remove") as mock_remove, patch("animetta.utils.logger_manager.logger.add") as mock_add:
            mock_add.return_value = 123
            mgr = LoggerManager()
            mock_remove.assert_called_once()
            mock_add.assert_called_once()
            assert mgr._handler_id == 123
            assert mgr._current_level == "INFO"
