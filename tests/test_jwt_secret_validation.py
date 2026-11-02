"""
Regression tests: app.core.security and app.core.auth must fail fast at
import time when JWT_SECRET is not set, rather than allowing the app to
start and then failing with opaque errors at the first auth call.

Each test launches a subprocess with JWT_SECRET removed from the environment
so the module-level startup check can be exercised in isolation.
"""
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def _run_import(module: str) -> subprocess.CompletedProcess:
    """Run `import <module>` in a child process without JWT_SECRET."""
    env = {k: v for k, v in os.environ.items() if k != "JWT_SECRET"}
    # Ensure the project root is on PYTHONPATH so app.* is importable.
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    return subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )


# ── Startup validation regression ────────────────────────────────────────────

def test_security_module_fails_fast_without_jwt_secret():
    """
    Regression: before the fix, app.core.security imported successfully
    even with JWT_SECRET unset; create_access_token then raised a cryptic
    JWTError at runtime.  After the fix, import raises ValueError immediately.
    """
    result = _run_import("app.core.security")
    assert result.returncode != 0, (
        "app.core.security must refuse to import when JWT_SECRET is unset. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "JWT_SECRET" in result.stderr


def test_auth_module_fails_fast_without_jwt_secret():
    """
    app.core.auth also reads JWT_SECRET and must perform the same fail-fast
    check.
    """
    result = _run_import("app.core.auth")
    assert result.returncode != 0, (
        "app.core.auth must refuse to import when JWT_SECRET is unset. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "JWT_SECRET" in result.stderr


# ── Normal operation with the secret set ─────────────────────────────────────

def test_security_module_imports_normally_with_jwt_secret(monkeypatch):
    """When JWT_SECRET is set, the module must be importable without error."""
    # The module is already imported in this process (JWT_SECRET was set by conftest).
    # We just verify the module-level constant is not None.
    from app.core.security import SECRET_KEY
    assert SECRET_KEY is not None
    assert len(SECRET_KEY) > 0


def test_access_token_creation_works_with_set_secret():
    """create_access_token must succeed when JWT_SECRET is set."""
    from app.core.security import create_access_token
    token = create_access_token({"user_id": 1})
    assert isinstance(token, str)
    assert len(token) > 20
