import asyncio
import contextlib
import csv
import json
import os
import sys
import time
from pathlib import Path

import litellm
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

RESULT_COLUMNS = [
    "id", "model", "mode", "thinking", "web_search", "repeat", "answer",
    "headline_number", "year_given", "source_claimed", "searched", "caveat",
    "number_score", "year_score", "source_score", "error_types",
    "input_tokens", "output_tokens", "cost", "seconds", "search_log", "error",
]


def build_search_log(response, grounding):
    queries, sources = [], []
    for g in grounding:
        if not isinstance(g, dict):
            continue
        queries.extend(g.get("webSearchQueries") or [])
        for chunk in g.get("groundingChunks") or []:
            web = chunk.get("web") or {}
            if web:
                sources.append({"title": web.get("title"), "uri": web.get("uri")})

    tool_calls = []
    for call in response.choices[0].message.tool_calls or []:
        fn = getattr(call, "function", None)
        tool_calls.append({"name": getattr(fn, "name", None),
                           "arguments": getattr(fn, "arguments", None)})

    details = getattr(response.usage, "prompt_tokens_details", None)
    billed_searches = getattr(details, "web_search_requests", None)

    if not (queries or sources or tool_calls):
        return ""
    return json.dumps({"queries": queries, "sources": sources, "tool_calls": tool_calls,
                       "billed_search_requests": billed_searches}, ensure_ascii=False)


def mode_cold(prompt, run):
    return [{"role": "user", "content": prompt}]


def mode_skill(prompt, run):
    skill = (REPO_ROOT / run["skill_file"]).read_text(encoding="utf-8")
    return [{"role": "system", "content": skill}, {"role": "user", "content": prompt}]


MODES = {"cold": mode_cold, "skill": mode_skill, "mcp": mode_cold}


async def open_mcp(stack):
    sys.path.insert(0, str(REPO_ROOT / "pipeline"))
    import mcp_test
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    if not os.getenv("DC_API_KEY"):
        sys.exit("mode 'mcp' needs DC_API_KEY in .env (free key: https://apikeys.datacommons.org)")
    read, write = await stack.enter_async_context(stdio_client(mcp_test.server_params()))
    session = await stack.enter_async_context(ClientSession(read, write))
    await session.initialize()
    mcp_tools = (await session.list_tools()).tools
    try:
        has_resources = bool((await session.list_resources()).resources)
    except Exception:
        has_resources = False
    print(f"MCP server up: {len(mcp_tools)} tools")
    return session, mcp_test.to_openai_tools(mcp_tools, with_bridge=has_resources)


async def ask_mcp(model, prompt, session, tools):
    import mcp_test
    r = await mcp_test.ask(model["litellm_model"], prompt, session=session, tools=tools, nudge=True)
    cost = (r["input_tokens"] * model.get("price_input_per_m", 0)
            + r["output_tokens"] * model.get("price_output_per_m", 0)) / 1e6
    return {
        "answer": r["answer"],
        "searched": bool(r["calls"]),
        "search_log": json.dumps({"tool_calls": r["calls"]}, ensure_ascii=False) if r["calls"] else "",
        "input_tokens": r["input_tokens"],
        "output_tokens": r["output_tokens"],
        "cost": cost,
        "seconds": round(r["seconds"], 2),
        "error": r["error"],
    }


TIMEOUT_SECONDS = 120
RETRYABLE = (litellm.Timeout, litellm.RateLimitError, litellm.ServiceUnavailableError,
             litellm.InternalServerError)


def ask(model, messages, thinking, web_search, log):
    kwargs = {"model": model["litellm_model"], "messages": messages}
    if model["supports_thinking"]:
        if model["provider"] == "gemini":
            kwargs["reasoning_effort"] = "low" if thinking else "disable"
        elif model["provider"] == "groq":
            kwargs["reasoning_effort"] = "default" if thinking else "none"
    if web_search:
        kwargs["tools"] = [{"googleSearch": {}}]

    for wait in [30, 60, 120, None]:
        start = time.time()
        try:
            response = litellm.completion(**kwargs, timeout=TIMEOUT_SECONDS)
            break
        except RETRYABLE as err:
            error = f"{type(err).__name__}: {str(err).splitlines()[0][:200]}"
            if "check your plan and billing" in str(err):
                raise RuntimeError("quota refused (free Gemini key can't use web search; "
                                   "needs a paid Tier 1 key)") from err
            if wait is None:
                log(f"{error}, giving up")
                raise
            log(f"{error}, retrying in {wait}s")
            time.sleep(wait)
    seconds = round(time.time() - start, 2)

    input_tokens = response.usage.prompt_tokens or 0
    output_tokens = response.usage.completion_tokens or 0
    cost = (input_tokens * model.get("price_input_per_m", 0)
            + output_tokens * model.get("price_output_per_m", 0)) / 1e6
    grounding = getattr(response, "vertex_ai_grounding_metadata", None) or []
    searched = any(g.get("webSearchQueries") for g in grounding if isinstance(g, dict))

    return {
        "answer": response.choices[0].message.content or "",
        "searched": searched,
        "search_log": build_search_log(response, grounding),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost": cost,
        "seconds": seconds,
    }


