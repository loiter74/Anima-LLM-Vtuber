from __future__ import annotations

"""Tests for custom_tools module (url_preview, send_email, image_gen)."""

import pytest

from animetta.tools.custom_tools import (
    CUSTOM_TOOLS,
    get_custom_tools,
    image_gen,
    send_email,
    url_preview,
)


class TestCustomToolsModule:
    """Module-level tests for custom_tools."""

    def test_tool_list_export(self):
        """CUSTOM_TOOLS contains expected tools and get_custom_tools returns a copy."""

        assert len(CUSTOM_TOOLS) == 3
        assert get_custom_tools() == CUSTOM_TOOLS
        assert get_custom_tools() is not CUSTOM_TOOLS  # should be a copy


class TestToolSchemas:
    """Validate tool name, description, and argument schemas."""

    @pytest.mark.parametrize(
        ("tool", "name", "arguments"),
        [
            (url_preview, "url_preview", ("url",)),
            (send_email, "send_email", ("to", "subject", "body")),
            (image_gen, "image_gen", ("prompt", "size")),
        ],
    )
    def test_schema(self, tool, name, arguments):
        assert tool.name == name
        assert tool.description
        assert all(tool.args[argument]["type"] == "string" for argument in arguments)


class TestUrlPreview:
    """Tests for url_preview tool using invalid URLs (no network needed)."""

    @pytest.mark.parametrize("url", ["not-a-url", "", "example.com/path"])
    async def test_invalid_url(self, url):
        result = await url_preview.coroutine(url)
        assert "Invalid URL" in result


class TestSendEmail:
    """Tests for send_email without touching SMTP."""

    async def test_send_email_unconfigured(self, monkeypatch):
        monkeypatch.delenv("SMTP_USER", raising=False)
        monkeypatch.delenv("SMTP_PASSWORD", raising=False)
        result = await send_email.coroutine(
            to="test@example.com",
            subject="Test",
            body="Hello",
        )
        assert "not configured" in result


class TestImageGen:
    """Tests for image_gen without touching provider APIs."""

    async def test_image_gen_unconfigured(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
        result = await image_gen.coroutine(prompt="a cat")
        assert "unavailable" in result
