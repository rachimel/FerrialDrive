"""Call the real upstream MCP server over MCP stdio (not a socket imitation)."""
import argparse
import asyncio
import datetime
import json
import os
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'output/blender_pipeline'

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--script', type=Path)
    parser.add_argument('--code')
    args = parser.parse_args()
    env = dict(os.environ)
    env.update(BLENDER_HOST='127.0.0.1', BLENDER_PORT='9876', DISABLE_TELEMETRY='true')
    params = StdioServerParameters(
        command=str(ROOT / '.venv-capability-test/Scripts/mcp-for-blender.exe'),
        args=[], env=env,
    )
    OUT.mkdir(parents=True, exist_ok=True)
    server_log = (OUT / 'mcp-server.log').open('a', encoding='utf-8')
    async with stdio_client(params, errlog=server_log) as (read, write):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            available = await session.list_tools()
            code = args.code
            if args.script:
                script = args.script.resolve()
                code = ('exec(compile(' + repr(script.read_text(encoding='utf-8')) + ', ' + repr(str(script))
                        + ", 'exec'), dict(globals(), __file__=" + repr(str(script)) + ", __name__='__main__'))")
            tool = 'execute_blender_code' if code else 'get_scene_info'
            arguments = {'code':code} if code else {}
            result = await session.call_tool(tool, arguments, read_timeout_seconds=datetime.timedelta(seconds=600))
            record = {
                'time':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'server':initialized.serverInfo.model_dump(),
                'available_tools':[t.name for t in available.tools],
                'tool':tool, 'script':str(args.script) if args.script else None,
                'result':result.model_dump(mode='json'),
            }
            OUT.mkdir(parents=True, exist_ok=True)
            with (OUT / 'mcp_calls.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + '\n')
            for content in result.content:
                if hasattr(content, 'text'):
                    print(content.text)
            if result.isError or any(getattr(c, 'text', '').startswith('Error') for c in result.content):
                sys.exit(1)

if __name__ == '__main__':
    asyncio.run(main())
