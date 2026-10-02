# Orchestrator corrections — authoritative overrides

Written by the orchestrator during Wave C verification, **after** the writers finished. This file is
an override layer: where it contradicts a detail file, **this file wins.** It exists so that
corrections are auditable rather than silently applied to an agent's output.

The orchestrator verified every claim below by opening the cited line directly.

---

## COR-1 — `FE-2` was rejected in error. It is NOT a false finding.

**Writer A2 rejected FE-2 in full**, on the grounds that a guard at
`frontend/src/app/dashboard/risk-studio/page.tsx:605` kills the fabricated-zero path.
**That reasoning is wrong.** Verified:

```tsx
// :605 — the guard A2 relied on. It is COARSE: whole-matrix, not per-cell.
{copulaTickers.length > 0 && copulaMatrix.length > 0 ? (

// :621 — the fallback A2 believed unreachable. It is PER-CELL.
const num = copulaMatrix[rowIdx]?.[colIdx] ?? (rowIdx === colIdx ? 1.0 : 0.0);
```

A matrix that is **non-empty but ragged** — `matrix.length > 0` yet `matrix[r].length <
tickers.length` for some `r` — passes the `:605` guard and still yields `undefined` at `:621`,
producing the fabricated `0.000` on the emerald "no crash dependence" band and `0.0000` in the CSV.

And a ragged matrix is not guarded against on the way in:

```tsx
// :328-332 — assigned straight from the API, no square-completeness check
const copulaMatrix: number[][] = Array.isArray(tailRisk?.tail_dependence_matrix?.matrix)
  ? tailRisk.tail_dependence_matrix.matrix
  : Array.isArray(tailRisk?.matrix) ? tailRisk.matrix : [];
```

