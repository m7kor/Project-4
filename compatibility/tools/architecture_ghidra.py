"""Query an isolated COPY of the existing Ghidra project, without auto-analysis."""
from pathlib import Path
import asyncio,json,os,sys
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
ROOT=Path(__file__).resolve().parents[1]
async def main():
 out=ROOT/'artifacts/architecture'/('ghidra-01' if len(sys.argv)<2 else sys.argv[1]);assert out.parent==ROOT/'artifacts/architecture';out.mkdir(exist_ok=False);(out/'temp').mkdir()
 original=Path('C:/Project/PS2redmption');project=ROOT/'lab/ghidra-recovery-01'
 env=dict(os.environ,JAVA_HOME=str(original/'dependencies/tools/jdk21/jdk-21.0.12.1+1'),TEMP=str(out/'temp'),TMP=str(out/'temp'))
 env['JAVA_TOOL_OPTIONS']=f'-Dapplication.settingsdir={out.as_posix()}/settings -Dapplication.cachedir={out.as_posix()}/cache'
 server=StdioServerParameters(command=str(original/'dependencies/GhidraMCP/.venv/Scripts/ghidra-mcp.exe'),args=['--headless','--binary',str(project/'SLUS_211.34.elf'),'--project',str(project/'project'),'--project-name','re4','--no-analyze','--discard','--ghidra-install-dir',str(original/'dependencies/tools/ghidra/ghidra_12.1.4_PUBLIC'),'--language','r5900:LE:32:default','--ready-timeout','90'],env=env,cwd=str(project))
 with (out/'server.log').open('x',encoding='utf-8') as log:
  async with stdio_client(server,errlog=log) as streams:
   async with ClientSession(*streams) as session:
    await asyncio.wait_for(session.initialize(),90)
    listing=await session.list_tools();(out/'tools.json').write_text(json.dumps(listing.model_dump(mode='json'),indent=2));print('Ghidra tools',[x.name for x in listing.tools],flush=True)
    info=await asyncio.wait_for(session.call_tool('get_program_info',{}),120);(out/'program.json').write_text(json.dumps(info.model_dump(mode='json'),indent=2));print(str(info)[:2000],flush=True)
    if len(sys.argv)>2:
     queries=json.loads(Path(sys.argv[2]).read_text());allowed={'list_strings','search_functions_by_name','get_xrefs_to','get_xrefs_from','get_function_by_address','decompile_function_by_address','read_memory','get_function_calls','disassemble_function'}
     for i,q in enumerate(queries):
      assert q['tool'] in allowed,'Only read-only analysis tools allowed'
      result=await asyncio.wait_for(session.call_tool(q['tool'],q['arguments']),120);data=result.model_dump(mode='json');(out/f'query-{i:02}.json').write_text(json.dumps({'request':q,'response':data},indent=2));print('Query',i,q['tool'],str(data)[:4500],flush=True)
if __name__=='__main__':asyncio.run(main())
