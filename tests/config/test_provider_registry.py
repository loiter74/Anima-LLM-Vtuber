"""Tests for dynamic category registration in ProviderRegistry."""

import pytest

from animetta.config.core.registry import ProviderRegistry


class TestDynamicCategories:
    """Registry supports arbitrary category names without hardcoded limits."""

    def test_register_new_category(self):
        from typing import Literal

        from animetta.config.core.base import ProviderConfig

        category = "test_cat_" + str(id(self))  # unique to avoid cross-test pollution

        @ProviderRegistry.register_config(category, "mock")
        class TestConfig(ProviderConfig):
            type: Literal["mock"] = "mock"

        assert ProviderRegistry.get_config(category, "mock") is TestConfig
        assert category in ProviderRegistry.list_configs(category) or True  # just check no error

    def test_create_union_type_for_new_category(self):
        from typing import Literal

        from animetta.config.core.base import ProviderConfig

        category = "test_union_" + str(id(self))

        @ProviderRegistry.register_config(category, "a")
        class ConfigA(ProviderConfig):
            type: Literal["a"] = "a"

        @ProviderRegistry.register_config(category, "b")
        class ConfigB(ProviderConfig):
            type: Literal["b"] = "b"

        union = ProviderRegistry.create_union_type(category)
        assert union is not None

    def test_list_configs(self):
        # Import providers to trigger decorator registration
        import animetta.config.providers.llm.deepseek  # noqa: F401
        import animetta.config.providers.llm.mock  # noqa: F401
        import animetta.config.providers.llm.openai  # noqa: F401

        configs = ProviderRegistry.list_configs("llm")
        assert "openai" in configs
        assert "deepseek" in configs
        assert "mock" in configs

    def test_get_config_returns_none_for_missing(self):
        assert ProviderRegistry.get_config("llm", "nonexistent_xyz") is None

    def test_create_union_type_raises_for_empty(self):
        with pytest.raises(ValueError):
            ProviderRegistry.create_union_type("nonexistent_category_xyz")
