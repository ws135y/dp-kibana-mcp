"""Verify that the Kibana MCP service starts and exposes its tools.

This test intentionally does not call Kibana, so KIBANA_SID is not required.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    project_dir = Path(__file__).resolve().parent
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-B", str(project_dir / "kibana_mcp_server.py")],
        cwd=project_dir,
        encoding="utf-8",
        encoding_error_handler="replace",
    )
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            server_info = await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            required = {"check_connection", "search_logs", "get_trace_logs", "get_log_context", "aggregate_logs", "analyze_latency"}
            assert required <= names, f"Missing MCP tools: {required - names}"
            print(f"MCP handshake: OK ({server_info.server_info.name})")
            print("Tool names:", ", ".join(tool.name for tool in tools.tools))


if __name__ == "__main__":
    asyncio.run(main())
