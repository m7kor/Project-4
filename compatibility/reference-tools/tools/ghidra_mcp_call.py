"""Call GhidraMCP tools from the command line (HTTP transport).

Start the server once (headless, keeps the analysed RE4 project loaded):
    ghidra-mcp --headless --binary artifacts/ghidra/SLUS_211.34.elf --project artifacts/ghidra
               --project-name re4 --save --transport streamable-http --mcp-port 8091
Then:
    dependencies/GhidraMCP/.venv/Scripts/python tools/ghidra_mcp_call.py --list
    ... tools/ghidra_mcp_call.py decompile_function_by_address address=0x2cf190
Arguments are key=value; values that parse as JSON (numbers, lists) are sent as such.
"""
import argparse
import asyncio
import json
import math
import multiprocessing

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def run(url, tool, arguments, list_only):
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            if list_only:
                for t in (await session.list_tools()).tools:
                    print(f'{t.name}: {(t.description or "").splitlines()[0] if t.description else ""}')
                return
            result = await session.call_tool(tool, arguments)
            for item in result.content:
                print(getattr(item, 'text', item))


def call_worker(url, tool, arguments, list_only):
    asyncio.run(run(url, tool, arguments, list_only))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('tool', nargs='?')
    parser.add_argument('args', nargs='*')
    parser.add_argument('--url', default='http://127.0.0.1:8091/mcp')
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--timeout', type=float, default=120,
                        help='Maximum time for connection, initialization and tool call together')
    a = parser.parse_args()
    if not math.isfinite(a.timeout) or a.timeout <= 0:
        parser.error('Timeout must be finite and positive')
    if not a.list and not a.tool:
        parser.error('Choose a tool or --list')
    arguments = {}
    for item in a.args:
        key, _, value = item.partition('=')
        try:
            arguments[key] = json.loads(value)
        except ValueError:
            arguments[key] = value
    # MCP transport cleanup can shield cancellation while a connection is
    # blocked. Bound the entire worker lifetime instead of only its coroutine.
    worker = multiprocessing.get_context('spawn').Process(
        target=call_worker, args=(a.url, a.tool, arguments, a.list))
    worker.start()
    worker.join(a.timeout)
    if worker.is_alive():
        worker.terminate()
        worker.join()
        parser.exit(1, f'Ghidra MCP did not complete within {a.timeout:g} seconds: {a.url}\n')
    if worker.exitcode:
        parser.exit(1, 'Ghidra MCP request failed; see the worker diagnostics above.\n')


if __name__ == '__main__':
    main()