def load_env():
    env = REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and not key.startswith("#"):
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main():
    asyncio.run(run_file(sys.argv[1]))


async def run_file(run_path):
    load_env()
    with open(run_path) as f:
        run = yaml.safe_load(f)

    prompts = []
    for path in run["prompts"]:
        with open(REPO_ROOT / path, newline="", encoding="utf-8-sig") as f:
            prompts.extend(csv.DictReader(f))
    unknown = set(run["modes"]) - set(MODES)
    if unknown:
        sys.exit(f"unknown modes {sorted(unknown)}; choose from {sorted(MODES)}")

    grid = [
        (p, name, model, mode, thinking, web, repeat)
        for repeat in range(1, run["repeats"] + 1)
        for p in prompts
        for name, model in run["models"].items()
        for mode in run["modes"]
        for thinking in run["thinking"]
        for web in run["web_search"]
        if (model["supports_thinking"] or not thinking)
        and (model["supports_web_search"] or not web)
        and (mode != "mcp" or (not thinking and not web))
    ]

    out_dir = REPO_ROOT / "results" / run["run_name"]
    out_dir.mkdir(parents=True, exist_ok=True)
    async with contextlib.AsyncExitStack() as stack:
        session = tools = None
        if "mcp" in run["modes"]:
            session, tools = await open_mcp(stack)
        await run_grid(run, grid, out_dir, session, tools)


async def run_grid(run, grid, out_dir, session, tools):
    done = errors = 0
    errors_path = out_dir / "errors.csv"
    with open(out_dir / "results.csv", "w", newline="", encoding="utf-8") as f, \
         open(errors_path, "w", newline="", encoding="utf-8") as ef, \
         open(out_dir / "log.txt", "w", encoding="utf-8") as log_file:
        writer = csv.DictWriter(f, fieldnames=RESULT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        error_writer = csv.DictWriter(ef, fieldnames=RESULT_COLUMNS, lineterminator="\n")
        error_writer.writeheader()
        spent = 0.0
        for n, (p, name, model, mode, thinking, web, repeat) in enumerate(grid, 1):
            if spent >= run["budget_usd"]:
                break
            label = (f"[{n}/{len(grid)}] {p['id']} {name} {mode} "
                     f"thinking={thinking} web_search={web} repeat={repeat}")
            print(label)

            def log(message):
                line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {label} {message}"
                print(line)
                log_file.write(line + "\n")
                log_file.flush()

            try:
                if mode == "mcp":
                    result = await ask_mcp(model, p["prompt"], session, tools)
                else:
                    result = ask(model, MODES[mode](p["prompt"], run), thinking, web, log)
            except Exception as err:
                first_line = str(err).splitlines()[0][:300] if str(err) else ""
                message = f"{type(err).__name__}: {first_line}"
                log(f"failed: {message}")
                result = {"error": message, "cost": 0}
            spent += result["cost"]
            done += 1
            row = {c: "" for c in RESULT_COLUMNS}
            row.update({"id": p["id"], "model": name, "mode": mode, "thinking": thinking,
                        "web_search": web, "repeat": repeat, **result})
            if row["error"] and not row["answer"]:
                errors += 1
                error_writer.writerow(row)
                ef.flush()
            else:
                writer.writerow(row)
                f.flush()
    if not errors:
        errors_path.unlink()
    if done < len(grid):
        print(f"Stopped at the ${run['budget_usd']:.2f} budget cap after {done} of {len(grid)} calls")
    print(f"Done: {done - errors} answers saved, {errors} calls failed"
          + (f" (in {errors_path.relative_to(REPO_ROOT)})" if errors else "") + f", ${spent:.4f} spent")


if __name__ == "__main__":
    main()
