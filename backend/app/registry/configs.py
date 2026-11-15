"""Configuration models for executable node operations.

These models are part of the *definition* layer: the registry exposes them as
JSON Schema to the editor and the planner validates raw node configs against
them. Executors (``app.executors``) receive validated instances.

String fields may contain ``{{...}}`` expressions; they are resolved by the
engine before the executor runs (except fields listed in a definition's
``lazy_config_fields``, which the executor evaluates itself, e.g. per item).
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        name = v.strip()
        if not name:
            raise ValueError("Field name must not be blank")
        if any(not part.strip() for part in name.split(".")):
            raise ValueError(f"Field name '{name}' has an empty segment; use names like 'a.b.c'")
        return name

    @model_validator(mode="after")
    def _value_not_empty(self) -> "SetField":
        # An empty value is only meaningful when the user explicitly wants empty text.
        empty = self.value is None or (isinstance(self.value, str) and not self.value.strip())
        if empty and self.type != "string":
            raise ValueError(
                f"Field '{self.name}' has no value. Enter a value or a {{{{...}}}} reference, "
                "or set its type to 'string' to store empty text"
            )
        return self


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


# ---------------------------------------------------------------------------
# AI nodes (Milestone 2)
# ---------------------------------------------------------------------------

from app.ai.targets import ModelTarget, model_target_issues  # noqa: E402  (kept next to the AI configs)


def _check_model(target: Optional[ModelTarget], prefix: str) -> None:
    if target is None:
        return
    issues = model_target_issues(target, prefix)
    if issues:
        raise ValueError(issues[0][1])


def _check_schema(schema: Optional[Dict[str, Any]]) -> None:
    if schema is None:
        return
    from app.ai.structured import schema_problems

    problems = schema_problems(schema)
    if problems:
        raise ValueError(problems[0])


class AIGenerateConfig(_StrictConfig):
    """AI Generate: one bounded model call (text or schema-validated JSON). Never calls tools, never falls back."""

    model: ModelTarget
    system_prompt: str = Field(default="", max_length=20_000)
    prompt: str = Field(..., min_length=1, max_length=100_000,
                        description="User prompt; may contain {{...}} references.")
    inputs: Dict[str, Any] = Field(default_factory=dict,
                                   description="Named values (usually {{...}} references) appended to the prompt as JSON.")
    output_format: Literal["text", "json"] = "text"
    output_schema: Optional[Dict[str, Any]] = Field(default=None, description="JSON Schema for output_format=json.")
    max_retries: int = Field(default=2, ge=0, le=5, description="Retries for transient provider errors only.")
    max_repair_attempts: int = Field(default=1, ge=0, le=3)
    max_input_chars: int = Field(default=50_000, ge=100, le=500_000)

    @model_validator(mode="after")
    def _validate(self) -> "AIGenerateConfig":
        _check_model(self.model, "model")
        if self.output_format == "json" and not self.output_schema:
            raise ValueError("output_format 'json' requires an output schema")
        _check_schema(self.output_schema)
        return self


class AgentLimits(_StrictConfig):
    max_iterations: int = Field(default=6, ge=1, le=20, description="Maximum model calls in the tool loop.")
    max_tool_calls: int = Field(default=10, ge=0, le=50)
    max_tool_errors: int = Field(default=3, ge=1, le=10,
                                 description="Rejected/failed tool calls tolerated before the agent stops.")
    tool_timeout_seconds: float = Field(default=15, gt=0, le=120)
    timeout_seconds: float = Field(default=120, gt=0, le=600, description="Overall agent timeout.")
    max_input_chars: int = Field(default=50_000, ge=100, le=500_000)
    max_output_chars: int = Field(default=20_000, ge=100, le=200_000)
    max_total_tokens: Optional[int] = Field(default=None, ge=100, le=5_000_000,
                                            description="Stop when provider-reported tokens exceed this budget.")
    max_repair_attempts: int = Field(default=1, ge=0, le=3)


class AgentConfig(_StrictConfig):
    """AI Agent: instructions + mapped inputs + explicitly allowed tools + optional output schema."""

    model: ModelTarget
    fallback_model: Optional[ModelTarget] = None
    instructions: str = Field(..., min_length=1, max_length=20_000)
    task: str = Field(default="", max_length=100_000, description="Task message; may contain {{...}} references.")
    inputs: Dict[str, Any] = Field(default_factory=dict)
    tools: List[str] = Field(default_factory=list, description="Explicit tool allowlist (empty = no tools).")
    output_schema: Optional[Dict[str, Any]] = None
    limits: AgentLimits = Field(default_factory=AgentLimits)

    @model_validator(mode="after")
    def _validate(self) -> "AgentConfig":
        _check_model(self.model, "model")
        _check_model(self.fallback_model, "fallback_model")
        if self.fallback_model and (self.fallback_model.provider, self.fallback_model.model) == \
                (self.model.provider, self.model.model):
            raise ValueError("The fallback model must differ from the primary model")
        from app.ai.tools import get_tool_registry

        registry = get_tool_registry()
        unknown = [t for t in self.tools if registry.get(t) is None]
        if unknown:
            known = ", ".join(t.id for t in registry.list_tools())
            raise ValueError(f"Unknown tool(s): {', '.join(unknown)}. Available tools: {known}")
        if len(set(self.tools)) != len(self.tools):
            raise ValueError("Each tool may be listed only once")
        _check_schema(self.output_schema)
        return self


# ---------------------------------------------------------------------------
# Form Submission Trigger and Schedule Trigger (Milestone 2)
# ---------------------------------------------------------------------------

FormFieldType = Literal["text", "email", "number", "textarea", "select", "checkbox"]


class FormFieldSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(..., pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,63}$",
                     description="Field name in the submission (letters, digits, underscore).")
    label: str = Field(..., min_length=1, max_length=200)
    type: FormFieldType = "text"
    required: bool = False
    placeholder: Optional[str] = Field(default=None, max_length=200)
    help: Optional[str] = Field(default=None, max_length=500)
    options: List[str] = Field(default_factory=list, description="Choices for select fields.")
    min: Optional[float] = None
    max: Optional[float] = None
    min_length: Optional[int] = Field(default=None, ge=0, le=10_000)
    max_length: Optional[int] = Field(default=None, ge=1, le=10_000)

    @model_validator(mode="after")
    def _validate(self) -> "FormFieldSpec":
        if self.type == "select":
            options = [o.strip() for o in self.options if o.strip()]
            if not options:
                raise ValueError(f"Select field '{self.key}' needs at least one option")
            if len(set(options)) != len(options):
                raise ValueError(f"Select field '{self.key}' has duplicate options")
            self.options = options
        elif self.options:
            raise ValueError(f"Field '{self.key}': options are only allowed for select fields")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"Field '{self.key}': min is greater than max")
        if self.min_length is not None and self.max_length is not None and self.min_length > self.max_length:
            raise ValueError(f"Field '{self.key}': min_length is greater than max_length")
        return self


class FormTriggerConfig(_StrictConfig):
    """Form Submission Trigger: a public form; each valid submission starts one execution."""

    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    fields: List[FormFieldSpec] = Field(..., min_length=1, max_length=30)
    submit_label: str = Field(default="Submit", min_length=1, max_length=60)
    success_message: str = Field(default="Thank you! Your response has been received.", min_length=1,
                                 max_length=500)

    @model_validator(mode="after")
    def _unique_keys(self) -> "FormTriggerConfig":
        keys = [f.key for f in self.fields]
        duplicates = sorted({k for k in keys if keys.count(k) > 1})
        if duplicates:
            raise ValueError(f"Form field keys must be unique (duplicate: {', '.join(duplicates)})")
        return self


Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class ScheduleTriggerConfig(_StrictConfig):
    """Schedule Trigger: the backend scheduler starts the workflow at the configured times."""

    mode: Literal["interval", "hourly", "daily", "weekly", "weekdays", "cron"] = "daily"
    interval_minutes: int = Field(default=15, ge=1, le=10_080)
    minute: int = Field(default=0, ge=0, le=59)
    hour: int = Field(default=9, ge=0, le=23)
    weekdays: List[Weekday] = Field(default_factory=lambda: ["mon"])
    cron: Optional[str] = Field(default=None, max_length=120, description="5-field cron expression (mode=cron).")
    timezone: str = Field(default="UTC", max_length=64)
    enabled: bool = True
    misfire_policy: Literal["skip", "run_once"] = Field(
        default="skip", description="After downtime: skip missed runs, or run once to catch up.")

    @model_validator(mode="after")
    def _validate(self) -> "ScheduleTriggerConfig":
        from app.services.schedules import schedule_problems

        problems = schedule_problems(self)
        if problems:
            raise ValueError(problems[0])
        return self


# ---------------------------------------------------------------------------
# Flow and data nodes (Milestone 2): Switch, Merge, Loop Over Items, Date & Time, Array
# ---------------------------------------------------------------------------

RESERVED_SWITCH_PORTS = {"default", "main"}


class SwitchCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(..., pattern=r"^[a-z][a-z0-9_]{0,39}$",
                     description="Output port name for this case (lowercase letters, digits, underscore).")
    label: str = Field(default="", max_length=100)
    conditions: ConditionGroup


class SwitchConfig(_StrictConfig):
    """Switch: routes to the first matching case (or every matching case), else to 'default'."""

    cases: List[SwitchCase] = Field(..., min_length=1, max_length=20)
    mode: Literal["first", "all"] = "first"

    @model_validator(mode="after")
    def _validate(self) -> "SwitchConfig":
        keys = [c.key for c in self.cases]
        dupes = sorted({k for k in keys if keys.count(k) > 1})
        if dupes:
            raise ValueError(f"Case keys must be unique (duplicate: {', '.join(dupes)})")
        reserved = sorted(set(keys) & RESERVED_SWITCH_PORTS)
        if reserved:
            raise ValueError(f"'{reserved[0]}' is reserved; choose another case key")
        return self


class MergeConfig(_StrictConfig):
    """Merge: waits for its inputs (sequential synchronisation) and combines them."""

    inputs: int = Field(default=2, ge=2, le=5, description="Number of input ports (input_1 ... input_N).")
    mode: Literal["by_input", "append", "merge_objects"] = "by_input"
    require: Literal["all", "any"] = Field(
        default="all", description="all: fail when an input's branch did not run; any: merge what arrived.")


class LoopConfig(_StrictConfig):
    """Loop Over Items: runs the nodes connected to the 'item' output once per array element."""

    items: Any = Field(..., description="Array to iterate, usually a {{...}} reference.")
    max_items: int = Field(default=100, ge=1, le=10_000)
    on_item_error: Literal["stop", "continue"] = "stop"
    timeout_seconds: float = Field(default=300, gt=0, le=3600, description="Limit for the whole loop.")


class DateTimeConfig(_StrictConfig):
    operation: Literal["now", "format", "parse", "add", "subtract", "diff", "start_of"] = "now"
    value: Any = Field(default=None, description="ISO-8601 date/time or reference (not used by 'now').")
    other: Any = Field(default=None, description="Second date for 'diff' (other - value).")
    amount: Optional[float] = Field(default=None, ge=-1_000_000, le=1_000_000)
    unit: Literal["seconds", "minutes", "hours", "days", "weeks"] = "days"
    start_of: Literal["hour", "day", "week", "month"] = "day"
    timezone: str = Field(default="UTC", max_length=64)
    format: Optional[str] = Field(default=None, max_length=64, description="strftime format for 'format'.")

    @model_validator(mode="after")
    def _validate(self) -> "DateTimeConfig":
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown time zone '{self.timezone}'") from exc
        if self.operation in ("add", "subtract") and self.amount is None:
            raise ValueError(f"'{self.operation}' needs an amount")
        if self.operation in ("format", "parse", "add", "subtract", "diff", "start_of") and self.value in (None, ""):
            raise ValueError(f"'{self.operation}' needs a value")
        if self.operation == "diff" and self.other in (None, ""):
            raise ValueError("'diff' needs a second date in 'other'")
        return self


class ArrayConfig(_StrictConfig):
    items: Any = Field(..., description="Array, usually a {{...}} reference.")
    operation: Literal["sort", "limit", "unique", "pluck", "sum", "avg", "min", "max", "count", "flatten",
                       "chunk", "reverse"] = "count"
    field: Optional[str] = Field(default=None, max_length=200, description="Dot path inside each item.")
    order: Literal["asc", "desc"] = "asc"
    limit: Optional[int] = Field(default=None, ge=0, le=100_000)
    size: Optional[int] = Field(default=None, ge=1, le=10_000)

    @model_validator(mode="after")
    def _validate(self) -> "ArrayConfig":
        if self.operation == "pluck" and not self.field:
            raise ValueError("'pluck' needs a field")
        if self.operation == "limit" and self.limit is None:
            raise ValueError("'limit' needs a limit")
        if self.operation == "chunk" and not self.size:
            raise ValueError("'chunk' needs a size")
        return self
