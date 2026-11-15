"""Reference expression resolver.

Syntax: ``{{ <root>.<path> [| default(<json literal>)] }}``

Roots:
- ``nodes.<node_id>.output...``  output of an upstream node
- ``trigger...``                 output of the workflow's trigger node
- ``input...``                   output of the immediate active predecessor(s)
- ``item...``                    current item (Filter rules, Loop Over Items body)
- ``loop.index`` / ``loop.count`` position inside a Loop Over Items body
- ``execution.id`` / ``workflow.id`` / ``workflow.version`` / ``workflow.name``

Paths support ``.name``, ``[index]`` and ``["key"]`` segments. A string made of
exactly one expression keeps the referenced value's native type; expressions
embedded in longer strings are rendered as text.

This is a hand-written parser: nothing is ever passed to ``eval``. Only the
current execution's state (``ResolutionScope``) is visible.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple, Union

from app.core.errors import ErrorCategory, NodeExecutionError

EXPRESSION_RE = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
_WHOLE_RE = re.compile(r"^\s*\{\{(.*?)\}\}\s*$", re.DOTALL)
_DEFAULT_RE = re.compile(r"^(?P<path>.*?)\|\s*default\((?P<literal>.*)\)\s*$", re.DOTALL)
_NAME_CHARS = re.compile(r"[A-Za-z0-9_\-$]")

KNOWN_ROOTS = {"nodes", "trigger", "input", "item", "loop", "execution", "workflow"}
Segment = Union[str, int]


class _Missing:
    pass


MISSING = _Missing()


@dataclass
class ParsedExpression:
    raw: str
    root: str
    segments: List[Segment]
    has_default: bool = False
    default: Any = None

    @property
    def node_id(self) -> Optional[str]:
        if self.root == "nodes" and self.segments:
            return str(self.segments[0])
        return None


@dataclass
class ResolutionScope:
    """Everything an expression may read for one node of one execution."""

    node_outputs: Mapping[str, Any] = field(default_factory=dict)
    node_statuses: Mapping[str, str] = field(default_factory=dict)
    all_node_ids: Set[str] = field(default_factory=set)
    ancestors: Optional[Set[str]] = None  # None disables the upstream check
    trigger_node_id: Optional[str] = None
    upstream: Any = None
    execution: Dict[str, Any] = field(default_factory=dict)
    workflow: Dict[str, Any] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)


def suggest_node_id(ref: str, candidates: Iterable[str]) -> Optional[str]:
    """Closest existing node id to ``ref`` (for "Did you mean ...?" hints), or None."""
    pool = sorted(set(candidates))
    matches = difflib.get_close_matches(ref, pool, n=1, cutoff=0.6)
    if matches:
        return matches[0]
    lowered = {c.lower(): c for c in pool}
    return lowered.get(ref.lower())


def unknown_node_suggestion(ref: str, candidates: Iterable[str]) -> str:
    """User-facing suggestion text for a reference to a node id that does not exist."""
    pool = sorted(set(candidates))
    close = suggest_node_id(ref, pool)
    if close:
        return f"Did you mean '{close}'? Use {{{{nodes.{close}.output...}}}}."
    listed = ", ".join(pool[:12]) + (" ..." if len(pool) > 12 else "")
    return f"Node ids are case-sensitive. Existing nodes: {listed}." if pool else "This workflow has no nodes yet."


def _syntax_error(raw: str, message: str, field_path: Optional[str]) -> NodeExecutionError:
    return NodeExecutionError(
        ErrorCategory.INVALID_MAPPING,
        f"Invalid expression '{{{{{raw.strip()}}}}}': {message}",
        field=field_path,
        details={"expression": raw.strip()},
    )


def parse_path(text: str, raw: str, field_path: Optional[str] = None) -> Tuple[str, List[Segment]]:
    text = text.strip()
    i = 0
    n = len(text)

    def read_name() -> str:
        nonlocal i
        start = i
        while i < n and _NAME_CHARS.match(text[i]):
            i += 1
        if start == i:
            raise _syntax_error(raw, f"expected a name at position {start}", field_path)
        return text[start:i]

    root = read_name()
    segments: List[Segment] = []
    while i < n:
        ch = text[i]
        if ch == ".":
            i += 1
            segments.append(read_name())
        elif ch == "[":
            close = text.find("]", i)
            if close == -1:
                raise _syntax_error(raw, "unclosed '['", field_path)
            inner = text[i + 1 : close].strip()
            i = close + 1
            if len(inner) >= 2 and inner[0] == inner[-1] and inner[0] in "\"'":
                segments.append(inner[1:-1])
            elif re.fullmatch(r"-?\d+", inner):
                segments.append(int(inner))
            else:
                raise _syntax_error(raw, f"invalid index '[{inner}]'", field_path)
        elif ch.isspace():
            raise _syntax_error(raw, "unexpected whitespace inside path", field_path)
        else:
            raise _syntax_error(raw, f"unexpected character '{ch}'", field_path)
    return root, segments


def parse_expression(raw: str, field_path: Optional[str] = None) -> ParsedExpression:
    body = raw.strip()
    if not body:
        raise _syntax_error(raw, "empty expression", field_path)
    has_default = False
    default: Any = None
    match = _DEFAULT_RE.match(body)
    if match:
        has_default = True
        literal = match.group("literal").strip()
        try:
            default = json.loads(literal) if literal else None
        except json.JSONDecodeError as exc:
            raise _syntax_error(raw, f"default(...) must be a JSON literal ({exc.msg})", field_path) from exc
        body = match.group("path")
    root, segments = parse_path(body, raw, field_path)
    if root not in KNOWN_ROOTS:
        raise _syntax_error(
            raw, f"unknown root '{root}'. Use one of: {', '.join(sorted(KNOWN_ROOTS))}", field_path
        )
    if root == "nodes":
        if len(segments) < 2 or not isinstance(segments[0], str) or segments[1] != "output":
            raise _syntax_error(raw, "node references must look like nodes.<node_id>.output[...]", field_path)
    return ParsedExpression(raw=raw, root=root, segments=segments, has_default=has_default, default=default)


def contains_expression(value: Any) -> bool:
    if isinstance(value, str):
        return bool(EXPRESSION_RE.search(value))
    if isinstance(value, dict):
        return any(contains_expression(v) for v in value.values())
    if isinstance(value, list):
        return any(contains_expression(v) for v in value)
    return False


def iter_expressions(value: Any, field_path: str = "") -> List[Tuple[str, str]]:
    """Return ``(field_path, raw_expression)`` pairs found anywhere in ``value``."""
    found: List[Tuple[str, str]] = []
    if isinstance(value, str):
        for m in EXPRESSION_RE.finditer(value):
            found.append((field_path, m.group(1)))
    elif isinstance(value, dict):
        for k, v in value.items():
            found.extend(iter_expressions(v, f"{field_path}.{k}" if field_path else str(k)))
    elif isinstance(value, list):
        for idx, v in enumerate(value):
            found.extend(iter_expressions(v, f"{field_path}[{idx}]"))
    return found


def _fmt_path(root: str, segments: List[Segment]) -> str:
    out = root
    for seg in segments:
        out += f"[{seg}]" if isinstance(seg, int) else f".{seg}"
    return out


def _traverse(value: Any, segments: List[Segment], prefix: str, expr: ParsedExpression,
              field_path: Optional[str]) -> Any:
    current = value
    walked = prefix
    for seg in segments:
        if current is None:
            raise NodeExecutionError(
                ErrorCategory.MISSING_INPUT,
                f"Cannot read '{seg}' because '{walked}' is null (expression {{{{{expr.raw.strip()}}}}}).",
                field=field_path,
                details={"expression": expr.raw.strip(), "null_at": walked},
            )
        if isinstance(current, dict):
            key = str(seg)
            if key not in current:
                return MISSING
            current = current[key]
        elif isinstance(current, list):
            if isinstance(seg, str) and not seg.lstrip("-").isdigit():
                raise NodeExecutionError(
                    ErrorCategory.MISSING_INPUT,
                    f"'{walked}' is a list; use a numeric index instead of '{seg}' "
                    f"(expression {{{{{expr.raw.strip()}}}}}).",
                    field=field_path,
                    details={"expression": expr.raw.strip()},
                )
            idx = int(seg)
            if idx < -len(current) or idx >= len(current):
                return MISSING
            current = current[idx]
        else:
            raise NodeExecutionError(
                ErrorCategory.MISSING_INPUT,
                f"Cannot read '{seg}' of a {type(current).__name__} value at '{walked}' "
                f"(expression {{{{{expr.raw.strip()}}}}}).",
                field=field_path,
                details={"expression": expr.raw.strip()},
            )
        walked += f"[{seg}]" if isinstance(seg, int) else f".{seg}"
    return current


def evaluate(expr: ParsedExpression, scope: ResolutionScope, field_path: Optional[str] = None) -> Any:
    raw = expr.raw.strip()
    if expr.root == "nodes":
        node_id = str(expr.segments[0])
        if node_id not in scope.all_node_ids:
            candidates = scope.ancestors if scope.ancestors else scope.all_node_ids
            raise NodeExecutionError(
                ErrorCategory.INVALID_MAPPING,
                f"Expression {{{{{raw}}}}} references node '{node_id}', which does not exist in this workflow.",
                field=field_path,
                suggestion=unknown_node_suggestion(node_id, candidates),
                details={"expression": raw, "node_id": node_id},
            )
        if scope.ancestors is not None and node_id not in scope.ancestors:
            raise NodeExecutionError(
                ErrorCategory.INVALID_MAPPING,
                f"Expression {{{{{raw}}}}} references node '{node_id}', which does not run before this node.",
                field=field_path,
                details={"expression": raw, "node_id": node_id},
            )
        if node_id not in scope.node_outputs:
            status = scope.node_statuses.get(node_id, "pending")
            reason = "was skipped because its branch was not taken" if status == "skipped" else f"has status '{status}'"
            raise NodeExecutionError(
                ErrorCategory.INVALID_MAPPING,
                f"Expression {{{{{raw}}}}} references node '{node_id}', which {reason}, so it has no output.",
                field=field_path,
                details={"expression": raw, "node_id": node_id, "node_status": status},
            )
        base = scope.node_outputs[node_id]
        segments = expr.segments[2:]
        prefix = f"nodes.{node_id}.output"
    elif expr.root == "trigger":
        if not scope.trigger_node_id or scope.trigger_node_id not in scope.node_outputs:
            raise NodeExecutionError(
                ErrorCategory.INVALID_MAPPING, f"Expression {{{{{raw}}}}}: the trigger has no output yet.",
                field=field_path, details={"expression": raw},
            )
        base, segments, prefix = scope.node_outputs[scope.trigger_node_id], expr.segments, "trigger"
    elif expr.root == "input":
        base, segments, prefix = scope.upstream, expr.segments, "input"
    elif expr.root == "item":
        if "item" not in scope.extra:
            raise NodeExecutionError(
                ErrorCategory.INVALID_MAPPING,
                f"Expression {{{{{raw}}}}}: 'item' is only available inside Filter rules and loop bodies.",
                field=field_path, details={"expression": raw},
            )
        base, segments, prefix = scope.extra["item"], expr.segments, "item"
    elif expr.root == "loop":
        if "loop" not in scope.extra:
            raise NodeExecutionError(
                ErrorCategory.INVALID_MAPPING,
                f"Expression {{{{{raw}}}}}: 'loop' is only available inside a Loop Over Items body.",
                field=field_path, details={"expression": raw},
            )
        base, segments, prefix = scope.extra["loop"], expr.segments, "loop"
    elif expr.root == "execution":
        base, segments, prefix = scope.execution, expr.segments, "execution"
    else:  # workflow
        base, segments, prefix = scope.workflow, expr.segments, "workflow"

    value = _traverse(base, segments, prefix, expr, field_path)
    if value is MISSING or (value is None and expr.has_default):
        if expr.has_default:
            return expr.default
        raise NodeExecutionError(
            ErrorCategory.MISSING_INPUT,
            f"Expression {{{{{raw}}}}} could not be resolved: '{_fmt_path(prefix, segments)}' does not exist.",
            field=field_path,
            suggestion="Check the upstream output in the execution inspector, or add | default(<value>).",
            details={"expression": raw},
        )
    return value


def to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    return str(value)


def resolve_string(text: str, scope: ResolutionScope, field_path: Optional[str] = None) -> Any:
    whole = _WHOLE_RE.match(text)
    if whole and text.count("{{") == 1:
        return evaluate(parse_expression(whole.group(1), field_path), scope, field_path)
    if "{{" not in text:
        return text

    def _sub(match: re.Match[str]) -> str:
        return to_text(evaluate(parse_expression(match.group(1), field_path), scope, field_path))

    return EXPRESSION_RE.sub(_sub, text)


def resolve_value(value: Any, scope: ResolutionScope, field_path: str = "",
                  skip_keys: Optional[Set[str]] = None) -> Any:
    """Recursively resolve expressions inside ``value``.

    ``skip_keys`` lists top-level keys left untouched (lazy fields).
    """
    if isinstance(value, str):
        return resolve_string(value, scope, field_path or None)
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            if skip_keys and not field_path and k in skip_keys:
                out[k] = v
                continue
            out[k] = resolve_value(v, scope, f"{field_path}.{k}" if field_path else str(k))
        return out
    if isinstance(value, list):
        return [resolve_value(v, scope, f"{field_path}[{i}]") for i, v in enumerate(value)]
    return value
