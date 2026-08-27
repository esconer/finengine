# QH-08 — Frontend memoization + React Compiler evaluation

Status: closed
Type: task
Blocked by: —

## What

Three performance issues from missing memoization:

1. **`manage/page.tsx`** (~line 288): `filteredPositions` recalculates search + sort logic
   on every render (every keystroke in the search bar causes full array reprocessing).
   Should be wrapped in `useMemo(fn, [positions, searchTerm, sortConfig])`.

2. **`optimize/page.tsx`** (~line 358): Efficient Frontier scatter data (21-element array)
   is generated inline on every render inside a Recharts component. Should be `useMemo`.

3. **`next.config.ts`** line 5: `reactCompiler: false` disables React 19's automatic
   memoization. Was disabled "for stability" but should be re-evaluated — it would
   auto-fix issues 1 and 2 above plus every other missing memo.

## Fix

1. Wrap `filteredPositions` in `useMemo`.
2. Wrap frontier data generation in `useMemo`.
3. Re-enable `reactCompiler: true`, run full test suite + manual verification.

## Why

Search-as-you-type stutters on larger portfolios. Chart re-renders waste CPU on static data.

## Proof of done
- [ ] Typing in manage page search bar is smooth (no jank)
- [ ] Optimizer page doesn't regenerate frontier data on unrelated state changes
- [ ] If React Compiler enabled: test suite still passes, no visual regressions
