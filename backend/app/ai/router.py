"""Primary/fallback model routing with bounded retries and usage accounting.

Rules (Milestone 2 master prompt, section 6.4):
1. Both targets are validated against the verified catalogue and both API keys are resolved *before* the
   first call. A missing credential or unsupported model fails immediately - never a fallback.
2. The active model is called; failures are classified (``app.ai.errors``).
3. Retryable failures (429, 5xx, timeouts, connection errors) are retried a bounded number of times with
   backoff. Model calls are side-effect free; tool executions happen outside this router and are never
   re-run because a model request failed.
4. Only availability failures (``fallback_eligible``) switch to the configured fallback. Auth, permission,
   configuration, cancellation and output-validation errors never do.
5. Once switched, the router stays on the fallback for the rest of the node run (sticky) and records the
   actual provider/model used and the reason.
Every attempt - successful or not - is reported to ``ctx.usage_sink`` with provider-reported token usage
(never estimated).
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage

from app.ai.catalog import ModelInfo
from app.ai.errors import classify_provider_error
from app.ai.providers import ModelTarget, ResolvedKey, build_chat_model, require_model, resolve_api_key
from app.core.config import get_settings
from app.core.errors import ErrorCategory, NodeExecutionError
from app.engine.contracts import ExecutionContext

T = TypeVar("T")
ModelCall = Callable[[BaseChatModel, ModelInfo], Awaitable[Tuple[T, Optional[BaseMessage]]]]


def usage_of(message: Optional[BaseMessage]) -> Dict[str, Optional[int]]:
    """Provider-reported usage from a LangChain AIMessage; ``None`` fields when not reported."""
    meta = getattr(message, "usage_metadata", None) or {}
    def num(key: str) -> Optional[int]:
        value = meta.get(key) if isinstance(meta, dict) else None
        return int(value) if isinstance(value, (int, float)) else None
    usage = {"input_tokens": num("input_tokens"), "output_tokens": num("output_tokens"),
             "total_tokens": num("total_tokens")}
    if usage["total_tokens"] is None and usage["input_tokens"] is not None and usage["output_tokens"] is not None:
        usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
    return usage


@dataclass
class _Slot:
    role: str  # "primary" | "fallback"
    target: ModelTarget
    info: ModelInfo
    key: ResolvedKey
    field_prefix: str
    model: Optional[BaseChatModel] = None


@dataclass
class ModelRouter:
    ctx: ExecutionContext
    primary: ModelTarget
    fallback: Optional[ModelTarget] = None
    operation: str = "ai"
    primary_field: str = "model"
    fallback_field: str = "fallback_model"
    max_retries: Optional[int] = None
    attempts: List[Dict[str, Any]] = field(default_factory=list)
    fallback_reason: Optional[str] = None
    totals: Dict[str, Optional[int]] = field(default_factory=lambda: {"input_tokens": None, "output_tokens": None,
                                                                       "total_tokens": None})
    _slots: Dict[str, _Slot] = field(default_factory=dict)
    _active: str = "primary"

    async def prepare(self) -> ModelRouter:
        """Validate both targets and resolve both keys up front (no fallback for config/credential errors)."""
        info = require_model(self.primary, self.primary_field)
        key = await resolve_api_key(self.ctx, self.primary, self.primary_field)
        self._slots["primary"] = _Slot("primary", self.primary, info, key, self.primary_field)
        if self.fallback is not None:
            if (self.fallback.provider, self.fallback.model) == (self.primary.provider, self.primary.model):
                raise NodeExecutionError(ErrorCategory.SCHEMA_VALIDATION,
                                         "The fallback model must differ from the primary model.",
                                         field=f"{self.fallback_field}.model")
            finfo = require_model(self.fallback, self.fallback_field)
            fkey = await resolve_api_key(self.ctx, self.fallback, self.fallback_field)
            self._slots["fallback"] = _Slot("fallback", self.fallback, finfo, fkey, self.fallback_field)
        return self

    # ------------------------------------------------------------------ state
    @property
    def active(self) -> _Slot:
        return self._slots[self._active]

    @property
    def fallback_used(self) -> bool:
        return self._active == "fallback"

    def summary(self) -> Dict[str, Any]:
        slot = self.active
        return {
            "requested": {"provider": self.primary.provider, "model": self.primary.model},
            "fallback_configured": ({"provider": self.fallback.provider, "model": self.fallback.model}
                                    if self.fallback else None),
            "provider": slot.info.provider, "model": slot.info.model,
            "credential_source": slot.key.source,
            "fallback_used": self.fallback_used, "fallback_reason": self.fallback_reason,
            "model_calls": len(self.attempts), "usage": dict(self.totals),
        }

    def _model(self, slot: _Slot) -> BaseChatModel:
        if slot.model is None:
            slot.model = build_chat_model(slot.info, slot.target, slot.key.api_key)
        return slot.model

    def _add_usage(self, usage: Dict[str, Optional[int]]) -> None:
        for key, value in usage.items():
            if value is not None:
                self.totals[key] = (self.totals[key] or 0) + value

    async def _record(self, slot: _Slot, status: str, duration_ms: float, usage: Dict[str, Optional[int]],
                      category: Optional[str] = None, message: Optional[str] = None, attempt: int = 1) -> None:
        entry = {"role": slot.role, "provider": slot.info.provider, "model": slot.info.model, "attempt": attempt,
                 "status": status, "duration_ms": round(duration_ms, 2), "usage": usage}
        if category:
            entry.update({"error_category": category, "error": message})
        self.attempts.append(entry)
        if self.ctx.usage_sink is not None:
            await self.ctx.usage_sink({
                "operation": self.operation, "provider": slot.info.provider, "model": slot.info.model,
                "credential_source": slot.key.source, "status": status, "error_category": category,
                "fallback_used": slot.role == "fallback", "duration_ms": round(duration_ms, 2), **usage,
            })

    # ------------------------------------------------------------------ calls
    async def invoke(self, call: ModelCall[T]) -> T:
        """Run ``call(chat_model, model_info)`` with retries and (eligible) fallback; return its value."""
        retries = get_settings().AI_MODEL_MAX_RETRIES if self.max_retries is None else self.max_retries
        roles = [self._active] + (["fallback"] if self._active == "primary" and "fallback" in self._slots else [])
        last_error: Optional[NodeExecutionError] = None
        for role in roles:
            slot = self._slots[role]
            if role == "fallback" and self._active == "primary":
                self._active = "fallback"
                self.ctx.logger.warning(f"Switching to fallback model {slot.info.provider}/{slot.info.model}: "
                                        f"{self.fallback_reason}")
            for attempt in range(1, retries + 2):
                if self.ctx.cancelled:
                    raise NodeExecutionError(ErrorCategory.CANCELLED, "The agent was cancelled.")
                t0 = time.perf_counter()
                try:
                    value, message = await asyncio.wait_for(call(self._model(slot), slot.info),
                                                            timeout=float(slot.target.timeout_seconds))
                except NodeExecutionError:
                    raise
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    duration = (time.perf_counter() - t0) * 1000
                    failure = classify_provider_error(exc, slot.info.provider, slot.info.model, self.ctx.secrets)
                    await self._record(slot, "error", duration, {"input_tokens": None, "output_tokens": None,
                                                                 "total_tokens": None},
                                       failure.category.value, failure.message, attempt)
                    self.ctx.logger.warning(f"Model call failed ({failure.category.value}): {failure.message}",
                                            {"provider": slot.info.provider, "model": slot.info.model,
                                             "attempt": attempt})
                    last_error = failure.to_error(field=f"{slot.field_prefix}.model",
                                                  extra={"provider": slot.info.provider, "model": slot.info.model})
                    if failure.retryable and attempt <= retries:
                        await self._backoff(attempt)
                        continue
                    if failure.fallback_eligible and role == "primary" and "fallback" in self._slots:
                        self.fallback_reason = f"{failure.category.value}: {failure.message}"
                        break
                    raise last_error from None
                duration = (time.perf_counter() - t0) * 1000
                usage = usage_of(message)
                self._add_usage(usage)
                await self._record(slot, "success", duration, usage, attempt=attempt)
                return value
        assert last_error is not None
        raise last_error

    async def _backoff(self, attempt: int) -> None:
        delay = min(4.0, 0.5 * (2 ** (attempt - 1))) * random.uniform(0.8, 1.2)
        try:
            await asyncio.wait_for(self.ctx.cancel_event.wait(), timeout=delay)
        except TimeoutError:
            return
        raise NodeExecutionError(ErrorCategory.CANCELLED, "The agent was cancelled.")
