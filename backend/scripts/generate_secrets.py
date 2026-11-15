"""Generate fresh production secrets: JWT_SECRET and CREDENTIALS_ENCRYPTION_KEY.

Usage (PowerShell, from backend/):
    python scripts/generate_secrets.py            # prints both values ONCE to your terminal

Copy each value straight into the Render dashboard (Environment), then store CREDENTIALS_ENCRYPTION_KEY in
your password manager as well: if it is ever lost or changed, every stored credential becomes unreadable.
Never reuse local development values in production and never commit these values.
"""

from __future__ import annotations

import secrets

from cryptography.fernet import Fernet


def main() -> int:
    print("# Paste into Render > agentic-flow-api > Environment. Do not commit. Shown once.")
    print(f"JWT_SECRET={secrets.token_urlsafe(48)}")
    print(f"CREDENTIALS_ENCRYPTION_KEY={Fernet.generate_key().decode()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
