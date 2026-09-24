"""Deployment/config contracts for Agent D issues D-01..D-13."""

from __future__ import annotations

import importlib
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings
from migrations.schema_version import resolve_sqlite_database_path

BACKEND = Path(__file__).resolve().parent.parent
ROOT = BACKEND.parent


def _bind_sources(compose_text: str) -> list[str]:
    sources: list[str] = []
    for raw in compose_text.splitlines():
        match = re.match(r"\s*-\s+\./([^:]+)(?::[^:]+)(?:\s+#.*)?$", raw)
        if match:
            sources.append(match.group(1))
    return sources


@pytest.mark.parametrize("filename", ["docker-compose.yml", "docker-compose.prod.yml"])
def test_compose_async_url_mount_and_supported_settings(filename: str):
    text = (ROOT / filename).read_text(encoding="utf-8")

    assert "DATABASE_URL: sqlite+aiosqlite:////app/backend/data/daisy.db" in text
    assert "DATABASE_URL: sqlite:///" not in text
    assert "ALLOWED_ORIGINS:" in text
    assert "CORS_ORIGINS" not in text
    for unsupported in ("DATABASE_POOL_SIZE", "MAX_OVERFLOW", "POOL_TIMEOUT", "DATABASE_ECHO"):
        assert unsupported not in text
    assert "quick_check" in text
    assert re.search(r"ports:\s*\n\s*- [\"']?(?:127\.0\.0\.1:)?8000:8000", text)
    assert re.search(r"ports:\s*\n\s*- [\"']?(?:127\.0\.0\.1:)?3000:3000", text)


@pytest.mark.parametrize("filename", ["docker-compose.yml", "docker-compose.prod.yml"])
def test_compose_has_no_absent_bind_sources(filename: str):
    text = (ROOT / filename).read_text(encoding="utf-8")
    missing = [source for source in _bind_sources(text) if not (ROOT / source).exists()]
    assert missing == []


def test_settings_reject_sync_sqlite_and_resolve_exact_absolute_path(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./data/daisy.db")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)

    target = tmp_path / "mounted" / "daisy.db"
    url = f"sqlite+aiosqlite:///{target.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    settings = Settings(_env_file=None)
    assert settings.database_url == url
    assert resolve_sqlite_database_path(url) == target.resolve()


def test_production_health_probe_bypasses_https_redirect():
    from starlette.testclient import TestClient

    import main

    original_environment = main.settings.environment
    main.settings.environment = "production"
    client = None
    try:
        production_main = importlib.reload(main)
        # Do not enter the context manager: main's lifespan opens its configured DB.
        client = TestClient(production_main.app, base_url="http://127.0.0.1")
        for path in ("/health", "/api/v1/health"):
            response = client.get(path, follow_redirects=False)
            assert response.status_code == 200
            assert response.json()["status"] == "healthy"
            assert response.json()["environment"] == "production"

        redirected = client.get("/", follow_redirects=False)
        assert redirected.status_code == 307
        assert redirected.headers["location"].startswith("https://")
    finally:
        if client is not None:
            client.close()
        main.settings.environment = original_environment
        importlib.reload(main)

    text = (BACKEND / "main.py").read_text(encoding="utf-8")
    assert 'scope.get("path") in {"/health", "/api/v1/health"}' in text
    assert "await super().__call__(scope, receive, send)" in text
    assert "app.add_middleware(_HealthExemptHTTPSRedirectMiddleware)" in text


def test_backend_dockerfile_is_allowlisted_and_runtime_consistent():
    text = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
    copy_lines = [line.strip() for line in text.splitlines() if line.strip().startswith("COPY ")]

    assert "FROM python:3.12-slim-bookworm AS builder" in text
    assert "FROM python:3.12-slim-bookworm AS production" in text
    assert "WORKDIR /app/backend" in text
    assert 'CMD ["uvicorn", "main:app"' in text
    assert "libssl1.1" not in text
    assert "urllib.request" in text and "quick_check" in text
    assert not re.search(r"\b(curl|wget)\b", text.split("HEALTHCHECK", 1)[1])
    for forbidden in ("COPY . ", "COPY backend/", "COPY app/ ", "COPY tests/", "COPY data/"):
        assert forbidden not in text
    for line in copy_lines:
        assert any(
            token in line
            for token in (
                "pyproject.toml",
                "uv.lock",
                "README.md",
                ".venv",
                "*.py",
                "__init__.py",
                "config.py",
                "main.py",
            )
        ), line


def test_deploy_script_is_non_destructive_and_uses_real_backup_and_identity():
    text = (ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")

    for forbidden in (
        "docker volume prune",
        "docker container prune",
        "docker image prune",
        "compose down",
        "docker-compose down",
        "down -v",
        "iterdump",
        "your-secret-key",
    ):
        assert forbidden not in text
    assert "python -m migrations.sqlite_backup" in text
    assert "configured_database_path" in text
    assert "compose cp" in text
    assert "--verify-only" in text
    assert "BACKEND_IMAGE_ID" in text and "FRONTEND_IMAGE_ID" in text
    assert "docker image tag" in text and "rollback-${DEPLOY_ID}" in text
    assert "if ! rollback; then" in text
    assert "attempting recorded-image rollback" in text
    assert 'if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then' in text
    assert "PUBLIC_BASE_URL" in text
    assert "health" in text
    assert "umask 077" in text


def test_deploy_backup_permissions_are_private_before_copy_writes_content():
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash is required to exercise the deployment shell")

    harness = r'''
set -euo pipefail
source scripts/deploy.sh
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT
cd "$work_dir"

DEPLOY_ID="permission-test"
configured_database_path() { printf '/data/daisy.db\n'; }

compose() {
    if [[ "${1:-}" == "run" && "$*" == *"--destination"* ]]; then
        [[ "$*" == *"umask 077; exec python -m migrations.sqlite_backup"* ]] || {
            printf 'backup command does not set its creation umask\n' >&2
            return 92
        }
        return 0
    fi
    if [[ "${1:-}" == "cp" ]]; then
        local destination="${*: -1}"
        # Model a copy process whose creation default does not inherit the
        # caller's umask when the destination is absent.
        if [[ ! -e "$destination" ]]; then
            (umask 022; : > "$destination")
        fi
        [[ "$(stat -c '%a' "$destination")" == "600" ]] || {
            printf 'backup mode before content write: %s\n' "$(stat -c '%a' "$destination")" >&2
            return 93
        }
        printf 'verified backup\n' > "$destination"
        return 0
    fi
    return 0
}

umask 022
backup_database
[[ "$(stat -c '%a' "$BACKUP_ARTIFACT")" == "600" ]]
'''
    result = subprocess.run(
        [bash, "-s"],
        cwd=ROOT,
        input=textwrap.dedent(harness).encode("utf-8"),
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")


def test_ci_targets_existing_integration_file_and_no_phantom_rollout():
    text = (ROOT / ".github" / "workflows" / "ci-cd.yml").read_text(encoding="utf-8")

    target = "backend/tests/integration/test_compose_services.py"
    assert target in text
    assert (ROOT / target).is_file()
    assert "tests/integration/ -v" not in text
    assert "npm run test:e2e" not in text
    assert "lighthouserc.json" not in text
    assert "Run post-deployment tests" not in text
    assert "docker compose -f docker-compose.yml up -d --build --wait" in text
    assert text.count("docker build -f backend/Dockerfile") >= 1
    assert "docker build -f backend/Dockerfile -t $REGISTRY/$IMAGE_NAME-backend:latest backend/" in text