**Correct status: `NEEDS-RUNTIME`, not rejected.** The open question is narrow and answerable: does
`GET /analytics/tails` ever emit a `tail_dependence_matrix.matrix` whose rows are shorter than
`tickers.length`? That is a backend question, so it **cannot be settled by reading the frontend** —
which is exactly the narrow quarantine exception in plan §3 ("two code paths are genuinely
ambiguous"). It belongs in `unverified.md` with the settle-command, **not** in `rejected.md`.

**Do not drop FE-2.**

---

## COR-2 — `FE-4`: the writer's correction is RIGHT, and the explorer's original claim was false.

The inventory asserted FE-4's fabricated `buy_price: 0` "is **persisted** and surfaces as wrong total
cost, wrong P/L and wrong risk weight on every dashboard." **That is false.** Verified:

```python
# backend/app/models/schemas.py:17
buy_price: float = Field(..., gt=0, description="Price per share at time of purchase - must be > 0")
```

`gt=0` means the backend rejects the write with a 422. Nothing is persisted. (Also `:15`
`weight: float = Field(..., gt=0, le=1)` and `:16` `quantity: ... gt=0` — the same guard shape.)

**The real symptom is therefore different and should be stated as such:** the screener row is
clickable, the request is issued, and the user gets an opaque `422 buy_price: Input should be greater
than 0` instead of "this ticker has no measurable price." A dead-end control, not silent corruption.

A2's severity reduction is correct and its cross-boundary flag was well placed. **Severity: DEFECT,
not BLOCKER. Confidence: VERIFIED.**

---

## COR-3 — the adjacent bug A2 found but did not emit is REAL

A2 noted but declined to emit it. Verified:

```ts
// frontend/src/lib/store.ts:202-206
set({
    positions: snapshot.positions || [],          // :203 substitutes []
    totalValue: snapshot.total_value || 0,        // :204
    totalWeight: snapshot.total_weight || 0,      // :205
    positionCount: snapshot.positions.length,     // :206 — reads the RAW field
});
```

If `snapshot.positions` is absent, `:203` substitutes `[]` and `:206` throws on `.length` — **the
substitution on the line above does not protect the line below it.** Same *family* as FE-7
(absence laundered into a value) but a **different mechanism**: FE-7 launders, this one crashes.

**Promote to a ledger row.** Severity DEFECT, confidence VERIFIED.

---

## COR-4 — `FE-1` confirmed as DEFECT/VERIFIED, and its mechanism is stronger than stated

```tsx
// frontend/src/app/portfolio/manage/page.tsx:45-49
const monetaryValue = (base: number | null | undefined, native: number | null | undefined): number => {
    if (typeof base === 'number' && Number.isFinite(base)) return base;
    if (typeof native === 'number' && Number.isFinite(native)) return native;
    return 0;                                   // NaN and undefined BOTH land here
};
```

The return type is `number` and the terminal `return 0` absorbs `NaN`, so
`Number.isFinite(monetaryValue(...))` at `:786` is **always true** and the `N/A` branch at `:788` is
unreachable. Verified directly. Keep as DEFECT/VERIFIED.

**Generalise this into §0 as a named pattern.** Three of A2's findings were *guards that exist, read
as correct, and are structurally unreachable*. A file can look hardened end-to-end while the
fabrication happens one layer upstream. The audit question is not "is there a guard?" but **"can
this guard observe the value it tests?"**

---

## COR-5 — writer A4's rejection of `OE-13` is CORRECT. Verified.

The inventory claimed the backend CSV export has no formula-injection neutralisation (P1, `API-023`,
corroborated by 2 prior artifacts). **That is false.** Verified:

```
backend/app/api/portfolio.py:851   def _safe_csv_cell(value: Any) -> Any:
                                      """Prevent spreadsheet formula execution while retaining CSV structure."""
backend/app/api/portfolio.py:1827     _safe_csv_cell(position.custom_name or ''),
```

`_safe_csv_cell` is defined at `:851` and applied at `:1820, :1822, :1825, :1826, :1827` —
**including `custom_name` at `:1827`, the exact user-supplied field the finding named.**

The explorer missed it by grepping for the **frontend's** helper name (`escapeCsv|csv.writer|def _csv`)
and matching only the bare `csv.writer` — a grep-scoped audit that searched for a remembered
identifier instead of reading the file. Writer A4 caught it by reading.

**`OE-13` belongs in `rejected.md`, not the ledger.** A4 has already placed it there; this confirms it.

---

## COR-6 — heading-level deviation the assembler must tolerate

Writer A4 emitted OE findings as `## OE-nn` (h2), not the `### OE-nn` (h3) specified in the plan.
All **15** OE ids are present and unique — confirmed by scan. The assembler must match on the
`OE-\d\d` token, **not** on `^###`. A naive `^###` scan reports zero OE rows, which is exactly the
kind of silent-empty that produces a confidently wrong ledger.

---

## COR-7 — the orchestrator's own inventory carried wrong filenames

Writer A1 found that the **cache inventory table in `inventory-a1-api-services.md` cites the wrong
source file on 6 of 8 rows** — line numbers correct, filenames not. A1 re-verified 4 of 8,
documented a corrected table, and **declined to endorse the original table's conclusion.**

Treat any filename in an inventory *table* as unverified. Line-level citations in the inventory were
spot-checked by the orchestrator (11 of 11 confirmed) and by both writers that used them.

---

## COR-8 — `SVC-1`'s published score is 5.9, not 3.0 — the inventory understated it

The inventory asserted an all-NaN `Volume` mean publishes `score = 3.0`. **Measured: 5.9.**

```
inner   3.0 + (nan / 2e7) * 2.9  ->  nan
min(5.9, nan)                    ->  5.9      # Python builtin: `nan < 5.9` is False, so it keeps 5.9
max(2.5, 5.9)                    ->  5.9
```

The trap: Python's builtin `min`/`max` **silently swallow NaN**, where numpy propagates it —
`np.minimum(5.9, nan)` returns `nan`, but `min(5.9, nan)` returns `5.9`. So the fabricated score is
**2.9 points worse** than reported and lands 0.1 below the Medium cut. Use A1's figure; the
inventory's `3.0` is wrong.

Same failure family as the earlier `float()`-on-a-numpy-scalar error: the plausible semantics were
assumed rather than the actual ones.

---

## Net effect on the ledger

| Item | Status | Action for the assembler |
|---|---|---|
| FE-2 | **NEEDS-RUNTIME**, not rejected | route to `unverified.md` with a settle-command; do **not** count as a closed/rejected finding |
| FE-4 | DEFECT / VERIFIED, symptom restated (422, not persistence) | keep, use COR-2's symptom wording |
| COR-3 (store.ts:206) | new DEFECT / VERIFIED | add as a ledger row |
| FE-1 | DEFECT / VERIFIED | keep; use COR-4's generalised wording |