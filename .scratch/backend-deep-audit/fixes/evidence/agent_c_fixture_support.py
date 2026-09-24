"""Shared hermetic helpers for Agent C pre-change fixtures."""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[4]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
class ScalarRows:
    def __init__(self, rows): self._rows = rows
    def scalars(self): return self
    def all(self): return list(self._rows)
    def first(self): return self._rows[0] if self._rows else None
    def scalar_one_or_none(self): return self._rows[0] if self._rows else None
class FakeDB:
    def __init__(self, rows=None):
        self.rows = list(rows or []); self.commits = 0; self.rollbacks = 0; self.refreshes = 0
    async def execute(self, statement): return ScalarRows(self.rows)
    async def commit(self): self.commits += 1
    async def rollback(self): self.rollbacks += 1
    async def refresh(self, obj): self.refreshes += 1; return obj
    def add(self, obj): self.rows.append(obj)
    async def delete(self, obj):
        if obj in self.rows: self.rows.remove(obj)
    async def flush(self): return None
def run(coro): return asyncio.run(coro)
