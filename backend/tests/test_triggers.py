"""Form Submission Trigger and Schedule Trigger (Milestone 2, Phase 5).

Form tests submit through the real public HTTP endpoint. Schedule tests drive the real ``Scheduler`` on the
app's event loop (``app_client.portal``) - executions are started by the scheduler, never by a manual run.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, UTC

import pytest
from builders import edge, node, workflow
from conftest import register, wait_for_execution
from fake_llm import Script, ai, install
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.core.config import get_settings
from app.core.ratelimit import limiter
from app.db.models import Execution, ScheduleOccurrence, Workflow, WorkflowSchedule
from app.db.session import get_sessionmaker
from app.engine.scheduler import Scheduler

FORM_CONFIG = {
    "title": "Project enquiry", "description": "Tell us about your project.",
    "fields": [
        {"key": "name", "label": "Name", "type": "text", "required": True, "max_length": 100},
        {"key": "email", "label": "Email", "type": "email", "required": True},
        {"key": "budget", "label": "Budget", "type": "number", "required": True, "min": 0, "max": 1_000_000},
        {"key": "plan", "label": "Plan", "type": "select", "options": ["starter", "pro"]},
        {"key": "details", "label": "Details", "type": "textarea"},
        {"key": "consent", "label": "I agree", "type": "checkbox", "required": True},
    ],
    "success_message": "Thanks, we will be in touch!",
}
VALID = {"name": "Ada", "email": "ada@example.com", "budget": "5000", "plan": "pro", "details": "", "consent": True}


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()
    yield
    limiter.reset()


def form_workflow(base_url: str) -> dict:
    """Workflow F: Form -> Set -> If -> HTTP (high) / HTTP (low) -> End."""
    return workflow("Workflow F", [
        node("form_trigger_1", "core.form_trigger", FORM_CONFIG),
        node("set_1", "core.set", {"fields": [
            {"name": "budget", "value": "{{trigger.submission.budget}}", "type": "number"},
            {"name": "email", "value": "{{trigger.submission.email}}", "type": "string"}]}),
        node("if_1", "core.if", {"conditions": {"combinator": "all", "rules": [
            {"left": "{{nodes.set_1.output.budget}}", "operator": "gte", "right": 1000}]}}),
        node("http_1", "http.request", {"method": "POST", "url": f"{base_url}/echo", "query": {"lane": "high"},
                                        "body_type": "json", "body": {"email": "{{nodes.set_1.output.email}}"}}),
        node("http_2", "http.request", {"method": "POST", "url": f"{base_url}/echo", "query": {"lane": "low"},
                                        "body_type": "json", "body": {"email": "{{nodes.set_1.output.email}}"}}),
        node("end_1", "core.end", {"output": {"lane": "{{input.body.query.lane}}",
                                              "budget": "{{nodes.set_1.output.budget}}"}}),
    ], [edge("e1", "form_trigger_1", "set_1"), edge("e2", "set_1", "if_1"),
        edge("e3", "if_1", "http_1", "true"), edge("e4", "if_1", "http_2", "false"),
        edge("e5", "http_1", "end_1"), edge("e6", "http_2", "end_1")])


def create(client, headers, definition):
    res = client.post("/api/workflows", json={"definition": definition}, headers=headers)
    assert res.status_code == 201, res.text
    assert res.json()["validation"]["valid"], res.json()["validation"]["issues"]
    return res.json()


def form_id_of(client, headers, wf_id):
    forms = client.get(f"/api/workflows/{wf_id}/forms", headers=headers).json()
    assert len(forms) == 1
    return forms[0]


def executions(client, headers, wf_id):
    return client.get(f"/api/workflows/{wf_id}/executions", headers=headers).json()


def wait_for_new_execution(client, headers, wf_id, count=1, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        rows = executions(client, headers, wf_id)
        if len(rows) >= count:
            return rows
        time.sleep(0.05)
    raise AssertionError("no execution started")


# =============================================================================================== form
def test_public_form_definition_is_sanitised(app_client, auth_headers, http_server):
    wf = create(app_client, auth_headers, form_workflow(http_server))
    info = form_id_of(app_client, auth_headers, wf["id"])
    assert info["form_id"].startswith("frm_") and len(info["form_id"]) >= 24
    assert info["url"].endswith(f"/forms/{info['form_id']}")
    res = app_client.get(f"/api/public/forms/{info['form_id']}")
    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "Project enquiry" and [f["key"] for f in body["fields"]][:2] == ["name", "email"]
    text = res.text
    for private in (wf["id"], "set_1", "http", "user_id", "success_message", http_server):
        assert private not in text


def test_valid_submission_starts_workflow_and_routes_branches(app_client, auth_headers, http_server):
    wf = create(app_client, auth_headers, form_workflow(http_server))
    form_id = form_id_of(app_client, auth_headers, wf["id"])["form_id"]
    res = app_client.post(f"/api/public/forms/{form_id}", json={"data": VALID, "_hp": ""})
    assert res.status_code == 202 and res.json() == {"ok": True, "message": "Thanks, we will be in touch!"}
    assert "exe_" not in res.text
    row = wait_for_new_execution(app_client, auth_headers, wf["id"])[0]
    assert row["trigger_type"] == "form"
    detail = wait_for_execution(app_client, auth_headers, row["id"])
    assert detail["status"] == "completed", detail
    assert detail["output"] == {"lane": "high", "budget": 5000}
    trigger = next(n for n in detail["nodes"] if n["node_id"] == "form_trigger_1")["output"]
    assert trigger["submission"]["budget"] == 5000 and trigger["submission"]["consent"] is True
    assert trigger["submission"]["details"] is None and trigger["form_id"] == form_id and trigger["submitted_at"]
    statuses = {n["node_id"]: n["status"] for n in detail["nodes"]}
    assert statuses["http_1"] == "success" and statuses["http_2"] == "skipped"

    low = app_client.post(f"/api/public/forms/{form_id}", json={"data": {**VALID, "budget": 20}})
    assert low.status_code == 202
    rows = wait_for_new_execution(app_client, auth_headers, wf["id"], count=2)
    detail = wait_for_execution(app_client, auth_headers, rows[0]["id"])
    assert detail["output"] == {"lane": "low", "budget": 20}


@pytest.mark.parametrize("data,field,fragment", [
    ({**VALID, "email": "not-an-email"}, "email", "valid email"),
    ({k: v for k, v in VALID.items() if k != "name"}, "name", "required"),
    ({**VALID, "budget": "lots"}, "budget", "must be a number"),
    ({**VALID, "budget": -5}, "budget", "at least 0"),
    ({**VALID, "plan": "enterprise"}, "plan", "listed options"),
    ({**VALID, "consent": False}, "consent", "must be checked"),
    ({**VALID, "name": "x" * 101}, "name", "at most 100"),
    ({**VALID, "admin": True}, "_form", "Unknown field"),
])
def test_invalid_submissions_are_rejected_without_starting_a_run(app_client, auth_headers, http_server, data,
                                                                 field, fragment):
    wf = create(app_client, auth_headers, form_workflow(http_server))
    form_id = form_id_of(app_client, auth_headers, wf["id"])["form_id"]
    res = app_client.post(f"/api/public/forms/{form_id}", json={"data": data})
    assert res.status_code == 422
    assert fragment in res.json()["errors"][field]
    time.sleep(0.1)
    assert executions(app_client, auth_headers, wf["id"]) == []


def test_invalid_form_token_inactive_workflow_and_rotation(app_client, auth_headers, http_server):
    assert app_client.get("/api/public/forms/frm_doesnotexist").status_code == 404
    assert app_client.post("/api/public/forms/frm_doesnotexist", json={"data": VALID}).status_code == 404
    assert app_client.get("/api/public/forms/../../etc").status_code == 404
    wf = create(app_client, auth_headers, form_workflow(http_server))
    form_id = form_id_of(app_client, auth_headers, wf["id"])["form_id"]
    assert app_client.patch(f"/api/workflows/{wf['id']}/active", json={"active": False},
                            headers=auth_headers).json()["active"] is False
    assert app_client.get(f"/api/public/forms/{form_id}").status_code == 404
    assert app_client.post(f"/api/public/forms/{form_id}", json={"data": VALID}).status_code == 404
    app_client.patch(f"/api/workflows/{wf['id']}/active", json={"active": True}, headers=auth_headers)
    rotated = app_client.post(f"/api/workflows/{wf['id']}/forms/form_trigger_1/rotate", headers=auth_headers).json()
    assert rotated["form_id"] != form_id
    assert app_client.get(f"/api/public/forms/{form_id}").status_code == 404
    assert app_client.get(f"/api/public/forms/{rotated['form_id']}").status_code == 200
    # form ids are stable across ordinary saves
    detail = app_client.get(f"/api/workflows/{wf['id']}", headers=auth_headers).json()
    app_client.put(f"/api/workflows/{wf['id']}", json={"definition": detail["definition"]}, headers=auth_headers)
    assert form_id_of(app_client, auth_headers, wf["id"])["form_id"] == rotated["form_id"]
    # other users cannot manage it
    other = register(app_client)
    assert app_client.get(f"/api/workflows/{wf['id']}/forms", headers=other).status_code == 404


def test_honeypot_rate_limit_and_size_limit(app_client, auth_headers, http_server, monkeypatch):
    wf = create(app_client, auth_headers, form_workflow(http_server))
    form_id = form_id_of(app_client, auth_headers, wf["id"])["form_id"]
    res = app_client.post(f"/api/public/forms/{form_id}", json={"data": VALID, "_hp": "i am a bot"})
    assert res.status_code == 202 and res.json()["ok"] is True
    time.sleep(0.1)
    assert executions(app_client, auth_headers, wf["id"]) == []  # bots get a success page, not a run

    big = app_client.post(f"/api/public/forms/{form_id}", content=b'{"data": "' + b"x" * 70_000 + b'"}',
                          headers={"content-type": "application/json"})
    assert big.status_code == 413
    assert app_client.post(f"/api/public/forms/{form_id}", content=b"name=x",
                           headers={"content-type": "application/x-www-form-urlencoded"}).status_code == 415

    limiter.reset()
    monkeypatch.setattr(get_settings(), "FORM_RATE_LIMIT_PER_MINUTE", 2)
    codes = [app_client.post(f"/api/public/forms/{form_id}", json={"data": {"email": "bad"}}).status_code
             for _ in range(3)]
    assert codes == [422, 422, 429]


def test_form_execution_failure_is_recorded_but_not_leaked(app_client, auth_headers, http_server):
    definition = form_workflow(http_server)
    definition["nodes"][3]["config"]["url"] = f"{http_server}/status/500"
    wf = create(app_client, auth_headers, definition)
    form_id = form_id_of(app_client, auth_headers, wf["id"])["form_id"]
    res = app_client.post(f"/api/public/forms/{form_id}", json={"data": VALID})
    assert res.status_code == 202 and "500" not in res.text
    row = wait_for_new_execution(app_client, auth_headers, wf["id"])[0]
    detail = wait_for_execution(app_client, auth_headers, row["id"])
    assert detail["status"] == "failed"
    assert next(n for n in detail["nodes"] if n["node_id"] == "http_1")["status"] == "failed"


def test_form_config_validation():
    from pydantic import ValidationError

    from app.registry.configs import FormTriggerConfig

    with pytest.raises(ValidationError, match="unique"):
        FormTriggerConfig.model_validate({"title": "t", "fields": [{"key": "a", "label": "A"},
                                                                   {"key": "a", "label": "B"}]})
    with pytest.raises(ValidationError, match="at least one option"):
        FormTriggerConfig.model_validate({"title": "t", "fields": [{"key": "a", "label": "A", "type": "select"}]})
    with pytest.raises(ValidationError):
        FormTriggerConfig.model_validate({"title": "t", "fields": [{"key": "bad key", "label": "A"}]})


def test_webhook_respects_active_flag_and_rate_limit(app_client, auth_headers, monkeypatch):
    wf = create(app_client, auth_headers, workflow("hook", [node("webhook_trigger_1", "core.webhook_trigger"),
                                                            node("end_1", "core.end")],
                                                   [edge("e1", "webhook_trigger_1", "end_1")]))
    hook = app_client.post(f"/api/workflows/{wf['id']}/webhook", headers=auth_headers).json()
    path = hook["url"].split("testserver")[1]
    assert app_client.post(path, json={"a": 1}).status_code == 202
    app_client.patch(f"/api/workflows/{wf['id']}/active", json={"active": False}, headers=auth_headers)
    assert app_client.post(path, json={"a": 1}).status_code == 409
    app_client.patch(f"/api/workflows/{wf['id']}/active", json={"active": True}, headers=auth_headers)
    limiter.reset()
    monkeypatch.setattr(get_settings(), "WEBHOOK_RATE_LIMIT_PER_MINUTE", 1)
    assert [app_client.post(path, json={}).status_code for _ in range(2)] == [202, 429]


# =============================================================================================== schedule
def schedule_workflow(config=None, with_ai=False) -> dict:
    """Workflow G: Schedule -> Set -> (AI Generate) -> End."""
    nodes = [node("schedule_trigger_1", "core.schedule_trigger",
                  config or {"mode": "interval", "interval_minutes": 5, "timezone": "UTC"}),
             node("set_1", "core.set", {"fields": [{"name": "when", "value": "{{trigger.scheduled_for}}",
                                                    "type": "string"}]})]
    edges = [edge("e1", "schedule_trigger_1", "set_1")]
    last = "set_1"
    if with_ai:
        nodes.append(node("ai_generate_1", "ai.generate", {
            "model": {"provider": "gemini", "model": "gemini-3.8-flash", "timeout_seconds": 5},
            "prompt": "Write a one-line status note for the run scheduled at {{nodes.set_1.output.when}}."}))
        edges.append(edge("e2", "set_1", "ai_generate_1"))
        last = "ai_generate_1"
    nodes.append(node("end_1", "core.end", {"output": {"when": "{{nodes.set_1.output.when}}",
                                                       "note": f"{{{{nodes.{last}.output}}}}"}}))
    edges.append(edge("e3", last, "end_1"))
    return workflow("Workflow G", nodes, edges)


def _schedule_row(client: TestClient, wf_id: str) -> WorkflowSchedule:
    async def load():
        async with get_sessionmaker()() as session:
            return (await session.execute(select(WorkflowSchedule).where(WorkflowSchedule.workflow_id == wf_id))
                    ).scalar_one()
    return client.portal.call(load)


def _set_next_run(client: TestClient, schedule_id: str, when: datetime) -> None:
    async def write():
        async with get_sessionmaker()() as session:
            await session.execute(update(WorkflowSchedule).where(WorkflowSchedule.id == schedule_id)
                                  .values(next_run_at=when))
            await session.commit()
    client.portal.call(write)


def _scheduler(client: TestClient) -> Scheduler:
    return Scheduler(get_sessionmaker(), client.app.state.execution_manager)


def _count(client: TestClient, model, *where) -> int:
    async def count():
        async with get_sessionmaker()() as session:
            return (await session.execute(select(func.count()).select_from(model).where(*where))).scalar_one()
    return client.portal.call(count)


@pytest.mark.parametrize("config,fragment", [
    ({"mode": "daily", "timezone": "Mars/Olympus"}, "Unknown time zone"),
    ({"mode": "cron", "cron": "61 * * * *"}, "not a valid"),
    ({"mode": "cron"}, "needs a cron expression"),
    ({"mode": "weekly", "weekdays": []}, "at least one weekday"),
    ({"mode": "interval", "interval_minutes": 0}, "greater than or equal"),
])
def test_schedule_validation(app_client, auth_headers, config, fragment):
    res = app_client.post("/api/workflows/schedule-preview", json={"config": config}, headers=auth_headers)
    assert res.json()["valid"] is False and any(fragment in e for e in res.json()["errors"]), res.json()
    issues = app_client.post("/api/workflows/validate", json={"definition": schedule_workflow(config)},
                             headers=auth_headers).json()["issues"]
    assert any(i["node_id"] == "schedule_trigger_1" for i in issues)


def test_schedule_preview_respects_timezones_and_dst(app_client, auth_headers):
    from app.services.schedules import next_runs

    cfg = {"mode": "daily", "hour": 9, "minute": 0, "timezone": "Europe/Berlin"}
    runs = next_runs(cfg, datetime(2026, 3, 27, 12, 0, tzinfo=UTC), count=3)
    # 09:00 Berlin is 08:00Z before the DST switch (29 Mar 2026) and 07:00Z after it.
    assert [r.isoformat() for r in runs] == ["2026-03-28T08:00:00+00:00", "2026-03-29T07:00:00+00:00",
                                             "2026-03-30T07:00:00+00:00"]
    weekdays = next_runs({"mode": "weekdays", "hour": 8, "minute": 30, "timezone": "UTC"},
                         datetime(2026, 11, 13, 9, 0, tzinfo=UTC), count=2)  # Friday after 08:30
    assert [r.strftime("%a %H:%M") for r in weekdays] == ["Mon 08:30", "Tue 08:30"]
    res = app_client.post("/api/workflows/schedule-preview", json={"config": {"mode": "weekly",
                          "weekdays": ["mon", "fri"], "hour": 7, "minute": 15, "timezone": "Asia/Kolkata"}},
                          headers=auth_headers).json()
    assert res["valid"] and res["expression"] == "15 7 * * 1,5" and len(res["next_runs"]) == 5


def test_saving_a_workflow_persists_its_schedule(app_client, auth_headers):
    wf = create(app_client, auth_headers, schedule_workflow())
    info = app_client.get(f"/api/workflows/{wf['id']}/schedules", headers=auth_headers).json()
    assert len(info) == 1 and info[0]["enabled"] and info[0]["next_run_at"] and len(info[0]["upcoming"]) == 3
    # disabling in the node config disables the persisted schedule
    definition = wf["definition"]
    definition["nodes"][0]["config"]["enabled"] = False
    app_client.put(f"/api/workflows/{wf['id']}", json={"definition": definition}, headers=auth_headers)
    assert app_client.get(f"/api/workflows/{wf['id']}/schedules", headers=auth_headers).json()[0]["enabled"] is False
    # removing the trigger removes the schedule
    definition["nodes"][0] = node("manual_trigger_1", "core.manual_trigger")
    definition["edges"][0]["source"] = "manual_trigger_1"
    definition["start_nodes"], definition["end_nodes"] = [], []  # derived again by the backend
    res = app_client.put(f"/api/workflows/{wf['id']}", json={"definition": definition}, headers=auth_headers)
    assert res.status_code == 200, res.text
    assert app_client.get(f"/api/workflows/{wf['id']}/schedules", headers=auth_headers).json() == []


def test_scheduler_fires_due_schedule_through_the_engine(app_client, auth_headers):
    wf = create(app_client, auth_headers, schedule_workflow())
    row = _schedule_row(app_client, wf["id"])
    due = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=5)
    _set_next_run(app_client, row.id, due)
    report = app_client.portal.call(_scheduler(app_client).tick)
    mine = [r for r in report if r["schedule_id"] == row.id]
    assert mine and mine[0]["result"] == "started"
    detail = wait_for_execution(app_client, auth_headers, mine[0]["execution_id"])
    assert detail["status"] == "completed" and detail["trigger_type"] == "schedule"
    trigger = next(n for n in detail["nodes"] if n["node_id"] == "schedule_trigger_1")["output"]
    assert trigger["schedule_id"] == row.id and trigger["timezone"] == "UTC"
    assert datetime.fromisoformat(trigger["scheduled_for"]) == due
    assert detail["output"]["when"] == trigger["scheduled_for"]
    after = _schedule_row(app_client, wf["id"])
    assert after.next_run_at.replace(tzinfo=UTC) > datetime.now(UTC)
    info = app_client.get(f"/api/workflows/{wf['id']}/schedules", headers=auth_headers).json()[0]
    assert info["last_execution_id"] == detail["id"] and info["last_status"] == "completed"


def test_duplicate_occurrences_are_prevented(app_client, auth_headers):
    wf = create(app_client, auth_headers, schedule_workflow())
    row = _schedule_row(app_client, wf["id"])
    due = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=2)
    _set_next_run(app_client, row.id, due)

    async def two_workers():
        a, b = _scheduler(app_client), _scheduler(app_client)
        return await asyncio.gather(a.tick(), b.tick())

    reports = app_client.portal.call(two_workers)
    results = [r["result"] for rep in reports for r in rep if r["schedule_id"] == row.id]
    assert results.count("started") == 1, results
    assert _count(app_client, Execution, Execution.workflow_id == wf["id"]) == 1

    # A claim already written by another worker blocks this one (unique constraint).
    due2 = due + timedelta(minutes=5)

    async def preclaim():
        async with get_sessionmaker()() as session:
            session.add(ScheduleOccurrence(schedule_id=row.id, scheduled_for=due2))
            await session.commit()
    app_client.portal.call(preclaim)
    _set_next_run(app_client, row.id, due2)
    report = app_client.portal.call(lambda: _scheduler(app_client).tick(now=due2 + timedelta(seconds=1)))
    assert [r["result"] for r in report if r["schedule_id"] == row.id] == ["duplicate"]
    assert _count(app_client, Execution, Execution.workflow_id == wf["id"]) == 1


def test_restart_does_not_replay_backlog(app_client, auth_headers):
    wf = create(app_client, auth_headers, schedule_workflow())
    row = _schedule_row(app_client, wf["id"])
    _set_next_run(app_client, row.id, datetime.now(UTC) - timedelta(hours=6))  # 72 missed occurrences
    fresh = _scheduler(app_client)  # a new process after downtime
    report = app_client.portal.call(fresh.tick)
    assert [r["result"] for r in report if r["schedule_id"] == row.id] == ["skipped_missed"]
    assert _count(app_client, Execution, Execution.workflow_id == wf["id"]) == 0
    assert _schedule_row(app_client, wf["id"]).next_run_at.replace(tzinfo=UTC) > datetime.now(UTC)

    # run_once policy: exactly one catch-up run, never the whole backlog
    wf2 = create(app_client, auth_headers, schedule_workflow({"mode": "interval", "interval_minutes": 5,
                                                              "misfire_policy": "run_once"}))
    row2 = _schedule_row(app_client, wf2["id"])
    _set_next_run(app_client, row2.id, datetime.now(UTC) - timedelta(hours=6))
    report = app_client.portal.call(fresh.tick)
    assert [r["result"] for r in report if r["schedule_id"] == row2.id] == ["started"]
    report = app_client.portal.call(fresh.tick)
    assert not [r for r in report if r["schedule_id"] == row2.id]
    assert _count(app_client, Execution, Execution.workflow_id == wf2["id"]) == 1


def test_inactive_workflow_or_disabled_schedule_never_fires(app_client, auth_headers):
    wf = create(app_client, auth_headers, schedule_workflow())
    row = _schedule_row(app_client, wf["id"])
    _set_next_run(app_client, row.id, datetime.now(UTC) - timedelta(seconds=5))
    app_client.patch(f"/api/workflows/{wf['id']}/active", json={"active": False}, headers=auth_headers)
    report = app_client.portal.call(_scheduler(app_client).tick)
    assert not [r for r in report if r["schedule_id"] == row.id]


def test_scheduler_loop_starts_workflow_with_ai_generate(app_client, auth_headers, monkeypatch):
    """Workflow G end to end: the background loop (short poll) fires the schedule; AI Generate is mocked here
    (the live variant is in the Phase 7 verification)."""
    settings = get_settings()
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "platform-gemini-test-key-1234")
    monkeypatch.setattr(settings, "SCHEDULER_POLL_SECONDS", 0.2)
    install(monkeypatch, Script({"gemini-3.8-flash": [ai("All systems nominal.")]}))
    wf = create(app_client, auth_headers, schedule_workflow(with_ai=True))
    row = _schedule_row(app_client, wf["id"])
    _set_next_run(app_client, row.id, datetime.now(UTC) + timedelta(seconds=1))
    scheduler = Scheduler(get_sessionmaker(), app_client.app.state.execution_manager, settings)

    async def start():
        scheduler.start()
    app_client.portal.call(start)
    try:
        rows = wait_for_new_execution(app_client, auth_headers, wf["id"], timeout=10)
    finally:
        app_client.portal.call(scheduler.stop)
    detail = wait_for_execution(app_client, auth_headers, rows[0]["id"])
    assert detail["trigger_type"] == "schedule" and detail["status"] == "completed", detail
    assert detail["output"]["note"]["result"] == "All systems nominal."


def test_schedule_ownership(app_client, auth_headers):
    wf = create(app_client, auth_headers, schedule_workflow())
    other = register(app_client)
    assert app_client.get(f"/api/workflows/{wf['id']}/schedules", headers=other).status_code == 404
    assert app_client.patch(f"/api/workflows/{wf['id']}/active", json={"active": False},
                            headers=other).status_code == 404
    async def owner():
        async with get_sessionmaker()() as session:
            return (await session.get(Workflow, wf["id"])).user_id
    assert _schedule_row(app_client, wf["id"]).user_id == app_client.portal.call(owner)
