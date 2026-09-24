"""Versioned, conservative SQLite schema migrations.

The application is SQLite-only in practice.  ``Base.metadata.create_all`` can
create missing tables, but it cannot evolve an existing table, so startup uses
this runner first and records the applied version in SQLite's built-in
``PRAGMA user_version``.

Safety contract:

* never open or create the configured production database unless a caller
  explicitly supplies its path;
* back up every non-empty existing database with :meth:`sqlite3.Connection.backup`
  before a mutation;
* preflight duplicate keys and invalid values before changing the schema;
* block on duplicates instead of deleting user data;
* use one transaction for schema/data reconciliation and foreign-key checks;
* support a constrained, data-preserving downgrade of the integrity layer.

Run explicitly with::

    python -m migrations.schema_version --db path/to/daisy.db
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from sqlalchemy.engine import make_url

LATEST_SCHEMA_VERSION = 1
MAX_SQLITE_FLOAT = 1.7976931348623157e308

ConnectFactory = Callable[..., sqlite3.Connection]


class MigrationError(RuntimeError):
    """Base class for safe-failing migration errors."""


class MigrationBlocked(MigrationError):
    """Existing data cannot be constrained without operator reconciliation."""

    def __init__(self, issues: list[dict[str, Any]], backup_path: Path | None = None):
        self.issues = issues
        self.backup_path = backup_path
        summary = json.dumps(issues, sort_keys=True, default=str)
        suffix = f"; backup={backup_path}" if backup_path else ""
        super().__init__(f"schema migration blocked without data loss{suffix}: {summary}")


@dataclass(frozen=True)
class MigrationResult:
    database_path: Path
    previous_version: int
    current_version: int
    applied: bool
    backup_path: Path | None
    mapped_null_metadata: int = 0


_PORTFOLIO_CREATE = """
CREATE TABLE portfolio_positions (
    id INTEGER NOT NULL PRIMARY KEY,
    ticker VARCHAR(20) COLLATE NOCASE NOT NULL,
    weight FLOAT NOT NULL,
    quantity FLOAT NOT NULL DEFAULT 0.0,
    buy_price FLOAT NOT NULL DEFAULT 0.0,
    region VARCHAR(10) DEFAULT 'US',
    primary_source VARCHAR(20) DEFAULT 'yfinance',
    fallback_source VARCHAR(20),
    last_validated_source VARCHAR(20) DEFAULT 'yfinance',
    last_price FLOAT DEFAULT 0.0,
    market_value FLOAT DEFAULT 0.0,
    sector VARCHAR(50) NOT NULL DEFAULT 'Unknown',
    industry VARCHAR(50) NOT NULL DEFAULT 'Unknown',
    custom_name VARCHAR(100),
    added_on DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_on DATETIME DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_portfolio_positions_ticker UNIQUE (ticker),
    CONSTRAINT ck_portfolio_positions_weight CHECK (weight >= 0 AND weight <= 1),
    CONSTRAINT ck_portfolio_positions_quantity CHECK (quantity >= 0 AND quantity <= 1.7976931348623157e308),
    CONSTRAINT ck_portfolio_positions_buy_price CHECK (buy_price >= 0 AND buy_price <= 1.7976931348623157e308),
    CONSTRAINT ck_portfolio_positions_last_price CHECK (last_price IS NULL OR (last_price >= 0 AND last_price <= 1.7976931348623157e308)),
    CONSTRAINT ck_portfolio_positions_market_value CHECK (market_value IS NULL OR (market_value >= 0 AND market_value <= 1.7976931348623157e308))
)
"""

_STOCK_CREATE = """
CREATE TABLE stock_timeseries (
    id INTEGER NOT NULL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL,
    date DATETIME NOT NULL,
    open FLOAT NOT NULL,
    high FLOAT NOT NULL,
    low FLOAT NOT NULL,
    close FLOAT NOT NULL,
    adj_close FLOAT NOT NULL,
    volume INTEGER NOT NULL,
    source_used VARCHAR(20) DEFAULT 'yfinance',
    fetch_status VARCHAR(20) DEFAULT 'fresh',
    fetched_on DATETIME DEFAULT CURRENT_TIMESTAMP,
    position_id INTEGER,
    FOREIGN KEY(position_id) REFERENCES portfolio_positions (id),
    CONSTRAINT uq_stock_timeseries_ticker_date UNIQUE (ticker, date),
    CONSTRAINT ck_stock_timeseries_open_finite CHECK (open >= 0 AND open <= 1.7976931348623157e308),
    CONSTRAINT ck_stock_timeseries_high_finite CHECK (high >= 0 AND high <= 1.7976931348623157e308),
    CONSTRAINT ck_stock_timeseries_low_finite CHECK (low >= 0 AND low <= 1.7976931348623157e308),
    CONSTRAINT ck_stock_timeseries_close_finite CHECK (close >= 0 AND close <= 1.7976931348623157e308),
    CONSTRAINT ck_stock_timeseries_adj_close_finite CHECK (adj_close >= 0 AND adj_close <= 1.7976931348623157e308),
    CONSTRAINT ck_stock_timeseries_volume_nonnegative CHECK (volume >= 0),
    CONSTRAINT ck_stock_timeseries_ohlc_open CHECK (low <= open AND open <= high),
    CONSTRAINT ck_stock_timeseries_ohlc_close CHECK (low <= close AND close <= high)
)
"""

_PORTFOLIO_INTEGRITY_COLUMNS = {
    "id",
    "ticker",
    "weight",
    "quantity",
    "buy_price",
    "region",
    "primary_source",
    "fallback_source",
    "last_validated_source",
    "last_price",
    "market_value",
    "sector",
    "industry",
    "custom_name",
    "added_on",
    "updated_on",
}

_STOCK_INTEGRITY_COLUMNS = {
    "id",
    "ticker",
    "date",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
    "source_used",
    "fetch_status",
    "fetched_on",
    "position_id",
}
_STOCK_REQUIRED_COLUMNS = {
    "id",
    "ticker",
    "date",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
}

_NATURAL_KEYS = {
    "portfolio_positions": (("ticker",), True),
    "stock_timeseries": (("ticker", "date"), False),
    "analytics_cache": (("ticker", "metric_name"), False),
    "nse_bhavcopy": (("symbol", "date"), False),
    "nse_institutional_flows": (("date", "category"), False),
    "nse_shareholding_patterns": (("symbol", "period_ended"), False),
}


def resolve_sqlite_database_path(database_url: str, base_dir: str | Path | None = None) -> Path:
    """Resolve a file-based async SQLite URL against an explicit base directory.

    Compose uses an absolute URL.  Local development intentionally keeps a
    relative URL, resolved from the process working directory just as SQLite
    itself would resolve it.
    """

    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        raise ValueError(f"expected a SQLite database URL, got {url.get_backend_name()!r}")
    if url.get_driver_name() != "aiosqlite":
        raise ValueError(
            f"async SQLAlchemy requires the aiosqlite driver, got {url.get_driver_name()!r}"
        )
    database = url.database
    if not database or database == ":memory:" or database.startswith("file:"):
        raise ValueError("a file-based SQLite database is required")
    path = Path(database).expanduser()
    if not path.is_absolute():
        path = Path(base_dir or Path.cwd()) / path
    return path.resolve()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")')}


def _schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row else 0


def _quick_check(conn: sqlite3.Connection) -> str:
    rows = conn.execute("PRAGMA quick_check").fetchall()
    values = [str(row[0]) for row in rows]
    return "ok" if values == ["ok"] else "; ".join(values)


def _connect(path: Path, connect_factory: ConnectFactory) -> sqlite3.Connection:
    conn = connect_factory(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def create_database_backup(
    db_path: str | Path,
    *,
    backup_dir: str | Path | None = None,
    connect_factory: ConnectFactory = sqlite3.connect,
) -> Path | None:
    """Create and verify an online SQLite backup before migration mutation.

    Empty/new databases do not contain user data and return ``None``.  An
    existing non-empty database is always snapshotted before the caller can
    proceed to reconciliation.
    """

    path = Path(db_path).expanduser().resolve()
    if not path.exists() or path.stat().st_size == 0:
        return None

    destination_dir = Path(backup_dir).expanduser().resolve() if backup_dir else path.parent / "backups"
    destination_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    destination = destination_dir / f"daisy_backup_{stamp}_pre_migration.db"

    source: sqlite3.Connection | None = None
    target: sqlite3.Connection | None = None
    try:
        source = _connect(path, connect_factory)
        if _quick_check(source) != "ok":
            raise MigrationError("source database failed PRAGMA quick_check; refusing migration")
        target = _connect(destination, connect_factory)
        source.backup(target)
        if _quick_check(target) != "ok":
            raise MigrationError("migration backup failed PRAGMA quick_check")
        return destination
    finally:
        if target is not None:
            target.close()
        if source is not None:
            source.close()


def _append_issue(
    issues: list[dict[str, Any]],
    *,
    table: str,
    kind: str,
    detail: str,
    rows: Iterable[sqlite3.Row] = (),
) -> None:
    materialised = [dict(row) for row in rows]
    issues.append(
        {
            "table": table,
            "kind": kind,
            "detail": detail,
            "rows": materialised,
        }
    )


def _preflight(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], int]:
    issues: list[dict[str, Any]] = []
    mapped_metadata = 0

    portfolio_columns = _columns(conn, "portfolio_positions")
    if portfolio_columns:
        missing = {"id", "ticker", "weight"} - portfolio_columns
        if missing:
            _append_issue(
                issues,
                table="portfolio_positions",
                kind="missing_required_columns",
                detail=f"cannot preserve rows without {sorted(missing)}",
            )
        else:
            duplicate_rows = conn.execute(
                """
                SELECT upper(trim(ticker)) AS canonical_ticker,
                       group_concat(id) AS row_ids,
                       COUNT(*) AS row_count
                FROM portfolio_positions
                WHERE ticker IS NULL OR trim(ticker) = ''
                GROUP BY upper(trim(ticker))
                """
            ).fetchall()
            duplicates = conn.execute(
                """
                SELECT upper(trim(ticker)) AS canonical_ticker,
                       group_concat(id) AS row_ids,
                       COUNT(*) AS row_count
                FROM portfolio_positions
                WHERE ticker IS NOT NULL AND trim(ticker) <> ''
                GROUP BY upper(trim(ticker))
                HAVING COUNT(*) > 1
                ORDER BY canonical_ticker
                """
            ).fetchall()
            for row in [*duplicate_rows, *duplicates]:
                _append_issue(
                    issues,
                    table="portfolio_positions",
                    kind="duplicate_or_empty_ticker",
                    detail="canonical ticker uniqueness cannot be added without an operator merge",
                    rows=[row],
                )

            invalid_weight = conn.execute(
                f"""
                SELECT id, ticker, weight
                FROM portfolio_positions
                WHERE weight IS NULL
                   OR typeof(weight) NOT IN ('integer', 'real')
                   OR weight < 0 OR weight > {MAX_SQLITE_FLOAT}
                LIMIT 20
                """
            ).fetchall()
            if invalid_weight:
                _append_issue(
                    issues,
                    table="portfolio_positions",
                    kind="invalid_weight",
                    detail="weight must be finite and in [0, 1]",
                    rows=invalid_weight,
                )

            for column in ("quantity", "buy_price"):
                if column not in portfolio_columns:
                    continue
                invalid = conn.execute(
                    f"""
                    SELECT id, ticker, {column}
                    FROM portfolio_positions
                    WHERE {column} IS NULL
                       OR typeof({column}) NOT IN ('integer', 'real')
                       OR {column} < 0 OR {column} > {MAX_SQLITE_FLOAT}
                    LIMIT 20
                    """
                ).fetchall()
                if invalid:
                    _append_issue(
                        issues,
                        table="portfolio_positions",
                        kind=f"invalid_{column}",
                        detail=f"{column} must be a finite non-negative legacy-compatible value",
                        rows=invalid,
                    )

            if "sector" in portfolio_columns:
                mapped_metadata += int(
                    conn.execute(
                        "SELECT COUNT(*) FROM portfolio_positions WHERE sector IS NULL"
                    ).fetchone()[0]
                )
            if "industry" in portfolio_columns:
                mapped_metadata += int(
                    conn.execute(
                        "SELECT COUNT(*) FROM portfolio_positions WHERE industry IS NULL"
                    ).fetchone()[0]
                )

    stock_columns = _columns(conn, "stock_timeseries")
    if stock_columns:
        # Source/status/relationship columns are additive and take model
        # defaults when absent. Core market columns must exist to avoid
        # fabricating OHLCV values during reconciliation.
        missing = _STOCK_REQUIRED_COLUMNS - stock_columns
        if missing:
            _append_issue(
                issues,
                table="stock_timeseries",
                kind="missing_required_columns",
                detail=f"cannot preserve rows without {sorted(missing)}",
            )
        else:
            duplicates = conn.execute(
                """
                SELECT upper(trim(ticker)) AS canonical_ticker, date,
                       group_concat(id) AS row_ids, COUNT(*) AS row_count
                FROM stock_timeseries
                GROUP BY upper(trim(ticker)), date
                HAVING COUNT(*) > 1
                ORDER BY canonical_ticker, date
                """
            ).fetchall()
            if duplicates:
                _append_issue(
                    issues,
                    table="stock_timeseries",
                    kind="duplicate_ticker_date",
                    detail="stock natural-key uniqueness cannot be added without operator reconciliation",
                    rows=duplicates,
                )
            for column in ("ticker", "date"):
                invalid = conn.execute(
                    f"""
                    SELECT id, ticker, date, {column}
                    FROM stock_timeseries
                    WHERE {column} IS NULL
                    LIMIT 20
                    """
                ).fetchall()
                if invalid:
                    _append_issue(
                        issues,
                        table="stock_timeseries",
                        kind=f"invalid_{column}",
                        detail=f"{column} may not be null",
                        rows=invalid,
                    )
            for column in ("open", "high", "low", "close", "adj_close", "volume"):
                invalid = conn.execute(
                    f"""
                    SELECT id, ticker, date, {column}
                    FROM stock_timeseries
                    WHERE {column} IS NULL
                       OR typeof({column}) NOT IN ('integer', 'real')
                    LIMIT 20
                    """
                ).fetchall()
                if invalid:
                    _append_issue(
                        issues,
                        table="stock_timeseries",
                        kind=f"invalid_{column}",
                        detail=f"{column} may not be null or non-numeric",
                        rows=invalid,
                    )
            invalid_prices = conn.execute(
                f"""
                SELECT id, ticker, date, open, high, low, close, adj_close
                FROM stock_timeseries
                WHERE open < 0 OR high < 0 OR low < 0 OR close < 0 OR adj_close < 0
                   OR open > {MAX_SQLITE_FLOAT} OR high > {MAX_SQLITE_FLOAT}
                   OR low > {MAX_SQLITE_FLOAT} OR close > {MAX_SQLITE_FLOAT}
                   OR adj_close > {MAX_SQLITE_FLOAT}
                   OR high < low OR open < low OR open > high OR close < low OR close > high
                LIMIT 20
                """
            ).fetchall()
            if invalid_prices:
                _append_issue(
                    issues,
                    table="stock_timeseries",
                    kind="invalid_ohlc",
                    detail="OHLCV rows must be finite, non-negative, and ordered",
                    rows=invalid_prices,
                )
            if "volume" in stock_columns:
                invalid_volume = conn.execute(
                    """
                    SELECT id, ticker, date, volume
                    FROM stock_timeseries
                    WHERE volume < 0 OR volume > 9223372036854775807
                    LIMIT 20
                    """
                ).fetchall()
                if invalid_volume:
                    _append_issue(
                        issues,
                        table="stock_timeseries",
                        kind="invalid_volume",
                        detail="volume must be a non-negative 64-bit integer",
                        rows=invalid_volume,
                    )

    # Other natural keys are never deleted.  Any legacy duplicate blocks the
    # migration with enough identity to reconcile it outside this transaction.
    for table, (columns, case_insensitive) in _NATURAL_KEYS.items():
        if table in {"portfolio_positions", "stock_timeseries"} or not _table_exists(conn, table):
            continue
        table_columns = _columns(conn, table)
        if not set(columns).issubset(table_columns):
            _append_issue(
                issues,
                table=table,
                kind="missing_natural_key_columns",
                detail=f"missing {sorted(set(columns) - table_columns)}",
            )
            continue
        key_sql = ", ".join(columns)
        if case_insensitive and "ticker" in columns:
            select_key = "upper(trim(ticker))" if len(columns) == 1 else "upper(trim(ticker)), " + ", ".join(
                column for column in columns[1:]
            )
        else:
            select_key = key_sql
        rows = conn.execute(
            f"""
            SELECT {select_key}, COUNT(*) AS row_count
            FROM "{table}"
            GROUP BY {select_key}
            HAVING COUNT(*) > 1
            LIMIT 20
            """
        ).fetchall()
        if rows:
            _append_issue(
                issues,
                table=table,
                kind="duplicate_natural_key",
                detail=f"unique key ({key_sql}) cannot be added without operator reconciliation",
                rows=rows,
            )

    return issues, mapped_metadata


def _index_rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    indexes: list[dict[str, Any]] = []
    if not _table_exists(conn, table):
        return indexes
    for row in conn.execute(f'PRAGMA index_list("{table}")').fetchall():
        index_name = str(row["name"])
        unique = bool(row["unique"])
        columns = [
            str(info["name"])
            for info in conn.execute(f'PRAGMA index_info("{index_name}")').fetchall()
            if info["name"] is not None
        ]
        collations: list[str | None] = []
        try:
            collations = [
                str(info[4]) if info[4] is not None else None
                for info in conn.execute(f'PRAGMA index_xinfo("{index_name}")').fetchall()
                if int(info[5]) == 1
            ]
        except sqlite3.DatabaseError:
            pass
        indexes.append(
            {
                "name": index_name,
                "unique": unique,
                "columns": columns,
                "collations": collations,
            }
        )
    return indexes


def _has_unique_index(
    conn: sqlite3.Connection,
    table: str,
    columns: tuple[str, ...],
    *,
    nocase_first: bool = False,
) -> bool:
    for index in _index_rows(conn, table):
        if not index["unique"] or tuple(index["columns"]) != columns:
            continue
        if nocase_first:
            collations = index["collations"]
            if not collations or (collations[0] or "").upper() != "NOCASE":
                continue
        return True
    return False


def _ensure_unique_index(
    conn: sqlite3.Connection,
    table: str,
    columns: tuple[str, ...],
    name: str,
    *,
    nocase_first: bool = False,
) -> None:
    if _has_unique_index(conn, table, columns, nocase_first=nocase_first):
        return
    # A case-sensitive or non-unique index over the same logical key adds no
    # correctness and can silently defeat CREATE UNIQUE INDEX IF NOT EXISTS.
    # Dropping only those exact indexes is non-destructive.
    for index in _index_rows(conn, table):
        if tuple(index["columns"]) == columns and not index["unique"]:
            conn.execute(f'DROP INDEX IF EXISTS "{index["name"]}"')
    expression = ", ".join(
        '"ticker" COLLATE NOCASE' if nocase_first and position == 0 else f'"{column}"'
        for position, column in enumerate(columns)
    )
    conn.execute(f'CREATE UNIQUE INDEX "{name}" ON "{table}" ({expression})')


def _copy_expression(table: str, column: str, available: set[str]) -> str | None:
    if column not in available:
        return None
    if table == "portfolio_positions" and column in {"sector", "industry"}:
        return f"COALESCE(\"{column}\", 'Unknown')"
    return f'"{column}"'


def _rebuild_table(
    conn: sqlite3.Connection,
    *,
    table: str,
    create_sql: str,
    integrity_columns: set[str],
) -> None:
    available = _columns(conn, table)
    required = {"id", "ticker", "weight"} if table == "portfolio_positions" else _STOCK_REQUIRED_COLUMNS
    missing = required - available
    if missing:
        raise MigrationError(f"{table} is missing required columns: {sorted(missing)}")

    columns = [column for column in _ordered_columns(integrity_columns) if column in available or column not in required]
    target = f"{table}__agent_d_rebuild"
    conn.execute(f'DROP TABLE IF EXISTS "{target}"')
    target_create_sql = create_sql.replace(
        f"CREATE TABLE {table}", f'CREATE TABLE "{target}"', 1
    )
    conn.execute(target_create_sql)
    selected = [(column, _copy_expression(table, column, available)) for column in columns]
    selected = [(column, expression) for column, expression in selected if expression is not None]
    column_sql = ", ".join(f'"{column}"' for column, _ in selected)
    expression_sql = ", ".join(expression for _, expression in selected)
    conn.execute(
        f'INSERT INTO "{target}" ({column_sql}) SELECT {expression_sql} FROM "{table}"'
    )
    source_count = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    target_count = int(conn.execute(f'SELECT COUNT(*) FROM "{target}"').fetchone()[0])
    if source_count != target_count:
        raise MigrationError(f"row-count mismatch rebuilding {table}: {source_count} != {target_count}")
    conn.execute(f'DROP TABLE "{table}"')
    conn.execute(f'ALTER TABLE "{target}" RENAME TO "{table}"')


def _ordered_columns(columns: set[str]) -> list[str]:
    order = [
        "id",
        "ticker",
        "weight",
        "quantity",
        "buy_price",
        "region",
        "primary_source",
        "fallback_source",
        "last_validated_source",
        "last_price",
        "market_value",
        "sector",
        "industry",
        "custom_name",
        "added_on",
        "updated_on",
        "date",
        "open",
        "high",
        "low",
        "close",
        "adj_close",
        "volume",
        "source_used",
        "fetch_status",
        "fetched_on",
        "position_id",
    ]
    return [column for column in order if column in columns]


def _validate_schema(conn: sqlite3.Connection) -> bool:
    portfolio_columns = _columns(conn, "portfolio_positions")
    if not {"ticker", "weight", "quantity", "buy_price", "sector", "industry"} <= portfolio_columns:
        return False
    notnull = {
        str(row["name"]): int(row["notnull"])
        for row in conn.execute('PRAGMA table_info("portfolio_positions")').fetchall()
    }
    if any(notnull.get(column) != 1 for column in ("ticker", "weight", "quantity", "buy_price", "sector", "industry")):
        return False
    if not _has_unique_index(conn, "portfolio_positions", ("ticker",), nocase_first=True):
        return False

    stock_columns = _columns(conn, "stock_timeseries")
    if not _STOCK_INTEGRITY_COLUMNS <= stock_columns:
        return False
    if not _has_unique_index(conn, "stock_timeseries", ("ticker", "date")):
        return False
    stock_sql_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='stock_timeseries'"
    ).fetchone()
    stock_sql = (stock_sql_row[0] if stock_sql_row else "").lower()
    if not all(
        marker in stock_sql
        for marker in (
            "ck_stock_timeseries_open_finite",
            "ck_stock_timeseries_high_finite",
            "ck_stock_timeseries_low_finite",
            "ck_stock_timeseries_close_finite",
            "ck_stock_timeseries_adj_close_finite",
            "ck_stock_timeseries_volume_nonnegative",
            "ck_stock_timeseries_ohlc_open",
            "ck_stock_timeseries_ohlc_close",
        )
    ):
        return False
    for table, (columns, nocase_first) in _NATURAL_KEYS.items():
        if _table_exists(conn, table) and not _has_unique_index(
            conn, table, columns, nocase_first=nocase_first
        ):
            return False
    return True


def _apply_integrity_schema(
    conn: sqlite3.Connection,
    *,
    version: int,
    mapped_metadata: int,
) -> None:
    if not _table_exists(conn, "portfolio_positions"):
        conn.execute(_PORTFOLIO_CREATE)
    else:
        _rebuild_table(
            conn,
            table="portfolio_positions",
            create_sql=_PORTFOLIO_CREATE,
            integrity_columns=_PORTFOLIO_INTEGRITY_COLUMNS,
        )

    if not _table_exists(conn, "stock_timeseries"):
        conn.execute(_STOCK_CREATE)
    else:
        _rebuild_table(
            conn,
            table="stock_timeseries",
            create_sql=_STOCK_CREATE,
            integrity_columns=_STOCK_INTEGRITY_COLUMNS,
        )

    for table, (columns, nocase_first) in _NATURAL_KEYS.items():
        if not _table_exists(conn, table):
            continue
        if not set(columns).issubset(_columns(conn, table)):
            raise MigrationError(f"cannot index {table}; natural-key columns are missing")
        _ensure_unique_index(
            conn,
            table,
            columns,
            f"uq_{table}_{'_'.join(columns)}",
            nocase_first=nocase_first,
        )

    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise MigrationError(f"foreign-key violations after schema rebuild: {len(violations)}")
    if _quick_check(conn) != "ok":
        raise MigrationError("PRAGMA quick_check failed during migration")
    if not _validate_schema(conn):
        raise MigrationError("post-migration schema validation failed")
    conn.execute(f"PRAGMA user_version = {int(version)}")
    if mapped_metadata:
        # Metadata nulls are compatibility-mapped to the model's historical
        # "Unknown" sentinel; no holding identity or market data is removed.
        pass


def apply_migrations(
    db_path: str | Path,
    *,
    target: int = LATEST_SCHEMA_VERSION,
    connect_factory: ConnectFactory = sqlite3.connect,
) -> MigrationResult:
    """Apply all missing schema versions to an isolated SQLite file."""

    if target != LATEST_SCHEMA_VERSION:
        raise ValueError(f"only upgrade target {LATEST_SCHEMA_VERSION} is supported")
    path = Path(db_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    conn: sqlite3.Connection | None = None
    backup_path: Path | None = None
    try:
        conn = _connect(path, connect_factory)
        if _quick_check(conn) != "ok":
            raise MigrationError("database failed PRAGMA quick_check before migration")
        previous = _schema_version(conn)
        if previous > LATEST_SCHEMA_VERSION:
            raise MigrationError(
                f"database schema version {previous} is newer than supported {LATEST_SCHEMA_VERSION}"
            )
        issues, mapped_metadata = _preflight(conn)
        if issues:
            conn.close()
            conn = None
            backup_path = create_database_backup(
                path, connect_factory=connect_factory
            )
            raise MigrationBlocked(issues, backup_path)
        if previous == LATEST_SCHEMA_VERSION and _validate_schema(conn):
            return MigrationResult(
                database_path=path,
                previous_version=previous,
                current_version=previous,
                applied=False,
                backup_path=None,
                mapped_null_metadata=0,
            )
    finally:
        if conn is not None:
            conn.close()

    backup_path = create_database_backup(path, connect_factory=connect_factory)
    conn = _connect(path, connect_factory)
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN IMMEDIATE")
        _apply_integrity_schema(
            conn,
            version=LATEST_SCHEMA_VERSION,
            mapped_metadata=mapped_metadata,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        try:
            conn.execute("PRAGMA foreign_keys=ON")
        finally:
            conn.close()

    return MigrationResult(
        database_path=path,
        previous_version=previous,
        current_version=LATEST_SCHEMA_VERSION,
        applied=True,
        backup_path=backup_path,
        mapped_null_metadata=mapped_metadata,
    )


def _downgrade_schema(conn: sqlite3.Connection) -> None:
    """Remove version-1 constraints while preserving every row and column."""

    portfolio_legacy = """
    CREATE TABLE portfolio_positions__agent_d_v0 (
        id INTEGER NOT NULL PRIMARY KEY,
        ticker VARCHAR(20),
        weight FLOAT,
        quantity FLOAT DEFAULT 0.0,
        buy_price FLOAT DEFAULT 0.0,
        region VARCHAR(10) DEFAULT 'US',
        primary_source VARCHAR(20) DEFAULT 'yfinance',
        fallback_source VARCHAR(20),
        last_validated_source VARCHAR(20) DEFAULT 'yfinance',
        last_price FLOAT DEFAULT 0.0,
        market_value FLOAT DEFAULT 0.0,
        sector VARCHAR(50) DEFAULT 'Unknown',
        industry VARCHAR(50) DEFAULT 'Unknown',
        custom_name VARCHAR(100),
        added_on DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_on DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """
    stock_legacy = """
    CREATE TABLE stock_timeseries__agent_d_v0 (
        id INTEGER NOT NULL PRIMARY KEY,
        ticker VARCHAR(20),
        date DATETIME,
        open FLOAT,
        high FLOAT,
        low FLOAT,
        close FLOAT,
        adj_close FLOAT,
        volume INTEGER,
        source_used VARCHAR(20) DEFAULT 'yfinance',
        fetch_status VARCHAR(20) DEFAULT 'fresh',
        fetched_on DATETIME DEFAULT CURRENT_TIMESTAMP,
        position_id INTEGER,
        FOREIGN KEY(position_id) REFERENCES portfolio_positions (id)
    )
    """
    conn.execute("DROP TABLE IF EXISTS portfolio_positions__agent_d_v0")
    conn.execute("DROP TABLE IF EXISTS stock_timeseries__agent_d_v0")
    conn.execute(portfolio_legacy)
    conn.execute(stock_legacy)
    conn.execute(
        """
        INSERT INTO portfolio_positions__agent_d_v0
        SELECT id, ticker, weight, quantity, buy_price, region, primary_source,
               fallback_source, last_validated_source, last_price, market_value,
               sector, industry, custom_name, added_on, updated_on
        FROM portfolio_positions
        """
    )
    conn.execute("DROP TABLE portfolio_positions")
    conn.execute("ALTER TABLE portfolio_positions__agent_d_v0 RENAME TO portfolio_positions")
    conn.execute(
        """
        INSERT INTO stock_timeseries__agent_d_v0
        SELECT id, ticker, date, open, high, low, close, adj_close, volume,
               source_used, fetch_status, fetched_on, position_id
        FROM stock_timeseries
        """
    )
    conn.execute("DROP TABLE stock_timeseries")
    conn.execute("ALTER TABLE stock_timeseries__agent_d_v0 RENAME TO stock_timeseries")
    if conn.execute("PRAGMA foreign_key_check").fetchall():
        raise MigrationError("foreign-key violations after downgrade")
    if _quick_check(conn) != "ok":
        raise MigrationError("PRAGMA quick_check failed after downgrade")
    conn.execute("PRAGMA user_version = 0")


def downgrade_database(
    db_path: str | Path,
    *,
    target: int = 0,
    connect_factory: ConnectFactory = sqlite3.connect,
) -> MigrationResult:
    """Data-preserving downgrade of the version-1 integrity layer."""

    if target != 0:
        raise ValueError("only downgrade target 0 is supported")
    path = Path(db_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    conn = _connect(path, connect_factory)
    try:
        previous = _schema_version(conn)
        if previous < target:
            raise MigrationError(f"cannot downgrade from version {previous} to {target}")
        if previous == target:
            return MigrationResult(path, previous, target, False, None)
        if _quick_check(conn) != "ok":
            raise MigrationError("database failed PRAGMA quick_check before downgrade")
    finally:
        conn.close()

    backup_path = create_database_backup(path, connect_factory=connect_factory)
    conn = _connect(path, connect_factory)
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN IMMEDIATE")
        _downgrade_schema(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        try:
            conn.execute("PRAGMA foreign_keys=ON")
        finally:
            conn.close()
    return MigrationResult(path, previous, target, True, backup_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, help="SQLite database path")
    parser.add_argument("--database-url", help="Resolve this SQLAlchemy SQLite URL and print its path")
    parser.add_argument("--downgrade", action="store_true", help="Downgrade integrity constraints to v0")
    args = parser.parse_args(argv)

    try:
        if args.database_url:
            print(resolve_sqlite_database_path(args.database_url))
        if args.db is None:
            parser.error("--db is required unless --database-url is used alone")
        if args.downgrade:
            result = downgrade_database(args.db)
        else:
            result = apply_migrations(args.db)
        print(
            json.dumps(
                {
                    "database": str(result.database_path),
                    "previous_version": result.previous_version,
                    "current_version": result.current_version,
                    "applied": result.applied,
                    "backup": str(result.backup_path) if result.backup_path else None,
                    "mapped_null_metadata": result.mapped_metadata,
                },
                sort_keys=True,
            )
        )
        return 0
    except (MigrationError, OSError, ValueError, sqlite3.DatabaseError) as exc:
        print(f"migration failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
