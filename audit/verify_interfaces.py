"""Real stdio MCP handshake and loopback HTTP acceptance; read-only runtime calls."""
import asyncio
import json
import os
from pathlib import Path
import sys
from urllib.request import urlopen
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]

async def main():
    server = StdioServerParameters(command=sys.executable,
                                  args=['-m', 'job_machine.ops.mcp_server'], cwd=str(ROOT),
                                  env={'PROGRAMDATA':os.environ['PROGRAMDATA']})
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            names = sorted(tool.name for tool in (await session.list_tools()).tools)
            assert names == ['runtime_data', 'runtime_health', 'runtime_logs', 'runtime_service', 'runtime_status']
            status = await session.call_tool('runtime_status', {})
            assert not status.isError, str(status.content)
            # FastMCP returns typed list structured content under result.
            assert len(status.structuredContent['result']) == 8
    with urlopen('http://127.0.0.1:18766/', timeout=120) as response:
        page = response.read().decode('utf-8')
        assert response.status == 200
        assert 'lab-do' in page and 'greenhouse-runtime-job-submit-1' in page
        assert 'confirmed: 1' in page and 'unknown: 36' in page
    report = {'mcp_tools':names, 'live_services_via_mcp':8, 'http_status':200,
              'dashboard_url':'http://127.0.0.1:18766/', 'mutations_performed':False}
    (ROOT / 'audit/baseline/interfaces.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))

if __name__ == '__main__':
    asyncio.run(main())
