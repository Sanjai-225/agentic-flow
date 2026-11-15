"""Schedule Trigger: spec compilation, validation, next-run computation and persistence sync.

Schedules are stored in ``workflow_schedules`` (one row per Schedule Trigger node) so they survive restarts.
Times are computed in the schedule's IANA time zone (DST-aware via croniter + zoneinfo) and stored in UTC.
"""

from __future__ import annotations

from datetime import datetime, timedelta, UTC
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import Workflow, WorkflowSchedule
from app.schemas.workflow import WorkflowSchema

SCHEDULE_OPERATION = "core.schedule_trigger"
_DAY_NUM = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}


def utcnow() -> datetime:
    return datetime.now(UTC)


def _get(config: Any, key: str, default: Any = None) -> Any:
    return config.get(key, default) if isinstance(config, dict) else getattr(config, key, default)


def compile_spec(config: Any) -> Tuple[str, Any]:
    """('interval', minutes) or ('cron', expression) for a Schedule Trigger config (dict or model)."""
    mode = _get(config, "mode", "daily")
    minute, hour = int(_get(config, "minute", 0)), int(_get(config, "hour", 9))
    if mode == "interval":
        return "interval", int(_get(config, "interval_minutes", 15))
    if mode == "hourly":
        return "cron", f"{minute} * * * *"
    if mode == "daily":
        return "cron", f"{minute} {hour} * * *"
    if mode == "weekdays":
        return "cron", f"{minute} {hour} * * 1-5"
    if mode == "weekly":
        days = ",".join(str(_DAY_NUM[d]) for d in sorted(set(_get(config, "weekdays", []) or []),
                                                          key=lambda d: _DAY_NUM[d]))
        return "cron", f"{minute} {hour} * * {days}"
    return "cron", str(_get(config, "cron", "") or "").strip()


def zone(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def schedule_problems(config: Any) -> List[str]:
    problems: List[str] = []
    tz_name = str(_get(config, "timezone", "UTC") or "")
    try:
        zone(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        problems.append(f"Unknown time zone '{tz_name}'. Use an IANA name such as 'Europe/Berlin' or 'UTC'.")
    mode = _get(config, "mode", "daily")
    if mode == "weekly" and not (_get(config, "weekdays") or []):
        problems.append("Weekly schedules need at least one weekday.")
    if mode == "interval":
        minimum = get_settings().SCHEDULE_MIN_INTERVAL_MINUTES
        if int(_get(config, "interval_minutes", 15)) < minimum:
            problems.append(f"The interval must be at least {minimum} minute(s).")
    if mode == "cron":
        expression = str(_get(config, "cron", "") or "").strip()
        if not expression:
            problems.append("Cron mode needs a cron expression, e.g. '*/15 * * * *'.")
        elif len(expression.split()) != 5 or not croniter.is_valid(expression):
            problems.append(f"'{expression}' is not a valid 5-field cron expression (minute hour day month weekday).")
        else:
            # Reject expressions that fire more often than the minimum interval allows.
            it = croniter(expression, datetime(2026, 1, 5, tzinfo=UTC))
            first, second = it.get_next(datetime), it.get_next(datetime)
            minimum = get_settings().SCHEDULE_MIN_INTERVAL_MINUTES
            if (second - first) < timedelta(minutes=minimum):
                problems.append(f"The cron expression fires more often than every {minimum} minute(s).")
    return problems


def next_runs(config: Any, after: datetime, count: int = 1, anchor: Optional[datetime] = None) -> List[datetime]:
    """Next ``count`` run times strictly after ``after`` (UTC-aware results)."""
    after = after.astimezone(UTC)
    kind, value = compile_spec(config)
    out: List[datetime] = []
    if kind == "interval":
        step = timedelta(minutes=int(value))
        base = (anchor or after).astimezone(UTC).replace(second=0, microsecond=0)
        current = base
        if current <= after:
            periods = int((after - current) / step) + 1
            current = current + periods * step
        for _ in range(count):
            out.append(current)
            current += step
        return out
    tz = zone(str(_get(config, "timezone", "UTC")))
    it = croniter(value, after.astimezone(tz))
    for _ in range(count):
        out.append(it.get_next(datetime).astimezone(UTC))
    return out


def schedule_nodes(workflow: WorkflowSchema) -> List[Any]:
    return [n for n in workflow.nodes if n.operation == SCHEDULE_OPERATION]


async def sync_schedules(session: AsyncSession, record: Workflow, workflow: WorkflowSchema) -> None:
    """Upsert one schedule row per Schedule Trigger node; drop rows whose node disappeared.

    A changed spec or time zone recomputes ``next_run_at``; an unchanged one keeps it (so saving a workflow
    does not shift or duplicate an upcoming occurrence). Invalid configs are stored disabled (the planner
    reports the problem).
    """
    nodes = {n.id: n for n in schedule_nodes(workflow)}
    rows = (await session.execute(select(WorkflowSchedule).where(WorkflowSchedule.workflow_id == record.id))).scalars()
    existing = {r.node_id: r for r in rows}
    for node_id in set(existing) - set(nodes):
        await session.execute(delete(WorkflowSchedule).where(WorkflowSchedule.id == existing[node_id].id))
    now = utcnow()
    for node_id, node in nodes.items():
        config: Dict[str, Any] = dict(node.config or {})
        valid = not schedule_problems(config)
        tz_name = str(config.get("timezone", "UTC"))
        enabled = bool(config.get("enabled", True)) and valid
        row = existing.get(node_id)
        if row is None:
            row = WorkflowSchedule(workflow_id=record.id, user_id=record.user_id, node_id=node_id, spec=config,
                                   timezone=tz_name, enabled=enabled,
                                   next_run_at=next_runs(config, now, anchor=now)[0] if valid else None)
            session.add(row)
            continue
        if row.spec != config or not valid:
            row.next_run_at = next_runs(config, now, anchor=now)[0] if valid else None
        elif row.next_run_at is None and valid:
            row.next_run_at = next_runs(config, now, anchor=now)[0]
        row.spec, row.timezone, row.enabled = config, tz_name, enabled
