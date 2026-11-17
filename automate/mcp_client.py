"""로컬 DCC 서버의 공개 MCP 도구를 조회하거나 한 번 호출한다."""
import argparse
import asyncio
from datetime import timedelta
import json
from pathlib import Path
import sys
import site
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "automate/runtime/client/python"))
site.addsitedir(str(ROOT / "automate/runtime/client/python"))


async def execute(args):
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    parsed = urlparse(args.url)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost") or parsed.username:
        raise ValueError("현재 작업의 로컬 MCP 서버만 사용한다.")
    async with httpx.AsyncClient(timeout=httpx.Timeout(args.timeout, connect=10)) as client:
        async with streamable_http_client(args.url, http_client=client) as (read, write, _):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=args.timeout)) as session:
                initialized = await session.initialize()
                if args.action == "tools":
                    result = await session.list_tools()
                    all_tools = list(result.tools)
                    while result.nextCursor:
                        result = await session.list_tools(cursor=result.nextCursor)
                        all_tools.extend(result.tools)
                    result = result.model_copy(update={"tools": all_tools, "nextCursor": None})
                else:
                    request = json.loads(args.request.read_text(encoding="utf-8-sig"))
                    result = await session.call_tool(args.tool, request, read_timeout_seconds=timedelta(seconds=args.timeout))
                data = {"server": initialized.serverInfo.model_dump(mode="json"), "result": result.model_dump(mode="json")}
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                if args.action == "tools":
                    print(json.dumps({"server": data["server"], "tools": [{"name": tool.name, "description": tool.description} for tool in result.tools]}, ensure_ascii=False))
                else:
                    print(json.dumps({"server": data["server"], "is_error": getattr(result, "isError", None), "output": str(args.output), "content_types": [item.type for item in result.content]}, ensure_ascii=False))
    return bool(getattr(result, "isError", False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["tools", "call"])
    parser.add_argument("--url", help="생략하면 automate/workspace/unreal/mcp_ready.json을 읽는다.")
    parser.add_argument("--tool")
    parser.add_argument("--request", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=90)
    args = parser.parse_args()
    if not args.url:
        ready = ROOT / "automate/workspace/unreal/mcp_ready.json"
        if not ready.is_file():
            parser.error("Unreal 연결 정보가 없다. 실행 중인 서버의 --url을 지정한다.")
        args.url = json.loads(ready.read_text(encoding="utf-8-sig"))["mcp_url"]
    if args.action == "call" and (not args.tool or not args.request):
        parser.error("call에는 --tool과 --request가 필요하다.")
    if args.output.exists():
        raise FileExistsError("호출 결과가 이미 있다. 실행 상태를 확인한다: " + str(args.output))
    if asyncio.run(execute(args)):
        parser.exit(1, "MCP 호출이 실패했다. 저장된 결과와 실제 상태를 먼저 확인한다.\n")


if __name__ == "__main__":
    main()
