"""Post-deployment verification against the REAL deployed URLs. Read-only: creates no users or data.

Usage (PowerShell, from backend/):
    python scripts/verify_production.py --backend https://<service>.onrender.com --frontend https://<project>.vercel.app
    python scripts/verify_production.py --backend ... --frontend ... --form-id frm_xxx      # + a real form

Checks the backend (liveness, readiness: database + schema + scheduler, auth enforcement, CORS for the
frontend origin and rejection of a foreign origin, public form and webhook endpoints reachable and
rejecting unknown ids) and the frontend (pages, security headers, server-side backend reachability,
no localhost backend URL baked into the browser bundle, backend URL present in the bundle).

A PASS here means these endpoints behaved as expected at this moment - not that every feature works.
Follow the manual checklist in docs/PRODUCTION_DEPLOYMENT.md (sign up, run a workflow, form, schedule).
"""

from __future__ import annotations

import argparse
import re
from urllib.parse import urljoin, urlparse

import httpx
from _deploy_common import FAIL, INFO, PASS, SKIP, WARN, Report

FOREIGN_ORIGIN = "https://attacker-example.vercel.app"


def _origin(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def check_backend(client: httpx.Client, report: Report, backend: str, frontend: str | None,
                  form_id: str | None) -> None:
    report.add(PASS if backend.startswith("https://") else FAIL, "backend uses https", backend)
    try:
        res = client.get(f"{backend}/health")
        ok = res.status_code == 200 and res.json().get("status") == "healthy"
        report.add(PASS if ok else FAIL, "backend /health", f"HTTP {res.status_code}")
    except httpx.HTTPError as exc:
        report.add(FAIL, "backend /health", f"{type(exc).__name__}: {exc} (a sleeping free instance can take ~1 min)")
        return

    res = client.get(f"{backend}/health/ready")
    try:
        body = res.json()
    except ValueError:
        body = {}
    checks = body.get("checks", {})
    report.add(PASS if res.status_code == 200 else FAIL, "backend /health/ready",
               f"HTTP {res.status_code}, database={checks.get('database')}, "
               f"schema_up_to_date={checks.get('schema_up_to_date')}, revision={checks.get('schema_revision')}")
    report.add(PASS if checks.get("scheduler") == "running" else WARN, "scheduler loop", str(checks.get("scheduler")))
    report.add(PASS if checks.get("environment") == "production" else WARN, "APP_ENV", str(checks.get("environment")))

    res = client.get(f"{backend}/api/workflows")
    report.add(PASS if res.status_code == 401 else FAIL, "API requires authentication", f"HTTP {res.status_code}")

    def preflight(origin: str) -> httpx.Response:
        return client.options(f"{backend}/api/workflows", headers={
            "Origin": origin, "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,content-type"})

    if frontend:
        origin = _origin(frontend)
        res = preflight(origin)
        allowed = res.headers.get("access-control-allow-origin")
        report.add(PASS if allowed == origin else FAIL, "CORS allows the frontend origin",
                   f"allow-origin={allowed!r} (set CORS_ORIGINS={origin} on Render)" if allowed != origin else origin)
    res = preflight(FOREIGN_ORIGIN)
    report.add(PASS if "access-control-allow-origin" not in res.headers else FAIL,
               "CORS rejects a foreign origin", FOREIGN_ORIGIN)

    res = client.get(f"{backend}/api/public/forms/frm_verify_does_not_exist")
    report.add(PASS if res.status_code == 404 else FAIL, "public form endpoint reachable (unknown id -> 404)",
               f"HTTP {res.status_code}")
    res = client.post(f"{backend}/api/webhooks/wf_verify_does_not_exist/invalid-token", json={"ping": True})
    report.add(PASS if res.status_code in {401, 403, 404} else FAIL,
               "webhook endpoint reachable and rejects unknown workflow", f"HTTP {res.status_code}")
    if form_id:
        res = client.get(f"{backend}/api/public/forms/{form_id}")
        report.add(PASS if res.status_code == 200 else FAIL, f"public form {form_id} is live", f"HTTP {res.status_code}")
    else:
        report.add(SKIP, "a real public form", "pass --form-id after creating a Form Trigger workflow")


def check_frontend(client: httpx.Client, report: Report, frontend: str, backend: str) -> None:
    report.add(PASS if frontend.startswith("https://") else FAIL, "frontend uses https", frontend)
    try:
        res = client.get(frontend)
    except httpx.HTTPError as exc:
        report.add(FAIL, "frontend home page", f"{type(exc).__name__}: {exc}")
        return
    report.add(PASS if res.status_code == 200 else FAIL, "frontend home page", f"HTTP {res.status_code}")
    html = res.text
    for header in ("x-content-type-options", "x-frame-options", "referrer-policy"):
        report.add(PASS if header in res.headers else WARN, f"security header {header}")
    report.add(PASS if "x-powered-by" not in res.headers else WARN, "no X-Powered-By header")

    res = client.get(f"{frontend}/health")
    report.add(PASS if res.status_code == 200 else FAIL, "frontend server reaches backend (/health)",
               f"HTTP {res.status_code} {res.text[:120]}")
    res = client.get(f"{frontend}/forms/frm_verify_page")
    report.add(PASS if res.status_code == 200 else FAIL, "public form page route renders", f"HTTP {res.status_code}")

    # The API client is loaded by the app pages, not necessarily by "/": collect chunks from several pages.
    for page in ("/login", "/workflows"):
        r = client.get(f"{frontend}{page}")
        if r.status_code == 200:
            html += r.text
    chunks = sorted(set(re.findall(r'src="(/_next/static/[^"]+\.js)"', html)))
    bundle = ""
    for path in chunks[:80]:
        r = client.get(urljoin(frontend, path))
        if r.status_code == 200:
            bundle += r.text
    if not bundle:
        report.add(WARN, "browser bundle scan", "no script chunks found on the home page")
        return
    leaked = [s for s in ("localhost:8000", "127.0.0.1:8000", "http://localhost", "http://127.0.0.1")
              if s in bundle and s not in backend]
    report.add(PASS if not leaked else FAIL, "no localhost backend URL in browser bundle", ", ".join(leaked))
    host = urlparse(backend).netloc
    report.add(PASS if host in bundle else INFO, "browser bundle calls the backend directly",
               host if host in bundle else "backend host not found: frontend uses the same-origin /api proxy")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", required=True, help="Render backend origin, e.g. https://<service>.onrender.com")
    parser.add_argument("--frontend", help="Vercel frontend origin, e.g. https://<project>.vercel.app")
    parser.add_argument("--form-id", help="public id of a live form (frm_...) to check end to end")
    parser.add_argument("--timeout", type=float, default=60.0, help="per-request timeout (cold starts)")
    args = parser.parse_args()
    backend = args.backend.rstrip("/")
    frontend = args.frontend.rstrip("/") if args.frontend else None

    report = Report()
    with httpx.Client(timeout=args.timeout, follow_redirects=True,
                      headers={"User-Agent": "agentic-flow-verify/1.0"}) as client:
        check_backend(client, report, backend, frontend, args.form_id)
        if frontend:
            check_frontend(client, report, frontend, backend)
        else:
            report.add(SKIP, "frontend checks", "pass --frontend")
    return report.finish("Production verification")


if __name__ == "__main__":
    raise SystemExit(main())
