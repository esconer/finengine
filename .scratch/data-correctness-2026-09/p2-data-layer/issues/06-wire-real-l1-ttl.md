# 06 — Wire the real L1 TTL

Status: ready-for-agent
Type: task
Phase: 2
Blocked by: —
Repo: `backend/`
Severity: **MEDIUM**

## What

`_L1_TTL_SECONDS = 300` and `_l1_ttl` at `data_service.py:313-317` are **never read**. The
effective L1 TTL comes from `_l1_ttl_seconds(config)` at `:259-261`, which is the persisted
`cache_ttl_minutes` setting — **default 60 minutes**.

## Why

Two problems, one behavioural and one epistemic.

**Behavioural:** an in-memory frame is served for up to an hour after a vendor correction. A
wrong close published at 09:00 propagates into every analytics call for the next 60 minutes with no
way to shorten it.

**Epistemic:** the code contains a constant that says "L1 keeps a 5-min TTL" while the actual
behaviour is 60 minutes. A future maintainer reading `_L1_TTL_SECONDS = 300` will reason about a
TTL the system does not have. This is the same class of defect as Phase 1 issue 10's silent no-ops:
the code lies about itself.

## Decision needed

Pick one and make the code match:

- **Option A** — honour the 5-minute constant and delete the setting-derived path.
- **Option B** — delete the constant and make the comment say the TTL is
  `cache_ttl_minutes × 60`.
- **Option C** — keep both, with the constant as a floor and the setting as a ceiling, documented.

Option B is simplest. Option A is better if 5 minutes is genuinely the intent for live quotes.

## Proof of done

- [ ] Exactly one TTL source of truth. The other is deleted.
- [ ] The comment matches the code.
- [ ] A test asserts the effective L1 TTL for a given config, so a future change to the setting
      default is caught.
- [ ] The settings UI (`/dashboard/settings`, which already exposes cache controls) shows the
      **actual** effective value, so the user can see what they are getting.
- [ ] `cache_ttl_minutes` is validated to a sane range at the settings layer. A 0 or negative
      value currently produces a no-TTL cache.
- [ ] The same audit is applied to any other dead TTL constant in the file. Grep for constants
      that are assigned and never read.

## Notes

Also related and worth fixing in the same pass — **`clear_service_memos` reach** is already
correct, but the L1 preference fence at `data_service.py:411` **fails open** when
`_l1_preferences[ticker]` is absent. It is unreachable today (both dicts are always written
together at `:555-558` and `:651-653`, and cleared together at `cache_service.py:149-157`), but it
is fail-open by construction. Make it fail closed.

Refs: `../spec.md`, `app/services/data_service.py:259-261,313-317,407,411,555-558,651-653`, `app/services/cache_service.py:149-157`
