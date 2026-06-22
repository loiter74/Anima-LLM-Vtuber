from __future__ import annotations

"""Tests for custom_tools module (url_preview, send_email, image_gen)."""

import pytest

import animetta.core.tools.custom_tools as custom_tools
from animetta.core.tools.custom_tools import (
    CUSTOM_TOOLS,
    get_custom_tools,
    image_gen,
    send_email,
    url_preview,
)


class TestCustomToolsModule:
    """Module-level tests for custom_tools."""

    def test_module_import(self):
        """Verify custom_tools module imports without error."""
        assert custom_tools is not None

    def test_tool_list_export(self):
        """CUSTOM_TOOLS contains expected tools and get_custom_tools returns a copy."""

        assert len(CUSTOM_TOOLS) == 3
        assert get_custom_tools() == CUSTOM_TOOLS
        assert get_custom_tools() is not CUSTOM_TOOLS  # should be a copy


class TestToolSchemas:
    """Validate tool name, description, and argument schemas."""

    def test_url_preview_schema(self):
        assert url_preview.name == "url_preview"
        assert isinstance(url_preview.description, str)
        assert len(url_preview.description) > 0
        assert "url" in url_preview.args
        assert url_preview.args["url"]["type"] == "string"

    def test_send_email_schema(self):
        assert send_email.name == "send_email"
        assert isinstance(send_email.description, str)
        assert len(send_email.description) > 0
        for arg in ("to", "subject", "body"):
            assert arg in send_email.args
            assert send_email.args[arg]["type"] == "string"

    def test_image_gen_schema(self):
        assert image_gen.name == "image_gen"
        assert isinstance(image_gen.description, str)
        assert len(image_gen.description) > 0
        assert "prompt" in image_gen.args
        assert "size" in image_gen.args


class TestUrlPreview:
    """Tests for url_preview tool using invalid URLs (no network needed)."""

    @pytest.mark.asyncio
    async def test_invalid_url_format(self):
        result = await url_preview.coroutine("not-a-url")
        assert "Invalid URL" in result

    @pytest.mark.asyncio
    async def test_empty_string_url(self):
        result = await url_preview.coroutine("")
        assert "Invalid URL" in result

    @pytest.mark.asyncio
    async def test_url_without_scheme(self):
        result = await url_preview.coroutine("example.com/path")
        assert "Invalid URL" in result


class TestSendEmail:
    """Tests for send_email — skipped; requires SMTP credentials."""

    @pytest.mark.skip(reason="Requires SMTP_USER and SMTP_PASSWORD environment variables")
    @pytest.mark.asyncio
    async def test_send_email_unconfigured(self):
        result = await send_email.coroutine(
            to="test@example.com",
            subject="Test",
            body="Hello",
        )
        assert "not configured" in result


class TestImageGen:
    """Tests for image_gen — skipped; requires API keys."""

    @pytest.mark.skip(reason="Requires OPENAI_API_KEY or REPLICATE_API_TOKEN")
    @pytest.mark.asyncio
    async def test_image_gen_unconfigured(self):
        result = await image_gen.coroutine(prompt="a cat")
        assert "unavailable" in result
