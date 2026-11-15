"""Built-in agent tools. All are real executors; none executes model-generated code.

| id              | permission | side effects | purpose                                              |
|-----------------|------------|--------------|------------------------------------------------------|
| calculator      | read_only  | no           | exact arithmetic via a safe parser                   |
| datetime        | read_only  | no           | now / format / parse / add / diff with time zones    |
| json_tools      | read_only  | no           | parse JSON text, read a path, validate a JSON schema |
| text_tools      | read_only  | no           | length, word count, case, find/replace, split, ...   |
| data_aggregate  | read_only  | no           | sum/avg/min/max/count/group over a list of records   |
| http_get        | network    | no           | read-only HTTP GET with SSRF protection and limits   |
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, UTC
from typing import Any, Dict, List, Literal, Optional, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ai.tools import ToolContext, ToolDefinition
from app.ai.tools.calculator import CalculatorError, evaluate_expression
from app.core.config import get_settings
from app.core.errors import NodeExecutionError
from app.core.net import ensure_url_allowed


class ToolInputError(ValueError):
    """Raised by a tool for bad (but schema-valid) input; reported to the model as a tool error."""


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Out(BaseModel):
    model_config = ConfigDict(extra="allow")


# --------------------------------------------------------------------------- calculator
class CalculatorInput(_In):
    expression: str = Field(..., min_length=1, max_length=500,
                            description="Arithmetic expression, e.g. '(1200 + 349.5) * 0.18'. Supports + - * / // % "
                                        "**, parentheses, abs, round, min, max, sum, avg, sqrt, floor, ceil, log, "
                                        "log10, pi, e.")


class CalculatorOutput(_Out):
    expression: str
    result: Union[int, float]


async def _calculator(args: CalculatorInput, ctx: ToolContext) -> Dict[str, Any]:
    try:
        return {"expression": args.expression, "result": evaluate_expression(args.expression)}
    except CalculatorError as exc:
        raise ToolInputError(str(exc)) from exc


# --------------------------------------------------------------------------- datetime
class DateTimeInput(_In):
    operation: Literal["now", "format", "parse", "add", "diff"]
    timezone: str = Field("UTC", description="IANA time zone, e.g. 'Europe/Berlin'.")
    value: Optional[str] = Field(None, description="ISO-8601 date/time (format, parse, add, diff).")
    other: Optional[str] = Field(None, description="Second ISO-8601 date/time (diff: other - value).")
    amount: Optional[float] = Field(None, description="Amount to add (add); negative subtracts.")
    unit: Literal["seconds", "minutes", "hours", "days", "weeks"] = "days"
    format: Optional[str] = Field(None, max_length=64, description="strftime format, e.g. '%Y-%m-%d'.")


class DateTimeOutput(_Out):
    result: Any


def _tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ToolInputError(f"Unknown time zone {name!r}.") from exc


def _parse_dt(text: Optional[str], tz: ZoneInfo, label: str) -> datetime:
    if not text:
        raise ToolInputError(f"'{label}' is required for this operation.")
    try:
        parsed = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ToolInputError(f"'{label}' is not an ISO-8601 date/time: {text!r}.") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)


async def _datetime(args: DateTimeInput, ctx: ToolContext) -> Dict[str, Any]:
    tz = _tz(args.timezone)
    if args.operation == "now":
        return {"result": datetime.now(UTC).astimezone(tz).isoformat()}
    value = _parse_dt(args.value, tz, "value")
    if args.operation == "parse":
        return {"result": {"iso": value.isoformat(), "year": value.year, "month": value.month, "day": value.day,
                           "weekday": value.strftime("%A"), "timestamp": value.timestamp()}}
    if args.operation == "format":
        try:
            return {"result": value.astimezone(tz).strftime(args.format or "%Y-%m-%d %H:%M:%S %Z")}
        except ValueError as exc:
            raise ToolInputError(f"Invalid format: {exc}") from exc
    if args.operation == "add":
        if args.amount is None:
            raise ToolInputError("'amount' is required for add.")
        if abs(args.amount) > 1_000_000:
            raise ToolInputError("'amount' is too large.")
        return {"result": (value + timedelta(**{args.unit: args.amount})).isoformat()}
    other = _parse_dt(args.other, tz, "other")
    seconds = (other - value).total_seconds()
    factor = {"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400, "weeks": 604800}[args.unit]
    return {"result": round(seconds / factor, 6)}


# --------------------------------------------------------------------------- json
class JsonToolInput(_In):
    operation: Literal["parse", "get", "validate"]
    text: Optional[str] = Field(None, max_length=200_000, description="JSON text (parse).")
    data: Optional[Any] = Field(None, description="Structured data (get, validate).")
    path: Optional[str] = Field(None, max_length=200, description="Dot path for get, e.g. 'items.0.price'.")
    json_schema: Optional[Dict[str, Any]] = Field(None, description="JSON Schema (validate).")


class JsonToolOutput(_Out):
    result: Any = None
    valid: Optional[bool] = None
    errors: Optional[List[str]] = None


async def _json_tools(args: JsonToolInput, ctx: ToolContext) -> Dict[str, Any]:
    if args.operation == "parse":
        if args.text is None:
            raise ToolInputError("'text' is required for parse.")
        try:
            return {"result": json.loads(args.text)}
        except json.JSONDecodeError as exc:
            raise ToolInputError(f"Invalid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}.") from exc
    if args.operation == "get":
        current = args.data
        for part in [p for p in (args.path or "").split(".") if p]:
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif isinstance(current, list) and part.lstrip("-").isdigit() and -len(current) <= int(part) < len(current):
                current = current[int(part)]
            else:
                raise ToolInputError(f"Path segment {part!r} not found.")
        return {"result": current}
    if args.json_schema is None:
        raise ToolInputError("'json_schema' is required for validate.")
    try:
        Draft202012Validator.check_schema(args.json_schema)
    except SchemaError as exc:
        raise ToolInputError(f"Invalid JSON Schema: {exc.message}") from exc
    errors = [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}"
              for e in list(Draft202012Validator(args.json_schema).iter_errors(args.data))[:20]]
    return {"valid": not errors, "errors": errors}


# --------------------------------------------------------------------------- text
class TextToolInput(_In):
    operation: Literal["length", "word_count", "upper", "lower", "title", "trim", "replace", "split",
                       "truncate", "contains", "count_occurrences"]
    text: str = Field(..., max_length=200_000)
    find: Optional[str] = Field(None, max_length=1000, description="Substring for replace/contains/count.")
    replace_with: Optional[str] = Field(None, max_length=1000)
    separator: Optional[str] = Field(None, max_length=50, description="Separator for split (default: whitespace).")
    max_length: Optional[int] = Field(None, ge=1, le=200_000, description="Length for truncate.")
    case_sensitive: bool = True


class TextToolOutput(_Out):
    result: Any


async def _text_tools(args: TextToolInput, ctx: ToolContext) -> Dict[str, Any]:
    text, op = args.text, args.operation
    if op == "length":
        return {"result": len(text)}
    if op == "word_count":
        return {"result": len(text.split())}
    if op in ("upper", "lower", "title", "trim"):
        return {"result": {"upper": text.upper, "lower": text.lower, "title": text.title, "trim": text.strip}[op]()}
    if op == "split":
        parts = text.split(args.separator) if args.separator else text.split()
        return {"result": parts[:5000]}
    if op == "truncate":
        if not args.max_length:
            raise ToolInputError("'max_length' is required for truncate.")
        return {"result": text[: args.max_length]}
    if not args.find:
        raise ToolInputError(f"'find' is required for {op}.")
    haystack, needle = (text, args.find) if args.case_sensitive else (text.lower(), args.find.lower())
    if op == "contains":
        return {"result": needle in haystack}
    if op == "count_occurrences":
        return {"result": haystack.count(needle)}
    if not args.case_sensitive:
        raise ToolInputError("replace is always case-sensitive.")
    return {"result": text.replace(args.find, args.replace_with or "")}


# --------------------------------------------------------------------------- data aggregate
class DataAggregateInput(_In):
    # Typed items (object or number) give every provider an explicit item schema; with untyped items some
    # models (observed live with Gemini) send each record as a JSON-encoded string instead of an object.
    records: List[Union[Dict[str, Any], float]] = Field(
        ..., max_length=10_000, description="List of records (JSON objects, not strings) or plain numbers.")

    @field_validator("records", mode="before")
    @classmethod
    def _decode_json_strings(cls, value: Any) -> Any:
        """Accept records that a model JSON-encoded as strings (decoded strictly; anything else still fails)."""
        if not isinstance(value, list):
            return value
        out = []
        for item in value:
            if isinstance(item, str):
                try:
                    decoded = json.loads(item)
                except json.JSONDecodeError:
                    out.append(item)
                    continue
                out.append(decoded if isinstance(decoded, (dict, int, float)) and not isinstance(decoded, bool)
                           else item)
            else:
                out.append(item)
        return out
    operation: Literal["sum", "avg", "min", "max", "count", "count_by", "sum_by"]
    field: Optional[str] = Field(None, max_length=200, description="Numeric field (dot path) to aggregate.")
    group_by: Optional[str] = Field(None, max_length=200, description="Field (dot path) to group by.")


class DataAggregateOutput(_Out):
    result: Any
    count: int


def _get(record: Any, path: Optional[str]) -> Any:
    if not path:
        return record
    current = record
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _number(value: Any, index: int, field: Optional[str]) -> float:
    if isinstance(value, bool) or value is None:
        raise ToolInputError(f"Record {index}: field {field!r} is not a number ({value!r}).")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ToolInputError(f"Record {index}: field {field!r} is not a number ({value!r}).") from exc


def _tidy(value: float) -> Union[int, float]:
    return int(value) if float(value).is_integer() else round(value, 10)


async def _data_aggregate(args: DataAggregateInput, ctx: ToolContext) -> Dict[str, Any]:
    records, op = args.records, args.operation
    if op == "count":
        return {"result": len(records), "count": len(records)}
    if op in ("count_by", "sum_by"):
        if not args.group_by:
            raise ToolInputError(f"'group_by' is required for {op}.")
        groups: Dict[str, float] = {}
        for i, record in enumerate(records):
            key = str(_get(record, args.group_by))
            groups[key] = groups.get(key, 0) + (1 if op == "count_by" else _number(_get(record, args.field), i, args.field))
        return {"result": {k: _tidy(v) for k, v in groups.items()}, "count": len(records)}
    values = [_number(_get(r, args.field), i, args.field) for i, r in enumerate(records)]
    if not values:
        raise ToolInputError("There are no records to aggregate.")
    result = {"sum": sum(values), "avg": sum(values) / len(values), "min": min(values), "max": max(values)}[op]
    return {"result": _tidy(result), "count": len(values)}


# --------------------------------------------------------------------------- http_get
class HttpGetInput(_In):
    url: str = Field(..., min_length=8, max_length=2000, description="http(s) URL to fetch with GET.")
    query: Dict[str, str] = Field(default_factory=dict, description="Query string parameters.")


class HttpGetOutput(_Out):
    status_code: int
    content_type: str
    body: Any
    truncated: bool


HTTP_TOOL_MAX_BYTES = 1_000_000
HTTP_TOOL_MAX_TEXT = 20_000
HTTP_TOOL_MAX_REDIRECTS = 3


async def _http_get(args: HttpGetInput, ctx: ToolContext) -> Dict[str, Any]:
    settings = get_settings()
    allow_private = settings.HTTP_ALLOW_PRIVATE_NETWORKS
    try:
        url = httpx.URL(args.url.strip())
    except (httpx.InvalidURL, TypeError) as exc:
        raise ToolInputError(f"Invalid URL: {exc}") from exc
    headers = {"User-Agent": "AgenticFlow-Agent/1.0 (read-only)", "Accept": "application/json, text/*;q=0.9"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(8.0), follow_redirects=False) as client:
        current = url
        response: Optional[httpx.Response] = None
        for hop in range(HTTP_TOOL_MAX_REDIRECTS + 1):
            try:
                await ensure_url_allowed(current, allow_private)  # re-checked on every redirect hop (SSRF)
            except NodeExecutionError as exc:
                raise ToolInputError(exc.error.message) from exc
            request = client.build_request("GET", current, headers=headers, params=args.query if hop == 0 else None)
            response = await client.send(request, stream=True)
            if response.is_redirect and hop < HTTP_TOOL_MAX_REDIRECTS:
                location = response.headers.get("location", "")
                await response.aclose()
                current = current.join(location)
                continue
            break
        assert response is not None
        chunks, total, truncated = [], 0, False
        try:
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > HTTP_TOOL_MAX_BYTES:
                    truncated = True
                    break
                chunks.append(chunk)
        finally:
            await response.aclose()
    raw = b"".join(chunks)
    text = raw.decode(response.encoding or "utf-8", errors="replace")
    content_type = response.headers.get("content-type", "")
    body: Any = text
    if "json" in content_type and not truncated:
        try:
            body = json.loads(text)
        except json.JSONDecodeError:
            body = text
    if isinstance(body, str) and len(body) > HTTP_TOOL_MAX_TEXT:
        body, truncated = body[:HTTP_TOOL_MAX_TEXT], True
    return {"status_code": response.status_code, "content_type": content_type, "body": body, "truncated": truncated}


class BuiltinToolProvider:
    id = "builtin"

    def list_tools(self) -> List[ToolDefinition]:
        return [
            ToolDefinition(id="calculator", name="calculator", input_model=CalculatorInput,
                           output_model=CalculatorOutput, execute=_calculator, timeout_seconds=5,
                           description="Evaluate an arithmetic expression exactly. Use it for any calculation "
                                       "instead of computing in your head.", tags=["math"]),
            ToolDefinition(id="datetime", name="datetime", input_model=DateTimeInput, output_model=DateTimeOutput,
                           execute=_datetime, timeout_seconds=5,
                           description="Current date/time, parse/format ISO dates, add durations, or compute the "
                                       "difference between two dates, in any IANA time zone.", tags=["date"]),
            ToolDefinition(id="json_tools", name="json_tools", input_model=JsonToolInput, output_model=JsonToolOutput,
                           execute=_json_tools, timeout_seconds=5,
                           description="Parse JSON text, read a value by dot path, or validate data against a "
                                       "JSON Schema.", tags=["json", "data"]),
            ToolDefinition(id="text_tools", name="text_tools", input_model=TextToolInput, output_model=TextToolOutput,
                           execute=_text_tools, timeout_seconds=5,
                           description="Deterministic text operations: length, word count, case changes, trim, "
                                       "find/replace, split, truncate, contains, count occurrences.", tags=["text"]),
            ToolDefinition(id="data_aggregate", name="data_aggregate", input_model=DataAggregateInput,
                           output_model=DataAggregateOutput, execute=_data_aggregate, timeout_seconds=5,
                           description="Aggregate a list of records: sum, avg, min, max or count of a numeric field, "
                                       "or count/sum grouped by a field. Fields use dot paths.", tags=["data", "math"]),
            ToolDefinition(id="http_get", name="http_get", input_model=HttpGetInput, output_model=HttpGetOutput,
                           execute=_http_get, timeout_seconds=12, permission="network",
                           description="Fetch a public URL with a read-only HTTP GET (no credentials). Private and "
                                       "local network addresses are blocked; responses are size-limited.",
                           tags=["http", "network"]),
        ]
