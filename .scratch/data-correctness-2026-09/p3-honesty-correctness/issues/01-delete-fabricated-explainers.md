# 01 — Delete the fabricated `EXPLAINERS` numbers

Status: ready-for-agent
Type: task
Phase: 3
Blocked by: —
Repo: `frontend/`
Severity: **HIGH — the widest-spread honesty defect in the app**

## What

Seven pages carry an `EXPLAINERS` dictionary of static prose that contains **fabricated,
portfolio-specific numbers**, presented in a panel labelled "Quantitative Benchmark" or "Target
Benchmark". Every number is a string literal with no response binding.

### The worst offender — `tear-sheet/page.tsx`

| Line | Text |
|---|---|
| 56 | `"Nifty 50 1-Year Total Return: -2.6% (Portfolio Alpha: +28.4%)."` |
| 72 | `"Current Portfolio: 1.26 vs NIFTY 50: -0.20."` |
| 79 | `"…the portfolio temporarily declined 14.24% from its highest peak."` / `"March 2026 correction"` |
| 95 | `"28.51% indicates massive active outperformance … (MCX, Motherson, Redington)."` |
| 109 | `"Calmar = CAGR / \|Max Drawdown\| = 25.98% / 14.24% = 1.82."` |
| 165 | `"Check largest weights (Motherson 13.6%, JuniorBees 12.8%, Midcap ETF 10.5%)…"` |

None of these tickers or figures come from the response. A user with a completely different book
sees **someone else's portfolio described as "Current Portfolio"**, including a named holdings list
with weights.

### The other six

```
risk-studio/page.tsx:56,64,72,80,88,95,109
risk-contribution/page.tsx:50,58,66,74,96,110
regime/page.tsx:49,56,64,79,93
liquidity/page.tsx:74
volatility-sizing/page.tsx:117
forecast-risk/page.tsx:86,98,182
```

`risk-contribution` is the second worst: *"Motherson (19.9% risk share vs 13.6% capital weight)"*,
*"Redington (1.70x) … JuniorBees (0.77x) … Cipla (0.44x)"*.

## Why

This is the defect most likely to be mistaken for live data, because it renders in the same
visual treatment as real metric cards and uses the same numeric formatting.

The `e.g.`-prefixed strings are defensible pedagogy — they are explicitly hypothetical. The ones
worded **"Current Portfolio:"** or naming **specific tickers with weights** are not, and no amount
of surrounding disclosure makes them honest.

## Change

- **Delete** every explainer string that asserts a portfolio-specific fact or names specific
  tickers with numbers.
- **Keep** the `e.g.`-framed pedagogical strings, which teach the concept without claiming to
  describe your book.
- Where a genuinely useful explanation exists, make it a **template** driven by the live response
  values, not a literal. If the value is missing, show nothing rather than a placeholder number.
- Remove the "Quantitative Benchmark" / "Target Benchmark" panel heading, or repurpose it for
  genuinely comparative live data.
- Add a lint rule or test preventing a bare numeric literal inside an explainer string that is not
  interpolated from the response.

## Proof of done

- [ ] No `EXPLAINERS` string asserts a portfolio-specific fact. Grep for `"Current Portfolio` and
      for ticker-like tokens in string literals returns nothing.
- [ ] No explainer string contains a bare percentage, ratio, or currency figure that is not
      interpolated. A test asserts every numeric token in the explainer dictionaries is either
      absent or template-interpolated.
- [ ] `tear-sheet` renders no named holdings in any explainer text.
- [ ] The pedagogical `e.g.` strings survive and still read naturally.
- [ ] Where an explainer is genuinely useful, it is driven by the live response. Spot-check three
      such cases and confirm the numbers change when the response changes.
- [ ] The lint rule or test fails if a future literal number is added to an explainer dictionary.
- [ ] All seven pages still render. Several of these are the only explanatory text on their page,
      so check the page does not become a bare number wall.

## Notes

This is a judgement call per string, not a blanket delete. The distinction is whether the string
describes *the user's book* (delete or template) or *the concept* (keep).

Refs: `../spec.md`
