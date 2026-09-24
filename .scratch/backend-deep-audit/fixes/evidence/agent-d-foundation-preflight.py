"""Deterministic Agent D pre/post fixture for foundation issues D-01..D-13.

This script is intentionally stdlib-only and never opens the live portfolio DB,
contacts the network, or invokes Docker. Run from any directory:

    python .scratch/backend-deep-audit/fixes/evidence/agent-d-foundation-preflight.py
"""

from __future__ import annotations

import importlib.util
import re
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BACKEND = ROOT / "backend"
EVIDENCE = Path(__file__).resolve().parent

checks: list[tuple[str, bool, str]] = []


def check(issue: str, condition: bool, detail: str) -> None:
    checks.append((issue, bool(condition), detail))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def relative_compose_bind_sources(text: str) -> list[str]:
    sources: list[str] = []
    for raw in text.splitlines():
        match = re.match(r"\s*-\s+\./([^:]+):", raw)
        if match:
            sources.append(match.group(1))
    return sources


# D-01/D-10: rendered operational values and Settings aliases.
compose_dev = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
compose_prod = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
for label, text in (("dev", compose_dev), ("prod", compose_prod)):
    expected_url = "DATABASE_URL: sqlite+aiosqlite:////app/backend/data/daisy.db"
    check(
        f"D-01/{label}",
        expected_url in text and "DATABASE_URL=sqlite:///" not in text,
        "exact async URL must resolve to /app/backend/data/daisy.db",
    )
    check(
        f"D-10/{label}",
        "ALLOWED_ORIGINS:" in text
        and "CORS_ORIGINS" not in text
        and not re.search(r"\b(DATABASE_POOL_SIZE|MAX_OVERFLOW|POOL_TIMEOUT|DATABASE_ECHO)\s*:", text),
        "only Settings-backed CORS/database keys may be injected",
    )

# D-07: every repository bind source currently referenced by Compose must exist.
for label, text in (("dev", compose_dev), ("prod", compose_prod)):
    bind_sources = relative_compose_bind_sources(text)
    missing = [source for source in bind_sources if not (ROOT / source).exists()]
    check(
        f"D-07/{label}",
        not missing,
        f"bind sources={bind_sources!r}; missing={missing!r}",
    )

# D-02/D-05/D-11: backend context/layout/probe and explicit COPY allowlist.
dockerfile = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
copy_lines = [line.strip() for line in dockerfile.splitlines() if line.strip().upper().startswith("COPY ")]
forbidden_copy = [
    line
    for line in copy_lines
    if "--from=builder" not in line
    and re.search(r"\b(app|backend|tests|data|logs|backups|\.env)\b", line)
    and not any(token in line for token in ("*.py", "__init__.py", "config.py", "pyproject.toml", "README.md", "uv.lock"))
]
check(
    "D-02",
    "WORKDIR /app/backend" in dockerfile
    and '["uvicorn", "main:app"' in dockerfile
    and "libssl1.1" not in dockerfile
    and "COPY pyproject.toml uv.lock README.md ./" in dockerfile,
    "runtime workdir/import/dependencies must agree",
)
check(
    "D-05",
    "urllib.request" in dockerfile
    and "quick_check" in dockerfile.lower()
    and not re.search(r"\b(curl|wget)\b", dockerfile.split("HEALTHCHECK", 1)[-1]),
    "backend probe must use stdlib and test HTTP plus DB",
)
check(
    "D-11",
    not forbidden_copy and all(any(token in line for token in ("*.py", "__init__.py", "config.py", "main.py", "pyproject.toml", "uv.lock", "README.md", ".venv")) for line in copy_lines),
    f"COPY lines must be source allowlist only; forbidden={forbidden_copy!r}",
)

