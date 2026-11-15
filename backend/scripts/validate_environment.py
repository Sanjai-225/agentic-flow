"""Validate backend environment variables WITHOUT printing their values.

Usage (PowerShell, from backend/):
    python scripts/validate_environment.py --env-file ..\\deploy\\production.env     # a file you keep outside git
    python scripts/validate_environment.py --production                             # current process environment
    python scripts/validate_environment.py --use-local-dotenv                       # check local development setup

Applies the same rules the backend enforces at startup with APP_ENV=production (app/core/production.py) and
reports which documented variables are set. Exit code 1 when any error is found.
"""

from __future__ import annotations

import argparse
import os

from _deploy_common import FAIL, INFO, PASS, WARN, Report, add_env_args, prepare_environment

# Variables documented in backend/.env.example, grouped by importance for a production deployment.
REQUIRED_IN_PRODUCTION = ["APP_ENV", "DATABASE_URL", "JWT_SECRET", "CREDENTIALS_ENCRYPTION_KEY", "PUBLIC_APP_URL",
                          "CORS_ORIGINS"]
RECOMMENDED = ["GEMINI_API_KEY", "DB_AUTO_MIGRATE", "AI_ALLOW_PLATFORM_KEYS", "HTTP_ALLOW_PRIVATE_NETWORKS"]
SECRETS = {"DATABASE_URL", "JWT_SECRET", "CREDENTIALS_ENCRYPTION_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY",
           "ANTHROPIC_API_KEY"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_env_args(parser)
    parser.add_argument("--production", action="store_true",
                        help="apply production rules even if APP_ENV is not 'production'")
    args = parser.parse_args()
    prepare_environment(args.env_file, isolate=not args.use_local_dotenv)

    from app.core.config import Settings
    from app.core.production import check_settings
    from app.db.url import redact_database_url

    settings = Settings()
    production = args.production or settings.is_production
    report = Report()
    report.add(INFO, "APP_ENV", f"{settings.APP_ENV} (production rules: {'on' if production else 'off'})")

    for name in REQUIRED_IN_PRODUCTION:
        present = bool(os.environ.get(name, "").strip())
        if name == "APP_ENV" and not production:
            continue
        status = PASS if present else (FAIL if production else WARN)
        kind = "secret" if name in SECRETS else "value"
        report.add(status, f"{name} is set", f"{kind}, value not shown" if present else "missing")
    for name in RECOMMENDED:
        present = bool(os.environ.get(name, "").strip())
        report.add(PASS if present else WARN, f"{name} is set", "" if present else "not set (default applies)")

    if os.environ.get("DATABASE_URL", "").strip():
        report.add(INFO, "DATABASE_URL (redacted)", redact_database_url(os.environ["DATABASE_URL"]))
    report.add(INFO, "PUBLIC_BASE_URL (effective)", settings.PUBLIC_BASE_URL +
               (" (from RENDER_EXTERNAL_URL)" if not os.environ.get("PUBLIC_BASE_URL") and
                os.environ.get("RENDER_EXTERNAL_URL") else ""))
    if production and not os.environ.get("PUBLIC_BASE_URL") and not os.environ.get("RENDER_EXTERNAL_URL"):
        report.add(INFO, "PUBLIC_BASE_URL", "not set here; on Render it defaults to RENDER_EXTERNAL_URL")

    issues = check_settings(settings, production=production)
    for issue in issues:
        # On Render, RENDER_EXTERNAL_URL is injected at runtime, so a missing PUBLIC_BASE_URL is not an error there.
        if (issue.name == "PUBLIC_BASE_URL" and not os.environ.get("PUBLIC_BASE_URL")
                and not os.environ.get("RENDER_EXTERNAL_URL")):
            report.add(WARN, issue.name, issue.message + " (ignored: Render provides RENDER_EXTERNAL_URL)")
            continue
        report.add(FAIL if issue.level == "error" else WARN, issue.name, issue.message)
    if not issues:
        report.add(PASS, "configuration rules", "no issues")
    return report.finish("Environment validation")


if __name__ == "__main__":
    raise SystemExit(main())
