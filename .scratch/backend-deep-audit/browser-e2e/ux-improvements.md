# UX, Accessibility, and Responsive Improvements

Status: active.

## Confirmed categories

- App scrolling occurs inside a `main` element rather than the document. Native browser full-page screenshots capture only the viewport; audit evidence therefore requires explicit internal-scroll sections.
- Empty state displays `0.0%` diversification instead of N/A.
- Expected unavailable analytics generate visible console/API errors on empty pages.
- Dashboard has an unnamed icon-only button.
- Portfolio Management exposes ten unnamed icon-only row-action buttons.
- Factor Exposure and Stress Testing have unnamed selects.
- Forecast Risk and Volatility Sizing have label violations.
- Forecast Risk, Stress Testing, Volatility Sizing, and mobile Liquidity contain nested-interactive violations.
- Realized Risk, Regime, Pairs, Risk Studio, and mobile India data expose scrollable regions that are not keyboard-focusable.
- Heading order skips levels on most dashboard pages.
- Color-contrast violations occur across the product, especially sidebar descriptions, badges, and secondary text.
- The 404 page lacks the expected main landmark/H1 structure.

These are evidence-backed accessibility issues, not style preferences. Current axe evidence contains 65/110 captures with violations, 148 rule-occurrence records, and 11 unique rule IDs; these are repeated capture instances, not 148 unique defects. No empty-state axe run was performed, and manual keyboard/screen-reader validation remains pending.

## Responsive review

Final evidence uses:

- Desktop: 1440×900.
- Mobile: 390×844.
- Top/middle/bottom contiguous internal-scroll sections.
- Full network/console capture after load and scroll.

## Final section visual review

Representative top/middle/bottom section images were reviewed by desktop and mobile subagents:

- **Desktop:** the Summary positions table and shell state disagree; Equity Research peer rows do not match the selected Reliance category; Screener dividend-yield values are implausibly scaled; Realized Risk and Forecast core outputs are unavailable; Concentration and Liquidity show contradictory risk states; several pages retain `Last updated: Never` beside populated data.
- **Mobile:** fixed headers obscure Tear Sheet, Risk Contribution, and Monte Carlo content; Pairs/India Flows/Portfolio Management controls or table columns clip at the right edge; Settings action labels are low contrast; Risk Contribution category labels truncate.
- **Scope limit:** static images prove visibility/legibility issues but do not prove whether clipped regions are horizontally scrollable or keyboard reachable. Those paths remain `NOT TESTED`.

Evidence: `evidence/calculations/outputs/desktop-visual-review.md` and `evidence/calculations/outputs/mobile-visual-review.md`.
