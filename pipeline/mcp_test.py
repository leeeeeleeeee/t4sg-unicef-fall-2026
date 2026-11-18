"""MCP test: the same prompts on one free model, with and without the Data Commons MCP server.

Usage:
    python pipeline/mcp_test.py --list-tools                 # check the MCP server starts (no LLM call)
    python pipeline/mcp_test.py --limit 5                    # always try 5 prompts first
    python pipeline/mcp_test.py                              # the full 10-prompt test
    python pipeline/mcp_test.py --model gemini/gemini-3.1-flash-lite --ids N1 P2 T3-1

For every prompt it runs two conditions:
    cold  the bare question, no tools
    mcp   the same question, with the Data Commons MCP tools (search_indicators, get_observations, ...)
and records, besides the usual scores: did the model call a tool, which ones, did the number in its answer
come from a tool result, did the tool even return the right number, tokens, cost and time.

Outputs:
    results/mcp_test/results.csv        shared results columns (mode = cold / mcp), scored by scorer.py
    results/mcp_test/mcp_details.csv    tool-use columns per answer
    results/mcp_test/transcripts.jsonl  every message and tool result, for checking by hand
    reports/mcp_test_summary.md         the comparison table

Needs in .env:  DC_API_KEY (free: https://apikeys.datacommons.org)
                GEMINI_API_KEY (or OPENROUTER_API_KEY for openrouter/ models)
The server is the `datacommons-mcp` package (pip install datacommons-mcp), the Data Commons MCP server
from our Week 1 research. To point it at a custom Data Commons (e.g. the UN's), set DC_AGENT_API_ROOT.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re

import sys
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    RESULTS_COLUMNS, ROOT, SCORER_EXTRA_COLUMNS, load_answer_key, load_dotenv_if_present, load_prompts, to_float,
)
from scorer import close_tolerance, score_row  # noqa: E402

TS = os.path.join(ROOT, "data", "test_set")
OUT_DIR = os.path.join(ROOT, "results", "mcp_test")
# Free and supports tool calling (checked 17 Nov 2026; gemini-2.5-flash is retired for new keys).
DEFAULT_MODEL = "gemini/gemini-3.5-flash-lite"
# 10 prompts with a clean, verified official value, covering all topics, user types and a leading question
DEFAULT_IDS = ["N1", "R1", "P1", "T1-5", "P2", "N5", "T2-1", "T2-3", "T3-1", "T3-2"]
NUDGE = ("You can call Data Commons tools to look up official statistics. Use them when the question asks "
         "for a statistic, and say which source and year your figure comes from.")
MAX_TOOL_TURNS = 8
TOOL_RESULT_CHARS = 8000


# ------------------------------------------------------------------ MCP server --
def server_params():
    from mcp import StdioServerParameters
    # Start through the Python interpreter rather than the datacommons-mcp.exe launcher: Windows Smart App
    # Control can block freshly installed .exe launchers, while python.exe is already trusted.
    cmd, args = sys.executable, ["-c", "from datacommons_mcp.cli import cli; cli()", "serve", "stdio"]
    if not os.getenv("DC_API_KEY"):
        args.append("--skip-api-key-validation")
    return StdioServerParameters(command=cmd, args=args, env={**os.environ})


def clean_schema(s):
    """Make an MCP JSON schema acceptable to Gemini/OpenAI function calling."""
    if isinstance(s, dict):
        s = {k: v for k, v in s.items() if k not in ("$schema", "additionalProperties", "title", "default")}
        for key in ("anyOf", "oneOf"):
            if key in s:  # Optional[X] -> X
                opts = [o for o in s.pop(key) if o.get("type") != "null"]
                if opts:
                    s.update(clean_schema(opts[0]))
        return {k: clean_schema(v) for k, v in s.items()}
    if isinstance(s, list):
        return [clean_schema(x) for x in s]
    return s


RESOURCE_TOOL = "read_mcp_resource"


def to_openai_tools(tools, with_bridge: bool = True) -> list[dict]:
    out = [{"type": "function", "function": {
        "name": t.name, "description": (t.description or "")[:1024],
        "parameters": clean_schema(t.inputSchema or {"type": "object", "properties": {}})}} for t in tools]
    if not with_bridge:
        return out
    # Newer Data Commons servers tell the model to read 'skill://...' playbook resources first. Plain function
    # calling has no way to read MCP resources, so we expose one bridge tool for it.
    out.append({"type": "function", "function": {
        "name": RESOURCE_TOOL,
        "description": "Read an MCP resource by URI (e.g. 'skill://data-commons-researcher/SKILL.md'), "
                       "as the Data Commons tool descriptions instruct.",
        "parameters": {"type": "object", "properties": {"uri": {"type": "string"}}, "required": ["uri"]}}})
    return out


async def call_mcp(session, name: str, args: dict) -> tuple[str, list[float], bool]:
    """Run one tool call; returns (text, numbers found, is_error)."""
    if name == RESOURCE_TOOL:
        res = await session.read_resource(args.get("uri", ""))
        return "\n".join(getattr(c, "text", "") or "" for c in res.contents), [], False
    res = await session.call_tool(name, args)
    text = "\n".join(getattr(c, "text", "") for c in res.content)
    nums = numbers_in(res.structuredContent) if getattr(res, "structuredContent", None) else []
    return text, nums + numbers_in(text), bool(res.isError)


def numbers_in(obj) -> list[float]:
    """Every number in a tool result (JSON or text)."""
    out = []
    if isinstance(obj, (int, float)) and not isinstance(obj, bool):
        out.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            out += numbers_in(v)
    elif isinstance(obj, list):
        for v in obj:
            out += numbers_in(v)
    elif isinstance(obj, str):
        try:
            out += numbers_in(json.loads(obj))
        except (ValueError, TypeError):
            out += [float(x) for x in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?", obj)]
    return out


def matches(value: float, candidates: list[float]) -> bool:
    """Answer value equals a tool number, allowing for rounding (and fraction/percent)."""
    for c in candidates:
        for cc in (c, c * 100):
            if abs(cc - value) <= max(0.051, abs(cc) * 0.005) or round(cc) == value or round(cc, 1) == value:
                return True
    return False


# -------------------------------------------------------------------- one run --
async def ask(model: str, prompt: str, session=None, tools=None, nudge=False) -> dict:
    import litellm
    litellm.suppress_debug_info = True
    litellm.drop_params = True  # some models (e.g. Gemini 3.x) reject settings like temperature
    msgs =([{"role": "system", "content": NUDGE}] if (tools and nudge) else []) + [{"role": "user", "content": prompt}]
    calls, tool_nums, in_tok, out_tok, cost, err = [], [], 0, 0, 0.0, ""
    t0 = time.time()
    for _turn in range(MAX_TOOL_TURNS + 1):
        kwargs = dict(model=model, messages=msgs, temperature=0)
        if tools:
            kwargs["tools"] = tools
        for attempt in range(4):  # free tiers allow only a few requests per minute: wait and retry
            try:
                resp = await litellm.acompletion(**kwargs)
                break
            except litellm.RateLimitError:
                if attempt == 3:
                    raise
                await asyncio.sleep(20 * (attempt + 1))
        u = getattr(resp, "usage", None)
        in_tok += getattr(u, "prompt_tokens", 0) or 0
        out_tok += getattr(u, "completion_tokens", 0) or 0
        try:
            cost += litellm.completion_cost(completion_response=resp) or 0.0
        except Exception:
            pass
        msg = resp.choices[0].message
        tcs = getattr(msg, "tool_calls", None) or []
        if not tcs or session is None:
            return {"answer": msg.content or "", "calls": calls, "tool_numbers": tool_nums, "input_tokens": in_tok,
                    "output_tokens": out_tok, "cost": cost, "seconds": time.time() - t0, "error": err,
                    "messages": msgs + [{"role": "assistant", "content": msg.content}]}
        msgs.append(msg.model_dump() if hasattr(msg, "model_dump") else dict(msg))
        for tc in tcs:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except ValueError:
                args = {}
            try:
                text, nums, is_err = await call_mcp(session, name, args)
                tool_nums += nums
                if is_err:
                    err = f"{name}: {text[:200]}"
            except Exception as e:  # keep going so one bad call doesn't sink the run
                text, err = f"Tool error: {e}", f"{name}: {e}"
            calls.append({"tool": name, "args": args, "result_preview": text[:500]})
            msgs.append({"role": "tool", "tool_call_id": tc.id, "name": name, "content": text[:TOOL_RESULT_CHARS]})
    return {"answer": "", "calls": calls, "tool_numbers": tool_nums, "input_tokens": in_tok, "output_tokens": out_tok,
            "cost": cost, "seconds": time.time() - t0, "error": "hit max tool turns", "messages": msgs}


async def run(args) -> None:
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    prompts = load_prompts(args.prompts)
    key = load_answer_key(args.answer_key)
    ids = (args.ids or DEFAULT_IDS)[: args.limit or None]
    missing = [i for i in ids if i not in prompts]
    if missing:
        sys.exit(f"prompt ids not found: {missing}")

    async with stdio_client(server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            mcp_tools = (await session.list_tools()).tools
            try:
                has_resources = bool((await session.list_resources()).resources)
            except Exception:
                has_resources = False
            tools = to_openai_tools(mcp_tools, with_bridge=has_resources)
            print(f"MCP server up: {len(mcp_tools)} tools ({', '.join(t.name for t in mcp_tools)})"
                  + (f" + {RESOURCE_TOOL} bridge" if has_resources else ""))
            if args.list_tools:
                try:
                    resources = (await session.list_resources()).resources
                    print("resources:", ", ".join(str(r.uri) for r in resources) or "none")
                    tmpl = (await session.list_resource_templates()).resourceTemplates
                    print("resource templates:", ", ".join(str(r.uriTemplate) for r in tmpl) or "none")
                    txt, _, _ = await call_mcp(session, RESOURCE_TOOL, {"uri": "skill://data-commons-researcher/SKILL.md"})
                    print(f"read skill://data-commons-researcher/SKILL.md OK ({len(txt)} chars)")
                except Exception as e:
                    print("resource check failed:", e)
                for t in mcp_tools:
                    print(f"\n## {t.name}\n{(t.description or '').strip()[:400]}\nparams: "
                          f"{list((t.inputSchema or {}).get('properties', {}).keys())}")
                if not os.getenv("DC_API_KEY"):
                    print("\nNOTE: DC_API_KEY is not set, so tools will fail when called. Get a free key at "
                          "https://apikeys.datacommons.org and add it to .env")
                return
            if not os.getenv("DC_API_KEY"):
                sys.exit("DC_API_KEY is not set (free key: https://apikeys.datacommons.org). Add it to .env.")

            os.makedirs(OUT_DIR, exist_ok=True)
            rows, details, spent = [], [], 0.0
            tx = open(os.path.join(OUT_DIR, "transcripts.jsonl"), "w", encoding="utf-8")
            for pid in ids:
                p, k = prompts[pid], key.get(pid, {})
                for mode in ("cold", "mcp"):
                    if spent >= args.max_cost:
                        print(f"budget cap ${args.max_cost} reached; stopping")
                        break
                    try:
                        r = await ask(args.model, p["prompt"], session if mode == "mcp" else None,
                                      tools if mode == "mcp" else None, nudge=args.nudge)
                    except Exception as e:
                        r = {"answer": "", "calls": [], "tool_numbers": [], "input_tokens": 0, "output_tokens": 0,
                             "cost": 0.0, "seconds": 0.0, "error": str(e)[:300], "messages": []}
                    spent += r["cost"]
                    row = {c: "" for c in RESULTS_COLUMNS}
                    row.update({"id": pid, "model": args.model, "mode": mode, "thinking": "N", "web_search": "N",
                                "repeat": "1", "answer": r["answer"], "searched": "N",
                                "input_tokens": str(r["input_tokens"]), "output_tokens": str(r["output_tokens"]),
                                "cost": f"{r['cost']:.6f}", "seconds": f"{r['seconds']:.1f}"})
                    row = score_row(row, p, k)
                    val = to_float(row.get("number_value"))
                    official = to_float(k.get("unicef_value"))
                    called = bool(r["calls"])
                    used = ("NA" if not called else ("Y" if val is not None and matches(val, r["tool_numbers"]) else "N"))
                    tool_right = ("NA" if not called else (
                        "Y" if official is not None and any(abs(x - official) <= close_tolerance(official, k.get("unit", ""))
                                                            for x in r["tool_numbers"]) else "N"))
                    details.append({"id": pid, "model": args.model, "mode": mode, "called_tool": "Y" if called else "N",
                                    "n_tool_calls": len(r["calls"]),
                                    "tools_called": "; ".join(c["tool"] for c in r["calls"]),
                                    "used_tool_number": used, "tool_returned_official_value": tool_right,
                                    "number_score": row["number_score"], "number_value": row["number_value"],
                                    "official_value": row["official_value"], "error": r["error"]})
                    rows.append(row)
                    tx.write(json.dumps({"id": pid, "mode": mode, "calls": r["calls"], "answer": r["answer"],
                                         "error": r["error"]}, default=str) + "\n")
                    print(f"{pid:6} {mode:4} tool={details[-1]['called_tool']} used={used:2} "
                          f"score={row['number_score'] or '-':9} value={row['number_value'] or '-':>7} "
                          f"official={row['official_value']:>7} ${r['cost']:.4f} {r['seconds']:.0f}s "
                          + (f"ERR {r['error'][:60]}" if r["error"] else ""))
                    await asyncio.sleep(args.sleep)
            tx.close()

    res = pd.DataFrame(rows)[RESULTS_COLUMNS + SCORER_EXTRA_COLUMNS]
    det = pd.DataFrame(details)
    res.to_csv(os.path.join(OUT_DIR, "results.csv"), index=False)
    det.to_csv(os.path.join(OUT_DIR, "mcp_details.csv"), index=False)
    write_summary(res, det, args)


def write_summary(res: pd.DataFrame, det: pd.DataFrame, args) -> None:
    lines = ["# MCP test: with vs without the Data Commons MCP server", "",
             f"Model: `{args.model}`. Prompts: {det['id'].nunique()}. Nudge system prompt: {'on' if args.nudge else 'off'}.",
             "", "| | cold (no tools) | mcp (Data Commons tools) |", "|---|---|---|"]

    def by(mode, f):
        d, r = det[det["mode"] == mode], res[res["mode"] == mode]
        return f(d, r) if len(d) else "-"

    def pct(n, d):
        return f"{n}/{d} ({n / d:.0%})" if d else "-"

    metrics = [
        ("Correct", lambda d, r: pct(int((r.number_score == "Correct").sum()), len(r))),
        ("Correct or Close", lambda d, r: pct(int(r.number_score.isin(["Correct", "Close"]).sum()), len(r))),
        ("Wrong", lambda d, r: pct(int((r.number_score == "Wrong").sum()), len(r))),
        ("No number", lambda d, r: pct(int((r.number_score == "No number").sum()), len(r))),
        ("Latest year given", lambda d, r: pct(int((r.year_score == "Latest").sum()), len(r))),
        ("Primary source", lambda d, r: pct(int((r.source_score == "Primary").sum()), len(r))),
        ("Called a tool", lambda d, r: pct(int((d.called_tool == "Y").sum()), len(d))),
        ("Used the tool's number (of answers that called a tool)",
         lambda d, r: pct(int((d.used_tool_number == "Y").sum()), int((d.called_tool == "Y").sum()))),
        ("Tool returned a value within the Close cutoff of UNICEF's",
         lambda d, r: pct(int((d.tool_returned_official_value == "Y").sum()), int((d.called_tool == "Y").sum()))),
        ("Avg tool calls", lambda d, r: f"{d.n_tool_calls.mean():.1f}"),
        ("Input tokens (total)", lambda d, r: f"{pd.to_numeric(r.input_tokens).sum():,.0f}"),
        ("Output tokens (total)", lambda d, r: f"{pd.to_numeric(r.output_tokens).sum():,.0f}"),
        ("Cost (total)", lambda d, r: f"${pd.to_numeric(r.cost).sum():.4f}"),
        ("Avg seconds per answer", lambda d, r: f"{pd.to_numeric(r.seconds).mean():.1f}"),
        ("Errors", lambda d, r: str(int((d.error != '').sum()))),
    ]
    for name, f in metrics:
        lines.append(f"| {name} | {by('cold', f)} | {by('mcp', f)} |")
    lines += ["", "## Per prompt", "", "| ID | cold score | mcp score | mcp tools called | used tool number | official |",
              "|---|---|---|---|---|---|"]
    for pid in det["id"].unique():
        c = det[(det.id == pid) & (det["mode"] == "cold")]
        m = det[(det.id == pid) & (det["mode"] == "mcp")]
        g = lambda d, col: d[col].iloc[0] if len(d) else "-"  # noqa: E731
        lines.append(f"| {pid} | {g(c, 'number_score')} ({g(c, 'number_value')}) | {g(m, 'number_score')} "
                     f"({g(m, 'number_value')}) | {g(m, 'tools_called') or 'none'} | {g(m, 'used_tool_number')} | "
                     f"{g(m, 'official_value')} |")
    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    path = os.path.join(ROOT, "reports", "mcp_test_summary.md")
    open(path, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines[4:4 + 2 + len(metrics)]))
    print(f"-> {path}\n-> {OUT_DIR}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=None, help="LiteLLM model name (needs tool calling)")
    ap.add_argument("--ids", nargs="+", help=f"prompt ids (default: {' '.join(DEFAULT_IDS)})")
    ap.add_argument("--prompts", nargs="+", default=[os.path.join(TS, "week2_prompts.csv")])
    ap.add_argument("--answer-key", default=os.path.join(TS, "week2_answer_key.csv"))
    ap.add_argument("--limit", type=int, default=0, help="only the first N prompts (try 5 first)")
    ap.add_argument("--max-cost", type=float, default=0.50, help="stop once this many dollars are spent")
    ap.add_argument("--sleep", type=float, default=4.0, help="seconds between calls (free-tier rate limits)")
    ap.add_argument("--nudge", action="store_true", help="add a one-line system prompt telling it to use the tools")
    ap.add_argument("--list-tools", action="store_true", help="start the MCP server, list its tools, exit")
    args = ap.parse_args()
    load_dotenv_if_present()
    args.model = args.model or os.getenv("MCP_TEST_MODEL") or DEFAULT_MODEL
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
