# 12 — Fix the AI dossier markdown

Status: ready-for-agent
Type: task
Phase: 1
Blocked by: —
Repo: `C:\es\coding\bfinance`
Severity: **MEDIUM — the shipped artifact is broken**

## What

`src/bfinance/ai/context.py:166`
```python
"\n".join([line for line in lines if line.strip() != ""])
```

Every intentional blank line is stripped, so a `## Heading` is butted directly against the
following table or list.

## Why

GFM — and most chat renderers — require a blank line before a pipe table. So **every table in the
flagship "AI-ready dossier" renders as a run-on paragraph of pipes.** This affects
`to_ai_context()`, `to_investment_memo_prompt()`, `to_forensic_audit_prompt()`,
`to_concall_analyst_prompt()`, and `BFinanceAITools.execute_tool('get_stock_dossier')`.

Confirmed against the repo's own committed output, `exports/TCS_AI_Dossier.md:11-13`:
```
## Annual Income Statement (Last 7 Years in ₹ Cr)
|                   |   Mar 2021 | ...
```

No blank line. The flagship deliverable of the library's AI module ships as invalid markdown.

## Proof of done

- [ ] Lines are joined with `"\n"` unfiltered, then runs of 3+ newlines collapse to 2.
- [ ] Every table in `exports/TCS_AI_Dossier.md` renders as a GFM table. Regenerate the file and
      confirm visually.
- [ ] A test asserts a **blank line precedes every pipe-table block** in the output of all four
      prompt builders, not just one.
- [ ] A test asserts a blank line follows every `##` heading.
- [ ] The leading `"\n"` markers already present at `context.py:69-79` are confirmed to be
      sufficient for separation, or the join strategy is adjusted.
- [ ] Round-trip through a markdown parser (e.g. `markdown-it-py` in dev deps) confirms the
      expected node count, rather than asserting on raw string shape alone.

## Notes

Small, self-contained, high visibility. The library's AI module is a differentiator and its
primary artifact is currently malformed.

Refs: `../spec.md`, `ai/context.py:69-79,166`, `exports/TCS_AI_Dossier.md:11-13`

## Verification correction (2026-09-28)

**CONFIRMED, and broader than this ticket states.** `src/bfinance/ai/context.py:229` is exactly
`return "\n".join([line for line in lines if line.strip() != ""])`.

Measured through the **real public API** (`AIContextBuilder.build_markdown_context`) on a real
`CompanyProfile` built from the repo's own `_synthetic_profile` in
`tests/test_ai_context_rendering.py`, fully offline:

    total lines emitted: 64    blank lines surviving: 11
    GFM tables found: 7        tables with no preceding blank line: 7 / 7

**Mechanism:** sections append headings as `f"\n## Heading"` (context.py:139, 147, 155, 163, 171).
That leading newline is *inside* the string, so it survives the filter and produces the blank line
*before* the heading. The heading-to-table gap needs a standalone `""` entry, which line 229
strips. Hence 11 blank lines survive while all 7 table gaps vanish.

"renders as run-on pipes" understates it: the tables are not joined together, they are **orphaned
from their own headings**.

**Honest limit:** the precondition markdown requires is verified absent, 7/7. The *rendered output*
is unverified - no GFM parser is installed and none may be fetched. "Tables do not render" is an
inference, not a measurement.
