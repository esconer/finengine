# QH-13 — CI/CD pipeline fixes

Status: closed
Type: task
Blocked by: —

## What

Three issues in `.github/workflows/ci-cd.yml`:

1. **Dead deployment reference**: The deploy step references a `k8s/` directory that does
   NOT exist in the repository. Deployment will always fail if triggered.

2. **Missing frontend CI**: No lint (`eslint`), type-check (`tsc --noEmit`), or test
   (`vitest run`) step for the frontend. Backend has ruff/mypy/pytest but frontend is
   completely unvalidated in CI.

3. **Security**: Pipeline uses long-lived AWS access keys (`AWS_ACCESS_KEY_ID` /
   `AWS_SECRET_ACCESS_KEY`) as repository secrets instead of secure OIDC role assumption
   via `aws-actions/configure-aws-credentials@v4` with `role-to-assume`.

## Fix

1. Remove or comment out the k8s deployment step until actual k8s manifests exist.
   Replace with Docker Compose deployment if that's the intended target.
2. Add frontend CI job: `bun install → bun run lint → tsc --noEmit → bun run test:run`.
3. Migrate to OIDC role assumption (or document the security risk if keeping keys).

## Also fix

- `TrustedHostMiddleware` in `main.py` (~line 85) omits `127.0.0.1` from allowed hosts.
  Add it to prevent 400 errors when accessing via IP instead of `localhost`.

## Why

CI that can't deploy and doesn't validate the frontend is theater, not safety.

## Proof of done
- [ ] CI pipeline runs green on push to main (no k8s failure)
- [ ] Frontend lint + typecheck + test included in CI
- [ ] `127.0.0.1` added to TrustedHostMiddleware
