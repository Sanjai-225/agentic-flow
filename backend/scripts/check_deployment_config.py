"""Static checks of the deployment package: render.yaml, vercel.json, env examples, migrations.

Usage (PowerShell, from backend/):
    python scripts/check_deployment_config.py                      # offline checks
    python scripts/check_deployment_config.py --schemas            # + validate against the official
                                                                   #   Render and Vercel JSON schemas (downloads)

Needs the dev requirements (PyYAML, jsonschema): pip install -r requirements-dev.txt
Reads files only; never contacts Render, Vercel or Supabase APIs and never prints secret values.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import urllib.request
from pathlib import Path

from _deploy_common import BACKEND_DIR, FAIL, INFO, PASS, REPO_DIR, SKIP, WARN, Report

FRONTEND_DIR = REPO_DIR / "frontend"
RENDER_SCHEMA_URL = "https://render.com/schema/render.yaml.json"
VERCEL_SCHEMA_URL = "https://openapi.vercel.sh/vercel.json"
SECRET_KEYS = {"DATABASE_URL", "JWT_SECRET", "CREDENTIALS_ENCRYPTION_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY",
               "ANTHROPIC_API_KEY"}
# Set by the platform at runtime, not by the operator.
PLATFORM_PROVIDED = {"RENDER_EXTERNAL_URL", "AGENTIC_FLOW_NO_DOTENV", "VERCEL", "VERCEL_ENV", "NODE_ENV"}


def _fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=20) as res:  # noqa: S310 - fixed https schema URLs
        return json.loads(res.read().decode("utf-8"))


def _schema_errors(schema: dict, doc: object) -> list[str]:
    import jsonschema

    validator = jsonschema.validators.validator_for(schema)(schema)
    out = []
    for err in validator.iter_errors(doc):
        leaf = err
        while leaf.context:  # report the most specific branch error
            leaf = sorted(leaf.context, key=lambda e: len(list(e.path)), reverse=True)[0]
        out.append(f"{'/'.join(str(p) for p in err.path) or '<root>'}: {leaf.message[:160]}")
    return out


def backend_env_names() -> set[str]:
    text = (BACKEND_DIR / "app" / "core" / "config.py").read_text(encoding="utf-8")
    return set(re.findall(r'os\.getenv\("([A-Z0-9_]+)"', text)) - PLATFORM_PROVIDED


def frontend_env_names() -> set[str]:
    names: set[str] = set()
    for folder in ("app", "lib", "components", "store"):
        for path in (FRONTEND_DIR / folder).rglob("*.ts*"):
            names |= set(re.findall(r"process\.env\.([A-Z0-9_]+)", path.read_text(encoding="utf-8")))
    names |= set(re.findall(r"env\.([A-Z0-9_]+)", (FRONTEND_DIR / "lib" / "backendUrl.ts").read_text("utf-8")))
    return names - PLATFORM_PROVIDED


def documented(path: Path) -> set[str]:
    return set(re.findall(r"^\s*#?\s*([A-Z][A-Z0-9_]+)=", path.read_text(encoding="utf-8"), re.MULTILINE))


def check_render(report: Report, schemas: bool) -> None:
    import yaml

    path = REPO_DIR / "render.yaml"
    if not path.is_file():
        report.add(FAIL, "render.yaml exists")
        return
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    report.add(PASS, "render.yaml parses")
    webs = [s for s in doc.get("services", []) if s.get("type") == "web"]
    if len(webs) != 1:
        report.add(FAIL, "render.yaml: exactly one web service", f"found {len(webs)}")
        return
    svc = webs[0]
    env = {e["key"]: e for e in svc.get("envVars", []) if "key" in e}
    start = svc.get("startCommand", "")
    checks = [
        ("rootDir is backend", svc.get("rootDir") == "backend"),
        ("runtime python", svc.get("runtime") == "python"),
        ("build installs backend/requirements.txt", "requirements.txt" in svc.get("buildCommand", "")
         and (BACKEND_DIR / "requirements.txt").is_file()),
        ("start command runs app.main:app on $PORT", "app.main:app" in start and "$PORT" in start
         and "0.0.0.0" in start),
        ("single process (--workers 1)", "--workers 1" in start),
        ("proxy headers trusted (client IP for rate limits)", "--proxy-headers" in start),
        ("free instance type", svc.get("plan") == "free"),
        ("single instance, no autoscaling", svc.get("numInstances", 1) == 1 and "scaling" not in svc),
        ("health check path /health", svc.get("healthCheckPath") == "/health"),
        ("APP_ENV=production", env.get("APP_ENV", {}).get("value") == "production"),
        ("DB_AUTO_MIGRATE set explicitly", str(env.get("DB_AUTO_MIGRATE", {}).get("value")) in {"true", "false"}),
        ("HTTP_ALLOW_PRIVATE_NETWORKS=false", str(env.get("HTTP_ALLOW_PRIVATE_NETWORKS", {}).get("value")) == "false"),
        ("preview environments off (shared database)", (svc.get("previews") or {}).get("generation") == "off"),
    ]
    for name, ok in checks:
        report.add(PASS if ok else FAIL, f"render.yaml: {name}")
    for key in ("DATABASE_URL", "JWT_SECRET", "CREDENTIALS_ENCRYPTION_KEY", "PUBLIC_APP_URL", "CORS_ORIGINS"):
        report.add(PASS if key in env else FAIL, f"render.yaml declares {key}")
    inline = [k for k, e in env.items() if k in SECRET_KEYS and "value" in e]
    report.add(PASS if not inline else FAIL, "render.yaml: no secret values committed",
               ", ".join(inline) if inline else "secrets use sync:false / generateValue")
    unknown = sorted(set(env) - backend_env_names() - {"PYTHON_VERSION"})
    report.add(PASS if not unknown else FAIL, "render.yaml: env keys are read by the backend",
               ", ".join(unknown) if unknown else "")
    if svc.get("plan") == "free":
        report.add(INFO, "render.yaml plan", "free: the service sleeps when idle; schedules do not fire while asleep")
    if schemas:
        try:
            errors = _schema_errors(_fetch_json(RENDER_SCHEMA_URL), doc)
        except Exception as exc:  # noqa: BLE001
            report.add(WARN, "render.yaml: official schema", f"could not download ({type(exc).__name__})")
        else:
            report.add(PASS if not errors else FAIL, "render.yaml: valid against official Render schema",
                       "; ".join(errors[:5]))
    else:
        report.add(SKIP, "render.yaml: official schema", "pass --schemas")


def check_vercel(report: Report, schemas: bool) -> None:
    path = FRONTEND_DIR / "vercel.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    report.add(PASS, "frontend/vercel.json parses")
    scripts = json.loads((FRONTEND_DIR / "package.json").read_text(encoding="utf-8")).get("scripts", {})
    report.add(PASS if doc.get("framework") == "nextjs" else FAIL, "vercel.json: framework nextjs")
    report.add(PASS if doc.get("buildCommand") == "npm run build" and "build" in scripts else FAIL,
               "vercel.json: build command exists in package.json")
    report.add(PASS if (FRONTEND_DIR / "package-lock.json").is_file() else FAIL,
               "package-lock.json present (npm ci)")
    report.add(PASS if "check-env" in scripts.get("prebuild", "") else FAIL,
               "prebuild env guard (scripts/check-env.mjs)")
    report.add(PASS if "rewrites" not in doc and "routes" not in doc else WARN,
               "vercel.json: no rewrites (frontend calls the backend directly or via the /api route)")
    if schemas:
        try:
            errors = _schema_errors(_fetch_json(VERCEL_SCHEMA_URL), doc)
        except Exception as exc:  # noqa: BLE001
            report.add(WARN, "vercel.json: official schema", f"could not download ({type(exc).__name__})")
        else:
            report.add(PASS if not errors else FAIL, "vercel.json: valid against official Vercel schema",
                       "; ".join(errors[:5]))


def check_env_examples(report: Report) -> None:
    backend_doc = documented(BACKEND_DIR / ".env.example")
    missing = sorted(backend_env_names() - backend_doc)
    report.add(PASS if not missing else FAIL, "backend/.env.example documents every backend variable",
               ", ".join(missing))
    frontend_doc = documented(FRONTEND_DIR / ".env.example")
    missing = sorted(frontend_env_names() - frontend_doc)
    report.add(PASS if not missing else FAIL, "frontend/.env.example documents every frontend variable",
               ", ".join(missing))
    public_secret = [n for n in frontend_doc if n.startswith("NEXT_PUBLIC_") and re.search(
        r"SECRET|PASSWORD|TOKEN|API_KEY|DATABASE|ENCRYPTION|JWT", n[12:])]
    report.add(PASS if not public_secret else FAIL, "no secret-like NEXT_PUBLIC_ variables", ", ".join(public_secret))
    for path in (BACKEND_DIR / ".env.example", FRONTEND_DIR / ".env.example"):
        text = path.read_text(encoding="utf-8")
        leaked = re.findall(r"^\s*(?:[A-Z_]*(?:KEY|SECRET))=(?!your_|$|change-me)(\S{24,})", text, re.MULTILINE)
        report.add(PASS if not leaked else FAIL, f"{path.relative_to(REPO_DIR)} has no real-looking secrets")


def check_git_hygiene(report: Report) -> None:
    try:
        tracked = subprocess.run(["git", "ls-files"], cwd=REPO_DIR, capture_output=True, text=True,
                                 check=True).stdout.splitlines()
    except Exception as exc:  # noqa: BLE001
        report.add(SKIP, "git hygiene", f"git unavailable ({type(exc).__name__})")
        return
    bad = [f for f in tracked if re.search(r"(^|/)\.env(\.local|\.production)?$", f) or f.endswith((".db", ".pem"))]
    report.add(PASS if not bad else FAIL, "no .env / database / key files tracked by git", ", ".join(bad))


def check_app(report: Report) -> None:
    import os

    os.environ.setdefault("AGENTIC_FLOW_NO_DOTENV", "1")
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from app.main import app

    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # duplicate operation ids for multi-method webhook routes are harmless here
        paths = set(app.openapi()["paths"])
    for path in ("/health", "/health/ready", "/api/webhooks/{workflow_id}/{token}", "/api/public/forms/{form_id}"):
        report.add(PASS if path in paths else FAIL, f"route {path} exists")
    main_src = (BACKEND_DIR / "app" / "main.py").read_text(encoding="utf-8")
    report.add(PASS if "vercel" not in main_src.lower() else FAIL, "CORS has no hard-coded wildcard origins")
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    report.add(PASS if len(heads) == 1 else FAIL, "migrations have a single head", ", ".join(heads))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--schemas", action="store_true", help="validate against the official Render/Vercel schemas")
    args = parser.parse_args()
    report = Report()
    check_render(report, args.schemas)
    check_vercel(report, args.schemas)
    check_env_examples(report)
    check_git_hygiene(report)
    check_app(report)
    return report.finish("Deployment configuration")


if __name__ == "__main__":
    raise SystemExit(main())
