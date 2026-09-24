# Test Matrix

Status: complete with explicit `PARTIAL` / `NOT TESTED` limitations. `PASS` means exercised with evidence; it does not imply financial correctness unless the reconciliation verdict is also `VERIFIED`.

| Route | Empty desktop/mobile | Seeded desktop/mobile | Internal-scroll sections | Primary interactions | Financial replay | Status |
|---|---|---|---|---|---|---|
| `/` | Yes | Yes | 13 desktop + 13 mobile sections captured | Redirect, database-abort state | N/A | PASS |
| `/dashboard` | Yes | Yes | 13 desktop + 13 mobile sections captured | CRUD/currency, controlled failures, browser WebSocket probe | Partial | PASS/PARTIAL |
| `/portfolio/manage` | Yes | Yes | 13 desktop + 13 mobile sections captured | Add/edit/delete/currency/import/supported-input rejection | Partial | PASS/PARTIAL |
| `/dashboard/equity-research` | Yes | Yes | 13 desktop + 13 mobile sections captured | Ticker search, statements tab, memo/forensic prompts | N/A | PASS/PARTIAL |
| `/dashboard/screener-studio` | Yes | Yes | 13 desktop + 13 mobile sections captured | Built-in/custom screen, add-to-portfolio, cleanup | N/A | PASS/PARTIAL |
| `/dashboard/realized-risk` | Yes | Yes | 13 desktop + 13 mobile sections captured | Load/error states; direct replay | Partial | PASS/PARTIAL |
| `/dashboard/forecast-risk` | Yes | Yes | 13 desktop + 13 mobile sections captured | EGARCH/10-day, provider abort | Partial | PASS/PARTIAL |
| `/dashboard/factor-exposure` | Yes | Yes | 13 desktop + 13 mobile sections captured | 252d→504d lookback | Partial | PASS/PARTIAL |
| `/dashboard/stress-testing` | Yes | Yes | 13 desktop + 13 mobile sections captured | Run All, custom -17% shock | N/A | PASS/PARTIAL |
| `/dashboard/concentration` | Yes | Yes | 13 desktop + 13 mobile sections captured | Load states; independent arithmetic | Partial | PASS/PARTIAL |
| `/dashboard/liquidity` | Yes | Yes | 13 desktop + 13 mobile sections captured | Refresh/fan-out; direct replay | Partial | PASS/PARTIAL |
| `/dashboard/volatility-sizing` | Yes | Yes | 13 desktop + 13 mobile sections captured | Dry-run simulation; no live commit | Partial | PASS/PARTIAL |
| `/dashboard/tear-sheet` | Yes | Yes | 13 desktop + 13 mobile sections captured | Load/error states; direct API capture | Partial | PASS/PARTIAL |
| `/dashboard/risk-contribution` | Yes | Yes | 13 desktop + 13 mobile sections captured | Empty/error states; direct replay | Partial | PASS/PARTIAL |
| `/dashboard/risk-studio` | Yes | Yes | 13 desktop + 13 mobile sections captured | Empty/error states | Partial | PASS/PARTIAL |
| `/dashboard/optimize` | Yes | Yes | 13 desktop + 13 mobile sections captured | All five strategies | Partial | PASS/PARTIAL |
| `/dashboard/regime` | Yes | Yes | 13 desktop + 13 mobile sections captured | Refresh | Partial | PASS/PARTIAL |
| `/dashboard/monte-carlo` | Yes | Yes | 13 desktop + 13 mobile sections captured | GBM, Student-t, Bootstrap | Partial | PASS/PARTIAL |
| `/dashboard/pairs` | Yes | Yes | 13 desktop + 13 mobile sections captured | Scan Universe | Partial | PASS/PARTIAL |
| `/dashboard/india-flows` | Yes | Yes | 13 desktop + 13 mobile sections captured | Refresh | Partial | PASS/PARTIAL |
| `/dashboard/settings` | Yes | Yes | 13 desktop + 13 mobile sections captured | Source save/restore, cache purge | N/A | PASS/PARTIAL |
| 404 | Yes | Yes | 13 desktop + 13 mobile sections captured | Direct navigation | N/A | PASS |

## State matrix

| State | Evidence status |
|---|---|
| Empty portfolio | Captured desktop/mobile; false safety verdicts confirmed |
| Single holding | Captured; 100% weight and 0% diversification verified |
| Mixed INR/USD portfolio | Captured; native/base contract discrepancy confirmed |
| Invalid required fields | Captured |
| Malformed ticker | Captured |
| Duplicate ticker/409 | Captured |
| Edit persistence | Captured and reverted |
| Delete confirmation/persistence | Captured |
| CSV import/unsupported input | Captured; temporary rows removed |
| Loading states | Final section captures complete; observed skeleton/unavailable states preserved |
| Provider/network failure | Controlled forecast API abort captured |
| Database unavailable | Controlled portfolio API abort captured; backend itself remained isolated and healthy |
| Stale timestamp | External spot checks and DF findings recorded; exact provider as-of remains unavailable |
| WebSocket connect/reconnect | Python client, browser ping, status, disconnect, and reconnect captured; product-page automatic connection absent |
| Keyboard/focus and axe | Axe captured; manual keyboard/screen-reader pass not tested |
