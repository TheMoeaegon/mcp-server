import logging
import os
import random
import sys

import requests
from fastmcp import FastMCP

name = "demo-mcp-server"
logging.basicConfig(
    level=logging.INFO,
    format="%(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(name)

port = int(os.environ.get("PORT", "8080"))
mcp = FastMCP(name)


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers"""
    logger.info(f"Tool called: add({a}, {b})")
    return a + b


@mcp.tool()
def get_secret_word() -> str:
    """Get a random secret word"""
    logger.info("Tool called: get_secret_word()")
    return random.choice(["apple", "banana", "cherry"])


@mcp.tool()
def get_current_weather(city: str) -> str:
    """Get current weather for a city"""
    logger.info(f"Tool called: get_current_weather({city})")

    try:
        endpoint = "https://wttr.in"
        response = requests.get(f"{endpoint}/{city}", timeout=10)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        logger.error(f"Error fetching weather data: {e}")
        return f"Error fetching weather data: {e}"


if __name__ == "__main__":
    logger.info(f"Starting MCP server on port {port}....")
    try:
        mcp.run(transport="sse", port=port)
    except Exception as e:  # noqa: BLE001
        logger.error(f"Server error: {e}")
        sys.exit(1)
    finally:
        logger.info("Server terminated")
