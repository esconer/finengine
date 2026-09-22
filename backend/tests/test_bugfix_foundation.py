"""Foundation fix regressions (audit 06-foundation).

One gate per nontrivial fix: migrations never fabricate/always back up,
cleanup refuses missing DBs, init_db creates the data dir + registers models
without routers, config defaults/env parsing (debug, ALLOWED_ORIGINS comma
separated, name-based env binding), NSE natural-key uniqueness, schema bounds
(EVT optional GPD + model_fitted, VolCone None quantiles, custom screener
bounds, ticker pattern), AnalyticsCache mutable default, LOG_LEVEL wiring,
and the deleted trap scripts staying deleted.
"""

import importlib.util
import logging
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.models.database import (
    AnalyticsCache,
    NSEBhavcopy,
    NSEInstitutionalFlow,
)
from app.models.schemas import (
    CustomScreenRequest,
    EVTPOTVarMetrics,
    VolConeWindow,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = BACKEND_DIR / "migrations"


def _load_migration(name: str):
    """migrations/ is not a package — load by file path."""
    spec = importlib.util.spec_from_file_location(name, MIGRATIONS_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- B1/B11/B12: add_portfolio_columns -------------------------------------

def test_add_portfolio_columns_never_fabricates(tmp_path):
    mod = _load_migration("add_portfolio_columns")
    db = tmp_path / "daisy.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE portfolio_positions ("
        "id INTEGER PRIMARY KEY, ticker TEXT, weight REAL, market_value REAL DEFAULT 0.0)"
    )
    conn.execute(
        "INSERT INTO portfolio_positions (ticker, weight, market_value) VALUES ('OLD.NS', 1.0, 5000.0)"
    )
    conn.commit()
    conn.close()

    assert mod.migrate_database(db_path=db) is True

    conn = sqlite3.connect(db)
    qty, buy_price = conn.execute(
        "SELECT quantity, buy_price FROM portfolio_positions"
    ).fetchone()
    conn.close()
    # ALTER default backfill only — never quantity=100 / buy_price=mv/100
    assert qty == 0.0
    assert buy_price == 0.0

    # backup taken BEFORE mutation (cleanup_duplicates pattern)
    backups = list((tmp_path / "backups").glob("daisy_backup_*.db"))
    assert len(backups) == 1


def test_add_portfolio_columns_connect_failure_no_unboundlocal(tmp_path, monkeypatch, capsys):
    mod = _load_migration("add_portfolio_columns")
    db = tmp_path / "daisy.db"
    db.write_bytes(b"")  # exists(), so the connect path (not the missing-DB path) runs

    def _boom(*_args, **_kwargs):
        raise RuntimeError("connect exploded")

    monkeypatch.setattr(mod.sqlite3, "connect", _boom)
    result = mod.migrate_database(db_path=db)

    out = capsys.readouterr().out
    assert result is False
    assert "connect exploded" in out          # original exception surfaces
    assert "UnboundLocalError" not in out     # conn=None before try


# --- B13: cleanup_duplicates path safety -----------------------------------

def test_cleanup_refuses_missing_db_and_uses_absolute_default(tmp_path, monkeypatch):
    mod = _load_migration("cleanup_duplicates_and_add_constraints")

    missing = tmp_path / "nope" / "daisy.db"
    with pytest.raises(FileNotFoundError):
        mod.DatabaseCleanupManager(db_path=missing)
    assert not missing.exists()  # sqlite never got a chance to create an empty file

    default = Path(mod._DEFAULT_DB_PATH)
    assert default.is_absolute()
    assert default.parts[-2:] == ("data", "daisy.db")

    # monkeypatch chdir: a CWD-relative default would resolve elsewhere
    other = tmp_path / "daisy.db"
    other.write_bytes(b"")
    monkeypatch.chdir(tmp_path)
    mgr = mod.DatabaseCleanupManager()  # still anchors to migrations/../data
    assert Path(mgr.db_path) == default


# --- B2/B7/B18: init_db startup order, echo, model registration ------------

def test_init_db_creates_missing_dir_registers_models_no_echo(tmp_path):
    db_file = tmp_path / "nested" / "data" / "test.db"
    url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    env = {k: v for k, v in os.environ.items() if k.upper() not in ("DEBUG", "DATABASE_URL")}
    env["DATABASE_URL"] = url
    env["DEBUG"] = "false"
    code = (
        "import asyncio\n"
        "from app.db.database import init_db, engine, Base\n"
        "asyncio.run(init_db())\n"
        "print('ECHO', engine.echo)\n"
        "print('TABLES', len(Base.metadata.tables))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    # dir created BEFORE create_all (previously OperationalError here)
    assert db_file.exists()
    # SQL echo decoupled: off by default / without debug+development
    assert "ECHO False" in proc.stdout
    # models registered without importing routers (init_db is self-sufficient)
    tables = int(proc.stdout.split("TABLES")[1].strip())
    assert tables >= 9


# --- B7/B8/B16: Settings ----------------------------------------------------

def test_settings_debug_defaults_false(monkeypatch):
    from app.config import Settings
    monkeypatch.delenv("DEBUG", raising=False)
    assert Settings(_env_file=None).debug is False


def test_allowed_origins_accepts_comma_separated(monkeypatch):
    from app.config import Settings
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://a:3000, http://b:3000")
    s = Settings(_env_file=None)
    assert s.allowed_origins == ["http://a:3000", "http://b:3000"]


def test_allowed_origins_still_accepts_json_array(monkeypatch):
    from app.config import Settings
    monkeypatch.setenv("ALLOWED_ORIGINS", '["http://a:3000", "http://b:3000"]')
    s = Settings(_env_file=None)
    assert s.allowed_origins == ["http://a:3000", "http://b:3000"]


def test_env_binding_is_by_field_name(monkeypatch):
    # Field(env=...) was a silent no-op; name-uppercasing IS the contract
    from app.config import Settings
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./data/env_override.db")
    s = Settings(_env_file=None)
    assert s.database_url == "sqlite+aiosqlite:///./data/env_override.db"


# --- B9: AnalyticsCache mutable shared default ------------------------------

def test_model_params_default_is_fresh_callable_dict():
    default = AnalyticsCache.__table__.c.model_params.default
    assert default is not None
    # default={} was a shared scalar literal; default=dict is a per-row callable
    assert getattr(default, "is_callable", False)
    assert callable(default.arg)
    first, second = default.arg(None), default.arg(None)
    assert first == {} and second == {}
    assert first is not second  # never the SAME dict object for two rows


# --- B10: NSE natural-key uniqueness ----------------------------------------

def test_nse_tables_declare_unique_natural_keys():
    def unique_cols(table):
        return {
            tuple(c.name for c in constraint.columns)
            for constraint in table.constraints
            if type(constraint).__name__ == "UniqueConstraint"
        }

    assert ("symbol", "date") in unique_cols(NSEBhavcopy.__table__)
    assert ("date", "category") in unique_cols(NSEInstitutionalFlow.__table__)
    # bulk/block deals: (symbol, date) is NOT a natural key (many client
    # trades per symbol per day) — must stay a plain index
    from app.models.database import NSEBulkBlockDeal
    assert ("symbol", "date") not in unique_cols(NSEBulkBlockDeal.__table__)


async def test_nse_duplicate_insert_raises_integrity_error(test_db):
    d = datetime(2026, 1, 15)
    test_db.add(NSEBhavcopy(
        symbol="RELIANCE", date=d, open=1.0, high=1.0, low=1.0, close=1.0,
        prev_close=1.0, avg_price=1.0, ttl_trd_qnty=1, turnover_lacs=1.0,
        no_of_trades=1,
    ))
    await test_db.commit()

    test_db.add(NSEBhavcopy(
        symbol="RELIANCE", date=d, open=1.0, high=1.0, low=1.0, close=1.0,
        prev_close=1.0, avg_price=1.0, ttl_trd_qnty=1, turnover_lacs=1.0,
        no_of_trades=1,
    ))
    with pytest.raises(IntegrityError):
        await test_db.commit()
    await test_db.rollback()

    test_db.add(NSEInstitutionalFlow(
        date=d, category="FII", buy_value_crores=1.0, sell_value_crores=1.0,
        net_value_crores=0.0,
    ))
    await test_db.commit()
    test_db.add(NSEInstitutionalFlow(
        date=d, category="FII", buy_value_crores=2.0, sell_value_crores=1.0,
        net_value_crores=1.0,
    ))
    with pytest.raises(IntegrityError):
        await test_db.commit()
    await test_db.rollback()


# --- Cross-area schema prep (reports 04 P1/P3, 02 P2) -----------------------

def test_evt_metrics_allows_unfitted_gpd():
    base = dict(
        evt_pot_var_99=-0.02, evt_pot_es_99=-0.03,
        historical_var_99=-0.015, historical_es_99=-0.02,
        threshold_u=-0.01, exceedances_count=3, total_observations=60,
        is_fat_tailed=False,
    )
    # fallback path: no GPD fit -> None params + model_fitted=False is legal
    unfitted = EVTPOTVarMetrics(
        gpd_shape_xi=None, gpd_scale_beta=None, model_fitted=False, **base
    )
    assert unfitted.gpd_shape_xi is None
    assert unfitted.model_fitted is False

    # fitted path unchanged: model_fitted defaults True for existing callers
    fitted = EVTPOTVarMetrics(gpd_shape_xi=0.15, gpd_scale_beta=0.01, **base)
    assert fitted.model_fitted is True


def test_vol_cone_window_accepts_none_quantiles():
    w = VolConeWindow(
        window_days=5, min=None, p25=None, median=None, p75=None,
        max=None, current_realized=12.5,
    )
    assert w.median is None
    assert w.current_realized == 12.5


def test_custom_screen_request_bounds():
    assert CustomScreenRequest().max_stocks == 50
    assert CustomScreenRequest(min_roce=15.0, max_pe=22.0, max_stocks=100).max_stocks == 100
    with pytest.raises(ValidationError):
        CustomScreenRequest(max_stocks=10**9)
    with pytest.raises(ValidationError):
        CustomScreenRequest(max_stocks=3)
    with pytest.raises(ValidationError):
        CustomScreenRequest(min_roce=-1.0)
    with pytest.raises(ValidationError):
        CustomScreenRequest(min_div_yield=-0.5)


# --- B17: LOG_LEVEL wiring --------------------------------------------------

def test_setup_logger_honors_settings_log_level(monkeypatch):
    import app.utils.logger as logger_mod

    monkeypatch.setattr(logger_mod.settings, "log_level", "WARNING")
    lg = logger_mod.setup_logger("test.foundation.loglevel")
    assert lg.level == logging.WARNING

    # typo'd level fails cleanly to INFO instead of AttributeError (I9)
    monkeypatch.setattr(logger_mod.settings, "log_level", "TYPO")
    lg2 = logger_mod.setup_logger("test.foundation.loglevel_typo")
    assert lg2.level == logging.INFO


# --- B3/B4/B5/B6/B15/I10: trap root scripts stay deleted --------------------

def test_trap_root_scripts_stay_deleted():
    for name in ("test_api_integrity.py", "test_bulk_operations_integrity.py", "_diag_rc.py"):
        assert not (BACKEND_DIR / name).exists(), (
            f"{name} deleted: it imported dead symbols and/or deleted or "
            "polluted live portfolio_positions data (audit 06 B3-B6/B15/I10)"
        )
