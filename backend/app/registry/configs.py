"""Configuration models for executable node operations.

These models are part of the *definition* layer: the registry exposes them as
JSON Schema to the editor and the planner validates raw node configs against
them. Executors (``app.executors``) receive validated instances.

String fields may contain ``{{...}}`` expressions; they are resolved by the
engine before the executor runs (except fields listed in a definition's
``lazy_config_fields``, which the executor evaluates itself, e.g. per item).
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.conditions import ConditionGroup


class _StrictConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ManualTriggerConfig(_StrictConfig):
    """Manual trigger: the run payload becomes this node's output."""

    sample_payload: Dict[str, Any] = Field(
        default_factory=dict, description="Default payload used by the editor's Run dialog."
    )


class WebhookTriggerConfig(_StrictConfig):
    """Webhook trigger: requests to the workflow webhook URL start an execution."""

    method: Literal["POST", "GET", "PUT"] = "POST"


class SetField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, description="Field name; dots create nested objects (a.b.c).")
    value: Any = Field(default=None, description="Literal or {{...}} expression.")
    type: Literal["auto", "string", "number", "boolean", "object", "array"] = "auto"


class SetConfig(_StrictConfig):
    fields: List[SetField] = Field(default_factory=list)
    keep_input: bool = Field(default=False, description="Merge the upstream output into the result.")


class JsonParseConfig(_StrictConfig):
    source: Any = Field(..., description="JSON text to parse, usually a {{...}} expression.")


class FilterConfig(_StrictConfig):
    items: Any = Field(..., description="Array to filter, usually a {{...}} expression.")
    conditions: ConditionGroup = Field(..., description="Rules evaluated per item; use {{item.<field>}}.")


class IfConfig(_StrictConfig):
    conditions: ConditionGroup


class TransformConfig(_StrictConfig):
    mappings: Dict[str, Any] = Field(
        default_factory=dict, description="Target path -> literal or {{...}} expression."
    )


class HttpAuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["none", "bearer", "basic", "header"] = "none"
    credential_id: Optional[str] = Field(default=None, description="Stored credential reference.")


class HttpRequestConfig(_StrictConfig):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"] = "GET"
    url: str = Field(..., min_length=1)
    query: Dict[str, Any] = Field(default_factory=dict)
    headers: Dict[str, Any] = Field(default_factory=dict)
    body_type: Literal["none", "json", "form", "raw"] = "none"
    body: Any = None
    auth: HttpAuthConfig = Field(default_factory=HttpAuthConfig)
    timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    response_format: Literal["auto", "json", "text"] = "auto"
    ignore_http_errors: bool = False
    follow_redirects: bool = True


class EndConfig(_StrictConfig):
    output: Any = Field(
        default=None, description="Final workflow output (expression). Defaults to the upstream output."
    )
