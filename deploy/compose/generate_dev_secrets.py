"""Generate the development secret fixtures the Compose stack expects.

The Compose stack reads the PostgreSQL password from a file secret rather than an
environment variable, so the value never appears in a process listing or in the
repository. This script writes it once, with restrictive permissions, and is
safe to re-run: an existing value is left alone so that recreating the stack does
not invalidate an initialised volume.

This is a development convenience only. A real deployment supplies secrets from
Vault (ADR-0008); nothing here is suitable outside a local stack.
"""

from __future__ import annotations

import os
import secrets
import stat
import sys
from contextlib import suppress
from pathlib import Path

SECRETS_DIR = Path(__file__).resolve().parent / "secrets"
POSTGRES_PASSWORD = SECRETS_DIR / "postgres_password"


def _write_secret(path: Path, value: str) -> bool:
    """Write a secret with owner-only permissions. Returns False if it existed."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    # Create with 0600 from the start so the value is never briefly world-readable.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(value)
    # Windows has no POSIX mode bits; the directory is git-ignored regardless.
    with suppress(NotImplementedError, PermissionError):
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return True


def main() -> int:
    created = _write_secret(POSTGRES_PASSWORD, secrets.token_urlsafe(32))
    if created:
        print(f"created {POSTGRES_PASSWORD}")
    else:
        print(f"{POSTGRES_PASSWORD} already exists; left unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
