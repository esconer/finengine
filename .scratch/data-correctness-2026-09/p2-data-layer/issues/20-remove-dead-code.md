# 20 — Remove dead code and the unreachable branches it hides

Status: ready-for-agent
Type: task
Phase: 2
Blocked by: —
Repo: `backend/`
Severity: **LOW** — but it hides real defects

## What

Four pieces of dead or unreachable code, each of which is masking something.

### a) `check_data_integrity` has no caller

`data_service.py:1789-1848`. Grep finds no caller anywhere.

It also returns `{"error": "CHECK_FAILED"}` on **any** failure, which would be useless as a
diagnostic if it were ever wired up.

### b) The `download()` re-raise is unreachable

`data_service.py:95` re-raises, but the caller at `:838` returns `None` first. Issue 03 fixes the
`None`; this ticket removes what becomes newly-reachable dead code.

### c) `data_service.py:1652` truncates volume

`int(row["volume"])` truncates a fractional vendor volume. Not dead, but wrong.

### d) Broad `except` in the pure-frame helpers

`:339`, `:355`, `:383`, `:401` — `except Exception: return df / return None / pass`.

These do no vendor I/O, so a bare catch is defensible. But they hide genuine **shape** bugs behind
a silent `None`, which upstream becomes a 404 via issue 03. Once issue 03 lands, a shape bug
returns a provider error with no indication of what was wrong with the shape.

### e) Process-global mutable cascade order

`source_preference_service.py:99-101` — `_ACTIVE_SOURCE_ORDER` is a **process-global mutable**
cascade used by `CompanyDataService` when `source_order is None`
(`company_data_service.py:146-147,323-324`).

Every live route passes `source_order` explicitly (`data.py:263`, `:290`), so this is currently
unreachable — but it is a request-race waiting to happen, and a global mutable is the wrong
default for a per-request setting.

### f) The currency-service singleton holds a session

`currency_service.py:380-381` — the module-global FX singleton captures the first request's
`AsyncSession` into `cache_service` and never releases it. Not triggered today, because no caller
passes `db`. It is a latent leak that will hold a database handle open indefinitely the first time
someone passes one.

## Change

- Delete `check_data_integrity`, or wire it up and make it return a useful per-check result. The
  current all-or-nothing shape is not worth wiring.
- After issue 03, re-audit the newly-unreachable branches and delete them.
- Fix the volume truncation.
- Narrow the broad `except` blocks to the specific exceptions a pure-frame operation can raise,
  and let a genuine shape bug surface as a typed error naming the problem.
- Make the source order an explicit required parameter rather than defaulting to a global.
- Fix the FX singleton's session lifetime.

## Proof of done

- [ ] `check_data_integrity` is either deleted or has a caller and returns per-check results.
- [ ] No `return None` in `data_service.py` is unreachable.
- [ ] Volume is not truncated.
- [ ] Every broad `except` in the pure-frame helpers is narrowed, and a shape mismatch raises a
      typed error naming the offending columns.
- [ ] `_ACTIVE_SOURCE_ORDER` is gone, and `source_order` is a required parameter.
- [ ] The FX singleton does not retain an `AsyncSession`. A test constructs it twice with
      different sessions and asserts the first is released.
- [ ] A dead-code check runs in CI, or ruff's `F` rules are confirmed to cover the cases that
      matter. Note that `CONTEXT.md` documents the ruff scope as deliberately narrow (`E9`, `F`),
      so widening it needs a dedicated cleanup PR per the repo's own rules.

## Notes

Pure hygiene, but each item is a place where a real defect is currently invisible. Do it after
the correctness work, not before.

Refs: `../spec.md`, `app/services/data_service.py:95,339,355,383,401,838,1652,1789-1848`, `app/services/source_preference_service.py:99-101`, `app/services/company_data_service.py:146-147,323-324`, `app/services/currency_service.py:380-381`, `AGENTS.md` ruff scope note
