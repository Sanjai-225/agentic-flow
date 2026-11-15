"""Scripted fake chat model for deterministic AI tests (mocked inference - never reported as live).

Injected through ``app.ai.providers.set_chat_model_factory`` so the real router, structured-output,
agent graph and executor code paths run unchanged; only the network call is replaced.

Script entries (consumed in order, per model id):
- ``AIMessage``                 returned as-is (usage metadata is added if missing)
- ``Exception`` instance        raised (to simulate provider failures)
- ``callable(messages, tools)`` called; may be ``async``; returns an AIMessage or raises
- ``("sleep", seconds)``        awaits, then continues with the next entry (timeouts/cancellation)
Structured-output calls consume the same script: the AIMessage's text content is parsed as JSON.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any, Dict, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
from pydantic import PrivateAttr


def ai(text: str = "", tool_calls: Optional[List[Dict[str, Any]]] = None, input_tokens: int = 11,
       output_tokens: int = 7) -> AIMessage:
    calls = [{"name": c["name"], "args": c.get("args", {}), "id": c.get("id", f"call_{i}"), "type": "tool_call"}
             for i, c in enumerate(tool_calls or [])]
    return AIMessage(content=text, tool_calls=calls,
                     usage_metadata={"input_tokens": input_tokens, "output_tokens": output_tokens,
                                     "total_tokens": input_tokens + output_tokens})


def ai_json(data: Any, **kw: Any) -> AIMessage:
    return ai(json.dumps(data), **kw)


def _tool_name(tool: Any) -> str:
    if isinstance(tool, dict):
        return str((tool.get("function") or {}).get("name") or tool.get("name"))
    return str(getattr(tool, "name", tool))


class Script:
    """Shared per-test script: ``{model_id: [entries...]}`` plus a call log."""

    def __init__(self, entries: Optional[Dict[str, List[Any]]] = None) -> None:
        self.entries: Dict[str, List[Any]] = {k: list(v) for k, v in (entries or {}).items()}
        self.calls: List[Dict[str, Any]] = []
        self.keys_seen: List[str] = []

    def next(self, model: str) -> Any:
        queue = self.entries.get(model)
        if not queue:
            raise AssertionError(f"Fake model {model!r} has no scripted response left")
        return queue.pop(0)


class FakeChatModel(BaseChatModel):
    model_id: str
    provider: str
    script: Any
    _tools: List[Any] = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "fake-scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> FakeChatModel:
        clone = FakeChatModel(model_id=self.model_id, provider=self.provider, script=self.script)
        clone._tools = list(tools)
        return clone

    async def _respond(self, messages: List[BaseMessage]) -> AIMessage:
        while True:
            entry = self.script.next(self.model_id)
            self.script.calls.append({"model": self.model_id, "messages": list(messages),
                                      "tools": [_tool_name(t) for t in self._tools]})
            if isinstance(entry, tuple) and entry and entry[0] == "sleep":
                await asyncio.sleep(entry[1])
                continue
            if isinstance(entry, BaseException):
                raise entry
            if callable(entry) and not isinstance(entry, AIMessage):
                result = entry(messages, self._tools)
                if inspect.isawaitable(result):
                    result = await result
                return result
            return entry

    def _generate(self, messages: List[BaseMessage], stop: Any = None, run_manager: Any = None,
                  **kwargs: Any) -> ChatResult:
        raise NotImplementedError("use the async API")

    async def _agenerate(self, messages: List[BaseMessage], stop: Any = None, run_manager: Any = None,
                         **kwargs: Any) -> ChatResult:
        message = await self._respond(messages)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def with_structured_output(self, schema: Any, *, include_raw: bool = False, **kwargs: Any) -> RunnableLambda:
        async def run(messages: Any) -> Dict[str, Any]:
            msgs = messages if isinstance(messages, list) else [messages]
            raw = await self._respond(msgs)
            try:
                parsed = json.loads(raw.content) if isinstance(raw.content, str) and raw.content else None
            except json.JSONDecodeError:
                parsed = None
            return {"raw": raw, "parsed": parsed, "parsing_error": None if parsed is not None else "invalid json"}

        def run_sync(messages: Any) -> Dict[str, Any]:
            raise NotImplementedError("use the async API")

        return RunnableLambda(run_sync, afunc=run)


def install(monkeypatch: Any, script: Script) -> Script:
    """Route every provider through the fake model for the duration of a test."""
    from app.ai import providers

    def factory(info: Any, target: Any, api_key: str) -> FakeChatModel:
        script.keys_seen.append(api_key)
        return FakeChatModel(model_id=info.model, provider=info.provider, script=script)

    monkeypatch.setattr(providers, "_factory_override", factory)
    return script
