"""Compare the catalogue models of each AI provider with REAL API calls and recommend primary/fallback models.

Usage (from backend/):
    python scripts/compare_ai_models.py                       # every provider that has a real key in backend/.env
    python scripts/compare_ai_models.py --providers openai anthropic
    python scripts/compare_ai_models.py --repeat 3             # average latency over 3 runs per check

For every model it runs, through the same LangChain adapters the AI nodes use:
  1. availability   - is the model listed for this key (models.list, no tokens billed)
  2. structured     - schema-constrained JSON classification, validated with jsonschema (what AI Generate / the
                      Agent's final answer need)
  3. tool calling   - does it call the calculator tool with arguments that pass the tool's own validation
                      (what the AI Agent needs)

Recommendation per provider:
  primary  = the most capable model (catalogue order) that passed every check
  fallback = the fastest *other* passing model of the same provider (different model => useful when the
             primary is rate limited or overloaded); a cross-provider alternative is printed as well.
This costs a few cents of tokens per model. API keys are never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jsonschema import Draft202012Validator  # noqa: E402
from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402

from app.ai.catalog import PROVIDERS, list_models, platform_key  # noqa: E402
from app.ai.errors import classify_provider_error  # noqa: E402
from app.ai.providers import build_chat_model, structured_runnable, test_connection  # noqa: E402
from app.ai.targets import ModelTarget  # noqa: E402
from app.ai.tools import get_tool_registry  # noqa: E402

SCHEMA = {"type": "object", "properties": {
    "category": {"type": "string", "enum": ["billing", "technical", "account", "general"]},
    "priority": {"type": "string", "enum": ["low", "medium", "high"]},
    "summary": {"type": "string"}}, "required": ["category", "priority", "summary"]}
MESSAGE = "I was charged twice for my subscription this month and need a refund urgently."
TIMEOUT = 120.0


async def _timed(coro) -> tuple[Any, float]:
    t0 = time.perf_counter()
    result = await asyncio.wait_for(coro, timeout=TIMEOUT)
    return result, time.perf_counter() - t0


async def check_structured(model_info, key: str) -> Dict[str, Any]:
    target = ModelTarget(provider=model_info.provider, model=model_info.model, max_output_tokens=1024,
                         timeout_seconds=TIMEOUT)
    chat = build_chat_model(model_info, target, key)
    runnable = structured_runnable(chat, model_info.provider, SCHEMA)
    out, seconds = await _timed(runnable.ainvoke([SystemMessage(content="Classify customer support messages."),
                                                   HumanMessage(content=MESSAGE)]))
    parsed = out.get("parsed") if isinstance(out, dict) else None
    errors = [e.message for e in Draft202012Validator(SCHEMA).iter_errors(parsed)] if parsed is not None else ["no JSON"]
    usage = getattr(out.get("raw"), "usage_metadata", None) or {}
    ok = not errors and parsed.get("category") == "billing"
    return {"ok": ok, "seconds": seconds, "tokens": usage.get("total_tokens"),
            "detail": json.dumps(parsed) if parsed is not None else "; ".join(errors)}


async def check_tools(model_info, key: str) -> Dict[str, Any]:
    tool = get_tool_registry().get("calculator")
    target = ModelTarget(provider=model_info.provider, model=model_info.model, max_output_tokens=1024,
                         timeout_seconds=TIMEOUT)
    chat = build_chat_model(model_info, target, key).bind_tools([tool.model_schema()])
    msg, seconds = await _timed(chat.ainvoke([
        SystemMessage(content="You must use the calculator tool for arithmetic."),
        HumanMessage(content="What is 1249.5 * 0.18 + 37? Use the calculator.")]))
    calls = [c for c in (msg.tool_calls or []) if c.get("name") == "calculator"]
    valid = False
    if calls:
        try:
            tool.input_model.model_validate(calls[0].get("args") or {})
            valid = True
        except Exception:  # invalid arguments count as a failed check
            valid = False
    usage = getattr(msg, "usage_metadata", None) or {}
    return {"ok": bool(calls) and valid, "seconds": seconds, "tokens": usage.get("total_tokens"),
            "detail": json.dumps(calls[0].get("args")) if calls else "no calculator call"}


async def run_check(fn, model_info, key: str, repeat: int) -> Dict[str, Any]:
    runs: List[Dict[str, Any]] = []
    for _ in range(repeat):
        try:
            runs.append(await fn(model_info, key))
        except Exception as exc:  # classified, never raw (no keys in output)
            failure = classify_provider_error(exc, model_info.provider, model_info.model, [key])
            runs.append({"ok": False, "seconds": None, "tokens": None,
                         "detail": f"{failure.category.value}: {failure.message}"})
    ok_runs = [r for r in runs if r["ok"]]
    return {"ok": len(ok_runs) == repeat,
            "seconds": statistics.mean(r["seconds"] for r in ok_runs) if ok_runs else None,
            "tokens": ok_runs[-1]["tokens"] if ok_runs else None,
            "detail": runs[-1]["detail"], "passed": f"{len(ok_runs)}/{repeat}"}


async def compare_provider(provider: str, repeat: int) -> Optional[Dict[str, Any]]:
    key = platform_key(provider)
    label = PROVIDERS[provider].label
    if not key:
        print(f"\n== {label}: SKIPPED - no real key in backend/.env ({PROVIDERS[provider].platform_key_setting})")
        return None
    print(f"\n== {label}")
    conn = await test_connection(provider, key)
    print(f"   connection: {'OK' if conn.ok else 'FAILED'} - {conn.message}")
    if not conn.ok:
        return None
    rows = []
    for info in list_models(provider):
        available = info.model in (conn.models_available or [])
        row = {"model": info.model, "available": available, "recommended": info.recommended}
        if available:
            row["structured"] = await run_check(check_structured, info, key, repeat)
            row["tools"] = await run_check(check_tools, info, key, repeat)
        row["ok"] = available and row["structured"]["ok"] and row["tools"]["ok"]
        if available:
            speed = [r["seconds"] for r in (row["structured"], row["tools"]) if r["seconds"]]
            row["avg_seconds"] = statistics.mean(speed) if speed else None
        rows.append(row)
        s, t = row.get("structured", {}), row.get("tools", {})
        fmt = lambda c: (f"{c['passed']} {c['seconds']:.1f}s tok={c['tokens']}" if c.get("seconds")  # noqa: E731
                         else f"{c.get('passed', '-')} {c.get('detail', '')[:70]}")
        print(f"   {info.model:24} available={str(available):5} structured=[{fmt(s) if s else '-'}] "
              f"tools=[{fmt(t) if t else '-'}]")
    passing = [r for r in rows if r["ok"]]
    if not passing:
        print("   -> no model passed every check")
        return {"provider": provider, "primary": None, "fallback": None}
    primary = next((r for r in passing if r["recommended"]), passing[0])
    others = sorted((r for r in passing if r is not primary), key=lambda r: r["avg_seconds"] or 1e9)
    fallback = others[0] if others else None
    print(f"   -> recommended primary : {primary['model']}")
    print(f"   -> recommended fallback: {fallback['model'] if fallback else '(none: only one model passed)'}")
    return {"provider": provider, "primary": primary["model"], "fallback": fallback["model"] if fallback else None}


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--providers", nargs="*", default=["openai", "anthropic", "gemini"],
                        choices=["openai", "anthropic", "gemini"])
    parser.add_argument("--repeat", type=int, default=1, help="runs per check (latency is averaged)")
    args = parser.parse_args()
    results = [r for r in [await compare_provider(p, max(1, args.repeat)) for p in args.providers] if r]
    print("\n== Copy-ready Agent / AI Generate model settings")
    for r in results:
        if not r["primary"]:
            continue
        cfg: Dict[str, Any] = {"model": {"provider": r["provider"], "model": r["primary"], "max_output_tokens": 2048,
                                         "timeout_seconds": 120}}
        if r["fallback"]:
            cfg["fallback_model"] = {"provider": r["provider"], "model": r["fallback"], "max_output_tokens": 2048,
                                     "timeout_seconds": 120}
        print(f"   {PROVIDERS[r['provider']].label}: {json.dumps(cfg)}")
    tops = [r for r in results if r["primary"]]
    if len(tops) >= 2:
        print(f"   Cross-provider option: primary {tops[0]['provider']}/{tops[0]['primary']} with fallback "
              f"{tops[1]['provider']}/{tops[1]['primary']} (survives a full outage of one provider).")


if __name__ == "__main__":
    asyncio.run(main())
