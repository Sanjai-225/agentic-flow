"""Form Submission Trigger: public definition, server-side validation and endpoint sync.

Every form gets an unguessable public id (``frm_`` + 128 bits). The public API exposes only the sanitised
form definition (title, description, fields, labels) - never the workflow, its nodes, owner or config.
Submissions are validated here regardless of any browser-side validation.
"""

from __future__ import annotations

import math
import secrets
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional, Tuple

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Workflow, WorkflowForm
from app.schemas.workflow import WorkflowSchema

FORM_OPERATION = "core.form_trigger"
HONEYPOT_FIELD = "_hp"
_TRUE = {True, "true", "on", "yes", "1"}
_FALSE = {False, "false", "off", "no", "0", "", None}


def new_form_id() -> str:
    return "frm_" + secrets.token_urlsafe(16)


def public_definition(form_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
    fields = []
    for f in config.get("fields") or []:
        fields.append({k: f.get(k) for k in ("key", "label", "type", "required", "placeholder", "help", "options",
                                             "min", "max", "min_length", "max_length") if f.get(k) not in (None, [])}
                      | {"required": bool(f.get("required", False)), "type": f.get("type", "text")})
    return {"form_id": form_id, "title": config.get("title", "Form"), "description": config.get("description", ""),
            "submit_label": config.get("submit_label", "Submit"), "fields": fields,
            "honeypot_field": HONEYPOT_FIELD}


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def validate_submission(config: Dict[str, Any], data: Any) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Return (clean submission, {field_key: error}). The clean values are typed (number, bool, str)."""
    errors: Dict[str, str] = {}
    if not isinstance(data, dict):
        return {}, {"_form": "The submission must be a JSON object of field values."}
    fields = {f["key"]: f for f in config.get("fields") or []}
    unknown = sorted(k for k in data if k not in fields and k != HONEYPOT_FIELD)
    if unknown:
        errors["_form"] = f"Unknown field(s): {', '.join(unknown[:5])}."
    clean: Dict[str, Any] = {}
    for key, spec in fields.items():
        ftype, label = spec.get("type", "text"), spec.get("label", key)
        raw = data.get(key)
        if ftype == "checkbox":
            if raw in _TRUE:
                clean[key] = True
            elif raw in _FALSE:
                clean[key] = False
            else:
                errors[key] = f"{label} must be checked or unchecked."
                continue
            if spec.get("required") and not clean[key]:
                errors[key] = f"{label} must be checked."
            continue
        empty = raw is None or (isinstance(raw, str) and not raw.strip())
        if empty:
            if spec.get("required"):
                errors[key] = f"{label} is required."
            else:
                clean[key] = None
            continue
        if isinstance(raw, (dict, list)):
            errors[key] = f"{label} must be a single value."
            continue
        if ftype == "number":
            number = _number(raw)
            if number is None:
                errors[key] = f"{label} must be a number."
                continue
            if spec.get("min") is not None and number < spec["min"]:
                errors[key] = f"{label} must be at least {spec['min']:g}."
                continue
            if spec.get("max") is not None and number > spec["max"]:
                errors[key] = f"{label} must be at most {spec['max']:g}."
                continue
            clean[key] = int(number) if number.is_integer() else number
            continue
        text = str(raw).strip()
        if ftype == "email":
            try:
                text = validate_email(text, check_deliverability=False).normalized
            except EmailNotValidError:
                errors[key] = f"{label} must be a valid email address."
                continue
        elif ftype == "select":
            if text not in (spec.get("options") or []):
                errors[key] = f"{label} must be one of the listed options."
                continue
        max_length = spec.get("max_length") or (5000 if ftype == "textarea" else 500)
        if len(text) > max_length:
            errors[key] = f"{label} must be at most {max_length} characters."
            continue
        if spec.get("min_length") and len(text) < spec["min_length"]:
            errors[key] = f"{label} must be at least {spec['min_length']} characters."
            continue
        clean[key] = text
    return clean, errors


def build_payload(form_id: str, submission: Dict[str, Any]) -> Dict[str, Any]:
    """Trigger output: ``{submission: {...configured fields...}, submitted_at, form_id}``."""
    return {"submission": submission, "submitted_at": datetime.now(UTC).isoformat(), "form_id": form_id}


def form_nodes(workflow: WorkflowSchema) -> List[Any]:
    return [n for n in workflow.nodes if n.operation == FORM_OPERATION]


async def sync_forms(session: AsyncSession, record: Workflow, workflow: WorkflowSchema) -> None:
    """Keep one public form endpoint per Form Trigger node (ids are stable across saves)."""
    node_ids = {n.id for n in form_nodes(workflow)}
    rows = (await session.execute(select(WorkflowForm).where(WorkflowForm.workflow_id == record.id))).scalars()
    existing = {r.node_id: r for r in rows}
    for node_id in set(existing) - node_ids:
        await session.execute(delete(WorkflowForm).where(WorkflowForm.id == existing[node_id].id))
    for node_id in node_ids - set(existing):
        session.add(WorkflowForm(id=new_form_id(), workflow_id=record.id, user_id=record.user_id, node_id=node_id,
                                 enabled=True))
