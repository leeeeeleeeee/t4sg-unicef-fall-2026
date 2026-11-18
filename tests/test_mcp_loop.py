"""Smoke test for pipeline/mcp_test.py: real Data Commons MCP server, scripted fake model (no API keys needed).

Run:  python tests/test_mcp_loop.py
The fake model asks for Chad's DTP3 data with get_observations, then answers. Checks the tool loop, the
transcript bookkeeping and the 'used the tool's number' matcher. With DC_API_KEY in .env it also checks
that real data comes back.
"""
import asyncio
import json
import os
import sys
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipeline"))
import litellm  # noqa: E402

import mcp_test  # noqa: E402


def fake_response(content=None, tool_calls=None):
    msg = NS(content=content, tool_calls=tool_calls,
             model_dump=lambda: {"role": "assistant", "content": content,
                                 "tool_calls": [{"id": t.id, "type": "function",
                                                 "function": {"name": t.function.name,
                                                              "arguments": t.function.arguments}}
                                                for t in (tool_calls or [])]})
    return NS(choices=[NS(message=msg)], usage=NS(prompt_tokens=100, completion_tokens=20))


async def main():
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    mcp_test.load_dotenv_if_present()  # uses DC_API_KEY if .env has it; without it the tool returns an error
    script = [
        fake_response(tool_calls=[NS(id="c1", function=NS(name="get_observations", arguments=json.dumps(
            {"variable_dcid": "sdg/SH_ACS_DTP3", "place_dcid": "country/TCD"})))]),
        fake_response(content="Chad's DTP3 coverage was 67% in 2023 (WHO/UNICEF estimates)."),
    ]
    seen = []

    async def fake_acompletion(**kw):
        seen.append(kw)
        return script[len(seen) - 1]

    litellm.acompletion = fake_acompletion
    async with stdio_client(mcp_test.server_params()) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = mcp_test.to_openai_tools((await s.list_tools()).tools, with_bridge=False)
            out = await mcp_test.ask("fake/model", "Chad DTP3 2023?", s, tools)

    assert out["answer"].startswith("Chad's DTP3"), out
    assert [c["tool"] for c in out["calls"]] == ["get_observations"], out["calls"]
    if os.getenv("DC_API_KEY"):
        assert out["tool_numbers"], f"real key set but no data came back: {out['calls'][0]['result_preview'][:200]}"
    assert out["input_tokens"] == 200 and len(seen) == 2
    assert any(m.get("role") == "tool" for m in seen[1]["messages"]), "tool result not sent back to the model"
    assert all("parameters" in t["function"] for t in tools)
    assert mcp_test.matches(67, [66.9]) and mcp_test.matches(67, [0.67]) and not mcp_test.matches(67, [71])
    print("PASS mcp tool loop (real MCP server, fake model)")


if __name__ == "__main__":
    asyncio.run(main())
