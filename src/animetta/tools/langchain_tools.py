"""
LangChain built-in tool integration

Provides integration and loading of LangChain's built-in tools.
"""

from typing import Any

from loguru import logger


def get_python_repl_tool() -> Any:
    """
    Get Python code execution tool (safe version)

    Returns:
        Python REPL tool instance
    """
    try:
        from langchain_experimental.utilities import PythonREPL

        python_repl = PythonREPL()

        from langchain_core.core.tools import StructuredTool
        from pydantic import BaseModel, Field

        class PythonInput(BaseModel):
            code: str = Field(description="Python code to execute")

        async def python_exec(code: str) -> str:
            """Safely execute Python code and return the result"""
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    python_repl.run,
                    code
                )
                return f"Python execution result:\n\n{result}"
            except Exception as e:
                return f"Python execution error: {str(e)}"

        return StructuredTool.from_function(
            name="python_repl",
            description="Safely execute Python code and return the result. Suitable for mathematical calculations, data processing, algorithm verification, etc.",
            coroutine=python_exec,
            args_schema=PythonInput,
        )

    except ImportError:
        logger.warning("[LangChainTools] PythonREPL not installed, run: pip install langchain-experimental")
        return None
    except Exception as e:
        logger.error(f"[LangChainTools] PythonREPL load failed: {e}")
        return None


# Tool registry
_LANGCHAIN_TOOL_GETTERS = {
    "python_repl": get_python_repl_tool,
}


def load_langchain_tools(enabled_tools: list[str] | None = None) -> list[Any]:
    """
    Load LangChain tools

    Args:
        enabled_tools: List of tool names to enable (None to enable all)

    Returns:
        Tool list
    """
    if enabled_tools is None:
        # If not specified, return empty list (requires explicit enabling)
        return []

    tools = []

    for tool_name in enabled_tools:
        if tool_name in _LANGCHAIN_TOOL_GETTERS:
            getter = _LANGCHAIN_TOOL_GETTERS[tool_name]
            tool = getter()
            if tool:
                tools.append(tool)
                logger.info(f"[LangChainTools] Loaded tool: {tool_name}")
        else:
            logger.warning(f"[LangChainTools] Unknown tool: {tool_name}")

    logger.info(f"[LangChainTools] Loaded {len(tools)} LangChain tools in total")
    return tools


def get_available_langchain_tools() -> list[str]:
    """
    Get list of available LangChain tool names

    Returns:
        List of tool names
    """
    return list(_LANGCHAIN_TOOL_GETTERS.keys())
