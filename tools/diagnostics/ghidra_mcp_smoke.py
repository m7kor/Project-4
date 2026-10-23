"""Check the installed GhidraMCP on a synthetic PS2 ELF in an isolated project.

Run with dependencies/GhidraMCP/.venv/Scripts/python.exe; no game project is opened.
"""
import asyncio
import json
import os
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    root = Path(__file__).resolve().parents[2]
    output = root / 'artifacts/tool-audit/20261012'
    output.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment['JAVA_HOME'] = str(root / 'dependencies/tools/jdk21/jdk-21.0.12.1+1')
    environment['JAVA_TOOL_OPTIONS'] = (
        f'-Dapplication.settingsdir={output.as_posix()}/mcp-settings '
        f'-Dapplication.cachedir={output.as_posix()}/mcp-cache')
    server = StdioServerParameters(
        command=str(root / 'dependencies/GhidraMCP/.venv/Scripts/ghidra-mcp.exe'),
        args=['--headless', '--binary', str(root / 'artifacts/canary/canary.elf'),
              '--project', str(output / 'mcp-project'), '--project-name', 'smoke',
              '--ghidra-install-dir', str(root / 'dependencies/tools/ghidra/ghidra_12.1.4_PUBLIC'),
              '--language', 'r5900:LE:32:default', '--discard', '--ready-timeout', '90'],
        env=environment, cwd=str(root))
    with (output / 'ghidra-mcp-server.log').open('w', encoding='utf-8') as log:
        async with stdio_client(server, errlog=log) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listing = await session.list_tools()
                result = await session.call_tool('get_program_info', {})
                report = {'tools': [tool.name for tool in listing.tools],
                          'program_info': result.model_dump(mode='json')}
                text = json.dumps(report, indent=2)
                (output / 'ghidra-mcp-smoke.json').write_text(text + '\n', encoding='utf-8')
                info = result.structuredContent or {}
                if result.isError or info.get('name') != 'canary.elf' or info.get('language_id') != 'r5900:LE:32:default':
                    raise RuntimeError(text)
                print(text)


if __name__ == '__main__':
    asyncio.run(asyncio.wait_for(main(), timeout=120))
