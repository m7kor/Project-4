"""Read-only MCP startup/connection probe; no game memory or settings writes.

Run with dependencies/GhidraMCP/.venv/Scripts/python.exe.
Connection failure is recorded separately from successful MCP initialization.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
if __package__:
    from .pcsx2_probe_schema import connection_args
else:
    from pcsx2_probe_schema import connection_args


async def probe(out):
    root = Path(__file__).resolve().parents[2]
    config = json.loads((root / '.mcp.json').read_text())['mcpServers']['pcsx2']
    env = dict(os.environ, **config['env'])
    params = StdioServerParameters(command=config['command'], args=config['args'], env=env, cwd=str(root))
    with out.with_suffix('.stderr.log').open('x', encoding='utf-8') as log:
        async with stdio_client(params, errlog=log) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listing = await session.list_tools()
                tools = [tool.name for tool in listing.tools]
                if not {'pcsx2_connect', 'pcsx2_status'}.issubset(tools):
                    raise RuntimeError('Expected PCSX2 tools missing')
                spec = next(tool for tool in listing.tools if tool.name == 'pcsx2_connect')
                arguments = connection_args(spec.inputSchema)
                connect = await session.call_tool('pcsx2_connect', arguments)
                status = await session.call_tool('pcsx2_status', {})
                status_text = '\n'.join(getattr(item, 'text', '') for item in status.content)
                report = {'scope': __doc__, 'mcp_initialized': True, 'tools': tools,
                          'connection_arguments': arguments,
                          'connection_attempt_valid': not connect.isError,
                          'debugserver_connected': (not status.isError and
                                                    'DebugServer: ✅ connected' in status_text),
                          'connection': connect.model_dump(mode='json'),
                          'status': status.model_dump(mode='json'),
                          'full_game_lockstep_tested': False}
                if 'Pine IPC:    ✅ connected' in status_text and 'pcsx2_game_info' in tools:
                    game = await session.call_tool('pcsx2_game_info', {})
                    report['game_info'] = game.model_dump(mode='json')
                with out.open('x', encoding='utf-8') as output:
                    json.dump(report, output, indent=2, ensure_ascii=False)
                print(json.dumps({'mcp_initialized': True, 'tools': len(tools),
                                  'status': report['status']}))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Preserve existing evidence')
    asyncio.run(asyncio.wait_for(probe(args.out), timeout=40))


if __name__ == '__main__':
    main()
