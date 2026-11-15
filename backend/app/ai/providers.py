"""Provider adapters: LangChain chat models for OpenAI, Anthropic and Google Gemini.

All provider-specific behaviour lives here (constructor parameters, which
options a provider accepts, structured-output schema preparation, connection
tests). The rest of the engine only sees ``ModelTarget`` / ``BaseChatModel``.

SDK-level retries are disabled (``max_retries=0``): the router in
``app.ai.router`` owns retries and fallback so every attempt is recorded.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Literal, Optional

from langchain_core.language_models.chat_models import BaseChatModel

from app.ai.catalog import PROVIDERS, SUPPORTED_PROVIDERS, ModelInfo, get_model, list_models, platform_key
from app.ai.targets import ModelTarget, model_target_issues
from app.ai.errors import classify_provider_error
from app.core.config import get_settings
from app.core.errors import ErrorCategory, NodeExecutionError
from app.engine.contracts import ExecutionContext
from app.services.credentials import PROVIDER_CREDENTIAL_TYPE


def require_model(target: ModelTarget, field_prefix: str) -> ModelInfo:
    issues = model_target_issues(target, field_prefix)
    if issues:
        field, message = issues[0]
        raise NodeExecutionError(ErrorCategory.UNSUPPORTED_MODEL, message, field=field)
    info = get_model(target.provider, target.model)
    assert info is not None
    return info


@dataclass
class ResolvedKey:
    api_key: str
    source: Literal["user", "platform"]


async def resolve_api_key(ctx: ExecutionContext, target: ModelTarget, field_prefix: str) -> ResolvedKey:
    """Decrypt the node's provider credential (owned by the executing user) or fall back to the platform key.

    The key is added to ``ctx.secrets`` so the runner scrubs it from anything it records.
    """
    if target.credential_id:
        data = await ctx.credentials.get(target.credential_id, [PROVIDER_CREDENTIAL_TYPE[target.provider]],
                                         field=f"{field_prefix}.credential_id")
        key = str(data.get("api_key") or "")
        if not key:
            raise NodeExecutionError(ErrorCategory.MISSING_CREDENTIALS, "The selected credential has no API key.",
                                     field=f"{field_prefix}.credential_id")
        ctx.secrets.add(key)
        return ResolvedKey(key, "user")
    settings = get_settings()
    label = PROVIDERS[target.provider].label
    key = platform_key(target.provider)
    if key and settings.AI_ALLOW_PLATFORM_KEYS:
        ctx.secrets.add(key)
        return ResolvedKey(key, "platform")
    reason = ("platform-level keys are disabled (AI_ALLOW_PLATFORM_KEYS=false)" if key
              else f"no platform key ({PROVIDERS[target.provider].platform_key_setting}) is configured")
    raise NodeExecutionError(
        ErrorCategory.MISSING_CREDENTIALS,
        f"No {label} API key available: select a '{label} API key' credential for this node ({reason}).",
        field=f"{field_prefix}.credential_id",
    )


# ---------------------------------------------------------------------------
# Chat model construction
# ---------------------------------------------------------------------------

ChatModelFactory = Callable[[ModelInfo, ModelTarget, str], BaseChatModel]
_factory_override: Optional[ChatModelFactory] = None


def set_chat_model_factory(factory: Optional[ChatModelFactory]) -> None:
    """Test hook: replace real provider clients with a fake chat model (None restores the real factory)."""
    global _factory_override
    _factory_override = factory


def build_chat_model(info: ModelInfo, target: ModelTarget, api_key: str) -> BaseChatModel:
    if _factory_override is not None:
        return _factory_override(info, target, api_key)
    caps = info.capabilities
    timeout = float(target.timeout_seconds)
    if info.provider == "openai":
        from langchain_openai import ChatOpenAI

        kwargs: Dict[str, Any] = dict(model=info.model, api_key=api_key, timeout=timeout, max_retries=0,
                                      max_tokens=target.max_output_tokens, use_responses_api=True)
        if target.temperature is not None and caps.temperature:
            kwargs["temperature"] = target.temperature
        if target.reasoning_effort and caps.reasoning_effort:
            kwargs["reasoning_effort"] = target.reasoning_effort
        return ChatOpenAI(**kwargs)
    if info.provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        kwargs = dict(model=info.model, api_key=api_key, timeout=timeout, max_retries=0,
                      max_tokens=target.max_output_tokens)
        if target.temperature is not None and caps.temperature:
            kwargs["temperature"] = target.temperature
        if target.reasoning_effort and caps.reasoning_effort:
            kwargs["output_config"] = {"effort": target.reasoning_effort}
        return ChatAnthropic(**kwargs)
    if info.provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        kwargs = dict(model=info.model, google_api_key=api_key, timeout=timeout, max_retries=0,
                      max_output_tokens=target.max_output_tokens)
        if target.temperature is not None and caps.temperature:
            kwargs["temperature"] = target.temperature
        return ChatGoogleGenerativeAI(**kwargs)
    raise NodeExecutionError(ErrorCategory.UNSUPPORTED_MODEL, f"Unsupported provider '{info.provider}'.")


def provider_schema(provider: str, schema: Dict[str, Any]) -> Dict[str, Any]:
    """Provider-ready copy of a user JSON schema for native structured output.

    The user's original schema is always the one used for validation; this copy only adapts presentation:
    a ``title`` (required by OpenAI's response_format name) and, for Anthropic, ``additionalProperties: false``
    on every object (required by Anthropic structured outputs).
    """
    out = copy.deepcopy(schema)
    out.setdefault("title", "structured_output")
    if provider == "anthropic":
        def close(node: Any) -> None:
            if isinstance(node, dict):
                if node.get("type") == "object" or "properties" in node:
                    node.setdefault("additionalProperties", False)
                for value in node.values():
                    close(value)
            elif isinstance(node, list):
                for value in node:
                    close(value)
        close(out)
    return out


def structured_runnable(model: BaseChatModel, provider: str, schema: Dict[str, Any]) -> Any:
    """LangChain runnable returning {'raw', 'parsed', 'parsing_error'} using the provider's native JSON schema mode."""
    prepared = provider_schema(provider, schema)
    if provider == "openai":
        return model.with_structured_output(prepared, method="json_schema", include_raw=True, strict=False)
    return model.with_structured_output(prepared, method="json_schema", include_raw=True)


# ---------------------------------------------------------------------------
# Connection tests (real provider calls; used by POST /api/credentials/{id}/test)
# ---------------------------------------------------------------------------

@dataclass
class ConnectionResult:
    ok: bool
    message: str
    category: Optional[str] = None
    models_available: Optional[List[str]] = None


async def test_connection(provider: str, api_key: str, timeout: float = 20.0) -> ConnectionResult:
    """List the provider's models with ``api_key`` (cheap, no inference) and report catalogue availability."""
    if provider not in SUPPORTED_PROVIDERS:
        return ConnectionResult(False, f"Unsupported provider '{provider}'.", "UNSUPPORTED_MODEL")
    try:
        if provider == "openai":
            import openai

            client = openai.AsyncOpenAI(api_key=api_key, timeout=timeout, max_retries=0)
            ids = {m.id async for m in client.models.list()}
        elif provider == "anthropic":
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout, max_retries=0)
            ids = {m.id async for m in client.models.list()}
        else:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout * 1000)))
            ids = {m.name.removeprefix("models/") async for m in await client.aio.models.list()}
    except Exception as exc:  # classified, never raw
        failure = classify_provider_error(exc, provider, "models.list", [api_key])
        return ConnectionResult(False, failure.message, failure.category.value)
    available = sorted(m.model for m in list_models(provider) if m.model in ids)
    label = PROVIDERS[provider].label
    if not available:
        return ConnectionResult(True, f"{label} accepted the key, but none of the supported models are available "
                                      "to it.", None, [])
    return ConnectionResult(True, f"{label} accepted the key. Supported models available: {', '.join(available)}.",
                            None, available)
