"""Functional smoke test of a deployed stack. WRITES DATA - opt-in, run it only when you mean to.

Usage (PowerShell, from backend/):
    python scripts/smoke_test_deployment.py --backend https://<service>.onrender.com --frontend https://<project>.vercel.app
    python scripts/smoke_test_deployment.py --backend ... --frontend ... --with-schedule     # + waits ~2 min

It signs up a throwaway user (smoke-<random>@example.com), then exercises the real platform paths with core
nodes only (no AI provider keys or external HTTP needed):
  1. create + manual run (Set -> End) and read the persisted execution back
  2. webhook trigger: issue a token, POST to the PUBLIC webhook URL the backend reports (PUBLIC_BASE_URL)
  3. form trigger: the PUBLIC form link (PUBLIC_APP_URL/forms/<id>) is served by the frontend; an invalid
     submission is rejected, a valid one starts a run
  4. (--with-schedule) a 1-minute Schedule Trigger fires through the real scheduler loop
  5. tenant isolation: a second user cannot read the first user's workflow
Every workflow it created is deleted at the end; the two throwaway user accounts remain (there is no
self-service account deletion endpoint yet).
"""

from __future__ import annotations

import argparse
import time
import uuid
from urllib.parse import urlparse

import httpx
from _deploy_common import FAIL, PASS, SKIP, Report


def node(id_, op, config=None):  # type: ignore[no-untyped-def]
    return {"id": id_, "operation": op, "label": id_, "config": config or {}}


def edge(id_, s, t, sp="main", tp="main"):  # type: ignore[no-untyped-def]
    return {"id": id_, "source": s, "target": t, "source_port": sp, "target_port": tp}


