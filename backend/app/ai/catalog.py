"""Verified model catalogue for AI Generate and the AI Agent.

Only hosted API providers are supported in Milestone 2: OpenAI, Anthropic and
Google Gemini. A node may only use a (provider, model) pair listed here; the
backend rejects anything else before execution. Each entry records where its
id and capabilities were verified. Capabilities drive validation: a node that
asks for a feature its model lacks (e.g. temperature on a model that rejects
sampling parameters) gets a clear configuration error instead of a silent
no-op.

Operators can add models through ``AI_EXTRA_MODELS`` (JSON); those entries are
marked ``operator-configured`` and are still validated against the provider list.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from app.core.config import get_settings

logger = logging.getLogger(__name__)

ProviderId = Literal["openai", "anthropic", "gemini"]
SUPPORTED_PROVIDERS: tuple[str, ...] = ("openai", "anthropic", "gemini")


class ProviderInfo(BaseModel):
    id: str
    label: str
    credential_type: str
    platform_key_setting: str  # name of the Settings attribute holding the platform-level key
    docs_url: str


PROVIDERS: Dict[str, ProviderInfo] = {
    "openai": ProviderInfo(id="openai", label="OpenAI", credential_type="openai_api_key",
                           platform_key_setting="OPENAI_API_KEY",
                           docs_url="https://developers.openai.com/api/docs/models"),
    "anthropic": ProviderInfo(id="anthropic", label="Anthropic", credential_type="anthropic_api_key",
                              platform_key_setting="ANTHROPIC_API_KEY",
                              docs_url="https://platform.claude.com/docs/en/about-claude/models/overview"),
    "gemini": ProviderInfo(id="gemini", label="Google Gemini", credential_type="gemini_api_key",
                           platform_key_setting="GEMINI_API_KEY",
                           docs_url="https://ai.google.dev/gemini-api/docs/models"),
}


class ModelCapabilities(BaseModel):
    tool_calling: bool = True
    # Native structured output via LangChain ``with_structured_output(method="json_schema")``.
    structured_output: bool = True
    streaming: bool = True
    temperature: bool = False          # only sent when True; several current models reject sampling params
    reasoning_effort: bool = False     # provider-specific effort control (OpenAI reasoning_effort, Anthropic effort)
    forced_tool_choice: bool = False   # informational; the agent always uses tool_choice "auto"
    usage_reporting: bool = True       # provider returns token usage
    context_window: int = Field(..., gt=0)
    max_output_tokens: int = Field(..., gt=0)


class ModelInfo(BaseModel):
    provider: str
    model: str
    label: str
    capabilities: ModelCapabilities
    verified: str = Field(..., description="Where the id/capabilities were verified (and whether live-tested).")
    recommended: bool = False


_OPENAI_DOCS = ("OpenAI model docs (developers.openai.com/api/docs/models), checked 2026-11-15: 1.05M context, "
                "128K output, function calling, structured outputs, streaming. Temperature is not documented for "
                "these reasoning models and is never sent.")
_ANTHROPIC_DOCS = ("Anthropic models reference (cached 2026-11-03): 1M context, 128K output; sampling parameters "
                   "and forced tool_choice return HTTP 400, so neither is sent.")
_GEMINI_LIVE = ("Verified live on 2026-11-15 (models.list + real generateContent calls; 1,048,576 input / 65,536 "
                "output tokens); temperature supported. gemini-2.5-pro / gemini-2.5-flash were removed: listed by "
                "models.list but generation returns 404 'no longer available to new users'.")

_OPENAI = ModelCapabilities(temperature=False, reasoning_effort=True, context_window=1_050_000,
                            max_output_tokens=128_000)
_ANTHROPIC = ModelCapabilities(temperature=False, reasoning_effort=True, context_window=1_000_000,
                               max_output_tokens=128_000)
_GEMINI = ModelCapabilities(temperature=True, reasoning_effort=False, forced_tool_choice=True,
                            context_window=1_048_576, max_output_tokens=65_536)

BUILTIN_MODELS: List[ModelInfo] = [
    # OpenAI (Responses API; ids from official docs)
    ModelInfo(provider="openai", model="gpt-6-astra", label="GPT-6 Astra (flagship)", capabilities=_OPENAI,
              verified=_OPENAI_DOCS),
    ModelInfo(provider="openai", model="gpt-6.1-sol", label="GPT-6.1 Sol (balanced)", capabilities=_OPENAI,
              verified=_OPENAI_DOCS, recommended=True),
    ModelInfo(provider="openai", model="gpt-6.1-terra", label="GPT-6.1 Terra (fast)", capabilities=_OPENAI,
              verified=_OPENAI_DOCS),
    ModelInfo(provider="openai", model="gpt-6-luna", label="GPT-6 Luna (low cost)", capabilities=_OPENAI,
              verified=_OPENAI_DOCS),
    # Anthropic
    ModelInfo(provider="anthropic", model="claude-opus-5-5", label="Claude Opus 5.5", capabilities=_ANTHROPIC,
              verified=_ANTHROPIC_DOCS, recommended=True),
    ModelInfo(provider="anthropic", model="claude-sonnet-5-5", label="Claude Sonnet 5.5", capabilities=_ANTHROPIC,
              verified=_ANTHROPIC_DOCS),
    ModelInfo(provider="anthropic", model="claude-haiku-5-5", label="Claude Haiku 5.5", capabilities=_ANTHROPIC,
              verified=_ANTHROPIC_DOCS),
    # Google Gemini
    ModelInfo(provider="gemini", model="gemini-3.5-flash", label="Gemini 3.5 Flash", capabilities=_GEMINI,
              verified=_GEMINI_LIVE + " Live generation and tool calling succeeded (2-9 s).", recommended=True),
    ModelInfo(provider="gemini", model="gemini-3.5-flash-lite", label="Gemini 3.5 Flash-Lite", capabilities=_GEMINI,
              verified=_GEMINI_LIVE + " Live generation succeeded."),
    ModelInfo(provider="gemini", model="gemini-3.8-flash", label="Gemini 3.8 Flash", capabilities=_GEMINI,
              verified=_GEMINI_LIVE + " Live structured generation succeeded; during verification tool calls hit "
                                      "provider 504/503 'high demand' errors, so configure a fallback model."),
]


def _extra_models(raw: str) -> List[ModelInfo]:
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("AI_EXTRA_MODELS is not valid JSON; ignoring it.")
        return []
    out: List[ModelInfo] = []
    for item in items if isinstance(items, list) else []:
        try:
            provider = str(item.get("provider", "")).strip().lower()
            if provider not in SUPPORTED_PROVIDERS:
                logger.error("AI_EXTRA_MODELS entry uses unsupported provider %r; ignoring it.", provider)
                continue
            caps = ModelCapabilities(**(item.get("capabilities") or {}))
            out.append(ModelInfo(provider=provider, model=str(item["model"]).strip(),
                                 label=str(item.get("label") or item["model"]), capabilities=caps,
                                 verified="operator-configured via AI_EXTRA_MODELS (not verified by Agentic Flow)"))
        except (KeyError, TypeError, ValidationError) as exc:
            logger.error("Invalid AI_EXTRA_MODELS entry %r: %s", item, exc)
    return out


@lru_cache(maxsize=1)
def _catalogue() -> Dict[tuple[str, str], ModelInfo]:
    models = BUILTIN_MODELS + _extra_models(get_settings().AI_EXTRA_MODELS)
    return {(m.provider, m.model): m for m in models}


def reset_catalogue_cache() -> None:
    _catalogue.cache_clear()


def get_model(provider: str, model: str) -> Optional[ModelInfo]:
    return _catalogue().get(((provider or "").strip().lower(), (model or "").strip()))


def list_models(provider: Optional[str] = None) -> List[ModelInfo]:
    return [m for m in _catalogue().values() if provider is None or m.provider == provider]


def is_placeholder_key(value: str) -> bool:
    """True for empty values and template placeholders such as 'your_openai_api_key_here'."""
    text = (value or "").strip().lower()
    return not text or text.startswith("your_") or "placeholder" in text or text in {"changeme", "change-me", "xxx"}


def platform_key(provider: str) -> str:
    """The platform-level key for ``provider`` from the environment ('' when unset or a placeholder)."""
    info = PROVIDERS.get(provider)
    value = str(getattr(get_settings(), info.platform_key_setting, "") or "").strip() if info else ""
    return "" if is_placeholder_key(value) else value
