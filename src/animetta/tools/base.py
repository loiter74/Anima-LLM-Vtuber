"""
Anima tool base classes and tool registry
"""

from typing import Any

from langchain_core.core.tools import tool
from loguru import logger


@tool
async def web_search(query: str, num_results: int = 5) -> str:
    """Search the Internet for real-time information"""
    import os

    import httpx

    tavily_api_key = os.getenv("TAVILY_API_KEY")
    if tavily_api_key:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": tavily_api_key,
                        "query": query,
                        "max_results": min(num_results, 10),
                        "search_depth": "basic",
                    },
                    headers={"Content-Type": "application/json"},
                )
                if response.status_code == 200:
                    data = response.json()
                    results = data.get("results", [])
                    if results:
                        formatted = f"Search results for '{query}':\n\n"
                        for i, r in enumerate(results[:num_results], 1):
                            title = r.get("title", "N/A")
                            url = r.get("url", "")
                            snippet = r.get("content", "")[:150]
                            formatted += f"{i}. {title}\n{snippet}...\nURL: {url}\n\n"
                        logger.info("[web_search] Tavily success")
                        return formatted
        except Exception as e:
            logger.warning(f"[web_search] Tavily failed: {e}")

    # DuckDuckGo fallback
    try:
        from langchain_community.core.tools import DuckDuckGoSearchRun
        search = DuckDuckGoSearchRun()
        import asyncio
        loop = asyncio.get_event_loop()
        results_text = await loop.run_in_executor(None, search.run, query)
        return f"Search results (DuckDuckGo) for '{query}':\n\n{results_text}"
    except Exception as e:
        logger.warning(f"[web_search] DuckDuckGo failed: {e}")

    return "Search service unavailable. Please set TAVILY_API_KEY environment variable."


@tool
async def get_weather(city: str) -> str:
    """Get current weather for a specified city"""
    import os

    import httpx

    amap_api_key = os.getenv("AMAP_API_KEY")
    if amap_api_key:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                geo_url = "https://restapi.amap.com/v3/geocode/geo"
                geo_response = await client.get(geo_url, params={"key": amap_api_key, "address": city})
                geo_data = geo_response.json()
                if geo_data.get("status") == "1" and geo_data.get("geocodes"):
                    adcode = geo_data["geocodes"][0].get("adcode")
                    if adcode:
                        weather_url = "https://restapi.amap.com/v3/weather/weatherInfo"
                        weather_response = await client.get(weather_url, params={"key": amap_api_key, "city": adcode, "extensions": "base"})
                        weather_data = weather_response.json()
                        if weather_data.get("status") == "1" and weather_data.get("lives"):
                            live = weather_data["lives"][0]
                            result = f"Weather for {live.get('province', '')}{live.get('city', '')}: "
                            result += f"{live.get('weather', '')}, {live.get('temperature', '')}C"
                            return result
        except Exception as e:
            logger.warning(f"[get_weather] Amap failed: {e}")

    # Mock data fallback
    mock = {"Beijing": "Sunny, 15-25C", "Shanghai": "Cloudy, 18-26C", "Guangzhou": "Rain, 22-30C"}
    return mock.get(city, f"Weather data unavailable for {city}")


@tool
async def get_current_time(timezone: str = "Asia/Shanghai") -> str:
    """Get the current time"""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    try:
        tz = ZoneInfo(timezone)
        now = datetime.now(tz)
        return f"Current time ({timezone}): {now.strftime('%Y-%m-%d %H:%M:%S')}"
    except Exception:
        return f"Current local time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"


@tool
async def calculator(expression: str) -> str:
    """Execute mathematical calculations"""
    try:
        import ast
        import operator as op
        operators = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv, ast.Pow: op.pow, ast.USub: op.neg}
        def eval_node(n):
            if isinstance(n, ast.Constant):
                return n.value
            elif isinstance(n, ast.BinOp):
                return operators[type(n.op)](eval_node(n.left), eval_node(n.right))
            elif isinstance(n, ast.UnaryOp):
                return operators[type(n.op)](eval_node(n.operand))
            elif isinstance(n, ast.Expression):
                return eval_node(n.body)
            else:
                raise TypeError(f"Unsupported: {type(n)}")
        tree = ast.parse(expression, mode='eval')
        result = eval_node(tree)
        return f"Result: {expression} = {result}"
    except Exception as e:
        return f"Calculation failed: {str(e)}"


# Tool list
_BUILTIN_TOOLS = [web_search, get_weather, get_current_time, calculator]


def get_builtin_tools() -> list[Any]:
    return _BUILTIN_TOOLS.copy()


def get_tools_map(tools: list[Any] | None = None) -> dict[str, Any]:
    if tools is None:
        tools = _BUILTIN_TOOLS
    return {tool.name: tool for tool in tools}


def create_tool_registry(builtin_enabled: list[str] | None = None, extra_tools: list[Any] | None = None) -> tuple:
    tools = []
    if builtin_enabled is None:
        tools.extend(_BUILTIN_TOOLS)
    else:
        tools_map = get_tools_map(_BUILTIN_TOOLS)
        for name in builtin_enabled:
            if name in tools_map:
                tools.append(tools_map[name])
    if extra_tools:
        tools.extend(extra_tools)
    tools_map = get_tools_map(tools)
    logger.info(f"[Tool Registry] Registered {len(tools)} tools: {list(tools_map.keys())}")
    return tools, tools_map


def load_tools_from_config(config: dict[str, Any]) -> tuple:
    builtin_enabled = config.get("builtin_tools")
    extra_tools = []

    # LangChain tools
    lc_config = config.get("langchain_tools", {})
    if lc_config:
        try:
            from .langchain_tools import load_langchain_tools
            lc_tools = load_langchain_tools(lc_config.get("enabled", []))
            extra_tools.extend(lc_tools)
        except Exception as e:
            logger.error(f"[LangChain Tools] Failed: {e}")

    # Custom tools
    custom_config = config.get("custom_tools", {})
    if custom_config:
        try:
            from .custom_tools import get_custom_tools
            enabled_custom = custom_config.get("enabled", [])
            if enabled_custom:
                all_custom = get_custom_tools()
                custom_tools_map = {tool.name: tool for tool in all_custom}
                for name in enabled_custom:
                    if name in custom_tools_map:
                        extra_tools.append(custom_tools_map[name])
                        logger.info(f"[Custom Tools] Loaded tool: {name}")
                    else:
                        logger.warning(f"[Custom Tools] Tool not found: {name}")
        except Exception as e:
            logger.error(f"[Custom Tools] Failed: {e}")

    # Minecraft tools (requires Node.js subprocess)
    minecraft_config = config.get("minecraft", {})
    if minecraft_config.get("enabled", False):
        try:
            from .minecraft.core.tools import get_minecraft_tools, init_bridge
            init_bridge(minecraft_config)
            mc_tools = get_minecraft_tools()
            extra_tools.extend(mc_tools)
            logger.info(f"[Minecraft Tools] Loaded {len(mc_tools)} tools: {[t.name for t in mc_tools]}")
        except Exception as e:
            logger.error(f"[Minecraft Tools] Failed to load: {e}")

    return create_tool_registry(builtin_enabled=builtin_enabled, extra_tools=extra_tools)
