# Issue 03: Eliminate Nested Double DashboardLayout on /dashboard/risk-studio

Status: ready-for-agent
Type: bug
Priority: P1
Blocked by: —

## Description
`frontend/src/app/dashboard/risk-studio/page.tsx` is wrapped in `<DashboardLayout title="Risk Studio">`. Because Next.js App Router already wraps all dashboard child routes in `DashboardLayout` via `src/app/dashboard/layout.tsx`, this creates duplicate sidebars, duplicate headers, and nested layout padding.

## Proposed Fix
Remove the inner `<DashboardLayout>` wrapper in `src/app/dashboard/risk-studio/page.tsx`, letting the root dashboard layout manage shell framing.

## Proof of Done
- [ ] Navigating to `/dashboard/risk-studio` displays a single sidebar, single top header, and clean unified canvas layout.
