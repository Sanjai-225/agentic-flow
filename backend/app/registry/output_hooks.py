"""``infer_output`` hooks for node definitions (static output-field hints).

A hook receives the node's raw config and returns either a list of expression
path suffixes (``.amount``, ``.body.items``, ``[0].id``) or
``PASSTHROUGH_OUTPUT`` when the node forwards its predecessor's output.
Aggregation over a workflow lives in ``app.engine.output_fields``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

PASSTHROUGH_OUTPUT = "__passthrough__"
MAX_DEPTH = 4
_SIMPLE_KEY = re.compile(r"^[A-Za-z0-9_\-$]+$")


def path_segment(key: str) -> str:
    """Render one object key as an expression path segment."""
    return f".{key}" if _SIMPLE_KEY.match(key) else f'["{key}"]'


def dotted_to_paths(dotted: str) -> List[str]:
    """``a.b.c`` -> ``['.a', '.a.b', '.a.b.c']`` (Set/Transform targets create nested objects)."""
    out: List[str] = []
    current = ""
    for part in [p.strip() for p in str(dotted).split(".") if p.strip()]:
        current += path_segment(part)
        out.append(current)
    return out


def paths_from_value(value: Any, prefix: str = "", depth: int = 0) -> List[str]:
    """Paths of a sample JSON value (e.g. the manual trigger's sample payload)."""
    out: List[str] = []
    if depth >= MAX_DEPTH:
        return out
    if isinstance(value, dict):
        for key, child in list(value.items())[:40]:
            path = prefix + path_segment(str(key))
            out.append(path)
            out.extend(paths_from_value(child, path, depth + 1))
    elif isinstance(value, list) and value:
        path = f"{prefix}[0]"
        out.append(path)
        out.extend(paths_from_value(value[0], path, depth + 1))
    return out


def infer_manual_trigger(config: Dict[str, Any]) -> List[str]:
    return paths_from_value(config.get("sample_payload") or {})


def infer_set(config: Dict[str, Any]) -> Any:
    paths: List[str] = []
    for f in config.get("fields") or []:
        if isinstance(f, dict) and str(f.get("name") or "").strip():
            target = dotted_to_paths(f["name"])
            paths.extend(target)
            if target and isinstance(f.get("value"), (dict, list)):
                paths.extend(paths_from_value(f["value"], target[-1]))
    if config.get("keep_input") and not paths:
        return PASSTHROUGH_OUTPUT
    return paths


def infer_transform(config: Dict[str, Any]) -> List[str]:
    paths: List[str] = []
    mappings = config.get("mappings") or {}
    if isinstance(mappings, dict):
        for target, value in mappings.items():
            target_paths = dotted_to_paths(target)
            paths.extend(target_paths)
            if target_paths and isinstance(value, (dict, list)):
                paths.extend(paths_from_value(value, target_paths[-1]))
    return paths


def infer_passthrough(config: Dict[str, Any]) -> str:
    return PASSTHROUGH_OUTPUT


def infer_end(config: Dict[str, Any]) -> Any:
    output = config.get("output")
    if output is None or output == "":
        return PASSTHROUGH_OUTPUT
    if isinstance(output, (dict, list)):
        return paths_from_value(output)
    return []


def _schema_paths(schema: Any, prefix: str, depth: int = 0) -> List[str]:
    out: List[str] = []
    if depth >= MAX_DEPTH or not isinstance(schema, dict):
        return out
    props = schema.get("properties")
    if isinstance(props, dict):
        for key, sub in props.items():
            path = prefix + path_segment(str(key))
            out.append(path)
            out.extend(_schema_paths(sub, path, depth + 1))
    items = schema.get("items")
    if isinstance(items, dict) and items.get("properties"):
        out.append(f"{prefix}[0]")
        out.extend(_schema_paths(items, f"{prefix}[0]", depth + 1))
    return out


def infer_ai(config: Dict[str, Any]) -> List[str]:
    """AI Generate / Agent: ``result`` (typed by the output schema) plus model metadata."""
    paths = [".result"]
    if isinstance(config.get("output_schema"), dict):
        paths.extend(_schema_paths(config["output_schema"], ".result"))
    paths.extend([".provider", ".model", ".usage", ".usage.input_tokens", ".usage.output_tokens",
                  ".usage.total_tokens"])
    if "instructions" in config:  # agent
        paths.extend([".fallback_used", ".iterations", ".tool_calls"])
    return paths
