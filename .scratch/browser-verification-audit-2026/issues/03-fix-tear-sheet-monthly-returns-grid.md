# Issue 03: Fix Monthly Returns Grid on Performance Tear-Sheet

Status: closed
Type: bug
Priority: P1
Blocked by: —

## Problem Description
On Page 9 (/dashboard/tear-sheet):
The Monthly Returns table renders empty cells ("") across all 12 months for years 2025 and 2026.

## Fix
In frontend/src/app/dashboard/tear-sheet/page.tsx:
Check monthly return key names and array parsing so monthly percentage values render with color-coded heatmap badges (green for positive return, red for negative return).
