"""Provider/model selection used in AI node configs (no provider SDK imports here)."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ai.catalog import get_model, list_models


class ModelTarget(BaseModel):
    """One provider/model selection inside a node config (primary or fallback)."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["openai", "anthropic", "gemini"]
    model: str = Field(..., min_length=1)
    credential_id: Optional[str] = Field(
        default=None, description="User credential holding the provider API key. Empty = platform key (if allowed).")
    temperature: Optional[float] = Field(default=None, ge=0, le=2)
    max_output_tokens: int = Field(default=4096, ge=1, le=128_000)
    timeout_seconds: float = Field(default=60, gt=0, le=600)
    reasoning_effort: Optional[Literal["low", "medium", "high"]] = None

    @field_validator("model")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


def model_target_issues(target: ModelTarget, field_prefix: str) -> List[tuple[str, str]]:
    """Static validation against the verified catalogue: [(field, message)]. Empty when valid."""
    info = get_model(target.provider, target.model)
    if info is None:
        known = ", ".join(m.model for m in list_models(target.provider)) or "none"
        return [(f"{field_prefix}.model", f"Model '{target.model}' is not a supported {target.provider} model. "
                                          f"Supported: {known}.")]
    issues: List[tuple[str, str]] = []
    caps = info.capabilities
    if target.temperature is not None and not caps.temperature:
        issues.append((f"{field_prefix}.temperature",
                       f"{info.label} does not accept a temperature setting; leave it empty."))
    if target.reasoning_effort is not None and not caps.reasoning_effort:
        issues.append((f"{field_prefix}.reasoning_effort",
                       f"{info.label} does not support a reasoning-effort option; leave it empty."))
    if target.max_output_tokens > caps.max_output_tokens:
        issues.append((f"{field_prefix}.max_output_tokens",
                       f"{info.label} allows at most {caps.max_output_tokens} output tokens."))
    return issues
