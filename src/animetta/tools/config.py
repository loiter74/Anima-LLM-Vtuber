"""
Tool configuration loader

Loads tool configuration from config/tools.yaml.
"""

from pathlib import Path
from typing import Any

import yaml
from loguru import logger


def load_tools_config(config_path: str | None = None) -> dict[str, Any]:
    """
    Load tool configuration

    Args:
        config_path: Configuration file path (default: config/tools.yaml)

    Returns:
        Dict: Tool configuration dictionary
    """
    if config_path is None:
        # Default path
        config_path = str(Path(__file__).parent.parent.parent / "config" / "tools.yaml")

    config_path_obj = Path(config_path)

    if not config_path_obj.exists():
        logger.warning(f"[Tool Config] Config file not found: {config_path_obj}, using default config")
        return _get_default_config()

    try:
        with open(config_path_obj, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        logger.info(f"[Tool Config] Loaded config: {config_path_obj}")
        return config or {}

    except Exception as e:
        logger.error(f"[Tool Config] Load failed: {e}, using default config")
        return _get_default_config()


def _get_default_config() -> dict[str, Any]:
    """
    Get default tool configuration

    Returns:
        Dict: Default configuration dictionary
    """
    return {
        "builtin_tools": [
            "web_search",
            "get_weather",
            "get_current_time",
            "calculator",
        ],
        "mcp_servers": [],
        "tool_settings": {
            "max_tool_calls_per_turn": 5,
            "tool_execution_timeout": 30,
            "retry_on_failure": True,
            "max_retries": 2,
            "log_tool_calls": True,
        },
    }


def validate_tools_config(config: dict[str, Any]) -> bool:
    """
    Validate tool configuration

    Args:
        config: Tool configuration dictionary

    Returns:
        bool: Whether the configuration is valid
    """
    # Validate built-in tools
    builtin_tools = config.get("builtin_tools", [])
    valid_builtin = {
        "web_search", "get_weather",
        "get_current_time", "calculator",
    }

    for tool in builtin_tools:
        if tool not in valid_builtin:
            logger.warning(f"[Tool Config] Unknown built-in tool: {tool}")

    # Validate MCP server configuration
    mcp_servers = config.get("mcp_servers", [])
    for server in mcp_servers:
        if "name" not in server:
            logger.error("[Tool Config] MCP server missing name field")
            return False

        transport = server.get("transport", "stdio")
        if transport == "stdio":
            if "command" not in server:
                logger.error(f"[Tool Config] MCP server {server['name']} missing command field")
                return False
        elif transport in ("sse", "streamable_http"):
            if "url" not in server:
                logger.error(f"[Tool Config] MCP server {server['name']} missing url field")
                return False
        else:
            logger.error(f"[Tool Config] Unsupported transport mode: {transport}")
            return False

    return True