def wf(name, nodes, edges):  # type: ignore[no-untyped-def]
    return {"schema_version": 2, "workflow_id": "draft", "workflow_name": name, "nodes": nodes, "edges": edges}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", required=True)
    parser.add_argument("--frontend", help="frontend origin (form page check)")
    parser.add_argument("--with-schedule", action="store_true", help="also wait for a real scheduled run (~2 min)")
    parser.add_argument("--keep", action="store_true", help="do not delete the created workflows")
    args = parser.parse_args()
    api = args.backend.rstrip("/")
    web = args.frontend.rstrip("/") if args.frontend else None
    report = Report()
    client = httpx.Client(timeout=90, follow_redirects=True)
    created: list[str] = []

    def register() -> dict:
        email = f"smoke-{uuid.uuid4().hex[:10]}@example.com"
        r = client.post(f"{api}/api/auth/register", json={"email": email, "password": uuid.uuid4().hex})
        r.raise_for_status()
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    def create(defn: dict, headers: dict) -> dict:
        r = client.post(f"{api}/api/workflows", json={"definition": defn}, headers=headers)
        r.raise_for_status()
        created.append(r.json()["id"])
        return r.json()

    def wait_run(wf_id: str, headers: dict, before: int, timeout: float = 90) -> dict | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            rows = client.get(f"{api}/api/workflows/{wf_id}/executions", headers=headers).json()
            if len(rows) > before and rows[0]["status"] in ("completed", "failed", "cancelled"):
                return client.get(f"{api}/api/executions/{rows[0]['id']}", headers=headers).json()
            time.sleep(1)
        return None

    try:
        user = register()
        report.add(PASS, "sign up + JWT issued")
        other = register()

        # 1. manual run
        w = create(wf("smoke manual", [
            node("manual_trigger_1", "core.manual_trigger"),
            node("set_1", "core.set", {"fields": [{"name": "n", "value": "{{trigger.n}}", "type": "number"}]}),
            node("end_1", "core.end", {"output": {"double_check": "{{nodes.set_1.output.n}}"}}),
        ], [edge("e1", "manual_trigger_1", "set_1"), edge("e2", "set_1", "end_1")]), user)
        r = client.post(f"{api}/api/workflows/{w['id']}/run?wait=true", json={"input": {"n": 21}}, headers=user)
        run = r.json() if r.status_code < 300 else {}
        exe_id = run.get("execution_id") or run.get("id")
        detail = client.get(f"{api}/api/executions/{exe_id}", headers=user).json() if exe_id else {}
        report.add(PASS if detail.get("status") == "completed" and detail.get("output", {}).get("double_check") == 21
                   else FAIL, "manual run executes and persists (typed output)", str(detail.get("output")))

        # 5. isolation
        r = client.get(f"{api}/api/workflows/{w['id']}", headers=other)
        report.add(PASS if r.status_code == 404 else FAIL, "tenant isolation (other user gets 404)", f"HTTP {r.status_code}")

        # 2. webhook
        w = create(wf("smoke webhook", [
            node("webhook_trigger_1", "core.webhook_trigger", {"method": "POST"}),
            node("end_1", "core.end", {"output": {"got": "{{trigger.body.ping}}"}}),
        ], [edge("e1", "webhook_trigger_1", "end_1")]), user)
        info = client.post(f"{api}/api/workflows/{w['id']}/webhook", headers=user).json()
        hook_host = urlparse(info["url"]).netloc
        report.add(PASS if hook_host == urlparse(api).netloc else FAIL, "webhook URL uses the public backend URL",
                   f"host={hook_host} (PUBLIC_BASE_URL)")
        r = client.post(info["url"], json={"ping": "pong"})
        det = wait_run(w["id"], user, 0)
        report.add(PASS if r.status_code == 202 and det and det["trigger_type"] == "webhook"
                   and det["output"].get("got") == "pong" else FAIL, "public webhook starts a run", f"HTTP {r.status_code}")
        r = client.post(info["url"].rsplit("/", 1)[0] + "/wrong-token", json={})
        report.add(PASS if r.status_code in {401, 403, 404} else FAIL, "webhook rejects a wrong token",
                   f"HTTP {r.status_code}")

        # 3. form
        w = create(wf("smoke form", [
            node("form_trigger_1", "core.form_trigger", {"title": "Smoke test", "fields": [
                {"key": "email", "label": "Email", "type": "email", "required": True}], "success_message": "ok"}),
            node("end_1", "core.end", {"output": {"email": "{{trigger.submission.email}}"}}),
        ], [edge("e1", "form_trigger_1", "end_1")]), user)
        form = client.get(f"{api}/api/workflows/{w['id']}/forms", headers=user).json()[0]
        if web:
            report.add(PASS if urlparse(form["url"]).netloc == urlparse(web).netloc else FAIL,
                       "form link uses the public frontend URL", f"{urlparse(form['url']).netloc} (PUBLIC_APP_URL)")
            r = client.get(form["url"])
            report.add(PASS if r.status_code == 200 else FAIL, "hosted form page loads", f"HTTP {r.status_code}")
        bad = client.post(form["api_url"], json={"data": {"email": "not-an-email"}})
        report.add(PASS if bad.status_code == 422 else FAIL, "invalid form submission rejected", f"HTTP {bad.status_code}")
        ok = client.post(form["api_url"], json={"data": {"email": "smoke@example.com"}})
        det = wait_run(w["id"], user, 0)
        report.add(PASS if ok.status_code == 202 and det and det["output"].get("email") == "smoke@example.com" else FAIL,
                   "valid form submission starts a run", f"HTTP {ok.status_code}")

        # 4. schedule
        if args.with_schedule:
            w = create(wf("smoke schedule", [
                node("schedule_trigger_1", "core.schedule_trigger", {"mode": "interval", "interval_minutes": 1,
                                                                     "timezone": "UTC"}),
                node("end_1", "core.end", {"output": {"at": "{{trigger.scheduled_for}}"}}),
            ], [edge("e1", "schedule_trigger_1", "end_1")]), user)
            det = wait_run(w["id"], user, 0, timeout=150)
            report.add(PASS if det and det["trigger_type"] == "schedule" and det["status"] == "completed" else FAIL,
                       "scheduler fired the 1-minute schedule", str(det and det["output"]))
        else:
            report.add(SKIP, "scheduled run", "pass --with-schedule")
    except httpx.HTTPError as exc:
        report.add(FAIL, "request failed", f"{type(exc).__name__}: {exc}")
    finally:
        if not args.keep and created:
            headers = locals().get("user") or {}
            gone = sum(client.delete(f"{api}/api/workflows/{i}", headers=headers).status_code == 204 for i in created)
            report.add(PASS if gone == len(created) else FAIL, "cleanup: smoke workflows deleted", f"{gone}/{len(created)}")
        client.close()
    return report.finish("Smoke test")


if __name__ == "__main__":
    raise SystemExit(main())