# D-03/D-04/D-06: deployment safety, real backup, and identity rollback.
deploy = (ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")
check(
    "D-03",
    "docker volume prune" not in deploy
    and "docker container prune" not in deploy
    and "docker image prune" not in deploy
    and "trap cleanup EXIT" not in deploy,
    "deployment must not globally prune or auto-prune on exit",
)
check(
    "D-04",
    "migrations.sqlite_backup" in deploy
    and "iterdump" not in deploy
    and "compose cp" in deploy
    and "quick_check" in (BACKEND / "migrations" / "sqlite_backup.py").read_text(encoding="utf-8")
    if (BACKEND / "migrations" / "sqlite_backup.py").exists()
    else False,
    "backup must copy a verified SQLite backup from the configured mounted DB",
)
check(
    "D-06",
    "BACKEND_IMAGE_ID" in deploy
    and "FRONTEND_IMAGE_ID" in deploy
    and "rollback-" in deploy
    and "read" in deploy,
    "rollback must load and select recorded image identities",
)

# D-08/D-09/D-13: isolated old-schema convergence and safe duplicate blocker.
schema_migration = BACKEND / "migrations" / "schema_version.py"
if schema_migration.exists():
    migration = load_module("agent_d_schema_version_preflight", schema_migration)
    with tempfile.TemporaryDirectory(prefix="agent-d-schema-") as tmp:
        db = Path(tmp) / "legacy.db"
        conn = sqlite3.connect(db)
        conn.executescript(
            """
            CREATE TABLE portfolio_positions (
                id INTEGER PRIMARY KEY,
                ticker TEXT,
                weight REAL,
                market_value REAL DEFAULT 0.0,
                sector TEXT,
                industry TEXT
            );
            CREATE TABLE stock_timeseries (
                id INTEGER PRIMARY KEY,
                ticker TEXT,
                date DATETIME,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                adj_close REAL,
                volume INTEGER
            );
            INSERT INTO portfolio_positions
                (ticker, weight, market_value, sector, industry)
            VALUES ('AAPL', 1.0, 100.0, 'Tech', NULL);
            INSERT INTO stock_timeseries
                (ticker, date, open, high, low, close, adj_close, volume)
            VALUES ('AAPL', '2025-01-01', 10, 11, 9, 10, 10, 100);
            """
        )
        conn.commit()
        conn.close()
        migration.apply_migrations(db)
        conn = sqlite3.connect(db)
        pcols = {row[1]: row for row in conn.execute("PRAGMA table_info(portfolio_positions)")}
        portfolio_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='portfolio_positions'"
        ).fetchone()[0].lower()
        stock_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='stock_timeseries'"
        ).fetchone()[0].lower()
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        quick = conn.execute("PRAGMA quick_check").fetchone()[0]
        conn.close()
        check(
            "D-08",
            version == migration.LATEST_SCHEMA_VERSION and quick == "ok",
            f"legacy DB converges to version={version}, quick_check={quick}",
        )
        check(
            "D-09",
            pcols["quantity"][3] == 1
            and pcols["buy_price"][3] == 1
            and pcols["sector"][3] == 1
            and "unique" in portfolio_sql
            and "ck_stock" in stock_sql,
            "fresh/migrated tables must expose canonical uniqueness and integrity checks",
        )
else:
    check("D-08", False, "versioned migration runner is absent")
    check("D-09", False, "versioned migration runner is absent")

# D-12: CI integration target must exist and build contexts must match Dockerfile layout.
ci = (ROOT / ".github" / "workflows" / "ci-cd.yml").read_text(encoding="utf-8")
check(
    "D-12",
    "backend/tests/integration/" in ci
    and (BACKEND / "tests" / "integration").is_dir()
    and "docker build -f backend/Dockerfile" in ci
    and len(re.findall(r"docker build .* backend/", ci)) >= 2,
    "CI targets existing integration tests and supplies backend/ as Docker context",
)

# D-13: migration CLI must propagate failure as a nonzero process status.
cleanup = (BACKEND / "migrations" / "cleanup_duplicates_and_add_constraints.py").read_text(encoding="utf-8")
check(
    "D-13/migrations",
    "SystemExit" in cleanup or "sys.exit" in cleanup,
    "failed cleanup must not exit zero",
)

failed = [item for item in checks if not item[1]]
for issue, ok, detail in checks:
    print(f"{'PASS' if ok else 'FAIL'} {issue}: {detail}")

output = EVIDENCE / "agent-d-foundation-preflight.txt"
lines = [f"{'PASS' if ok else 'FAIL'} {issue}: {detail}" for issue, ok, detail in checks]
lines.append(f"SUMMARY: {len(checks) - len(failed)} passed; {len(failed)} failed")
output.write_text("\n".join(lines) + "\n", encoding="utf-8")

if failed:
    raise SystemExit(1)
