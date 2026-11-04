"""Real stdio MCP client; records tools offered by the installed server."""
import asyncio
import json
import os
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    root=Path(__file__).resolve().parent
    env=dict(os.environ, MPLCONFIGDIR="/tmp/cmdresp-matplotlib")
    params=StdioServerParameters(command=sys.executable,
                                args=["-m","waveflow.mcp.server"],env=env)
    print("Opening Waveflow stdio MCP session",flush=True)
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as session:
            init=await session.initialize()
            print("Initialized MCP server",flush=True)
            offered=await session.list_tools()
            result=await session.call_tool("waveflow_get_components",{})
            report={"transport":"stdio","server":init.model_dump(mode="json"),
                    "tools":offered.model_dump(mode="json"),
                    "components":result.model_dump(mode="json"),
                    "limitation":"Installed revision has no frame-listing or local example/document retrieval tool. Reference files were read directly from the local clone; no MCP example retrieval is claimed."}
    (root/"evidence").mkdir(exist_ok=True)
    (root/"evidence/mcp_smoke.json").write_text(json.dumps(report,indent=2)+"\n")
    print("MCP stdio session succeeded; tools:",", ".join(t.name for t in offered.tools))
    print(report["limitation"])


if __name__=="__main__":
    asyncio.run(asyncio.wait_for(main(),timeout=25))
