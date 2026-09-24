"""Agent A pre-fix evidence: cointegration cache coverage identity."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
sys.dont_write_bytecode = True
from app.services.cointegration_service import _db_cache_keys, _mem_cache_key


def call(fn, **kwargs):
    try:
        return fn("A", "B", "2026-09-24", 0.05, False, **kwargs)
    except TypeError as exc:
        return f"TypeError:{exc}"


def main() -> None:
    mem_short = call(_mem_cache_key, lookback_days=60)
    mem_long = call(_mem_cache_key, lookback_days=2520)
    db_short = call(_db_cache_keys, lookback_days=60)
    db_long = call(_db_cache_keys, lookback_days=2520)
    for name, backend, reference in (
        ("memory_keys_differ", mem_short != mem_long, "different"),
        ("durable_keys_differ", db_short != db_long, "different"),
    ):
        # Boolean oracle: True is the expected identity separation.
        passed = bool(backend) if name.endswith("differ") else False
        print(f"CHECK|{name}|backend={backend!r}|reference={reference!r}|abs_diff=0|rel_diff=0|tolerance=atol:0,rtol:0|{'PASS' if passed else 'FAIL'}")
    print(f"OUTPUT|memory_short|{mem_short}")
    print(f"OUTPUT|memory_long|{mem_long}")
    print(f"OUTPUT|durable_short|{db_short}")
    print(f"OUTPUT|durable_long|{db_long}")


if __name__ == "__main__":
    main()
