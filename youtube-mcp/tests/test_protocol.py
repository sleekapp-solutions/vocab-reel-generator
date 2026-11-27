import asyncio
import json
import os
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from youtube_channel_mcp.server import create_server


def test_stdio_discovery_and_safe_call(tmp_path):
    async def check():
        env = dict(os.environ, YOUTUBE_MCP_TOKEN=str(tmp_path / "missing.json"), YOUTUBE_MCP_ENABLE_WRITES="0")
        params = StdioServerParameters(command=sys.executable, args=["-m", "youtube_channel_mcp.server"], env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                names = {tool.name for tool in listed.tools}
                assert len(names) == 10
                assert "schedule_private_video" not in names
                assert all(tool.annotations.readOnlyHint for tool in listed.tools)
                status = await session.call_tool("connection_status", {})
                assert not status.isError
                payload = status.structuredContent or json.loads(status.content[0].text)
                assert payload["live_connection_verified"] is False
                missing = await session.call_tool("authorized_channel", {})
                assert missing.isError
                assert "OAuth is not connected" in missing.content[0].text
                prompts = await session.list_prompts()
                assert prompts.prompts[0].name == "channel_review"
    asyncio.run(check())


def test_write_tools_require_environment_gate(monkeypatch):
    async def check():
        monkeypatch.setenv("YOUTUBE_MCP_ENABLE_WRITES", "1")
        tools = await create_server().list_tools()
        schedule = next(tool for tool in tools if tool.name == "schedule_private_video")
        assert schedule.annotations.readOnlyHint is False
        assert schedule.inputSchema["properties"]["confirm"]["default"] is False
    asyncio.run(check())
