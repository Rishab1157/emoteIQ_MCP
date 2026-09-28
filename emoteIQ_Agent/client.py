import asyncio
import concurrent.futures
import json
import threading
import time
from typing import Any, Optional

from mcp.client import Client

MCP_URL = "http://127.0.0.1:8000/mcp"
CALL_TIMEOUT_S = 180


class McpBridge:
    """Keeps one MCP session open on a background event loop, so sync CrewAI tools can call it."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True, name="mcp-client")
        self.queue: Optional[asyncio.Queue] = None
        self.ready = concurrent.futures.Future()
        self.tool_names: list[str] = []

    def start(self) -> list[str]:
        if not self.thread.is_alive():
            self.thread.start()
            asyncio.run_coroutine_threadsafe(self._session(), self.loop)
        return self.ready.result(timeout=30)

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.start()
        result = concurrent.futures.Future()
        self.loop.call_soon_threadsafe(self.queue.put_nowait, (name, arguments, result))
        return result.result(timeout=CALL_TIMEOUT_S)

    def close(self) -> None:
        if self.queue is not None:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, None)

    async def _session(self) -> None:
        self.queue = asyncio.Queue()
        try:
            async with Client(self.url) as client:
                self.tool_names = [t.name for t in (await client.list_tools()).tools]
                self.ready.set_result(self.tool_names)
                while (item := await self.queue.get()) is not None:
                    name, arguments, result = item
                    try:
                        response = await client.call_tool(name, arguments, progress_callback=_print_progress)
                        text = response.content[0].text if response.content else ""
                        result.set_result({"error": text} if response.is_error else json.loads(text))
                    except Exception as error:
                        result.set_exception(error)
        except Exception as error:
            if not self.ready.done():
                self.ready.set_exception(error)
            raise


async def _print_progress(progress: float, total: Optional[float], message: Optional[str]) -> None:
    print(f"    [mcp progress] {message or ''} ({progress:.0f}/{total or 0:.0f})")


_bridge = McpBridge(MCP_URL)


def initialize(wait_s: float = 30) -> list[str]:
    """Connect to the MCP server, retrying while it is still starting up."""
    global _bridge
    deadline = time.monotonic() + wait_s
    while True:
        try:
            return _bridge.start()
        except Exception as error:
            if time.monotonic() >= deadline:
                raise ConnectionError(f"MCP server at {MCP_URL} is not reachable: {error}") from None
            print(f"    [mcp] server not ready yet, retrying ... ({type(error).__name__})")
            _bridge = McpBridge(MCP_URL)
            time.sleep(1)


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return _bridge.call(name, arguments)


def close() -> None:
    _bridge.close()
